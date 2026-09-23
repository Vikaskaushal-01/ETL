import os
import logging
from fastapi import APIRouter, Depends, HTTPException, Query, Header
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import text, bindparam
from backend.database.mysql import get_db
from backend.database.models import RawUpload
from backend.schemas.schemas import DashboardSummary
from typing import Optional
from backend.core.security import DEFAULT_ADMIN_EMAIL
from backend.utils.account_utils import is_path_accessible, resolve_project_path

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])
logger = logging.getLogger("etl_dashboard_api")


def _iso(value) -> Optional[str]:
    """Raw SQL returns datetimes on MySQL but ISO strings on SQLite."""
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)

@router.get("/summary", response_model=DashboardSummary)
def get_dashboard_summary(db: Session = Depends(get_db), x_user_email: Optional[str] = Header(None)):
    
    # 0. Fetch user's batches from raw_uploads
    try:
        if x_user_email is None:
            user_batches = db.execute(text("SELECT batch_id FROM raw_uploads")).fetchall()
        else:
            user_batches = db.execute(
                text("SELECT batch_id FROM raw_uploads WHERE uploaded_by = :email"),
                {"email": x_user_email}
            ).fetchall()
        batch_ids = [b[0] for b in user_batches if b[0]]
    except Exception as e:
        logger.error(f"Error fetching user batches: {e}")
        batch_ids = []
        
    if not batch_ids:
        return {
            "total_rows_processed": 0,
            "success_rate": 100.0,
            "failed_records": 0,
            "processing_time_avg": 0.0,
            "quality_score_avg": 100.0,
            "active_pipelines": 0,
            "recent_runs": []
        }

    # 1. Active pipelines
    active_count = 0
    try:
        active_count = db.execute(
            text("SELECT COUNT(*) FROM pipeline_logs WHERE status = 'Running' AND pipeline_id IN :pids").bindparams(bindparam("pids", expanding=True)),
            {"pids": [f"pipe_{bid}" for bid in batch_ids]}
        ).scalar() or 0
    except Exception:
        pass

    # 2. Pipeline metrics (runtime, runs)
    avg_runtime = 0.0
    recent_runs = []
    try:
        runs = db.execute(
            text("SELECT pipeline_id, start_time, status, execution_time FROM pipeline_logs WHERE pipeline_id IN :pids ORDER BY start_time DESC LIMIT 10").bindparams(bindparam("pids", expanding=True)),
            {"pids": [f"pipe_{bid}" for bid in batch_ids]}
        ).fetchall()
        runtimes = [r[3] for r in runs if r[3] is not None]
        if runtimes:
            avg_runtime = sum(runtimes) / len(runtimes)
        for r in runs:
            bid = r[0].replace("pipe_", "") if r[0] else ""
            upload_rec = db.query(RawUpload).filter(RawUpload.batch_id == bid).first()
            file_name = upload_rec.filename if upload_rec else f"{bid}.csv"
            recent_runs.append({
                "pipeline_id": r[0],
                "filename": file_name,
                "start_time": _iso(r[1]),
                "status": r[2],
                "execution_time": r[3]
            })
    except Exception as e:
        logger.warning(f"Error compiling recent pipeline runs: {e}")

    # 3. Data quality and record counts
    total_processed = 0
    success_rate = 100.0
    failed_records = 0
    quality_score_avg = 100.0

    try:
        res = db.execute(text("""
            SELECT 
                SUM(missing_values) as missing,
                SUM(duplicate_count) as dups,
                AVG(quality_score) as avg_q
            FROM quality_reports
            WHERE batch_id IN :bids
        """).bindparams(bindparam("bids", expanding=True)), {"bids": list(batch_ids)}).first()
        
        if res and res[2] is not None:
            quality_score_avg = float(res[2])
    except Exception:
        pass

    # Row counts come from the staging tables, which hold every row of the user's batches
    # (including generic datasets) together with its validation outcome.
    try:
        total_loaded = 0
        failed_records = 0
        for staging_table in ["staging_customers", "staging_orders", "staging_sales", "staging_dataset"]:
            counts = db.execute(
                text(f"SELECT validation_status, COUNT(*) FROM {staging_table} WHERE batch_id IN :bids GROUP BY validation_status").bindparams(bindparam("bids", expanding=True)),
                {"bids": list(batch_ids)}
            ).fetchall()
            for status_val, cnt in counts:
                if status_val == "Rejected":
                    failed_records += cnt
                else:
                    total_loaded += cnt
        total_processed = total_loaded + failed_records
        if total_processed > 0:
            success_rate = round((total_loaded / total_processed) * 100, 2)
    except Exception as e:
        logger.warning(f"Error compiling record counts: {e}")

    return {
        "total_rows_processed": total_processed,
        "success_rate": success_rate,
        "failed_records": failed_records,
        "processing_time_avg": round(avg_runtime, 2),
        "quality_score_avg": round(quality_score_avg, 2),
        "active_pipelines": active_count,
        "recent_runs": recent_runs
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
    """
    Download a data file from the processed folders.
    """
    active_email = x_user_email or email or DEFAULT_ADMIN_EMAIL
    abs_path = resolve_project_path(file_path)
    # Only the caller's own workspace files are downloadable (never the database, .env, source code, ...)
    if not abs_path or not os.path.isfile(abs_path) or not is_path_accessible(abs_path, active_email):
        raise HTTPException(status_code=404, detail="File not found.")

    media_type = "application/octet-stream"
    if file_path.endswith(".csv"):
        media_type = "text/csv"
    elif file_path.endswith(".docx"):
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif file_path.endswith(".db"):
        media_type = "application/x-sqlite3"
    elif file_path.endswith(".json"):
        media_type = "application/json"
    elif file_path.endswith(".xml"):
        media_type = "application/xml"
    elif file_path.endswith(".xlsx") or file_path.endswith(".xls"):
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        
    return FileResponse(path=abs_path, media_type=media_type, filename=os.path.basename(file_path))

@router.get("/metrics")
def get_extended_dashboard_metrics(db: Session = Depends(get_db), x_user_email: Optional[str] = Header(None)):
    """
    Computes system throughput, engine health KPIs, and stage latency distribution metrics.
    """
    try:
        if x_user_email is None:
            user_batches = db.execute(text("SELECT batch_id FROM raw_uploads")).fetchall()
        else:
            user_batches = db.execute(
                text("SELECT batch_id FROM raw_uploads WHERE uploaded_by = :email"),
                {"email": x_user_email}
            ).fetchall()
        batch_ids = [b[0] for b in user_batches if b[0]]
    except Exception as e:
        logger.error(f"Error fetching batches for telemetry: {e}")
        batch_ids = []

    total_pipeline_runs = 0
    successful_runs = 0
    failed_runs = 0
    total_execution_seconds = 0.0

    if batch_ids:
        try:
            runs = db.execute(
                text("SELECT status, execution_time FROM pipeline_logs WHERE pipeline_id IN :pids").bindparams(bindparam("pids", expanding=True)),
                {"pids": [f"pipe_{bid}" for bid in batch_ids]}
            ).fetchall()
            total_pipeline_runs = len(runs)
            successful_runs = sum(1 for r in runs if str(r[0]).lower() in ("success", "passed with warnings", "completed"))
            failed_runs = sum(1 for r in runs if str(r[0]).lower() == "failed")
            total_execution_seconds = sum(float(r[1] or 0.0) for r in runs)
        except Exception:
            pass

    avg_latency = (total_execution_seconds / total_pipeline_runs) if total_pipeline_runs > 0 else 0.0
    engine_uptime_pct = round((successful_runs / total_pipeline_runs * 100), 2) if total_pipeline_runs > 0 else 100.0

    return {
        "telemetry": {
            "total_runs": total_pipeline_runs,
            "successful_runs": successful_runs,
            "failed_runs": failed_runs,
            "system_availability_pct": engine_uptime_pct,
            "avg_pipeline_latency_sec": round(avg_latency, 2),
            "engine_status": "Operational",
            "active_nodes": ["IntakeNode", "TransformationNode", "StorageNode", "ReportNode"]
        }
    }


