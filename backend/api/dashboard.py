import logging
import mimetypes
import os
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from backend.core.security import DEFAULT_ADMIN_EMAIL
from backend.database.models import STAGING_TABLES
from backend.database.mysql import get_db
from backend.schemas.schemas import DashboardSummary
from backend.utils.account_utils import is_path_accessible, resolve_project_path

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])
logger = logging.getLogger("etl_dashboard_api")

SUCCESS_STATUSES = ("success", "passed with warnings", "completed")


def _iso(value) -> Optional[str]:
    """Raw SQL returns datetimes on MySQL but ISO strings on SQLite."""
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _as_datetime(value) -> Optional[datetime]:
    if value is None or isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _visible_batch_ids(db: Session, email: Optional[str]) -> list:
    """The caller's batches; every batch for a service call made without a user."""
    if email is None:
        rows = db.execute(text("SELECT batch_id FROM raw_uploads")).fetchall()
    else:
        rows = db.execute(text("SELECT batch_id FROM raw_uploads WHERE uploaded_by = :e"), {"e": email}).fetchall()
    return [r[0] for r in rows if r[0]]


def _runs(db: Session, batch_ids: list, columns: str, suffix: str = "") -> list:
    """Selected pipeline_logs columns for these batches."""
    if not batch_ids:
        return []
    return db.execute(
        text(f"SELECT {columns} FROM pipeline_logs WHERE pipeline_id IN :pids {suffix}").bindparams(bindparam("pids", expanding=True)),
        {"pids": [f"pipe_{b}" for b in batch_ids]},
    ).fetchall()


def _quality_by_batch(db: Session, batch_ids: list) -> dict:
    if not batch_ids:
        return {}
    rows = db.execute(
        text("SELECT batch_id, AVG(quality_score) FROM quality_reports WHERE batch_id IN :b GROUP BY batch_id").bindparams(bindparam("b", expanding=True)),
        {"b": batch_ids},
    ).fetchall()
    return {r[0]: float(r[1]) for r in rows if r[1] is not None}


@router.get("/summary", response_model=DashboardSummary)
def get_dashboard_summary(db: Session = Depends(get_db), x_user_email: Optional[str] = Header(None)):
    batch_ids = _visible_batch_ids(db, x_user_email)
    if not batch_ids:
        return DashboardSummary(total_rows_processed=0, success_rate=100.0, failed_records=0, processing_time_avg=0.0,
                                quality_score_avg=100.0, active_pipelines=0, recent_runs=[])

    runs = _runs(db, batch_ids, "pipeline_id, start_time, status, execution_time", "ORDER BY start_time DESC")
    filenames = dict(db.execute(
        text("SELECT batch_id, filename FROM raw_uploads WHERE batch_id IN :b").bindparams(bindparam("b", expanding=True)),
        {"b": [r[0][5:] for r in runs[:10]] or [""]},
    ).fetchall())
    recent_runs = [{
        "pipeline_id": r[0],
        "filename": filenames.get(r[0][5:], f"{r[0][5:]}.csv"),
        "start_time": _iso(r[1]),
        "status": r[2],
        "execution_time": r[3],
    } for r in runs[:10]]
    runtimes = [r[3] for r in runs[:10] if r[3] is not None]

    quality_avg = db.execute(
        text("SELECT AVG(quality_score) FROM quality_reports WHERE batch_id IN :b").bindparams(bindparam("b", expanding=True)),
        {"b": batch_ids},
    ).scalar()

    # Row counts come from the staging tables, which hold every row of the user's batches
    # (including generic datasets) together with its validation outcome.
    loaded = rejected = 0
    for table in STAGING_TABLES:
        try:
            counts = db.execute(
                text(f"SELECT validation_status, COUNT(*) FROM {table} WHERE batch_id IN :b GROUP BY validation_status").bindparams(bindparam("b", expanding=True)),
                {"b": batch_ids},
            ).fetchall()
        except Exception as e:
            logger.warning(f"Could not count rows in {table}: {e}")
            continue
        for status, count in counts:
            if status == "Rejected":
                rejected += count
            else:
                loaded += count
    total = loaded + rejected

    return DashboardSummary(
        total_rows_processed=total,
        success_rate=round(loaded / total * 100, 2) if total else 100.0,
        failed_records=rejected,
        processing_time_avg=round(sum(runtimes) / len(runtimes), 2) if runtimes else 0.0,
        quality_score_avg=round(float(quality_avg), 2) if quality_avg is not None else 100.0,
        active_pipelines=sum(1 for r in runs if r[2] == "Running"),
        recent_runs=recent_runs,
    )


