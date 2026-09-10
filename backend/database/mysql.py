import os
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("etl_database")

MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = os.getenv("MYSQL_PORT", "3306")
MYSQL_DB = os.getenv("MYSQL_DB", "agentic_ai_etl")
MYSQL_USER = os.getenv("MYSQL_USER", "etl_user")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "etl_password")

# Attempt to configure MySQL connection
DATABASE_URL = f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}"

engine = None
SessionLocal = None
Base = declarative_base()

try:
    # Try connecting to MySQL with a short timeout (2s) to prevent startup freezing
    engine = create_engine(
        DATABASE_URL, 
        pool_pre_ping=True,
        connect_args={"connect_timeout": 2}
    )
    # Test connection
    with engine.connect() as conn:
        logger.info("Successfully connected to MySQL database.")
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
except Exception as e:
    logger.warning(f"MySQL connection failed: {e}. Falling back to local SQLite database.")
    # Fallback to local SQLite with WAL mode for fast concurrent operations
    SQLITE_URL = "sqlite:///./agentic_ai_etl.db"
    engine = create_engine(SQLITE_URL, connect_args={"check_same_thread": False, "timeout": 30})
    from sqlalchemy import event
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        try:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()
        except Exception:
            pass
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
