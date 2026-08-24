import os
from fastapi import APIRouter, Depends, HTTPException, Query, Header
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from backend.database.mysql import get_db
from backend.database.models import GeneratedReport
from backend.schemas.schemas import ReportSummary
from typing import List, Optional

router = APIRouter(prefix="/reports", tags=["Reports"])

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

def resolve_report_path(path: str) -> str:
    if not path:
        return ""
    if os.path.isabs(path):
        return os.path.abspath(path)
    return os.path.abspath(os.path.join(PROJECT_ROOT, path))

@router.get("/history", response_model=List[ReportSummary])
def get_reports_history(db: Session = Depends(get_db), x_user_email: Optional[str] = Header(None)):
    email = x_user_email or "admin@controlai.net"
    from backend.database.models import RawUpload
    user_batches = db.query(RawUpload.batch_id).filter(RawUpload.uploaded_by == email).all()
    batch_ids = [b[0] for b in user_batches if b[0]]
    if not batch_ids:
        return []
    reports = db.query(GeneratedReport).filter(GeneratedReport.batch_id.in_(batch_ids)).order_by(GeneratedReport.created_at.desc()).all()
    return reports

@router.get("/latest")
def get_latest_report(format: str = Query("pdf", enum=["pdf", "txt", "markdown", "json", "docx"]), db: Session = Depends(get_db), x_user_email: Optional[str] = Header(None)):
    email = x_user_email or "admin@controlai.net"
    from backend.database.models import RawUpload
    user_batches = db.query(RawUpload.batch_id).filter(RawUpload.uploaded_by == email).all()
    batch_ids = [b[0] for b in user_batches if b[0]]
    if not batch_ids:
        raise HTTPException(status_code=404, detail="No reports generated yet.")
        
    latest = db.query(GeneratedReport).filter(GeneratedReport.batch_id.in_(batch_ids)).order_by(GeneratedReport.created_at.desc()).first()
    if not latest:
        raise HTTPException(status_code=404, detail="No reports generated yet.")
        
    if format == "pdf":
        path = latest.pdf_path
        media_type = "application/pdf"
    elif format == "txt":
        path = latest.txt_path
        media_type = "text/plain"
    elif format == "docx":
        path = latest.docx_path
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif format == "markdown":
        path = latest.markdown_path
        media_type = "text/plain"  # set to text/plain for inline viewing in browser
    elif format == "json":
        path = latest.json_path
        media_type = "application/json"
    else:
        raise HTTPException(status_code=400, detail="Invalid format requested.")
        
    abs_path = resolve_report_path(path)
    if not abs_path or not os.path.exists(abs_path):
        raise HTTPException(status_code=404, detail=f"Report file not found on disk at {path}.")
        
    headers = {"Content-Disposition": f"inline; filename={os.path.basename(abs_path)}"}
    if format == "docx":
        headers = {"Content-Disposition": f"attachment; filename={os.path.basename(abs_path)}"}
        
    return FileResponse(
        path=abs_path,
        media_type=media_type,
        headers=headers
    )

@router.get("/download/{batch_id}")
def download_report_by_batch(batch_id: str, format: str = Query("pdf", enum=["pdf", "txt", "markdown", "json", "docx"]), db: Session = Depends(get_db), x_user_email: Optional[str] = Header(None)):
    email = x_user_email or "admin@controlai.net"
    from backend.database.models import RawUpload
    from sqlalchemy import text
    try:
        uploaded_by = db.execute(text("SELECT uploaded_by FROM raw_uploads WHERE batch_id = :b LIMIT 1"), {"b": batch_id}).scalar()
        if uploaded_by and uploaded_by != email:
            raise HTTPException(status_code=403, detail="Access denied: report does not belong to your account.")
    except HTTPException:
        raise
    except Exception:
        pass

    report = db.query(GeneratedReport).filter(GeneratedReport.batch_id == batch_id).first()
    if not report:
        raise HTTPException(status_code=404, detail=f"No report found for batch: {batch_id}")
        
    if format == "pdf":
        path = report.pdf_path
        media_type = "application/pdf"
    elif format == "txt":
        path = report.txt_path
        media_type = "text/plain"
    elif format == "docx":
        path = report.docx_path
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif format == "markdown":
        path = report.markdown_path
        media_type = "text/plain"  # set to text/plain for inline viewing in browser
    elif format == "json":
        path = report.json_path
        media_type = "application/json"
    else:
        raise HTTPException(status_code=400, detail="Invalid format requested.")
        
    abs_path = resolve_report_path(path)
    if not abs_path or not os.path.exists(abs_path):
        raise HTTPException(status_code=404, detail="Report file not found on disk.")
        
    headers = {"Content-Disposition": f"inline; filename={os.path.basename(abs_path)}"}
    if format == "docx":
        headers = {"Content-Disposition": f"attachment; filename={os.path.basename(abs_path)}"}
        
    return FileResponse(
        path=abs_path,
        media_type=media_type,
        headers=headers
    )

@router.get("/download-file")
def download_file(path: str, db: Session = Depends(get_db)):
    """
    Safely download any dataset or report file from allowed directories.
    """
    if not path:
        raise HTTPException(status_code=400, detail="Path parameter is required.")
        
    abs_path = resolve_report_path(path)
    if not abs_path or not os.path.exists(abs_path):
        raise HTTPException(status_code=404, detail="File not found on disk.")
        
    # Security check: verify that the path lies within one of the approved folders in PROJECT_ROOT
    allowed_folders = ["data", "cleaned data", "reports", "logs", "Accounts"]
    is_allowed = False
    for folder in allowed_folders:
        allowed_abs = os.path.abspath(os.path.join(PROJECT_ROOT, folder))
        if abs_path.startswith(allowed_abs):
            is_allowed = True
            break
            
    if not is_allowed:
        raise HTTPException(status_code=403, detail="Access denied. Directory not allowed.")
        
    filename = os.path.basename(abs_path)
    _, ext = os.path.splitext(filename.lower())
    if ext == ".pdf":
        media_type = "application/pdf"
    elif ext in [".docx", ".doc"]:
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif ext == ".json":
        media_type = "application/json"
    elif ext in [".csv", ".txt", ".tsv", ".xml"]:
        media_type = "text/plain"
    else:
        media_type = "application/octet-stream"
        
    headers = {"Content-Disposition": f"attachment; filename={filename}"}
    if ext in [".pdf", ".json", ".xml"]:
        headers = {"Content-Disposition": f"inline; filename={filename}"}
        
    return FileResponse(
        path=abs_path,
        media_type=media_type,
        headers=headers
    )

