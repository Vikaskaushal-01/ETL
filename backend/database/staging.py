import logging
from backend.database.mysql import SessionLocal, engine

logger = logging.getLogger("etl_staging")

def get_staging_db():
    """
    Returns a database session for the staging database operations.
    In this architecture, staging tables reside in the same database schema
    but have a 'staging_' prefix.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
