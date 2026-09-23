import os
import logging
from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("etl_database")

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = os.getenv("MYSQL_PORT", "3306")
MYSQL_DB = os.getenv("MYSQL_DB", "agentic_ai_etl")
MYSQL_USER = os.getenv("MYSQL_USER", "etl_user")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "etl_password")

# DATABASE_URL overrides the MySQL settings entirely (used by tests and custom deployments)
DATABASE_URL = os.getenv("DATABASE_URL") or f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}"
SQLITE_URL = f"sqlite:///{os.path.join(PROJECT_ROOT, 'agentic_ai_etl.db')}"

engine = None
SessionLocal = None
Base = declarative_base()


def _create_sqlite_engine(url: str):
    sqlite_engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})

    @event.listens_for(sqlite_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        try:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()
        except Exception:
            pass

    return sqlite_engine


if DATABASE_URL.startswith("sqlite"):
    engine = _create_sqlite_engine(DATABASE_URL)
else:
    try:
        # Try connecting to MySQL with a short timeout (2s) to prevent startup freezing
        engine = create_engine(
            DATABASE_URL,
            pool_pre_ping=True,
            connect_args={"connect_timeout": 2}
        )
        with engine.connect():
            logger.info("Successfully connected to MySQL database.")
    except Exception as e:
        logger.warning(f"MySQL connection failed: {e}. Falling back to local SQLite database.")
        # Anchored to the project root so the database does not depend on the working directory
        engine = _create_sqlite_engine(SQLITE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def is_sqlite() -> bool:
    return engine.dialect.name == "sqlite"


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_database_health() -> dict:
    """Evaluates real-time database connection latency and engine dialect."""
    import time
    from sqlalchemy import text
    start = time.time()
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        latency_ms = round((time.time() - start) * 1000, 2)
        return {
            "status": "Healthy",
            "dialect": engine.dialect.name,
            "latency_ms": latency_ms,
            "connected": True
        }
    except Exception as exc:
        return {
            "status": "Unhealthy",
            "dialect": "unknown",
            "error": str(exc),
            "connected": False
        }
