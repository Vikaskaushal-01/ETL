"""
Run management on top of the History: compare two runs, export the history as CSV
and preview and profile a run's dataset.
"""
import csv
import io
import json
import logging
import os
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from backend.api.pipeline import (
    _require_batch_access, list_runs
)
from backend.database.models import RawUpload
from backend.database.mysql import get_db
from backend.utils.file_utils import read_dataset

router = APIRouter(prefix="/history", tags=["Run Management"])
logger = logging.getLogger("etl_runs_api")

# Metrics shown side by side when comparing two runs: (key, label, higher is better)
COMPARE_METRICS = [
    ("rows", "Input rows", None),
    ("columns", "Columns", None),
    ("rows_loaded", "Rows loaded", True),
    ("rows_rejected", "Rows rejected", False),
    ("quality_before", "Quality before (%)", True),
    ("quality_after", "Quality after (%)", True),
    ("execution_time", "Runtime (s)", False),
]
EXPORT_COLUMNS = [
    "batch_id", "filename", "source", "status", "uploaded_at", "started_at", "ended_at", "execution_time",
    "rows", "columns", "rows_loaded", "rows_rejected", "quality_before", "quality_after", "format_selected",
]
PROFILE_SAMPLE_ROWS = 5000


def _dataset_path(run: dict) -> Optional[str]:
    """The cleaned dataset of a run, or its raw upload when cleaning has not produced one."""
    for path in (run.get("clean_file"), run.get("raw_file")):
        if path and os.path.isfile(path):
            return path
    return None


def _get_run(db: Session, batch_id: str, email: Optional[str]) -> dict:
    _require_batch_access(db, batch_id, email)
    owner = db.query(RawUpload.uploaded_by).filter(RawUpload.batch_id == batch_id).scalar()
    runs = list_runs(db, owner, batch_ids=[batch_id])
    if not runs:
        raise HTTPException(status_code=404, detail=f"Batch not found: {batch_id}")
    return runs[0]


def _column_profile(df: pd.DataFrame) -> list:
    profile = []
    for col in df.columns:
        series = df[col]
        non_null = int(series.notna().sum())
        entry = {
            "name": str(col),
            "dtype": str(series.dtype),
            "non_null": non_null,
            "null_pct": round(100 * (1 - non_null / len(df)), 1) if len(df) else 0.0,
            "unique": int(series.nunique(dropna=True)),
        }
        if pd.api.types.is_numeric_dtype(series) and non_null:
            entry.update(min=float(series.min()), max=float(series.max()), mean=round(float(series.mean()), 4))
        elif non_null:
            top = series.astype(str).value_counts().head(1)
            entry["top"] = {"value": top.index[0], "count": int(top.iloc[0])}
        profile.append(entry)
    return profile


@router.get("/compare")
def compare_runs(a: str, b: str, db: Session = Depends(get_db), x_user_email: Optional[str] = Header(None)):
    """Side-by-side metrics of two runs plus the columns that differ between their datasets."""
    if a == b:
        raise HTTPException(status_code=400, detail="Pick two different runs to compare.")
    run_a, run_b = _get_run(db, a, x_user_email), _get_run(db, b, x_user_email)

    metrics = []
    for key, label, higher_is_better in COMPARE_METRICS:
        va, vb = run_a.get(key), run_b.get(key)
        delta = round(vb - va, 4) if isinstance(va, (int, float)) and isinstance(vb, (int, float)) else None
        better = None
        if delta and higher_is_better is not None:
            better = "b" if (delta > 0) == higher_is_better else "a"
        metrics.append({"key": key, "label": label, "a": va, "b": vb, "delta": delta, "better": better})

    def columns_of(run):
        path = _dataset_path(run)
        try:
            return [str(c) for c in read_dataset(path, nrows=1).columns] if path else []
        except Exception as e:
            logger.warning(f"Could not read columns of {path}: {e}")
            return []

    cols_a, cols_b = columns_of(run_a), columns_of(run_b)
    summary = lambda r: {k: r.get(k) for k in ("batch_id", "filename", "status", "started_at")}
    return {
        "a": summary(run_a),
        "b": summary(run_b),
        "metrics": metrics,
        "schema": {
            "shared": [c for c in cols_a if c in cols_b],
            "only_in_a": [c for c in cols_a if c not in cols_b],
            "only_in_b": [c for c in cols_b if c not in cols_a],
        },
    }


@router.get("/export")
def export_history(db: Session = Depends(get_db), x_user_email: Optional[str] = Header(None)):
    """The caller's run history as a CSV file."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=EXPORT_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(list_runs(db, x_user_email, limit=1000))
    return Response(
        buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="pipeline_run_history.csv"'},
    )


@router.get("/{batch_id}/preview")
def preview_run_dataset(batch_id: str, rows: int = Query(50, ge=1, le=500), db: Session = Depends(get_db),
                        x_user_email: Optional[str] = Header(None)):
    """First rows of a run's dataset plus a per-column profile (types, nulls, distinct values, ranges)."""
    run = _get_run(db, batch_id, x_user_email)
    path = _dataset_path(run)
    if not path:
        raise HTTPException(status_code=404, detail="This run has no dataset file on disk.")
    try:
        df = read_dataset(path, nrows=PROFILE_SAMPLE_ROWS)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Could not read the dataset: {e}")
    return {
        "batch_id": batch_id,
        "filename": run.get("filename"),
        "source": "cleaned" if path == run.get("clean_file") else "raw",
        "total_rows": run.get("rows") or len(df),
        "profiled_rows": len(df),
        "columns": _column_profile(df),
        # to_json turns NaN/NaT/numpy values into plain JSON
        "rows": json.loads(df.head(rows).to_json(orient="records", date_format="iso", default_handler=str)),
    }

