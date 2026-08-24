import os
import uuid
from typing import Optional
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from backend.database.mysql import get_db
from backend.database.repository import create_raw_upload
from backend.core.config import get_settings
from backend.utils.account_utils import get_user_path

router = APIRouter(prefix="/upload", tags=["Upload"])

@router.post("")
async def upload_file(file: UploadFile = File(...), db: Session = Depends(get_db), x_user_email: Optional[str] = Header(None)):
    # Save file under user account directory
    filename = file.filename
    file_id = str(uuid.uuid4())[:8]
    file_path = get_user_path(x_user_email, os.path.join("data", "raw", filename))
    
    try:
        with open(file_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")
        
    # Infer file type
    _, ext = os.path.splitext(file.filename.lower())
    file_type = ext[1:]
    
    # Insert raw_uploads metadata
    try:
        upload_record = create_raw_upload(
            db, 
            filename=filename, 
            source="API_Upload", 
            file_type=file_type,
            batch_id=f"batch_{file_id}",
            uploaded_by=x_user_email
        )
    except Exception as db_err:
        # cleanup saved file if db record fails
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=500, detail=f"Database registration failed: {str(db_err)}")
        
    return {
        "status": "Success",
        "upload_id": upload_record.id,
        "batch_id": f"batch_{file_id}",
        "filename": filename,
        "file_path": file_path.replace("\\", "/")
    }
