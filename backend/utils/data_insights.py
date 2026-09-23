"""
Deterministic, data-derived report content: dataset insights, root cause analysis of rejected rows
and recommendations. Everything here is computed from the actual cleaned file and the actual
validation outcome, so reports never contain invented numbers.
"""
import re
from collections import OrderedDict

import pandas as pd

MAX_CATEGORY_CARDINALITY = 25


def _fmt_number(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "n/a"
    value = float(value)
    if value.is_integer():
        return f"{int(value):,}"
    return f"{value:,.2f}"


def compute_dataset_insights(df: pd.DataFrame, max_items: int = 12) -> list:
    """Factual observations about the cleaned dataset (volumes, numeric ranges, category mix, dates, gaps)."""
    if df is None:
        return []
    if df.empty:
        return ["The cleaned dataset contains no rows."]

    rows, cols = df.shape
    insights = [f"The cleaned dataset contains {rows:,} rows across {cols} columns."]

    numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and not pd.api.types.is_bool_dtype(df[c])]
    id_like = {c for c in df.columns if str(c).lower().endswith("_id") or str(c).lower() in ("id", "row_number", "line_number")}
    for col in [c for c in numeric_cols if c not in id_like][:5]:
        series = pd.to_numeric(df[col], errors="coerce").dropna()
        if series.empty:
            continue
        insights.append(
            f"'{col}': total {_fmt_number(series.sum())}, average {_fmt_number(series.mean())}, "
            f"range {_fmt_number(series.min())} to {_fmt_number(series.max())}."
        )

    date_like = [c for c in df.columns if re.search(r"(date|time|_at$|_on$)", str(c).lower())]
    for col in date_like[:2]:
        parsed = pd.to_datetime(df[col], errors="coerce", format="mixed").dropna()
        if len(parsed) >= 1:
            insights.append(f"'{col}' spans {parsed.min():%Y-%m-%d} to {parsed.max():%Y-%m-%d} ({len(parsed):,} dated records).")

    categorical = [
        c for c in df.columns
        if c not in numeric_cols and c not in id_like and c not in date_like
        and 1 < df[c].nunique(dropna=True) <= MAX_CATEGORY_CARDINALITY
    ]
    for col in categorical[:4]:
        counts = df[col].value_counts(dropna=True)
        total = int(counts.sum())
        top = ", ".join(f"{val} ({cnt / total:.0%})" for val, cnt in counts.head(3).items())
        insights.append(f"'{col}' has {df[col].nunique(dropna=True)} distinct values; most frequent: {top}.")

    null_counts = df.isnull().sum()
    gaps = null_counts[null_counts > 0].sort_values(ascending=False)
    if not gaps.empty:
        detail = ", ".join(f"'{c}' ({int(n):,})" for c, n in gaps.head(4).items())
        insights.append(f"{int(gaps.sum()):,} values remain empty after cleaning, mainly in {detail}.")
    else:
        insights.append("No empty values remain after cleaning.")

    return insights[:max_items]


# Rejection reason prefixes produced by the storage agent -> RCA explanation
_RCA_CATEGORIES = OrderedDict([
    ("Missing primary key", {
        "root_cause": "The source extract contains records without a value in the table's key column.",
        "business_impact": "These records cannot be identified or joined and are excluded from all analytics.",
        "technical_impact": "Rows fail the NOT NULL primary key check during staging.",
        "recommendation": "Make the key column mandatory in the source system or export, or assign keys upstream before loading.",
    }),
    ("Duplicate primary key", {
        "root_cause": "The same key appears on several differing records in one file (conflicting versions of an entity).",
        "business_impact": "Only one version can be kept; conflicting values may make totals or attributes inconsistent.",
        "technical_impact": "Rows violate the primary key uniqueness constraint within the batch.",
        "recommendation": "Deduplicate at the source or send one latest record per key (e.g. by last-updated timestamp).",
    }),
    ("Missing required field", {
        "root_cause": "A mandatory attribute is empty in the source records.",
        "business_impact": "Entities without required attributes cannot be reported on reliably.",
        "technical_impact": "Rows fail the NOT NULL constraint of the target table.",
        "recommendation": "Enforce the field as required at data entry or backfill it before export.",
    }),
    ("Invalid numeric value", {
        "root_cause": "Numeric columns contain text or malformed numbers.",
        "business_impact": "Quantities or amounts from these rows are missing from financial totals.",
        "technical_impact": "Values cannot be cast to the numeric column type.",
        "recommendation": "Validate numeric formats in the source (no text, units or stray characters in numeric fields).",
    }),
    ("Non-integer value", {
        "root_cause": "Whole-number columns contain fractional values.",
        "business_impact": "Counts from these rows are excluded from volume metrics.",
        "technical_impact": "Values cannot be stored in the INTEGER column.",
        "recommendation": "Round or correct fractional values for count columns in the source export.",
    }),
    ("Unparseable date", {
        "root_cause": "Date columns contain values that are not recognizable dates.",
        "business_impact": "Time-based trends and period filters omit these records.",
        "technical_impact": "Values cannot be converted to DATETIME.",
        "recommendation": "Export dates in ISO format (YYYY-MM-DD) and remove placeholder text from date fields.",
    }),
    ("DB Load Crash", {
        "root_cause": "The database rejected the load transaction as a whole.",
        "business_impact": "No rows from this batch reached the warehouse.",
        "technical_impact": "The transaction was rolled back; see the process log for the database error.",
        "recommendation": "Check database connectivity and the error in the process log, then re-run the batch.",
    }),
])