@router.get("/trends")
def get_dashboard_trends(days: int = Query(14, ge=1, le=90), db: Session = Depends(get_db), x_user_email: Optional[str] = Header(None)):
    """Runs per day (succeeded / failed), average runtime and average data quality over the last `days` days."""
    batch_ids = _visible_batch_ids(db, x_user_email)
    today = datetime.utcnow().date()
    first_day = today - timedelta(days=days - 1)
    buckets = defaultdict(lambda: {"runs": 0, "succeeded": 0, "failed": 0, "runtimes": [], "qualities": []})
    quality = _quality_by_batch(db, batch_ids)

    for pipeline_id, start, status, runtime in _runs(db, batch_ids, "pipeline_id, start_time, status, execution_time"):
        started = _as_datetime(start)
        if not started or started.date() < first_day:
            continue
        day = buckets[started.date()]
        day["runs"] += 1
        if str(status).lower() in SUCCESS_STATUSES:
            day["succeeded"] += 1
        elif str(status).lower() == "failed":
            day["failed"] += 1
        if runtime is not None:
            day["runtimes"].append(float(runtime))
        if pipeline_id[5:] in quality:
            day["qualities"].append(quality[pipeline_id[5:]])

    series = []
    for offset in range(days):
        date = first_day + timedelta(days=offset)
        day = buckets.get(date) or buckets.default_factory()
        series.append({
            "date": date.isoformat(),
            "runs": day["runs"],
            "succeeded": day["succeeded"],
            "failed": day["failed"],
            "avg_runtime": round(sum(day["runtimes"]) / len(day["runtimes"]), 2) if day["runtimes"] else None,
            "avg_quality": round(sum(day["qualities"]) / len(day["qualities"]), 2) if day["qualities"] else None,
        })
    total_runs = sum(d["runs"] for d in series)
    return {
        "days": days,
        "series": series,
        "totals": {
            "runs": total_runs,
            "succeeded": sum(d["succeeded"] for d in series),
            "failed": sum(d["failed"] for d in series),
            "busiest_day": max(series, key=lambda d: d["runs"])["date"] if total_runs else None,
        },
    }


_FORMAT_ALIASES = {"XLSX": "EXCEL", "XLS": "EXCEL", "DOCX": "WORD", "MD": "MARKDOWN"}
# Workspace folders shown in the Storage explorer: (relative folder, category)
_STORAGE_FOLDERS = [
    ("data/raw", "raw"),
    ("cleaned data", "cleaned"),
    ("reports", "report"),
    ("logs", "log"),
    ("powerbi", "powerbi"),
]


@router.get("/datasets")
def list_datasets(x_user_email: Optional[str] = Header(None)):
    """
    Lists every file in the caller's workspace: raw uploads, cleaned datasets, reports,
    process logs and Power BI exports, each tagged with its category.
    """
    from backend.utils.account_utils import get_user_path
    active_email = x_user_email or DEFAULT_ADMIN_EMAIL
    files_list = []
    for folder, category in _STORAGE_FOLDERS:
        base_dir = os.path.dirname(get_user_path(active_email, f"{folder}/dummy.txt"))
        for root, _, filenames in os.walk(base_dir):
            for file in sorted(filenames):
                file_path = os.path.join(root, file)
                if category == "powerbi" and not file.endswith(".csv"):
                    continue
                try:
                    stat_res = os.stat(file_path)
                except OSError as e:
                    logger.error(f"Failed stating file {file_path}: {e}")
                    continue
                ext = os.path.splitext(file.lower())[1][1:].upper() or "FILE"
                rel_dir = os.path.relpath(root, base_dir).replace("\\", "/")
                files_list.append({
                    "name": file,
                    "category": category,
                    "directory": f"{folder}/" if rel_dir == "." else f"{folder}/{rel_dir}/",
                    "path": file_path.replace("\\", "/"),
                    "format": _FORMAT_ALIASES.get(ext, ext),
                    "size": stat_res.st_size,
                    "modified_time": stat_res.st_mtime * 1000
                })
    files_list.sort(key=lambda f: f["modified_time"], reverse=True)
    return {"files": files_list}


@router.get("/download")
def download_dataset(file_path: str, x_user_email: Optional[str] = Header(None), email: Optional[str] = Query(None)):
    """Downloads a file from the caller's own workspace."""
    active_email = x_user_email or email or DEFAULT_ADMIN_EMAIL
    abs_path = resolve_project_path(file_path)
    # Only the caller's own workspace files are downloadable (never the database, .env, source code, ...)
    if not abs_path or not os.path.isfile(abs_path) or not is_path_accessible(abs_path, active_email):
        raise HTTPException(status_code=404, detail="File not found.")
    media_type = mimetypes.guess_type(abs_path)[0] or "application/octet-stream"
    return FileResponse(path=abs_path, media_type=media_type, filename=os.path.basename(file_path))


@router.get("/metrics")
def get_extended_dashboard_metrics(db: Session = Depends(get_db), x_user_email: Optional[str] = Header(None)):
    """Run telemetry: totals, availability and average latency."""
    runs = _runs(db, _visible_batch_ids(db, x_user_email), "status, execution_time")
    total = len(runs)
    successful = sum(1 for r in runs if str(r[0]).lower() in SUCCESS_STATUSES)
    total_seconds = sum(float(r[1] or 0.0) for r in runs)
    return {
        "telemetry": {
            "total_runs": total,
            "successful_runs": successful,
            "failed_runs": sum(1 for r in runs if str(r[0]).lower() == "failed"),
            "system_availability_pct": round(successful / total * 100, 2) if total else 100.0,
            "avg_pipeline_latency_sec": round(total_seconds / total, 2) if total else 0.0,
            "engine_status": "Operational",
            "active_nodes": ["IntakeNode", "TransformationNode", "StorageNode", "ReportNode"]
        }
    }
