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
