"""
Review Agent: decides which runs need a human.

The other agents always produce *something*: nulls get a default, invalid numbers are coerced,
duplicates are dropped and bad rows are rejected. Some of those automatic choices change what the
data says (a column that is 60% imputed, missing values concentrated in one group, a run that
crashed), so this agent re-reads the raw and cleaned data after a run and lists every problem a
person should decide on, each with what happened, how it affects the dataset and what to do.
The checks are computed from the data, so they work without an LLM.
"""
import logging
import os
import time
from typing import Optional

import numpy as np
import pandas as pd

from agents.transformation_agent.transformation_agent import is_date_column_name, parse_dates, standardize_column_name
from backend.utils.file_utils import read_dataset

logger = logging.getLogger("etl_review_agent")

# Rows read from each file for the checks (large files are sampled)
REVIEW_SAMPLE_ROWS = int(os.getenv("REVIEW_SAMPLE_ROWS", "100000"))
# Share of a column that is missing before its imputation is worth a look / a decision
MISSING_MEDIUM = 0.10
MISSING_HIGH = 0.40
# Imputation that moves a numeric column's mean or shrinks its spread by this much distorts it
MEAN_SHIFT = 0.10
STD_SHRINK = 0.20
# Share of a text column that ends up as the filled placeholder ("Unknown")
PLACEHOLDER_SHARE = 0.20
# Missing values are "not at random" when their rate differs this much between groups of another column
MNAR_GAP = 0.30
MNAR_MIN_GROUP_ROWS = 5
MNAR_MIN_NULLS = 3
MNAR_MAX_GROUPS = 20
DUPLICATE_RATE = 0.10
REJECTED_HIGH = 0.10
# Values beyond quartile +/- OUTLIER_FENCE * IQR are extreme
OUTLIER_FENCE = 3.0
OUTLIER_MIN_ROWS = 20
OUTLIER_MAX_SHARE = 0.05
# A text column whose values are mostly numbers, with some that are not
MIXED_TYPE_MIN_NUMERIC = 0.5
MAX_COLUMNS_CHECKED = 60

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2}
# Within a severity, problems that affect the whole run or bias the data come first
CATEGORY_ORDER = ["Pipeline failure", "File", "Validation", "Bias risk", "Missing values", "Data types", "Outliers", "Duplicates"]
NULL_TOKENS = {"", "nan", "none", "null", "n/a", "na", "-"}
POSITIVE_NAME_TOKENS = ("price", "amount", "quantity", "qty", "total", "cost", "revenue", "age")

# Known failure messages and what they mean for the person fixing the file
CRASH_EXPLANATIONS = [
    (("no columns to parse", "emptydataerror", "no data rows"), "The file is empty or has no header row.",
     "Check the export produced data, then upload the file again."),
    (("codec can't decode", "unicodedecodeerror"), "The file's text encoding could not be read.",
     "Save the file as UTF-8 (in Excel: Save As > CSV UTF-8) and upload it again."),
    (("error tokenizing", "expected", "fields in line"), "Rows have different numbers of columns, usually a delimiter or quoting problem.",
     "Open the file, look at the line named in the error and fix the stray delimiter or unclosed quote."),
    (("badzipfile", "excel file format", "not a zip file"), "The spreadsheet is damaged or is not a real Excel file.",
     "Re-export the spreadsheet from its source application, or save it as CSV."),
    (("unsupported", "unknown file"), "The file type is not supported.",
     "Convert the file to CSV, TSV, XLSX or JSON."),
    (("memoryerror", "out of memory"), "The file is too large to process in memory.",
     "Split the file into smaller parts and upload them separately."),
]


def _issue(code, severity, category, title, problem, impact, action, column=None, evidence=None) -> dict:
    return {
        "code": code,
        "severity": severity,
        "category": category,
        "column": column,
        "title": title,
        "problem": problem,
        "impact": impact,
        "action": action,
        "evidence": evidence or {},
    }


def _pct(share: float) -> str:
    return f"{share * 100:.0f}%" if share >= 0.01 or share == 0 else f"{share * 100:.1f}%"


def _num(value) -> str:
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return "-"
    return f"{value:,.0f}" if abs(value) >= 1000 else f"{value:,.4g}"


def _is_text(series: pd.Series) -> bool:
    # pandas 3 reads text as the "str" dtype, older versions as object
    return pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series)


