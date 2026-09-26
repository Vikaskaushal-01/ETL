import hmac
import logging
import os
from urllib.parse import parse_qsl, urlencode
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from backend.database.mysql import engine, Base
from typing import Optional
from backend.core.security import API_KEY_PREFIX, hash_api_key, verify_token
from backend import __version__
from backend.api import health, upload, pipeline, reports, dashboard, chat, auth, powerbi, rag

# Set up storage directories and logging format
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for d in ["logs", "cleaned data", "reports", os.path.join("data", "raw"), os.path.join("data", "processed"), os.path.join("data", "rejected"), os.path.join("data", "archive"), os.path.join("data", "rag_documents")]:
    os.makedirs(os.path.join(PROJECT_ROOT, d), exist_ok=True)

logs_dir = os.path.join(PROJECT_ROOT, "logs")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(logs_dir, "etl_platform.log"), encoding="utf-8")
    ]
)
logger = logging.getLogger("etl_main")

# Auto-create tables (SQLite fallback or MySQL connection initialized)
def _add_missing_columns():
    """create_all() never alters existing tables, so add columns introduced after a database was created."""
    from sqlalchemy import inspect, text
    inspector = inspect(engine)
    for table in Base.metadata.sorted_tables:
        if not inspector.has_table(table.name):
            continue
        existing = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name not in existing and column.nullable:
                ddl_type = column.type.compile(dialect=engine.dialect)
                with engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE {table.name} ADD COLUMN {column.name} {ddl_type}"))
                logger.info(f"Added missing column {table.name}.{column.name}")


try:
    logger.info("Initializing database schemas...")
    import backend.database.models  # noqa: F401 - registers every table on Base.metadata
    Base.metadata.create_all(bind=engine)
    _add_missing_columns()
    logger.info("Database schemas initialized successfully.")
except Exception as e:
    logger.error(f"Error during schema initialization: {e}")

# Initialize FastAPI
app = FastAPI(
    title="Intelligent Autonomous Agentic AI ETL Platform API",
    description="SnapLogic (Commercial Intelligent Integration Platform - SnapLogic IIP) + Multi-Agent AI + LangGraph + FastAPI + MySQL + Power BI Backend System",
    version=__version__
)

# Endpoints reachable without a session token
PUBLIC_API_PREFIXES = ("/api/v1/auth/", "/api/v1/health")
# Machine-to-machine key for SnapLogic / automation callers (optional)
SERVICE_API_KEY = os.getenv("SERVICE_API_KEY", "")


def _email_for_api_key(secret: str) -> Optional[str]:
    """Resolves a per-user API key (created in Settings > API Keys) and records its usage."""
    from datetime import datetime
    from backend.database.mysql import SessionLocal
    from backend.database.models import ApiKey
    db = SessionLocal()
    try:
        key = db.query(ApiKey).filter(ApiKey.key_hash == hash_api_key(secret), ApiKey.revoked == False).first()  # noqa: E712
        if not key:
            return None
        key.last_used_at = datetime.utcnow()
        key.request_count = (key.request_count or 0) + 1
        db.commit()
        return key.user_email
    finally:
        db.close()


class AuthIdentityMiddleware:
    """
    Authenticates every /api/v1 request and pins the caller identity.

    Browsers send `Authorization: Bearer <token>` (or `?token=` for plain download links).
    The verified email then replaces any client supplied `X-User-Email` header and `email`
    query parameter, so route handlers can keep reading those while no longer trusting them.
    Users may instead send one of their own API keys as `X-API-Key: cai_...`; service callers
    presenting SERVICE_API_KEY via `X-API-Key` may act on behalf of `X-User-Email`.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] != "http" or not path.startswith("/api/v1/") or path.startswith(PUBLIC_API_PREFIXES) or scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return

        headers = {k.decode("latin1").lower(): v.decode("latin1") for k, v in scope.get("headers", [])}
        query = parse_qsl(scope.get("query_string", b"").decode("latin1"), keep_blank_values=True)

        token = None
        auth_header = headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()
        if not token:
            token = next((v for k, v in query if k == "token"), None)

        email = verify_token(token)
        if not email and headers.get("x-api-key", "").startswith(API_KEY_PREFIX):
            email = _email_for_api_key(headers["x-api-key"])
        if not email and SERVICE_API_KEY and hmac.compare_digest(headers.get("x-api-key", ""), SERVICE_API_KEY):
            email = headers.get("x-user-email") or None
            if email is None:
                await self.app(scope, receive, send)
                return

        if not email:
            response = JSONResponse({"detail": "Not authenticated. Please sign in."}, status_code=401)
            await response(scope, receive, send)
            return

        scope = dict(scope)
        scope["headers"] = [(k, v) for k, v in scope.get("headers", []) if k.lower() not in (b"x-user-email",)]
        scope["headers"].append((b"x-user-email", email.encode("latin1")))
        query = [(k, v) for k, v in query if k not in ("email", "token")] + [("email", email)]
        scope["query_string"] = urlencode(query).encode("latin1")
        await self.app(scope, receive, send)


app.add_middleware(AuthIdentityMiddleware)

# The UI is served from this same origin; extra origins can be allowed explicitly.
cors_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
if cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Register endpoints
app.include_router(health.router, prefix="/api/v1")
app.include_router(upload.router, prefix="/api/v1")
app.include_router(pipeline.router, prefix="/api/v1")
app.include_router(reports.router, prefix="/api/v1")
app.include_router(dashboard.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1")
app.include_router(powerbi.router, prefix="/api/v1")
app.include_router(rag.router, prefix="/api/v1")

# Mount frontend files directory (anchored to the project root, independent of the working directory)
frontend_dir = os.path.join(PROJECT_ROOT, "frontend")
os.makedirs(frontend_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

@app.get("/", response_class=HTMLResponse)
def index():
    index_html_path = os.path.join(frontend_dir, "index.html")
    if os.path.exists(index_html_path):
        with open(index_html_path, "r", encoding="utf-8") as f:
            return f.read()
    return """
    <html>
        <body>
            <h1>ETL Platform Backend Online</h1>
            <p>Frontend assets are building. Access APIs at <a href="/docs">/docs</a></p>
        </body>
    </html>
    """

# Fallback mount for relative static files (style.css, app.js) at root
app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend_root")
