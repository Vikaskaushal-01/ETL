from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session
from sqlalchemy import text
from backend.database.mysql import get_db

router = APIRouter(prefix="/health", tags=["Health"])

@router.get("")
def health_check(response: Response, db: Session = Depends(get_db)):
    db_status = "Healthy"
    try:
        db.execute(text("SELECT 1"))
    except Exception as e:
        db_status = f"Unhealthy: {str(e)}"
        # Load balancers and hosts (e.g. Render's health check) act on the status code
        response.status_code = 503

    return {
        "status": "Healthy" if response.status_code != 503 else "Unhealthy",
        "database": db_status
    }
