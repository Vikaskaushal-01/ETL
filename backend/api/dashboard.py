import os
import logging
from fastapi import APIRouter, Depends, HTTPException, Query, Header
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from backend.database.mysql import get_db
from backend.database.models import RawUpload
from backend.schemas.schemas import DashboardSummary
from typing import List, Dict, Any, Optional

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])
logger = logging.getLogger("etl_dashboard_api")

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
            text("SELECT COUNT(*) FROM pipeline_logs WHERE status = 'Running' AND pipeline_id IN :pids"),
            {"pids": tuple(f"pipe_{bid}" for bid in batch_ids)}
        ).scalar() or 0
    except Exception:
        pass

    # 2. Pipeline metrics (runtime, runs)
    avg_runtime = 0.0
    recent_runs = []
    try:
        runs = db.execute(
            text("SELECT pipeline_id, start_time, status, execution_time FROM pipeline_logs WHERE pipeline_id IN :pids ORDER BY start_time DESC LIMIT 10"),
            {"pids": tuple(f"pipe_{bid}" for bid in batch_ids)}
        ).fetchall()
        runtimes = [r[3] for r in runs if r[3] is not None]
        if runtimes:
            avg_runtime = sum(runtimes) / len(runtimes)
        for r in runs:
            recent_runs.append({
                "pipeline_id": r[0],
                "start_time": r[1].isoformat() if r[1] else None,
                "status": r[2],
                "execution_time": r[3]
            })
    except Exception:
        pass

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
        """), {"bids": tuple(batch_ids)}).first()
        
        if res and res[2] is not None:
            quality_score_avg = float(res[2])
    except Exception:
        pass

    try:
        if x_user_email is None:
            cust_cnt = db.execute(text("SELECT COUNT(*) FROM customers")).scalar() or 0
            ord_cnt = db.execute(text("SELECT COUNT(*) FROM orders")).scalar() or 0
            sales_cnt = db.execute(text("SELECT COUNT(*) FROM sales")).scalar() or 0
        else:
            cust_cnt = db.execute(text("SELECT COUNT(*) FROM customers WHERE uploaded_by = :email"), {"email": x_user_email}).scalar() or 0
            ord_cnt = db.execute(text("SELECT COUNT(*) FROM orders WHERE uploaded_by = :email"), {"email": x_user_email}).scalar() or 0
            sales_cnt = db.execute(text("SELECT COUNT(*) FROM sales WHERE uploaded_by = :email"), {"email": x_user_email}).scalar() or 0
        cust_rej = 0
        ord_rej = 0
        sales_rej = 0
        try:
            cust_rej = db.execute(
                text("SELECT COUNT(*) FROM staging_customers WHERE validation_status = 'Rejected' AND batch_id IN :bids"),
                {"bids": tuple(batch_ids)}
            ).scalar() or 0
        except Exception:
            pass
        try:
            ord_rej = db.execute(
                text("SELECT COUNT(*) FROM staging_orders WHERE validation_status = 'Rejected' AND batch_id IN :bids"),
                {"bids": tuple(batch_ids)}
            ).scalar() or 0
        except Exception:
            pass
        try:
            sales_rej = db.execute(
                text("SELECT COUNT(*) FROM staging_sales WHERE validation_status = 'Rejected' AND batch_id IN :bids"),
                {"bids": tuple(batch_ids)}
            ).scalar() or 0
        except Exception:
            pass
            
        val_fails = cust_rej + ord_rej + sales_rej
        
        total_loaded = cust_cnt + ord_cnt + sales_cnt
        failed_records = val_fails
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

@router.get("/datasets")
def list_datasets(x_user_email: Optional[str] = Header(None)):
    """
    Scans the user-specific clean data directory and returns a list of processed files.
    """
    files_list = []
    from backend.utils.account_utils import get_user_path
    
    clean_dir = os.path.dirname(get_user_path(x_user_email or "admin@controlai.net", "cleaned data/dummy.txt"))
    
    if os.path.exists(clean_dir):
        for file in os.listdir(clean_dir):
            file_path = os.path.join(clean_dir, file)
            if os.path.isfile(file_path):
                try:
                    stat_res = os.stat(file_path)
                    _, ext = os.path.splitext(file.lower())
                    fmt = ext[1:].upper()
                    if fmt == "XLSX" or fmt == "XLS":
                        fmt = "EXCEL"
                    files_list.append({
                        "name": file,
                        "directory": "cleaned data/",
                        "path": file_path.replace("\\", "/"),
                        "format": fmt,
                        "size": stat_res.st_size,
                        "modified_time": stat_res.st_mtime * 1000
                    })
                except Exception as e:
                    logger.error(f"Failed stating file {file}: {e}")
                        
    return {"files": files_list}

@router.get("/download")
def download_dataset(file_path: str, x_user_email: Optional[str] = Header(None), email: Optional[str] = Query(None)):
    """
    Download a data file from the processed folders.
    """
    active_email = x_user_email or email or "admin@controlai.net"
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found.")
        
    abs_path = os.path.abspath(file_path)
    workspace_root = os.path.abspath(".")
    if not abs_path.replace("\\", "/").startswith(workspace_root.replace("\\", "/")):
        raise HTTPException(status_code=403, detail="Access denied: outside workspace path.")
        
    # Ownership check: if the path is inside Accounts/, ensure it matches active_email's folder
    if "Accounts" in abs_path.replace("\\", "/").split("/"):
        sanitized_email = active_email.replace("@", "_").replace(".", "_")
        if f"Accounts/{sanitized_email}" not in abs_path.replace("\\", "/"):
            raise HTTPException(status_code=403, detail="Access denied: file belongs to another user account.")
        
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
