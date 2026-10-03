"""
Data editor for Human Review: loads an uploaded file as text cells, finds the rows a review problem
refers to, applies a reviewer's edits and writes the file back in its own format, so the pipeline
can process the corrected file on the next run.
"""
import json
import os
import re
from typing import Optional

import pandas as pd

from agents.transformation_agent.transformation_agent import parse_dates, standardize_column_name
from backend.utils.file_utils import detect_file_info, read_dataset

DELIMITED_TYPES = {"csv", "tsv", "txt", "dat"}
EXCEL_TYPES = {"xlsx", "xlsm"}
JSON_TYPES = {"json"}
EDITABLE_TYPES = DELIMITED_TYPES | EXCEL_TYPES | JSON_TYPES
MAX_EDIT_ROWS = int(os.getenv("MAX_EDIT_ROWS", "200000"))
NULL_TOKENS = {"", "nan", "none", "null", "n/a", "na", "-"}
FILL_STRATEGIES = {"value", "mean", "median", "mode", "group_median", "group_mode"}


class EditError(ValueError):
    """A reviewer's edit that cannot be applied; the message is shown to them."""


def file_version(path: str) -> str:
    """Changes whenever the file is rewritten, so stale edits are refused."""
    st = os.stat(path)
    return f"{st.st_mtime_ns}-{st.st_size}"


def file_kind(path: str) -> str:
    return detect_file_info(path)["file_type"].lower()


def is_editable(path: Optional[str]) -> bool:
    return bool(path) and os.path.isfile(path) and file_kind(path) in EDITABLE_TYPES


def load(path: str) -> pd.DataFrame:
    """The file as text cells exactly as written (empty cells are ""), so saving it changes nothing else."""
    kind = file_kind(path)
    if kind not in EDITABLE_TYPES:
        raise EditError(f"{kind.upper()} files cannot be edited here. Convert the file to CSV, Excel or JSON and upload it again.")
    if kind in DELIMITED_TYPES:
        info = detect_file_info(path)
        try:
            df = pd.read_csv(path, sep=info["delimiter"], encoding=info["encoding"], dtype=str, keep_default_na=False, on_bad_lines="skip")
        except UnicodeDecodeError:
            df = pd.read_csv(path, sep=info["delimiter"], encoding="latin1", dtype=str, keep_default_na=False, on_bad_lines="skip")
    elif kind in EXCEL_TYPES:
        df = pd.read_excel(path, dtype=object)
    else:
        df = read_dataset(path)
    if len(df) > MAX_EDIT_ROWS:
        raise EditError(f"The file has {len(df):,} rows; the editor handles up to {MAX_EDIT_ROWS:,}. Fix it in the source instead.")
    df.columns = [str(c) for c in df.columns]
    df = df.astype(object).where(df.notna(), "")
    return df.apply(lambda s: s.map(lambda v: v if isinstance(v, str) else _cell_text(v))).reset_index(drop=True)


def _cell_text(value) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, pd.Timestamp):
        return value.isoformat(sep=" ")
    return str(value)


def _typed(df: pd.DataFrame) -> pd.DataFrame:
    """Text cells back to numbers and nulls for formats that keep types (Excel, JSON)."""
    out = df.copy()
    for col in out.columns:
        values = out[col].astype(str).str.strip()
        empty = values.str.lower().isin(NULL_TOKENS)
        numeric = pd.to_numeric(values.where(~empty), errors="coerce")
        if (~empty).any() and numeric[~empty].notna().all():
            out[col] = numeric.astype(object).where(~empty, None)
            out[col] = out[col].map(lambda v: int(v) if isinstance(v, float) and v.is_integer() else v)
        else:
            out[col] = out[col].where(~empty, None)
    return out


def save(df: pd.DataFrame, path: str) -> None:
    kind = file_kind(path)
    stem, ext = os.path.splitext(path)
    tmp = f"{stem}.editing{ext}"  # written next to the file, then swapped in, so a failed save leaves it intact
    if kind in DELIMITED_TYPES:
        sep = "\t" if kind == "tsv" else detect_file_info(path)["delimiter"]
        df.to_csv(tmp, sep=sep, index=False, encoding="utf-8")
    elif kind in EXCEL_TYPES:
        _typed(df).to_excel(tmp, index=False, engine="openpyxl")
    else:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_typed(df).to_dict(orient="records"), f, indent=2, default=str)
    os.replace(tmp, path)


# ---------- finding rows ----------

def resolve_column(df: pd.DataFrame, name: Optional[str]) -> str:
    """Review problems name columns as the cleaned data does (snake_case); match them to the file's headers."""
    if name in df.columns:
        return name
    for col in df.columns:
        if standardize_column_name(col) == standardize_column_name(name):
            return col
    raise EditError(f"Column '{name}' is not in the file.")


