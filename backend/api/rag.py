import os
import logging
import uuid
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from backend.database.mysql import get_db
from backend.database.models import RagDocument

router = APIRouter(prefix="/rag", tags=["RAG Knowledge Base"])
logger = logging.getLogger("etl_rag")

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RAG_DIR = os.path.join(PROJECT_ROOT, "data", "rag_documents")

def extract_text_from_pdf(file_path: str) -> str:
    text = ""
    # Try PyMuPDF (fitz)
    try:
        import fitz
        doc = fitz.open(file_path)
        for page in doc:
            t = page.get_text()
            if t:
                text += t + "\n"
        doc.close()
        if text.strip():
            logger.info("Extracted text successfully using PyMuPDF.")
            return text
    except Exception as e:
        logger.warning(f"PyMuPDF failed to extract text: {e}. Trying pypdf fallback...")
    
    # Try pypdf fallback
    try:
        from pypdf import PdfReader
        reader = PdfReader(file_path)
        for page in reader.pages:
            t = page.extract_text()
            if t:
                text += t + "\n"
        if text.strip():
            logger.info("Extracted text successfully using pypdf fallback.")
            return text
    except Exception as ex:
        logger.error(f"pypdf fallback failed: {ex}")
    
    return ""

def extract_text_from_docx(file_path: str) -> str:
    try:
        import docx
        doc = docx.Document(file_path)
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        logger.info("Extracted text successfully from DOCX.")
        return "\n".join(paragraphs)
    except Exception as e:
        logger.error(f"docx extraction failed: {e}")
        return ""

def extract_text_from_plain(file_path: str) -> str:
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            logger.info("Extracted plain text file.")
            return f.read()
    except Exception as e:
        logger.error(f"Plain text extraction failed: {e}")
        return ""

@router.post("/upload")
async def upload_rag_document(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    Upload a document (PDF, DOCX, TXT, MD, CSV, JSON) to RAG memory.
    Extracts text and saves the record in db.
    """
    os.makedirs(RAG_DIR, exist_ok=True)
    filename = file.filename
    _, ext = os.path.splitext(filename.lower())
    file_type = ext[1:] if ext else "unknown"
    
    allowed_types = ["pdf", "docx", "txt", "md", "csv", "json"]
    if file_type not in allowed_types:
        raise HTTPException(
            status_code=400, 
            detail=f"Unsupported file type: {file_type}. Supported types: {', '.join(allowed_types)}"
        )
    
    # Generate unique filename on disk to avoid conflicts
    unique_id = str(uuid.uuid4())[:8]
    base_name, _ = os.path.splitext(filename)
    safe_filename = f"{base_name}_{unique_id}{ext}"
    file_path = os.path.join(RAG_DIR, safe_filename)
    
    try:
        with open(file_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)
    except Exception as e:
        logger.error(f"Failed to save RAG file: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save file on disk: {str(e)}")
    
    # Check file size limit (10MB)
    file_size = os.path.getsize(file_path)
    if file_size > 10 * 1024 * 1024:
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=400, detail="File size exceeds 10MB limit.")
    
    # Extract content
    extracted_content = ""
    if file_type == "pdf":
        extracted_content = extract_text_from_pdf(file_path)
    elif file_type == "docx":
        extracted_content = extract_text_from_docx(file_path)
    else:
        extracted_content = extract_text_from_plain(file_path)
        
    if not extracted_content.strip():
        # If extraction was empty, don't fail, but log warning
        logger.warning(f"No textual content could be extracted from {filename}")
        extracted_content = "[No text content found in document]"
        
    # Save database entry
    try:
        db_doc = RagDocument(
            filename=filename,
            file_type=file_type,
            file_path=f"data/rag_documents/{safe_filename}",
            content=extracted_content
        )
        db.add(db_doc)
        db.commit()
        db.refresh(db_doc)
    except Exception as db_err:
        if os.path.exists(file_path):
            os.remove(file_path)
        logger.error(f"Database registration for RAG doc failed: {db_err}")
        raise HTTPException(status_code=500, detail=f"Database registration failed: {str(db_err)}")
        
    return {
        "status": "Success",
        "id": db_doc.id,
        "filename": db_doc.filename,
        "file_type": db_doc.file_type,
        "upload_time": db_doc.upload_time
    }

@router.get("/documents")
def list_rag_documents(db: Session = Depends(get_db)):
    """
    List all documents in RAG knowledge base.
    """
    try:
        docs = db.query(RagDocument).order_by(RagDocument.upload_time.desc()).all()
        return [
            {
                "id": d.id,
                "filename": d.filename,
                "file_type": d.file_type,
                "file_path": d.file_path,
                "upload_time": d.upload_time,
                "word_count": len(d.content.split()) if d.content else 0
            }
            for d in docs
        ]
    except Exception as e:
        logger.error(f"Failed to list RAG documents: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/documents/{doc_id}")
def delete_rag_document(doc_id: int, db: Session = Depends(get_db)):
    """
    Delete a document from RAG knowledge base.
    """
    try:
        doc = db.query(RagDocument).filter(RagDocument.id == doc_id).first()
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        
        # Delete file from disk
        full_path = os.path.join(PROJECT_ROOT, doc.file_path)
        if os.path.exists(full_path):
            try:
                os.remove(full_path)
                logger.info(f"Deleted physical file from disk: {full_path}")
            except Exception as fe:
                logger.warning(f"Could not delete physical file: {fe}")
                
        # Delete db record
        db.delete(doc)
        db.commit()
        return {"status": "Success", "message": f"Document {doc_id} deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete RAG document: {e}")
        raise HTTPException(status_code=500, detail=str(e))
