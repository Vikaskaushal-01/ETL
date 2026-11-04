"""
Data observability: learned baselines instead of fixed thresholds (the Monte Carlo / Metaplane approach).

Every run records a few health metrics (volume, columns, missing / duplicate / rejected share, quality,
runtime). A new run is compared with the earlier runs of the same dataset by the same owner using a robust
z-score (median and median absolute deviation), so one odd delivery does not distort the baseline.
Datasets also get a freshness monitor: a dataset that usually arrives every N hours is "late" when nothing
arrived for 2 x N.
"""
import logging
import re
import statistics
from datetime import datetime
from typing import Optional

logger = logging.getLogger("etl_observability")

MIN_HISTORY = 3          # earlier runs needed before a metric is judged
MAX_HISTORY = 30         # earlier runs kept in a baseline
Z_THRESHOLD = 3.5        # robust z-score above which a value is anomalous (Iglewicz & Hoaglin)
Z_HIGH = 7.0
LATE_FACTOR = 2.0        # late when silent for this many typical intervals
MIN_FRESHNESS_GAP_S = 300

# metric -> (label, unit, which direction is bad: "up", "down" or "both")
METRICS = {
    "rows": ("Row count", "rows", "both"),
    "columns": ("Column count", "columns", "both"),
    "missing_pct": ("Missing values", "%", "up"),
    "duplicate_pct": ("Duplicate rows", "%", "up"),
    "rejected_pct": ("Rejected rows", "%", "up"),
    "quality_after": ("Quality after cleaning", "%", "down"),
    "execution_time": ("Runtime", "s", "up"),
}

_STAMP_PATTERNS = [
    re.compile(r"[_\-. ]?\d{4}[-_]?\d{2}[-_]?\d{2}([_\-T ]?\d{2}[:_\-]?\d{2}([:_\-]?\d{2})?)?"),  # dates / timestamps
    re.compile(r"[_\-][0-9a-f]{6,}(?=\.|$)"),                                                     # random id suffix
    re.compile(r"[_\-]\d{6,}(?=\.|$)"),                                                           # long numeric suffix
    re.compile(r"\s*\(\d+\)(?=\.|$)"),                                                            # "file (2).csv"
]


def dataset_key(filename: Optional[str]) -> str:
    """Groups deliveries of the same dataset: 'orders_20260916_183805_c2346c.csv' -> 'orders.csv'."""
    name = (filename or "").strip().lower()
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    for pattern in _STAMP_PATTERNS:
        stem = pattern.sub("", stem)
    stem = re.sub(r"[_\-. ]+$", "", stem) or "dataset"
    return f"{stem}.{ext}" if ext else stem


def _out(state: dict, stage: str) -> dict:
    return ((state.get("stages") or {}).get(stage) or {}).get("output") or {}


def _num(value) -> Optional[float]:
    try:
        return None if value is None or value == "" else float(value)
    except (TypeError, ValueError):
        return None


def run_metrics(state: dict) -> dict:
    """Health metrics of a run, measured from its recorded stage outputs."""
    intake, transform, storage = _out(state, "intake"), _out(state, "transformation"), _out(state, "storage")
    rows, cols = _num(intake.get("rows")), _num(intake.get("columns"))
    metrics = {"rows": rows, "columns": cols}
    cells = (rows or 0) * (cols or 0)
    missing = _num(intake.get("missing_values_total"))
    metrics["missing_pct"] = round(100 * missing / cells, 3) if cells and missing is not None else None
    dups = _num(intake.get("duplicate_rows"))
    metrics["duplicate_pct"] = round(100 * dups / rows, 3) if rows and dups is not None else None
    loaded, rejected = _num(storage.get("rows_loaded")), _num(storage.get("rows_rejected"))
    handled = (loaded or 0) + (rejected or 0)
    metrics["rejected_pct"] = round(100 * (rejected or 0) / handled, 3) if handled else None
    metrics["quality_after"] = _num(transform.get("quality_after"))
    metrics["execution_time"] = _num(state.get("execution_time")) if state.get("status") != "Failed" else None
    return metrics


def _robust_stats(values: list) -> tuple:
    med = statistics.median(values)
    mad = statistics.median([abs(v - med) for v in values])
    # 1.4826 * MAD estimates the standard deviation for normal data; a flat history gets a 2% tolerance
    scale = 1.4826 * mad if mad > 0 else max(abs(med) * 0.02, 1e-6)
    return med, scale


def detect_anomalies(current: dict, history: list) -> list:
    """Compares current metrics with earlier runs' metrics (oldest first). Returns anomalies, worst first."""
    anomalies = []
    for key, (label, unit, bad) in METRICS.items():
        value = current.get(key)
        past = [h[key] for h in history if h.get(key) is not None]
        if value is None or len(past) < MIN_HISTORY:
            continue
        med, scale = _robust_stats(past)
        z = (value - med) / scale
        if abs(z) < Z_THRESHOLD or (bad == "up" and z < 0) or (bad == "down" and z > 0):
            continue
        low, high = med - Z_THRESHOLD * scale, med + Z_THRESHOLD * scale
        low = max(0.0, low)
        if unit == "%":
            high = min(100.0, high)
        change = f"{(value - med) / med * 100:+.0f}%" if med else "new"
        anomalies.append({
            "metric": key,
            "label": label,
            "unit": unit,
            "value": round(value, 3),
            "baseline": round(med, 3),
            "expected_low": round(low, 3),
            "expected_high": round(high, 3),
            "z_score": round(z, 2),
            "change": change,
            "direction": "up" if z > 0 else "down",
            "severity": "high" if abs(z) >= Z_HIGH else "medium",
            "message": (f"{label} is {_fmt(value, unit)}, {'above' if z > 0 else 'below'} the usual "
                        f"{_fmt(low, unit)} - {_fmt(high, unit)} "
                        f"(median {_fmt(med, unit)} over {len(past)} runs)."),
        })
    return sorted(anomalies, key=lambda a: -abs(a["z_score"]))


def _fmt(value: float, unit: str) -> str:
    if unit in ("rows", "columns"):
        return f"{value:,.0f} {unit}"
    return f"{value:,.2f}{unit}" if unit == "%" else f"{value:,.1f}{unit}"
