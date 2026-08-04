import logging
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from backend.database.mysql import engine, Base
from backend.api import health, upload, pipeline, reports, dashboard, chat, auth, powerbi

# Set up storage directories and logging format
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for d in ["logs", "cleaned data", "reports", os.path.join("data", "raw"), os.path.join("data", "processed"), os.path.join("data", "rejected"), os.path.join("data", "archive")]:
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
try:
    logger.info("Initializing database schemas...")
    Base.metadata.create_all(bind=engine)
    logger.info("Database schemas initialized successfully.")
except Exception as e:
    logger.error(f"Error during schema initialization: {e}")

# Initialize FastAPI
app = FastAPI(
    title="Intelligent Autonomous Agentic AI ETL Platform API",
    description="SnapLogic (Commercial Intelligent Integration Platform - SnapLogic IIP) + Multi-Agent AI + LangGraph + FastAPI + MySQL + Power BI Backend System",
    version="1.0.0"
)

# Enable CORS for local dashboards and frontend portals
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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

# Mount frontend files directory
frontend_dir = os.path.abspath("frontend")
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
