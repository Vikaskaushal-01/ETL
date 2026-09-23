import os
from fastapi import APIRouter, Depends, HTTPException, Query, Header
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from backend.database.mysql import get_db
from backend.database.models import GeneratedReport, RawUpload
from backend.schemas.schemas import ReportSummary
from backend.core.security import DEFAULT_ADMIN_EMAIL, is_valid_batch_id
from backend.utils.account_utils import (
    get_user_path, is_path_accessible, resolve_project_path, user_owns_batch
)
from typing import List, Optional

router = APIRouter(prefix="/reports", tags=["Reports"])

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

FORMAT_COLUMNS = {
    "pdf": "pdf_path", "docx": "docx_path", "word": "docx_path",
    "markdown": "markdown_path", "md": "markdown_path", "txt": "markdown_path", "json": "json_path"
}
FORMAT_EXTENSIONS = {"pdf": ".pdf", "docx": ".docx", "word": ".docx", "markdown": ".md", "md": ".md", "txt": ".md", "json": ".json"}
FORMAT_MEDIA = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "word": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "markdown": "text/markdown",
    "md": "text/markdown",
    "txt": "text/plain",
    "json": "application/json"
}


def resolve_report_path(path: str) -> str:
    return resolve_project_path(path)


def _active_email(x_user_email: Optional[str], email: Optional[str] = None) -> str:
    return x_user_email or email or DEFAULT_ADMIN_EMAIL


def _user_reports(db: Session, email: str):
    """Generated reports belonging to batches uploaded by this user, newest first."""
    batch_ids = [b[0] for b in db.query(RawUpload.batch_id).filter(RawUpload.uploaded_by == email).all() if b[0]]
    if not batch_ids:
        return []
    return db.query(GeneratedReport).filter(GeneratedReport.batch_id.in_(batch_ids)).order_by(GeneratedReport.created_at.desc()).all()


def _report_file_response(abs_path: str, fmt: str) -> FileResponse:
    disposition = "attachment" if fmt in ["docx", "word"] else "inline"
    return FileResponse(
        path=abs_path,
        media_type=FORMAT_MEDIA.get(fmt, "application/octet-stream"),
        headers={"Content-Disposition": f'{disposition}; filename="{os.path.basename(abs_path)}"'}
    )


@router.get("/history", response_model=List[ReportSummary])
def get_reports_history(db: Session = Depends(get_db), x_user_email: Optional[str] = Header(None)):
    return _user_reports(db, _active_email(x_user_email))