def build_root_cause_analysis(rejected_records: list, total_rows: int) -> list:
    """Groups the actual rejection reasons into RCA entries with counts, affected columns and examples."""
    groups = OrderedDict()
    for record in rejected_records or []:
        for reason in str(record.get("reason") or "Unknown validation failure").split("; "):
            category = next((c for c in _RCA_CATEGORIES if reason.startswith(c)), "Other validation failure")
            group = groups.setdefault(category, {"count": 0, "rows": [], "examples": [], "columns": set()})
            group["count"] += 1
            if len(group["rows"]) < 5:
                group["rows"].append(record.get("row_number"))
            if len(group["examples"]) < 3:
                group["examples"].append(reason)
            # The first quoted token names the column; later ones are the offending values
            col_match = re.search(r"'([^']+)'", reason)
            if col_match:
                group["columns"].add(col_match.group(1))

    rca = []
    for category, group in groups.items():
        template = _RCA_CATEGORIES.get(category, {
            "root_cause": "Records failed a validation rule during staging.",
            "business_impact": "Affected rows are excluded from analytics.",
            "technical_impact": "Rows were flagged Rejected in the staging table.",
            "recommendation": "Review the listed examples and correct the source data.",
        })
        share = f" ({group['count'] / total_rows:.1%} of rows)" if total_rows else ""
        columns = f" in column(s) {', '.join(sorted(group['columns']))}" if group["columns"] else ""
        rca.append({
            "issue": f"{category}{columns}: {group['count']} row(s) rejected{share}. Rows {', '.join(str(r) for r in group['rows'])}{'...' if group['count'] > len(group['rows']) else ''}. Example: {group['examples'][0]}",
            "root_cause": template["root_cause"],
            "business_impact": template["business_impact"],
            "technical_impact": template["technical_impact"],
            "recommendation": template["recommendation"],
            "confidence": 100.0,
        })
    return rca


def build_recommendations(df: pd.DataFrame, rca_list: list, duplicate_rows: int, quality_before, quality_after) -> list:
    """Actionable recommendations derived from what this run actually found."""
    recs = [r["recommendation"] for r in rca_list]
    if duplicate_rows:
        recs.append(f"{duplicate_rows} exact duplicate row(s) were removed; check the source export for repeated records.")
    if df is not None and not df.empty:
        null_counts = df.isnull().sum()
        worst = null_counts[null_counts > 0].sort_values(ascending=False)
        if not worst.empty:
            col, n = worst.index[0], int(worst.iloc[0])
            recs.append(f"Column '{col}' still has {n:,} empty value(s) ({n / len(df):.0%}); capture it at the source or define a default.")
    try:
        if quality_before is not None and quality_after is not None and float(quality_after) < 95:
            recs.append(f"Data quality is {float(quality_after):.1f}% after cleaning; add validation rules for the columns listed above.")
    except (TypeError, ValueError):
        pass
    if not recs:
        recs.append("No data quality issues were found in this run; keep the current source format and schedule.")
    # Preserve order, drop duplicates
    return list(OrderedDict.fromkeys(recs))