def _normalize_raw(df: pd.DataFrame) -> pd.DataFrame:
    """Raw data with the column names and null tokens the Transformation Agent works with."""
    df = df.copy()
    df.columns = [standardize_column_name(c) for c in df.columns]
    df = df.loc[:, ~pd.Index(df.columns).duplicated()]
    for col in df.columns:
        if _is_text(df[col]):
            stripped = df[col].astype(str).str.strip()
            df[col] = df[col].where(~stripped.str.lower().isin(NULL_TOKENS) & df[col].notna(), None)
    return df


def _read(path: Optional[str]) -> Optional[pd.DataFrame]:
    if not path or not os.path.isfile(path):
        return None
    try:
        return read_dataset(path, nrows=REVIEW_SAMPLE_ROWS)
    except Exception as e:
        logger.warning(f"Review agent could not read {path}: {e}")
        return None


def _fill_applied(history: list, col: str) -> Optional[dict]:
    """The imputation step the Transformation Agent recorded for a column, if any."""
    for step in history or []:
        if step.get("column_name") == col and str(step.get("old_value", "")).lower().startswith("null"):
            return step
    return None


class ReviewAgent:
    def __init__(self):
        self.role = "Data Steward"
        self.name = "Review Agent"

    def run(self, raw_path: Optional[str], clean_path: Optional[str] = None, transformation_history: list = None,
            validation_results: dict = None, pipeline_status: Optional[str] = None, error: Optional[str] = None,
            failed_stage: Optional[str] = None) -> dict:
        start = time.time()
        issues = []
        raw_df = _read(raw_path)

        if error:
            issues.append(self._crash_issue(error, failed_stage))
        if raw_df is not None and len(raw_df) == 0 and not error:
            issues.append(_issue(
                "empty_file", "critical", "File",
                "The file has no data rows",
                f"The file was read but contains {len(raw_df.columns)} column header(s) and no rows, so there was nothing to clean or load.",
                "Nothing from this file reached the database or the reports.",
                "Check that the export or download produced data, then upload the file again.",
            ))

        if raw_df is not None and len(raw_df):
            raw = _normalize_raw(raw_df)
            clean = _read(clean_path)
            if clean is not None:
                clean = clean.copy()
                clean.columns = [standardize_column_name(c) for c in clean.columns]
            history = transformation_history or []
            columns = list(raw.columns)[:MAX_COLUMNS_CHECKED]
            for col in columns:
                for check in (self._missing_values, self._mixed_types, self._dates, self._outliers):
                    try:
                        found = check(raw, clean, col, history)
                    except Exception as e:  # one odd column must not stop the other checks
                        logger.warning(f"Review check {check.__name__} failed on '{col}': {e}")
                        found = None
                    if found:
                        issues.append(found)
            try:
                issues.extend(self._missing_not_at_random(raw, columns))
            except Exception as e:
                logger.warning(f"Missing-not-at-random check failed: {e}")

        issues.extend(self._validation(validation_results or {}, pipeline_status, raw_df))
        issues.sort(key=lambda i: (SEVERITY_ORDER.get(i["severity"], 9), CATEGORY_ORDER.index(i["category"])))
        return {
            "required": bool(issues),
            "kind": "not_processed" if any(i["severity"] == "critical" for i in issues) else ("needs_decision" if issues else "clear"),
            "severity": issues[0]["severity"] if issues else None,
            "issues": issues,
            "execution_time": time.time() - start,
        }

    # ---------- run-level problems ----------

    def _crash_issue(self, error: str, failed_stage: Optional[str]) -> dict:
        lowered = error.lower()
        meaning, action = "The agent hit an error it cannot work around on its own.", \
            "Read the error and the process log, fix the file or the setting it points to, then re-run."
        for needles, known_meaning, known_action in CRASH_EXPLANATIONS:
            if any(n in lowered for n in needles):
                meaning, action = known_meaning, known_action
                break
        where = f" during the {failed_stage} stage" if failed_stage else ""
        return _issue(
            "pipeline_crash", "critical", "Pipeline failure",
            f"The run stopped{where}",
            f"{meaning} Error: {error}",
            "The file was not fully processed: later stages did not run, so the database, reports and Power BI export do not include it.",
            action,
            evidence={"error": error, "stage": failed_stage},
        )

    def _validation(self, validation: dict, pipeline_status: Optional[str], raw_df) -> list:
        rejected = validation.get("rejected_records") or []
        n_rejected = int(validation.get("rows_rejected") or len(rejected) or 0)
        n_loaded = int(validation.get("rows_loaded") or 0)
        total = n_rejected + n_loaded
        if not n_rejected or not total:
            return []
        reasons = {}
        for r in rejected:
            for part in str(r.get("reason") or "Unknown").split(";"):
                if part.strip():
                    reasons[part.strip()] = reasons.get(part.strip(), 0) + 1
        top = sorted(reasons.items(), key=lambda kv: -kv[1])[:4]
        reason_text = "; ".join(f"{reason} ({count} row{'s' if count != 1 else ''})" for reason, count in top)
        evidence = {"rows_rejected": n_rejected, "rows_loaded": n_loaded, "reasons": dict(top)}
        if n_loaded == 0 or pipeline_status == "Failed":
            return [_issue(
                "nothing_loaded", "critical", "Validation",
                f"None of the {total:,} rows could be loaded",
                f"Every row failed validation: {reason_text}.",
                "The file was not loaded into the database, so dashboards, Power BI and the reports have no data from it.",
                "Fix the listed fields in the source file (often a missing or renamed key column) and re-run. "
                "Download the rejected rows to see each row's reason.",
                evidence=evidence,
            )]
        share = n_rejected / total
        return [_issue(
            "rows_rejected", "high" if share >= REJECTED_HIGH else "medium", "Validation",
            f"{n_rejected:,} of {total:,} rows ({_pct(share)}) were rejected",
            f"These rows broke a rule the agent will not guess its way around: {reason_text}.",
            "Rejected rows are missing from the database. Totals and counts are understated, and if the rejected rows "
            "share something (one region, one source system, one date range) that group is under-represented in every result.",
            "Download the rejected rows, correct them in the source (or confirm they should be excluded) and re-run.",
            evidence=evidence,
        )]

    # ---------- column-level problems ----------

    def _missing_values(self, raw, clean, col, history) -> Optional[dict]:
        nulls = int(raw[col].isna().sum())
        if not nulls:
            return None
        share = nulls / len(raw)
        step = _fill_applied(history, col)
        fill = step.get("new_value") if step else None
        evidence = {"missing": nulls, "rows": len(raw), "missing_share": round(share, 4), "filled_with": fill}

        if share >= 0.999:
            return _issue(
                "column_empty", "high", "Missing values",
                f"Column '{col}' is completely empty",
                f"All {len(raw):,} values of '{col}' are missing."
                + (f" The agent filled every one with '{fill}', so the column now holds no real information." if fill is not None else ""),
                "Any analysis that uses this column is working with made-up values; the column looks valid but is not.",
                f"Find out why the source does not send '{col}'. Drop the column, or get the values and re-run.",
                column=col, evidence=evidence,
            )

        if fill is None:
            # Keys and names are never guessed; leaving them empty usually makes the row fail validation
            if share < MISSING_MEDIUM:
                return None
            return _issue(
                "missing_unfilled", "high" if share >= MISSING_HIGH else "medium", "Missing values",
                f"{nulls:,} rows ({_pct(share)}) have no '{col}'",
                f"'{col}' looks like an identifier or name, so the agent cannot invent a value and left it empty.",
                "Rows without it cannot be matched to other tables and may have been rejected; joins and per-entity counts will miss them.",
                f"Supply the missing '{col}' values in the source, or confirm those rows should be dropped, then re-run.",
                column=col, evidence=evidence,
            )

        effects, distorted = [], False
        observed = pd.to_numeric(raw[col], errors="coerce").dropna()
        is_numeric = len(observed) >= max(3, 0.8 * (len(raw) - nulls))
        if is_numeric and clean is not None and col in clean.columns:
            after = pd.to_numeric(clean[col], errors="coerce").dropna()
            mean_b, mean_a = float(observed.mean()), float(after.mean()) if len(after) else float("nan")
            std_b, std_a = float(observed.std()), float(after.std()) if len(after) > 1 else float("nan")
            evidence.update(mean_before=mean_b, mean_after=mean_a, std_before=std_b, std_after=std_a)
            if mean_b and np.isfinite(mean_a):
                shift = (mean_a - mean_b) / abs(mean_b)
                if abs(shift) >= MEAN_SHIFT:
                    distorted = True
                    effects.append(f"the average moved from {_num(mean_b)} to {_num(mean_a)} ({shift:+.0%})")
            if std_b and np.isfinite(std_a):
                shrink = 1 - std_a / std_b
                if shrink >= STD_SHRINK:
                    distorted = True
                    effects.append(f"the spread (standard deviation) shrank by {shrink:.0%}, from {_num(std_b)} to {_num(std_a)}")
            impact = ("Every missing value now has the same number, so the column looks more uniform than it really is: "
                      "variance and correlations are understated and rows with real values carry less weight in comparisons.")
            if str(fill) in ("0", "0.0"):
                impact = ("Filling with 0 makes missing readings look like real zeros: sums, averages and minimums are pulled down "
                          "and a model would learn that zero is common.")
        elif clean is not None and col in clean.columns:
            filled_share = float((clean[col].astype(str) == str(fill)).mean())
            top_value = clean[col].astype(str).value_counts().index[0] if len(clean) else None
            evidence.update(placeholder_share=round(filled_share, 4))
            if filled_share >= PLACEHOLDER_SHARE or top_value == str(fill):
                distorted = True
                effects.append(f"'{fill}' is now {_pct(filled_share)} of the column"
                               + (" and its most common value" if top_value == str(fill) else ""))
            impact = (f"'{fill}' becomes a category of its own: group counts and shares are distorted and charts by '{col}' "
                      f"show a large '{fill}' bar instead of the real breakdown.")
        else:
            impact = "The filled values are estimates, not observations; results that use this column are partly invented."

        if share < MISSING_MEDIUM and not distorted:
            return None
        severity = "high" if share >= MISSING_HIGH or distorted else "medium"
        problem = (f"{nulls:,} of {len(raw):,} values ({_pct(share)}) were missing. The agent filled them with '{fill}' "
                   f"({step.get('reason', 'default fill')}).")
        if effects:
            problem += " As a result " + "; ".join(effects) + "."
        return _issue(
            "missing_imputed", severity, "Missing values",
            f"{_pct(share)} of '{col}' was missing and filled with '{fill}'",
            problem, impact,
            f"Decide how '{col}' should be handled: collect the missing values, fill them per group instead of one value for all, "
            f"mark them as unknown and exclude them from averages, or drop the column. Then re-run.",
            column=col, evidence=evidence,
        )

    def _missing_not_at_random(self, raw, columns) -> list:
        """Missing values concentrated in one group: any single fill value biases the data against that group."""
        candidates = [c for c in columns if int(raw[c].isna().sum()) >= MNAR_MIN_NULLS]
        group_cols = [c for c in columns if 2 <= raw[c].nunique(dropna=True) <= MNAR_MAX_GROUPS]
        issues = []
        for col in candidates:
            best = None
            for g in group_cols:
                if g == col:
                    continue
                frame = pd.DataFrame({"g": raw[g], "missing": raw[col].isna()}).dropna(subset=["g"])
                stats = frame.groupby("g")["missing"].agg(["mean", "size"])
                stats = stats[stats["size"] >= MNAR_MIN_GROUP_ROWS]
                if len(stats) < 2:
                    continue
                hi, lo = stats["mean"].idxmax(), stats["mean"].idxmin()
                gap = float(stats.loc[hi, "mean"] - stats.loc[lo, "mean"])
                if gap >= MNAR_GAP and (best is None or gap > best[0]):
                    rest = frame[frame["g"] != hi]["missing"].mean()
                    best = (gap, g, hi, float(stats.loc[hi, "mean"]), float(rest), int(stats.loc[hi, "size"]))
            if best:
                gap, g, group, rate, rest_rate, size = best
                issues.append(_issue(
                    "missing_not_at_random", "high", "Bias risk",
                    f"Missing '{col}' values are concentrated in {g} = '{group}'",
                    f"{_pct(rate)} of the {size:,} rows with {g} = '{group}' have no '{col}', against {_pct(rest_rate)} of the other rows. "
                    "The values are not missing at random, so the agent cannot tell whether one fill value is fair for every group.",
                    f"A single fill value (median, 0 or 'Unknown') makes '{group}' look like the overall average and hides how it really "
                    f"differs, so results by {g} are biased toward the groups with complete data. Dropping those rows instead would "
                    f"under-represent '{group}'.",
                    f"Find out why '{group}' rows lack '{col}' (a different source system or form?). Fill '{col}' within each {g} group, "
                    f"collect the values, or exclude '{col}' from comparisons across {g}.",
                    column=col, evidence={"group_column": g, "group": str(group), "group_missing_share": round(rate, 4),
                                          "other_missing_share": round(rest_rate, 4), "group_rows": size},
                ))
        return issues

    def _mixed_types(self, raw, clean, col, history) -> Optional[dict]:
        if not _is_text(raw[col]):
            return None
        values = raw[col].dropna().astype(str).str.strip()
        if len(values) < 5:
            return None
        numeric = pd.to_numeric(values.str.replace(",", "", regex=False), errors="coerce")
        share = float(numeric.notna().mean())
        if not (MIXED_TYPE_MIN_NUMERIC <= share < 1.0):
            return None
        bad = values[numeric.isna()]
        examples = list(dict.fromkeys(bad.tolist()))[:5]
        coerced = clean is not None and col in clean.columns and pd.api.types.is_numeric_dtype(clean[col])
        return _issue(
            "mixed_types", "high" if coerced else "medium", "Data types",
            f"{len(bad):,} values in '{col}' are not numbers",
            f"'{col}' is {_pct(share)} numeric, but {len(bad):,} value(s) are text, e.g. {', '.join(repr(e) for e in examples)}."
            + (" The agent converted them to numbers and filled them as if they were missing." if coerced else
               " The agent kept the column as text so nothing was lost."),
            ("The original entries were replaced by a default, so real information (a typo of a real amount, a unit like '12kg') "
             "was thrown away." if coerced else
             "Because the column is stored as text, sums, averages and sorting on it do not work as numbers."),
            f"Correct the listed values in the source (or decide what they mean, e.g. 'N/A' = missing) and re-run.",
            column=col, evidence={"non_numeric": len(bad), "numeric_share": round(share, 4), "examples": examples},
        )

    def _dates(self, raw, clean, col, history) -> Optional[dict]:
        if not is_date_column_name(col) or pd.api.types.is_numeric_dtype(raw[col]):
            return None
        values = raw[col].dropna()
        if len(values) < 3:
            return None
        parsed = parse_dates(values)
        share = float(parsed.notna().mean())
        if share >= 1.0:
            return None
        bad = values[parsed.isna()].astype(str)
        examples = list(dict.fromkeys(bad.tolist()))[:5]
        standardized = any(s.get("column_name") == col and "date" in str(s.get("reason", "")).lower() for s in history)
        return _issue(
            "unparseable_dates", "medium" if standardized else "high", "Data types",
            f"{len(bad):,} values in '{col}' are not readable dates",
            f"{_pct(1 - share)} of '{col}' could not be read as a date, e.g. {', '.join(repr(e) for e in examples)}."
            + (" The rest were converted to YYYY-MM-DD HH:MM:SS and these were left as they were." if standardized else
               " Too many failed to parse, so the agent left the whole column unconverted."),
            "Rows with unreadable dates drop out of anything filtered or grouped by date (monthly trends, period totals)"
            + ("" if standardized else ", and the column cannot be sorted or compared as dates at all") + ".",
            f"Confirm the date format used in '{col}' (e.g. day-first vs month-first) and fix the listed values, then re-run.",
            column=col, evidence={"unparseable": len(bad), "examples": examples},
        )

    def _outliers(self, raw, clean, col, history) -> Optional[dict]:
        values = pd.to_numeric(raw[col], errors="coerce").dropna()
        if len(values) < OUTLIER_MIN_ROWS or len(values) < 0.8 * raw[col].notna().sum():
            return None
        negatives = values[values < 0]
        if len(negatives) and any(tok in col for tok in POSITIVE_NAME_TOKENS) and len(negatives) < 0.5 * len(values):
            examples = [_num(v) for v in negatives.head(5)]
            return _issue(
                "negative_values", "medium", "Outliers",
                f"{len(negatives):,} negative values in '{col}'",
                f"'{col}' should not be negative, but {len(negatives):,} value(s) are, e.g. {', '.join(examples)}. "
                "They may be refunds or returns, or data entry errors; the agent cannot tell which.",
                "Negative entries reduce totals and averages; if they are errors, every revenue or quantity figure is understated.",
                f"Confirm whether negative '{col}' values are valid (returns/refunds) or errors, and correct or exclude them.",
                column=col, evidence={"negative": len(negatives), "examples": examples},
            )
        q1, q3 = values.quantile(0.25), values.quantile(0.75)
        iqr = q3 - q1
        if iqr <= 0:
            return None
        low, high = q1 - OUTLIER_FENCE * iqr, q3 + OUTLIER_FENCE * iqr
        extreme = values[(values < low) | (values > high)]
        share = len(extreme) / len(values)
        if not len(extreme) or share > OUTLIER_MAX_SHARE:
            return None
        largest_first = extreme.iloc[extreme.abs().argsort()[::-1]]
        examples = list(dict.fromkeys(_num(v) for v in largest_first))[:5]
        return _issue(
            "outliers", "medium", "Outliers",
            f"{len(extreme):,} extreme values in '{col}'",
            f"{len(extreme):,} value(s) ({_pct(share)}) lie far outside the usual range of '{col}' "
            f"({_num(q1)} to {_num(q3)} for the middle half), e.g. {', '.join(examples)}. "
            "They could be real (a very large order) or errors (an extra zero, wrong unit); the agent kept them.",
            f"A few extreme values dominate sums and averages of '{col}' and can skew charts and models.",
            f"Check the listed values in the source. Correct errors, or confirm they are genuine.",
            column=col, evidence={"extreme": len(extreme), "q1": float(q1), "q3": float(q3), "examples": examples},
        )
