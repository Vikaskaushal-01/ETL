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
        user_batches = db.query(RawUpload.batch_id).all()
        batch_ids = [b[0] for b in user_batches if b[0]]
    if not batch_ids:
        return db.query(GeneratedReport).order_by(GeneratedReport.created_at.desc()).all()
    reports = db.query(GeneratedReport).filter(GeneratedReport.batch_id.in_(batch_ids)).order_by(GeneratedReport.created_at.desc()).all()
    if not reports:
        reports = db.query(GeneratedReport).order_by(GeneratedReport.created_at.desc()).all()
    return reports

@router.get("/folders")
def get_reports_by_folder(db: Session = Depends(get_db), x_user_email: Optional[str] = Header(None)):
    """
    Returns reports grouped by the cleaned file folder with all 4 formats available.
    Combines database metadata with on-disk filesystem reports scanning.
    """
    email = x_user_email or "admin@controlai.net"
    from backend.database.models import RawUpload
    from backend.utils.account_utils import get_user_path
    
    result = []
    seen_folders = set()
    
    # 1. First check DB uploads
    user_uploads = db.query(RawUpload.batch_id, RawUpload.filename, RawUpload.upload_time).filter(RawUpload.uploaded_by == email).order_by(RawUpload.upload_time.desc()).all()
    if not user_uploads:
        user_uploads = db.query(RawUpload.batch_id, RawUpload.filename, RawUpload.upload_time).order_by(RawUpload.upload_time.desc()).all()
        
    for batch_id, filename, upload_time in user_uploads:
        if not batch_id:
            continue
        folder_name = filename or "dataset"
        if folder_name in seen_folders:
            continue
            
        report = db.query(GeneratedReport).filter(GeneratedReport.batch_id == batch_id).first()
        if report:
            seen_folders.add(folder_name)
            result.append({
                "batch_id": batch_id,
                "dataset_name": filename,
                "folder_name": folder_name,
                "created_at": report.created_at.isoformat() if report.created_at else (upload_time.isoformat() if upload_time else None),
                "formats": {
                    "pdf": report.pdf_path,
                    "docx": report.docx_path,
                    "markdown": report.markdown_path,
                    "json": report.json_path
                }
            })
            
    # 2. Check all generated_reports records in database
    all_reports = db.query(GeneratedReport).order_by(GeneratedReport.created_at.desc()).all()
    for report in all_reports:
        bid = report.batch_id
        folder_name = "dataset"
        if report.pdf_path:
            parts = report.pdf_path.replace("\\", "/").split("/")
            if len(parts) >= 2 and parts[-2] != "reports":
                folder_name = parts[-2]
        if folder_name not in seen_folders:
            seen_folders.add(folder_name)
            result.append({
                "batch_id": bid,
                "dataset_name": folder_name,
                "folder_name": folder_name,
                "created_at": report.created_at.isoformat() if report.created_at else None,
                "formats": {
                    "pdf": report.pdf_path,
                    "docx": report.docx_path,
                    "markdown": report.markdown_path,
                    "json": report.json_path
                }
            })

    # 3. Check filesystem reports/ directory and account subdirectories
    reports_dirs_to_check = [
        os.path.join(PROJECT_ROOT, "reports"),
        os.path.dirname(get_user_path(email, "reports/dummy.txt"))
    ]
    for base_rep_dir in reports_dirs_to_check:
        if os.path.exists(base_rep_dir):
            for item in os.listdir(base_rep_dir):
                item_path = os.path.join(base_rep_dir, item)
                if os.path.isdir(item_path) and item not in seen_folders:
                    files = os.listdir(item_path)
                    pdf_f = next((f for f in files if f.endswith(".pdf")), "")
                    docx_f = next((f for f in files if f.endswith(".docx")), "")
                    md_f = next((f for f in files if f.endswith(".md")), "")
                    json_f = next((f for f in files if f.endswith(".json")), "")
                    
                    if pdf_f or docx_f or md_f or json_f:
                        first_f = pdf_f or docx_f or md_f or json_f
                        bid = first_f.split("_report.")[0] if "_report." in first_f else "batch_latest"
                        seen_folders.add(item)
                        result.append({
                            "batch_id": bid,
                            "dataset_name": item,
                            "folder_name": item,
                            "created_at": None,
                            "formats": {
                                "pdf": os.path.join(item_path, pdf_f).replace("\\", "/") if pdf_f else "",
                                "docx": os.path.join(item_path, docx_f).replace("\\", "/") if docx_f else "",
                                "markdown": os.path.join(item_path, md_f).replace("\\", "/") if md_f else "",
                                "json": os.path.join(item_path, json_f).replace("\\", "/") if json_f else ""
                            }
                        })
                        
    return result