def _missing(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.lower().isin(NULL_TOKENS)


def _numbers(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series.astype(str).str.strip().str.replace(",", "", regex=False), errors="coerce")


def match_rows(df: pd.DataFrame, flt: Optional[dict]) -> pd.Series:
    """Rows matching a review problem's filter, e.g. {"kind": "missing", "column": "income", "group_column": "region", "group": "South"}."""
    if not flt:
        return pd.Series(True, index=df.index)
    kind = flt.get("kind")
    if kind == "duplicate":
        mask = df.duplicated(keep=False)
    else:
        col = df[resolve_column(df, flt.get("column"))]
        missing = _missing(col)
        if kind == "missing":
            mask = missing
        elif kind == "non_numeric":
            mask = ~missing & _numbers(col).isna()
        elif kind == "bad_date":
            mask = ~missing & parse_dates(col.where(~missing)).isna()
        elif kind == "outlier":
            num = _numbers(col)
            mask = (num < float(flt["low"])) | (num > float(flt["high"]))
        elif kind == "negative":
            mask = _numbers(col) < 0
        elif kind == "duplicate_key":
            mask = ~missing & col.duplicated(keep=False)
        elif kind == "value":
            mask = col.astype(str).str.strip() == str(flt.get("value", "")).strip()
        else:
            raise EditError(f"Unknown row filter '{kind}'.")
    if flt.get("group_column"):
        mask = mask & (df[resolve_column(df, flt["group_column"])].astype(str).str.strip() == str(flt.get("group")))
    return mask.fillna(False).astype(bool)


def column_stats(df: pd.DataFrame) -> list:
    stats = []
    for col in df.columns:
        missing = _missing(df[col])
        filled = int((~missing).sum())
        numeric = int(_numbers(df[col][~missing]).notna().sum()) if filled else 0
        stats.append({"name": col, "missing": int(missing.sum()), "numeric": filled > 0 and numeric == filled,
                      "non_numeric": filled - numeric if numeric >= 0.5 * filled else 0})
    return stats


# ---------- applying edits ----------

def _fill_value(df: pd.DataFrame, col: str, strategy: str, missing: pd.Series, value=None, group_by: Optional[str] = None) -> pd.Series:
    observed = df.loc[~missing, col]
    if strategy == "value":
        if value is None or str(value).strip() == "":
            raise EditError("Enter the value to fill the empty cells with.")
        return pd.Series(str(value), index=df.index)
    if strategy in ("mean", "median"):
        nums = _numbers(observed).dropna()
        if nums.empty:
            raise EditError(f"'{col}' has no numbers to take the {strategy} of.")
        return pd.Series(_cell_text(round(float(getattr(nums, strategy)()), 4)), index=df.index)
    if strategy == "mode":
        if observed.empty:
            raise EditError(f"'{col}' has no values to take the most common one of.")
        return pd.Series(observed.astype(str).value_counts().index[0], index=df.index)
    # Per group: each group's own median / most common value, the overall one where a group has none
    group = df[resolve_column(df, group_by)].astype(str)
    overall = _fill_value(df, col, "median" if strategy == "group_median" else "mode", missing)
    fill = overall.copy()
    for key, rows in df[~missing].groupby(group[~missing]):
        if strategy == "group_median":
            nums = _numbers(rows[col]).dropna()
            if not nums.empty:
                fill[group == key] = _cell_text(round(float(nums.median()), 4))
        else:
            fill[group == key] = rows[col].astype(str).value_counts().index[0]
    return fill


def apply_ops(df: pd.DataFrame, ops: list) -> tuple:
    """Applies edits in order; returns the new frame and one plain sentence per edit."""
    summaries = []
    for op in ops:
        name = op.get("op")
        if name == "set_cells":
            changes = op.get("changes") or []
            for change in changes:
                row = int(change["row"])
                if not 0 <= row < len(df):
                    raise EditError(f"Row {row + 1} no longer exists. Reload the data and try again.")
                df.at[row, resolve_column(df, change["column"])] = "" if change.get("value") is None else str(change["value"])
            if changes:
                cols = sorted({resolve_column(df, c["column"]) for c in changes})
                summaries.append(f"Edited {len(changes)} cell(s) in {', '.join(repr(c) for c in cols[:4])}{' and more' if len(cols) > 4 else ''}")
        elif name == "delete_rows":
            rows = sorted({int(r) for r in op.get("rows") or [] if 0 <= int(r) < len(df)})
            if rows:
                df = df.drop(index=rows).reset_index(drop=True)
                summaries.append(f"Deleted {len(rows)} row(s)")
        elif name == "delete_matching":
            mask = match_rows(df, op.get("filter"))
            n = int(mask.sum())
            df = df[~mask].reset_index(drop=True)
            summaries.append(f"Deleted {n} row(s) {describe_filter(op.get('filter'))}")
        elif name == "clear_matching":
            col = resolve_column(df, op.get("column") or (op.get("filter") or {}).get("column"))
            mask = match_rows(df, op.get("filter"))
            df.loc[mask, col] = ""
            summaries.append(f"Emptied {int(mask.sum())} cell(s) of '{col}' {describe_filter(op.get('filter'))}")
        elif name == "fill_missing":
            col = resolve_column(df, op.get("column"))
            strategy = op.get("strategy")
            if strategy not in FILL_STRATEGIES:
                raise EditError(f"Unknown fill method '{strategy}'.")
            missing = _missing(df[col])
            if op.get("filter"):
                missing = missing & match_rows(df, op["filter"])
            fill = _fill_value(df, col, strategy, _missing(df[col]), op.get("value"), op.get("group_by"))
            df.loc[missing, col] = fill[missing]
            how = {"value": f"'{op.get('value')}'", "mean": "the average", "median": "the median", "mode": "the most common value",
                   "group_median": f"the median of each '{op.get('group_by')}' group", "group_mode": f"the most common value of each '{op.get('group_by')}' group"}[strategy]
            summaries.append(f"Filled {int(missing.sum())} empty cell(s) of '{col}' with {how}")
        elif name == "replace_values":
            col = resolve_column(df, op.get("column"))
            find = str(op.get("find", "")).strip()
            if op.get("replace") is None:
                raise EditError(f"Enter what '{find}' should become.")
            mask = df[col].astype(str).str.strip() == find
            df.loc[mask, col] = str(op["replace"])
            summaries.append(f"Replaced '{find}' with '{op['replace']}' in {int(mask.sum())} cell(s) of '{col}'")
        elif name == "standardize_dates":
            col = resolve_column(df, op.get("column"))
            text = df[col].astype(str).str.strip().where(~_missing(df[col]))
            # Year-first dates (2024-02-03) are unambiguous; only the others are read day- or month-first
            year_first = text.str.match(r"^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}").fillna(False).astype(bool)
            parsed = pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns]")
            for rows, dayfirst in ((year_first, False), (~year_first, bool(op.get("dayfirst")))):
                if rows.any():
                    parsed[rows] = pd.to_datetime(text[rows], errors="coerce", dayfirst=dayfirst, format="mixed")
            ok = parsed.notna()
            df.loc[ok, col] = parsed[ok].dt.strftime("%Y-%m-%d")
            summaries.append(f"Rewrote {int(ok.sum())} date(s) in '{col}' as YYYY-MM-DD, reading them {'day' if op.get('dayfirst') else 'month'}-first")
        elif name == "rename_column":
            col = resolve_column(df, op.get("column"))
            new = str(op.get("new_name") or "").strip()
            if not new or new in df.columns:
                raise EditError("Pick a new column name that is not already used.")
            df = df.rename(columns={col: new})
            summaries.append(f"Renamed column '{col}' to '{new}'")
        elif name == "drop_column":
            col = resolve_column(df, op.get("column"))
            df = df.drop(columns=[col])
            summaries.append(f"Removed column '{col}'")
        elif name == "drop_duplicates":
            before = len(df)
            df = df.drop_duplicates().reset_index(drop=True)
            summaries.append(f"Removed {before - len(df)} duplicate row(s)")
        else:
            raise EditError(f"Unknown edit '{name}'.")
    return df, summaries


def describe_filter(flt: Optional[dict]) -> str:
    if not flt:
        return ""
    col = flt.get("column")
    text = {
        "missing": f"where '{col}' is empty",
        "non_numeric": f"where '{col}' is not a number",
        "bad_date": f"where '{col}' is not a readable date",
        "outlier": f"with extreme '{col}' values",
        "negative": f"with negative '{col}'",
        "duplicate": "that are duplicates",
        "duplicate_key": f"with a repeated '{col}'",
        "value": f"where '{col}' is '{flt.get('value')}'",
    }.get(flt.get("kind"), "")
    if flt.get("group_column"):
        text += f" in {flt['group_column']} = '{flt.get('group')}'"
    return text


def reason_filter(reason: str) -> Optional[dict]:
    """Row filter for a storage rejection reason such as "Missing primary key 'customer_id'"."""
    found = re.search(r"'([^']+)'", reason or "")
    if not found:
        return None
    lowered = reason.lower()
    if "missing" in lowered:
        kind = "missing"
    elif "duplicate" in lowered:
        kind = "duplicate_key"
    elif "date" in lowered:
        kind = "bad_date"
    else:
        kind = "non_numeric"
    return {"kind": kind, "column": found.group(1)}