@router.get("/folders")
def get_reports_by_folder(db: Session = Depends(get_db), x_user_email: Optional[str] = Header(None)):
    """
    Returns the caller's reports grouped by dataset folder with all 4 formats available.
    Combines database metadata with an on-disk scan of the caller's reports directory.
    """
    email = _active_email(x_user_email)
    result = []
    seen_folders = set()

    reports_by_batch = {}
    for r in _user_reports(db, email):
        reports_by_batch.setdefault(r.batch_id, r)

    # 1. Reports registered in the database for the user's uploads
    user_uploads = db.query(RawUpload.batch_id, RawUpload.filename, RawUpload.upload_time).filter(RawUpload.uploaded_by == email).order_by(RawUpload.upload_time.desc()).all()
    for batch_id, filename, upload_time in user_uploads:
        report = reports_by_batch.get(batch_id)
        folder_name = filename or "dataset"
        if not report or folder_name in seen_folders:
            continue
        seen_folders.add(folder_name)
        result.append({
            "batch_id": batch_id,
            "dataset_name": filename,
            "folder_name": folder_name,
            "created_at": report.created_at.isoformat() if report.created_at else (upload_time.isoformat() if upload_time else None),
            "formats": {
                "pdf": (report.pdf_path or "").replace("\\", "/"),
                "docx": (report.docx_path or "").replace("\\", "/"),
                "markdown": (report.markdown_path or "").replace("\\", "/"),
                "json": (report.json_path or "").replace("\\", "/")
            }
        })

    # 2. Report folders present on disk in the user's workspace but missing from the database
    base_rep_dir = os.path.dirname(get_user_path(email, "reports/dummy.txt"))
    if os.path.exists(base_rep_dir):
        for item in sorted(os.listdir(base_rep_dir)):
            item_path = os.path.join(base_rep_dir, item)
            if not os.path.isdir(item_path) or item in seen_folders:
                continue
            files = sorted(os.listdir(item_path), reverse=True)
            pick = lambda ext: next((f for f in files if f.endswith(ext)), "")
            pdf_f, docx_f, md_f, json_f = pick(".pdf"), pick(".docx"), pick(".md"), pick(".json")
            first_f = pdf_f or docx_f or md_f or json_f
            if not first_f:
                continue
            seen_folders.add(item)
            result.append({
                "batch_id": first_f.split("_report.")[0] if "_report." in first_f else None,
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
def get_latest_report(format: str = Query("pdf", enum=list(FORMAT_COLUMNS.keys())), db: Session = Depends(get_db), x_user_email: Optional[str] = Header(None), email: Optional[str] = Query(None)):
    active_email = _active_email(x_user_email, email)
    fmt = format.lower()
    for report in _user_reports(db, active_email):
        path = getattr(report, FORMAT_COLUMNS[fmt]) or ""
        abs_path = resolve_report_path(path)
        if abs_path and os.path.isfile(abs_path) and is_path_accessible(abs_path, active_email):
            return _report_file_response(abs_path, fmt)
    raise HTTPException(status_code=404, detail="No reports found for this account.")


@router.get("/download/{batch_id}")
def download_report_by_batch(batch_id: str, format: str = Query("pdf", enum=list(FORMAT_COLUMNS.keys())), db: Session = Depends(get_db), x_user_email: Optional[str] = Header(None), email: Optional[str] = Query(None)):
    active_email = _active_email(x_user_email, email)
    fmt = format.lower()
    if not is_valid_batch_id(batch_id) or not user_owns_batch(db, batch_id, active_email):
        raise HTTPException(status_code=404, detail=f"Report not found for batch: {batch_id}")

    # 1. Path registered in the database (newest report for the batch)
    path = ""
    report = db.query(GeneratedReport).filter(GeneratedReport.batch_id == batch_id).order_by(GeneratedReport.created_at.desc()).first()
    if report:
        path = getattr(report, FORMAT_COLUMNS[fmt]) or ""

    # 2. Fall back to an exact <batch_id>_report.<ext> file in the owner's reports folder
    if not path or not os.path.isfile(resolve_report_path(path)):
        path = ""
        owner = db.query(RawUpload.uploaded_by).filter(RawUpload.batch_id == batch_id).scalar()
        reports_dir = os.path.dirname(get_user_path(owner, "reports/dummy.txt"))
        target_name = f"{batch_id}_report{FORMAT_EXTENSIONS[fmt]}"
        for root, _, files in os.walk(reports_dir):
            if target_name in files:
                path = os.path.join(root, target_name)
                break

    abs_path = resolve_report_path(path)
    if not abs_path or not os.path.isfile(abs_path) or not is_path_accessible(abs_path, active_email):
        raise HTTPException(status_code=404, detail=f"Report file ({fmt}) not found for batch: {batch_id}")
    return _report_file_response(abs_path, fmt)


@router.get("/download-file")
def download_file(path: str, x_user_email: Optional[str] = Header(None), email: Optional[str] = Query(None)):
    """
    Download a dataset or report file. Only files inside the caller's own workspace are served.
    """
    active_email = _active_email(x_user_email, email)
    if not path:
        raise HTTPException(status_code=400, detail="Path parameter is required.")

    abs_path = resolve_report_path(path)
    if not abs_path or not os.path.isfile(abs_path) or not is_path_accessible(abs_path, active_email):
        raise HTTPException(status_code=404, detail="File not found.")

    filename = os.path.basename(abs_path)
    _, ext = os.path.splitext(filename.lower())
    if ext == ".pdf":
        media_type = "application/pdf"
    elif ext in [".docx", ".doc"]:
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif ext == ".json":
        media_type = "application/json"
    elif ext in [".csv", ".txt", ".tsv", ".xml", ".md", ".sql", ".log"]:
        media_type = "text/plain"
    else:
        media_type = "application/octet-stream"

    disposition = "inline" if ext in [".pdf", ".json"] else "attachment"
    return FileResponse(
        path=abs_path,
        media_type=media_type,
        headers={"Content-Disposition": f'{disposition}; filename="{filename}"'}
    )