@router.get("/latest")
def get_latest_report(format: str = Query("pdf", enum=["pdf", "markdown", "json", "docx", "word", "md", "txt"]), db: Session = Depends(get_db), x_user_email: Optional[str] = Header(None), email: Optional[str] = Query(None)):
    active_email = x_user_email or email or "admin@controlai.net"
    from backend.database.models import RawUpload
    user_batches = db.query(RawUpload.batch_id).filter(RawUpload.uploaded_by == active_email).all()
    batch_ids = [b[0] for b in user_batches if b[0]]
    if not batch_ids:
        user_batches = db.query(RawUpload.batch_id).all()
        batch_ids = [b[0] for b in user_batches if b[0]]
        
    latest = None
    if batch_ids:
        latest = db.query(GeneratedReport).filter(GeneratedReport.batch_id.in_(batch_ids)).order_by(GeneratedReport.created_at.desc()).first()
    if not latest:
        latest = db.query(GeneratedReport).order_by(GeneratedReport.created_at.desc()).first()
        
    path = ""
    fmt = format.lower()
    if latest:
        if fmt == "pdf":
            path = latest.pdf_path
        elif fmt in ["docx", "word"]:
            path = latest.docx_path
        elif fmt in ["markdown", "md", "txt"]:
            path = latest.markdown_path
        elif fmt == "json":
            path = latest.json_path
            
    if not path or not os.path.exists(resolve_report_path(path)):
        ext_map = {"pdf": ".pdf", "docx": ".docx", "word": ".docx", "markdown": ".md", "md": ".md", "txt": ".md", "json": ".json"}
        target_ext = ext_map.get(fmt, ".pdf")
        for root, dirs, files in os.walk(os.path.join(PROJECT_ROOT, "reports")):
            for f in files:
                if f.endswith(target_ext):
                    path = os.path.join(root, f)
                    break
            if path and os.path.exists(path):
                break
                
    abs_path = resolve_report_path(path)
    if not abs_path or not os.path.exists(abs_path):
        raise HTTPException(status_code=404, detail="No reports found on disk.")
        
    media_map = {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "word": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "markdown": "text/plain",
        "md": "text/plain",
        "json": "application/json"
    }
    media_type = media_map.get(fmt, "application/octet-stream")
    headers = {"Content-Disposition": f"inline; filename={os.path.basename(abs_path)}"}
    if fmt in ["docx", "word"]:
        headers = {"Content-Disposition": f"attachment; filename={os.path.basename(abs_path)}"}
        
    return FileResponse(
        path=abs_path,
        media_type=media_type,
        headers=headers
    )

@router.get("/download/{batch_id}")
def download_report_by_batch(batch_id: str, format: str = Query("pdf", enum=["pdf", "markdown", "json", "docx", "word", "md", "txt"]), db: Session = Depends(get_db), x_user_email: Optional[str] = Header(None), email: Optional[str] = Query(None)):
    active_email = x_user_email or email or "admin@controlai.net"
    fmt = format.lower()
    
    # 1. Query database
    report = db.query(GeneratedReport).filter(GeneratedReport.batch_id == batch_id).first()
    path = ""
    if report:
        if fmt == "pdf":
            path = report.pdf_path
        elif fmt in ["docx", "word"]:
            path = report.docx_path
        elif fmt in ["markdown", "md", "txt"]:
            path = report.markdown_path
        elif fmt == "json":
            path = report.json_path
            
    # 2. If not in DB or path missing, search filesystem
    if not path or not os.path.exists(resolve_report_path(path)):
        ext_map = {"pdf": ".pdf", "docx": ".docx", "word": ".docx", "markdown": ".md", "md": ".md", "txt": ".md", "json": ".json"}
        target_ext = ext_map.get(fmt, ".pdf")
        for root, dirs, files in os.walk(os.path.join(PROJECT_ROOT, "reports")):
            for f in files:
                if (batch_id in f or "_report" in f) and f.endswith(target_ext):
                    path = os.path.join(root, f)
                    break
            if path and os.path.exists(path):
                break

    abs_path = resolve_report_path(path)
    if not abs_path or not os.path.exists(abs_path):
        raise HTTPException(status_code=404, detail=f"Report file ({fmt}) not found for batch: {batch_id}")
        
    media_map = {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "word": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "markdown": "text/plain",
        "md": "text/plain",
        "json": "application/json"
    }
    media_type = media_map.get(fmt, "application/octet-stream")
    headers = {"Content-Disposition": f"inline; filename={os.path.basename(abs_path)}"}
    if fmt in ["docx", "word"]:
        headers = {"Content-Disposition": f"attachment; filename={os.path.basename(abs_path)}"}
        
    return FileResponse(
        path=abs_path,
        media_type=media_type,
        headers=headers
    )

@router.get("/download-file")
def download_file(path: str, db: Session = Depends(get_db), x_user_email: Optional[str] = Header(None), email: Optional[str] = Query(None)):
    """
    Safely download any dataset or report file from allowed directories.
    """
    active_email = x_user_email or email or "admin@controlai.net"
    if not path:
        raise HTTPException(status_code=400, detail="Path parameter is required.")
        
    abs_path = resolve_report_path(path)
    if not abs_path or not os.path.exists(abs_path):
        raise HTTPException(status_code=404, detail="File not found on disk.")
        
    # Ownership check: if the path is inside Accounts/, ensure it matches active_email's folder
    if "Accounts" in abs_path.replace("\\", "/").split("/"):
        sanitized_email = active_email.replace("@", "_").replace(".", "_")
        if f"Accounts/{sanitized_email}" not in abs_path.replace("\\", "/"):
            raise HTTPException(status_code=403, detail="Access denied: file belongs to another user account.")
        
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

