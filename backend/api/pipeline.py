import os
import time
import logging
import json
import threading
import uuid
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Header, Response
from sqlalchemy.orm import Session
from sqlalchemy import text, bindparam
from typing import Optional
from backend.database.mysql import get_db
from backend.database.models import PipelineLog, QualityReport, RootCauseReport
from backend.database.repository import log_pipeline_start, log_pipeline_end, update_raw_upload_status_by_batch
from backend.schemas.schemas import PipelineStartRequest, PipelineStartResponse
from backend.core.security import is_valid_batch_id
from backend.utils.account_utils import (
    get_user_path, get_user_batch_ids, is_admin, is_path_accessible, user_owns_batch
)
from agents_graph.graph import compiled_graph

# Import Agents directly for SnapLogic endpoints
from agents.intake_agent.intake_agent import IntakeAgent
from agents.transformation_agent.transformation_agent import TransformationAgent
from agents.storage_agent.storage_agent import StorageAgent
from agents.report_agent.report_agent import ReportAgent

router = APIRouter(tags=["Pipeline"])
logger = logging.getLogger("etl_pipeline_api")

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
STAGE_IDS = ["intake", "transformation", "storage", "report", "pbi"]
# A run still marked Running after this long is considered abandoned (e.g. the server restarted mid-run)
STALE_PIPELINE_SECONDS = int(os.getenv("STALE_PIPELINE_SECONDS", "1800"))

_state_lock = threading.RLock()


def get_pipeline_state_path(pipeline_id: str) -> str:
    if not is_valid_batch_id(pipeline_id):
        raise ValueError(f"Invalid pipeline id: {pipeline_id!r}")
    return os.path.join(PROJECT_ROOT, "logs", f"{pipeline_id}_state.json")


def pipeline_state_exists(pipeline_id: str) -> bool:
    try:
        return os.path.exists(get_pipeline_state_path(pipeline_id))
    except ValueError:
        return False


def _empty_stage() -> dict:
    return {
        "status": "waiting",
        "start_time": None,
        "end_time": None,
        "input": {},
        "output": {},
        "logs": [],
        "metadata": {}
    }


def _new_pipeline_state(pipeline_id: str) -> dict:
    return {
        "pipeline_id": pipeline_id,
        "status": "Running",
        "start_time": datetime.utcnow().isoformat(),
        "end_time": None,
        "execution_time": 0.0,
        "stages": {stage_id: _empty_stage() for stage_id in STAGE_IDS}
    }


def read_pipeline_state(pipeline_id: str) -> dict:
    path = get_pipeline_state_path(pipeline_id)
    if os.path.exists(path):
        for _ in range(3):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (OSError, json.JSONDecodeError):
                time.sleep(0.05)
    return _new_pipeline_state(pipeline_id)

def clean_json_value(v):
    import math
    from datetime import date
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    elif hasattr(v, "item"): # numpy scalar types
        try:
            return clean_json_value(v.item())
        except Exception:
            return str(v)
    elif isinstance(v, (datetime, date)):
        return v.isoformat()
    elif isinstance(v, dict):
        return {k: clean_json_value(val) for k, val in v.items()}
    elif isinstance(v, (list, tuple)):
        return [clean_json_value(item) for item in v]
    else:
        return v

def write_pipeline_state(pipeline_id: str, state: dict):
    """Writes atomically (temp file + replace) so concurrent pollers never read a half-written file."""
    path = get_pipeline_state_path(pipeline_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    cleaned_state = clean_json_value(state)
    tmp_path = f"{path}.{uuid.uuid4().hex[:6]}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(cleaned_state, f, indent=2, default=str)
        for _ in range(10):
            try:
                os.replace(tmp_path, path)
                return
            except PermissionError:
                # Windows refuses to replace a file that a poller has open; retry briefly
                time.sleep(0.05)
        os.replace(tmp_path, path)
    except Exception as e:
        logger.error(f"Failed to write pipeline state file: {e}")
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

def update_pipeline_stage(pipeline_id: str, stage_id: str, status: str, **kwargs):
    with _state_lock:
        state = read_pipeline_state(pipeline_id)
        stage = state["stages"].setdefault(stage_id, _empty_stage())
        stage["status"] = status
        if status == "processing":
            stage["start_time"] = datetime.utcnow().isoformat()
        elif status in ["completed", "failed"]:
            stage["end_time"] = datetime.utcnow().isoformat()

        for k, v in kwargs.items():
            if k == "logs":
                # Accumulate so the "started" lines are kept alongside the "completed"/"failed" lines
                stage["logs"] = (stage.get("logs") or []) + list(v or [])
            else:
                stage[k] = v

        write_pipeline_state(pipeline_id, state)

def update_pipeline_overall_status(pipeline_id: str, status: str, execution_time: float = None, error: str = None):
    with _state_lock:
        state = read_pipeline_state(pipeline_id)
        state["status"] = status
        state["end_time"] = datetime.utcnow().isoformat()
        if execution_time is not None:
            state["execution_time"] = execution_time
        if error:
            state["error"] = error
        write_pipeline_state(pipeline_id, state)

def build_process_log(pipeline_id: str, batch_id: str, filename: str, uploaded_by: Optional[str], summary_logs: list = None) -> str:
    """Full human-readable process log: run header, every stage's timeline and log lines, agent summaries."""
    state = read_pipeline_state(pipeline_id)
    lines = [
        "=" * 78,
        f"ETL PROCESS LOG  |  File: {filename}",
        "=" * 78,
        f"Batch ID     : {batch_id}",
        f"Pipeline ID  : {pipeline_id}",
        f"Uploaded by  : {uploaded_by or '-'}",
        f"Status       : {state.get('status')}",
        f"Started (UTC): {state.get('start_time')}",
        f"Ended (UTC)  : {state.get('end_time')}",
        f"Duration     : {float(state.get('execution_time') or 0.0):.2f}s",
        "",
    ]
    stage_titles = {
        "intake": "1. DATA INTAKE & PROFILING",
        "transformation": "2. DATA CLEANSING & TRANSFORMATION",
        "storage": "3. STORAGE, STAGING & DATABASE LOAD",
        "report": "4. ROOT CAUSE ANALYSIS & REPORT GENERATION",
        "pbi": "5. POWER BI DATASET REFRESH",
    }
    for stage_id in STAGE_IDS:
        stage = state.get("stages", {}).get(stage_id, {})
        lines.append(f"--- {stage_titles[stage_id]} [{str(stage.get('status', 'waiting')).upper()}] ---")
        if stage.get("start_time"):
            lines.append(f"    {stage.get('start_time')} -> {stage.get('end_time') or '...'}")
        for log_line in stage.get("logs", []):
            lines.append(f"  * {log_line}")
        output = stage.get("output") or {}
        for key in ("rows", "columns", "estimated_quality", "quality_before", "quality_after", "rows_loaded", "rows_rejected", "format_selected", "pdf_path", "docx_path"):
            if output.get(key) not in (None, ""):
                lines.append(f"    {key}: {output[key]}")
        lines.append("")
    if summary_logs:
        lines.append("--- AGENT EXECUTION SUMMARY ---")
        lines.extend(f"  * {line}" for line in summary_logs)
        lines.append("")
    if state.get("error"):
        lines.append(f"!!! RUNTIME ERROR: {state['error']}")
    return "\n".join(lines) + "\n"


def save_pipeline_logs_to_file(batch_id: str, logs: list, raw_file_path: str = None, uploaded_by: Optional[str] = None):
    """
    Writes the process log as logs/<batch_id>.log and logs/<file name>.log in the project, and as
    logs/<file name>.log inside the uploader's workspace (listed in the UI's Storage explorer).
    """
    try:
        filename = os.path.basename(raw_file_path) if raw_file_path else batch_id
        content = build_process_log(f"pipe_{batch_id}", batch_id, filename, uploaded_by, logs)
        targets = [os.path.join(PROJECT_ROOT, "logs", f"{batch_id}.log")]
        if raw_file_path:
            targets.append(os.path.join(PROJECT_ROOT, "logs", f"{filename}.log"))
        if uploaded_by:
            targets.append(get_user_path(uploaded_by, f"logs/{filename}.log"))
        for target in targets:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "w", encoding="utf-8") as f:
                f.write(content)
        logger.info(f"Saved pipeline process log for {filename} to: {', '.join(targets)}")
    except Exception as le:
        logger.error(f"Failed to save execution logs to file: {le}")

def run_langgraph_pipeline(file_path: str, batch_id: str, pipeline_id: str):
    """
    Background worker that runs the LangGraph state machine sequentially.
    """
    logger.info(f"Starting background pipeline run: {pipeline_id}")
    db = SessionLocal_helper()
    uploaded_by = None

    start_time = time.time()
    try:
        # Initialize LangGraph state
        initial_state = {
            "dataset_name": os.path.basename(file_path),
            "dataset_path": file_path,
            "batch_id": batch_id,
            "metadata": {},
            "schema": {},
            "column_types": {},
            "missing_values": {},
            "duplicate_rows": 0,
            "transformation_history": [],
            "validation_results": {},
            "staging_status": "Pending",
            "mysql_status": "Pending",
            "quality_score": 0.0,
            "root_cause_report": [],
            "business_summary": "",
            "generated_reports": {},
            "dashboard_status": "Pending",
            "execution_logs": [f"Pipeline initialized. Batch ID: {batch_id}."],
            "pipeline_status": "Running",
            "format_selected": "Pending",
            "formatted_file_path": "Pending",
            "storage_reason": "Pending",
            "storage_status": "Pending"
        }

        uploaded_by = db.execute(text("SELECT uploaded_by FROM raw_uploads WHERE batch_id = :b LIMIT 1"), {"b": batch_id}).scalar()

        # Log start in DB
        log_pipeline_start(db, pipeline_id)
        update_raw_upload_status_by_batch(db, batch_id, "Processing")

        # Execute LangGraph compiled workflow
        final_state = compiled_graph.invoke(initial_state)

        execution_time = time.time() - start_time
        status = final_state.get("pipeline_status", "Success")

        # Write DB log update
        log_pipeline_end(db, pipeline_id, status, execution_time)
        update_raw_upload_status_by_batch(db, batch_id, "Failed" if status == "Failed" else "Processed")
        update_pipeline_overall_status(pipeline_id, status, execution_time)

        logger.info(f"Pipeline run finished in {execution_time:.2f}s with status {status}")

        # Save pipeline execution logs to disk
        logs_list = final_state.get("execution_logs", [])
        save_pipeline_logs_to_file(batch_id, logs_list, file_path, uploaded_by)

        if status in ["Success", "Passed with Warnings"]:
            try:
                backup_path = os.path.join(PROJECT_ROOT, ".last_cleaned_backup.json")
                backup_data = {
                    "batch_id": batch_id,
                    "filename": os.path.basename(file_path),
                    "timestamp": time.time(),
                    "quality_score": final_state.get("quality_score", 100.0),
                    "logs": "\n".join(logs_list),
                    "reports": final_state.get("generated_reports", {})
                }
                with open(backup_path, "w", encoding="utf-8") as bf:
                    json.dump(backup_data, bf, indent=2, default=str)
                logger.info(f"Cached last cleaned file metadata to: {backup_path}")
            except Exception as cache_err:
                logger.error(f"Failed to cache run metadata: {cache_err}")

    except Exception as e:
        execution_time = time.time() - start_time
        logger.exception(f"LangGraph execution crashed: {e}")
        try:
            db.rollback()
            log_pipeline_end(db, pipeline_id, "Failed", execution_time)
            update_raw_upload_status_by_batch(db, batch_id, "Failed")
            db.execute(text("INSERT INTO validation_logs (batch_id, validation_type, status, message) VALUES (:b, 'Pipeline', 'Failed', :m)"), {
                "b": batch_id,
                "m": f"Runtime Crash: {str(e)}"
            })
            db.commit()
        except Exception as inner_err:
            logger.error(f"Failed to log crash to DB: {inner_err}")
        update_pipeline_overall_status(pipeline_id, "Failed", execution_time, error=str(e))

        # Save crash log (same file names as a successful run, so failures are just as easy to find)
        save_pipeline_logs_to_file(batch_id, [
            f"Pipeline run initialized. Batch ID: {batch_id}.",
            f"Runtime Crash: {str(e)}"
        ], file_path, uploaded_by)
    finally:
        db.close()

def SessionLocal_helper():
    from backend.database.mysql import SessionLocal
    return SessionLocal()


def _require_batch_access(db: Session, batch_id: str, email: Optional[str]):
    if not is_valid_batch_id(batch_id):
        raise HTTPException(status_code=400, detail="Invalid batch id.")
    if not user_owns_batch(db, batch_id, email):
        raise HTTPException(status_code=404, detail=f"Batch not found: {batch_id}")


def _require_accessible_file(file_path: Optional[str], email: Optional[str], label: str = "File") -> str:
    """Only files inside the caller's own workspace may be fed into the pipeline."""
    if not file_path:
        raise HTTPException(status_code=400, detail=f"{label} path is required.")
    abs_path = os.path.abspath(file_path if os.path.isabs(file_path) else os.path.join(PROJECT_ROOT, file_path))
    if not os.path.isfile(abs_path) or not is_path_accessible(abs_path, email):
        raise HTTPException(status_code=404, detail=f"{label} not found: {file_path}")
    return abs_path.replace("\\", "/")


def _user_batch_filter(db: Session, email: Optional[str]) -> Optional[list]:
    """Batch ids visible to the caller, or None for the administrator (who sees everything)."""
    return None if is_admin(email) else get_user_batch_ids(db, email)


@router.post("/pipeline/start", response_model=PipelineStartResponse)
def start_pipeline(req: PipelineStartRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db), x_user_email: Optional[str] = Header(None)):
    file_path = _require_accessible_file(req.file_path, x_user_email)

    if req.batch_id:
        _require_batch_access(db, req.batch_id, x_user_email)
        batch_id = req.batch_id
    else:
        # Started from a bare file path: register it so the run is owned by the caller
        from backend.database.repository import create_raw_upload
        batch_id = f"batch_{uuid.uuid4().hex[:8]}"
        _, ext = os.path.splitext(file_path.lower())
        create_raw_upload(db, filename=os.path.basename(file_path), source="API_Pipeline_Start", file_type=ext[1:], batch_id=batch_id, uploaded_by=x_user_email)
    pipeline_id = f"pipe_{batch_id}"

    # Auto-recover stale running pipelines (e.g. interrupted by a server restart)
    stale_cutoff = datetime.utcnow() - timedelta(seconds=STALE_PIPELINE_SECONDS)
    stale_runs = db.query(PipelineLog).filter(
        PipelineLog.status == "Running",
        PipelineLog.start_time < stale_cutoff
    ).all()
    for sr in stale_runs:
        sr.status = "Failed"
        sr.end_time = datetime.utcnow()
    if stale_runs:
        db.commit()

    # Refuse to start a second concurrent run of the same batch
    existing = db.query(PipelineLog).filter(PipelineLog.pipeline_id == pipeline_id).first()
    if existing and existing.status == "Running":
        raise HTTPException(status_code=409, detail=f"Pipeline {pipeline_id} is already running.")

    # Initialize a fresh stage state file for this pipeline run
    with _state_lock:
        write_pipeline_state(pipeline_id, _new_pipeline_state(pipeline_id))

    background_tasks.add_task(run_langgraph_pipeline, file_path, batch_id, pipeline_id)

    return {
        "pipeline_id": pipeline_id,
        "status": "Running",
        "batch_id": batch_id,
        "dataset_name": os.path.basename(file_path)
    }

# --- SnapLogic HTTP Orchestration Agent Endpoints ---

@router.post("/pipeline/intake")
def run_intake_agent_endpoint(payload: dict, db: Session = Depends(get_db), x_user_email: Optional[str] = Header(None)):
    """
    Agent 1 REST API called by SnapLogic IIP to validate and profile raw data.
    """
    file_path = _require_accessible_file(payload.get("file_path"), x_user_email)
    batch_id = payload.get("batch_id")

    agent = IntakeAgent()
    try:
        res = agent.run(file_path)
    except ValueError as ve:
        raise HTTPException(status_code=422, detail=str(ve))
    return {
        "status": "Success",
        "batch_id": batch_id,
        "file_path": file_path,
        "metadata": res
    }

@router.post("/pipeline/transform")
def run_transform_agent_endpoint(payload: dict, db: Session = Depends(get_db), x_user_email: Optional[str] = Header(None)):
    """
    Agent 2 REST API called by SnapLogic IIP to clean the dataset.
    """
    file_path = _require_accessible_file(payload.get("file_path"), x_user_email)
    batch_id = payload.get("batch_id")
    metadata = payload.get("metadata") or {}

    agent = TransformationAgent()
    output_dir = os.path.dirname(get_user_path(x_user_email, "cleaned data/dummy.txt"))
    res = agent.run(file_path, {**metadata, "batch_id": batch_id}, output_dir=output_dir)
    return {
        "status": "Success",
        "batch_id": batch_id,
        "clean_file_path": res.get("clean_dataset_path"),
        "quality_before": res.get("quality_before"),
        "quality_after": res.get("quality_after"),
        "transformation_steps": res.get("transformation_steps")
    }

@router.post("/pipeline/store")
def run_store_agent_endpoint(payload: dict, db: Session = Depends(get_db), x_user_email: Optional[str] = Header(None)):
    """
    Agent 3 REST API called by SnapLogic IIP to select storage format and load DB.
    """
    clean_file_path = _require_accessible_file(payload.get("clean_file_path"), x_user_email, label="Clean file")
    batch_id = payload.get("batch_id")
    if batch_id:
        _require_batch_access(db, batch_id, x_user_email)
    metadata = payload.get("metadata") or {}

    agent = StorageAgent()
    res = agent.run(clean_file_path, batch_id, metadata)
    return {
        "status": "Success",
        "batch_id": batch_id,
        "format_selected": res.get("format_selected"),
        "formatted_file_path": res.get("formatted_file_path"),
        "storage_reason": res.get("storage_reason"),
        "validation_results": res.get("validation_results")
    }

@router.post("/pipeline/report")
def run_report_agent_endpoint(payload: dict, db: Session = Depends(get_db), x_user_email: Optional[str] = Header(None)):
    """
    Agent 4 REST API called by SnapLogic IIP to compile analytical PDF report.
    """
    batch_id = payload.get("batch_id")
    _require_batch_access(db, batch_id, x_user_email)
    agent = ReportAgent()

    # We construct a pipeline state dictionary from the payload to pass to the agent
    state_mock = {
        "batch_id": batch_id,
        "dataset_name": payload.get("dataset_name", "dataset"),
        "quality_score": payload.get("quality_score", 100.0),
        "metadata": payload.get("metadata", {}),
        "duplicate_rows": payload.get("duplicate_rows", 0),
        "missing_values": payload.get("missing_values", {}),
        "column_types": payload.get("column_types", {}),
        "transformation_history": payload.get("transformation_history", []),
        "validation_results": payload.get("validation_results", {}),
        "format_selected": payload.get("format_selected", "CSV"),
        "formatted_file_path": payload.get("formatted_file_path", ""),
        "storage_reason": payload.get("storage_reason", "")
    }

    res = agent.run(state_mock)

    # Re-export the caller's Power BI dataset so it reflects this run
    try:
        from backend.api.powerbi import export_powerbi_dataset
        meta = export_powerbi_dataset(x_user_email)
        summary = ", ".join(f"{name} ({info['rows']} rows)" for name, info in meta["tables"].items())
        db.execute(text("INSERT INTO agent_logs (batch_id, agent_name, task, reasoning, confidence, execution_time) VALUES (:b, 'Power BI Gateway', 'Export Power BI dataset', :r, 100.0, 0.0)"), {"b": batch_id, "r": f"Exported model tables: {summary}."})
        db.commit()
    except Exception as e:
        logger.error(f"Error exporting Power BI dataset during report endpoint: {e}")

    return {
        "status": "Success",
        "batch_id": batch_id,
        "generated_reports": res.get("generated_reports"),
        "business_summary": res.get("business_summary")
    }

# --- Management & Logs Endpoints ---

@router.get("/pipeline/status")
def get_pipeline_status(pipeline_id: str, db: Session = Depends(get_db), x_user_email: Optional[str] = Header(None)):
    if not is_valid_batch_id(pipeline_id) or not pipeline_id.startswith("pipe_"):
        raise HTTPException(status_code=400, detail="Invalid pipeline id.")
    batch_id = pipeline_id[len("pipe_"):]
    _require_batch_access(db, batch_id, x_user_email)

    pipe = db.query(PipelineLog).filter(PipelineLog.pipeline_id == pipeline_id).first()
    if not pipe and not pipeline_state_exists(pipeline_id):
        raise HTTPException(status_code=404, detail=f"No pipeline run found for {pipeline_id}.")

    state = read_pipeline_state(pipeline_id)

    if pipe:
        state["status"] = pipe.status
        if pipe.start_time:
            state["start_time"] = pipe.start_time.isoformat()
        if pipe.end_time:
            state["end_time"] = pipe.end_time.isoformat()
        if pipe.execution_time is not None:
            state["execution_time"] = pipe.execution_time

    # Construct backward-compatible flat log strings
    flat_logs = [f"Pipeline run initialized. Batch ID: {batch_id}."]

    for stage_id in STAGE_IDS:
        stage_data = state["stages"].get(stage_id, {})
        for log_line in stage_data.get("logs", []):
            flat_logs.append(log_line)
    if state.get("error"):
        flat_logs.append(f"Runtime Crash: {state['error']}")

    state["logs"] = flat_logs
    upload_row = db.execute(text("SELECT filename, uploaded_by FROM raw_uploads WHERE batch_id = :b LIMIT 1"), {"b": batch_id}).first()
    state["batch_id"] = batch_id
    state["filename"] = upload_row[0] if upload_row else None
    state["raw_file_path"] = get_user_path(upload_row[1], f"data/raw/{upload_row[0]}") if upload_row else None
    return state

@router.get("/logs")
def get_all_logs(batch_id: Optional[str] = None, db: Session = Depends(get_db), x_user_email: Optional[str] = Header(None)):
    query = "SELECT timestamp, agent_name, task, confidence, execution_time FROM agent_logs WHERE 1=1"
    params = {}
    if batch_id:
        _require_batch_access(db, batch_id, x_user_email)
        query += " AND batch_id = :b"
        params["b"] = batch_id
    visible = _user_batch_filter(db, x_user_email)
    stmt_binds = []
    if visible is not None:
        if not visible:
            return []
        query += " AND batch_id IN :bids"
        params["bids"] = visible
        stmt_binds.append(bindparam("bids", expanding=True))
    query += " ORDER BY timestamp ASC"

    rows = db.execute(text(query).bindparams(*stmt_binds), params).fetchall()
    log_list = []
    for r in rows:
        log_list.append({
            "timestamp": r[0],
            "agent": r[1],
            "task": r[2],
            "confidence": r[3],
            "execution_time": r[4]
        })
    return log_list

@router.get("/root-cause")
def get_root_cause(batch_id: Optional[str] = None, db: Session = Depends(get_db), x_user_email: Optional[str] = Header(None)):
    query = db.query(RootCauseReport)
    if batch_id:
        _require_batch_access(db, batch_id, x_user_email)
        query = query.filter(RootCauseReport.batch_id == batch_id)
    visible = _user_batch_filter(db, x_user_email)
    if visible is not None:
        query = query.filter(RootCauseReport.batch_id.in_(visible))
    return query.all()

@router.get("/data-quality")
def get_data_quality(batch_id: Optional[str] = None, db: Session = Depends(get_db), x_user_email: Optional[str] = Header(None)):
    query = db.query(QualityReport)
    if batch_id:
        _require_batch_access(db, batch_id, x_user_email)
        query = query.filter(QualityReport.batch_id == batch_id)
    visible = _user_batch_filter(db, x_user_email)
    if visible is not None:
        query = query.filter(QualityReport.batch_id.in_(visible))
    return query.all()

@router.get("/pipeline/flowchart")
def get_pipeline_flowchart_endpoint(batch_id: str, db: Session = Depends(get_db), x_user_email: Optional[str] = Header(None)):
    from backend.utils.flowchart_generator import generate_flowchart_svg

    _require_batch_access(db, batch_id, x_user_email)
    pipeline_id = f"pipe_{batch_id}"
    state = read_pipeline_state(pipeline_id)

    # Try to find the filename
    filename = "dataset.csv"
    try:
        row = db.execute(text("SELECT filename FROM raw_uploads WHERE batch_id = :b LIMIT 1"), {"b": batch_id}).first()
        if row and row[0]:
            filename = row[0]
        else:
            filename = state.get("dataset_name", "dataset.csv")
    except Exception:
        pass

    svg_content = generate_flowchart_svg(batch_id, state.get("stages", {}), filename)
    return Response(content=svg_content, media_type="image/svg+xml")

@router.get("/pipeline/graph-json")
def get_pipeline_graph_json_endpoint(batch_id: str, db: Session = Depends(get_db), x_user_email: Optional[str] = Header(None)):
    _require_batch_access(db, batch_id, x_user_email)
    pipeline_id = f"pipe_{batch_id}"
    state = read_pipeline_state(pipeline_id)

    filename = "dataset.csv"
    uploaded_by = None
    try:
        row = db.execute(text("SELECT filename, uploaded_by FROM raw_uploads WHERE batch_id = :b LIMIT 1"), {"b": batch_id}).first()
        if row:
            filename = row[0]
            uploaded_by = row[1]
        else:
            filename = state.get("dataset_name", "dataset.csv")
    except Exception:
        pass

    raw_full_path = get_user_path(uploaded_by, f"data/raw/{filename}")
    stages = state.get("stages", {})
    clean_full_path = stages.get("transformation", {}).get("output", {}).get("clean_dataset_path") or get_user_path(uploaded_by, f"cleaned data/{filename}")

    def to_rel(p: str) -> str:
        return os.path.relpath(os.path.abspath(p), PROJECT_ROOT).replace("\\", "/")

    from urllib.parse import quote
    rel_raw = quote(to_rel(raw_full_path))
    rel_clean = quote(to_rel(clean_full_path))

    intake_status = stages.get("intake", {}).get("status", "waiting")
    trans_status = stages.get("transformation", {}).get("status", "waiting")
    storage_status = stages.get("storage", {}).get("status", "waiting")
    report_status = stages.get("report", {}).get("status", "waiting")
    pbi_status = stages.get("pbi", {}).get("status", "waiting")
    raw_status = "completed" if intake_status != "waiting" else "waiting"

    storage_path = stages.get('storage', {}).get('output', {}).get('formatted_file_path')
    if storage_path:
        storage_path = quote(to_rel(storage_path))

    nodes = [
        {
            "id": "raw",
            "label": f"Raw Ingestion Input ({filename})",
            "type": "RawInputNode",
            "status": raw_status,
            "data_preview": stages.get("intake", {}).get("output", {}).get("preview", []),
            "download_url": f"/api/v1/reports/download-file?path={rel_raw}" if raw_status == "completed" else None
        },
        {
            "id": "intake",
            "label": "1. Iris AI Ingestion Profile & Readability Validate",
            "type": "IntakeAgentNode",
            "status": intake_status,
            "metrics": {
                "rows": stages.get("intake", {}).get("output", {}).get("rows"),
                "columns": stages.get("intake", {}).get("output", {}).get("columns"),
                "quality": stages.get("intake", {}).get("output", {}).get("estimated_quality")
            },
            "download_url": f"/api/v1/pipeline/status?pipeline_id={pipeline_id}" if intake_status == "completed" else None
        },
        {
            "id": "transformation",
            "label": "2. Data Cleanser & Quality Optimizer Snap",
            "type": "TransformationAgentNode",
            "status": trans_status,
            "metrics": {
                "quality_before": stages.get("transformation", {}).get("output", {}).get("quality_before"),
                "quality_after": stages.get("transformation", {}).get("output", {}).get("quality_after")
            },
            "download_url": f"/api/v1/reports/download-file?path={rel_clean}" if trans_status == "completed" else None
        },
        {
            "id": "storage",
            "label": "3. SQL Staging Target Format Sync",
            "type": "StorageAgentNode",
            "status": storage_status,
            "metrics": {
                "format_selected": stages.get("storage", {}).get("output", {}).get("format_selected"),
                "rows_loaded": stages.get("storage", {}).get("output", {}).get("rows_loaded"),
                "rows_rejected": stages.get("storage", {}).get("output", {}).get("rows_rejected")
            },
            "download_url": f"/api/v1/reports/download-file?path={storage_path}" if storage_status == "completed" and storage_path else None
        },
        {
            "id": "report",
            "label": "4. Analytical Docx & Executive Summary Exporter",
            "type": "ReportAgentNode",
            "status": report_status,
            "metrics": {
                "rca_alerts": stages.get("report", {}).get("output", {}).get("rca_alerts_count")
            },
            "download_url": f"/api/v1/reports/download/{batch_id}?format=pdf" if report_status == "completed" else None
        },
        {
            "id": "pbi",
            "label": "5. Power BI Gateway fact sync",
            "type": "PowerBIGatewayNode",
            "status": pbi_status,
            "metrics": {
                "refresh_status": stages.get("pbi", {}).get("output", {}).get("refresh_status")
            },
            "download_url": None
        }
    ]

    edges = [
        {"source": "raw", "target": "intake"},
        {"source": "intake", "target": "transformation"},
        {"source": "transformation", "target": "storage"},
        {"source": "storage", "target": "report"},
        {"source": "report", "target": "pbi"}
    ]

    return {
        "batch_id": batch_id,
        "pipeline_id": pipeline_id,
        "nodes": nodes,
        "edges": edges
    }


# --- Run History & Process Logs ---

def _existing_raw_path(uploaded_by: Optional[str], filename: Optional[str]) -> Optional[str]:
    if not filename:
        return None
    try:
        path = get_user_path(uploaded_by, f"data/raw/{filename}")
    except ValueError:
        return None
    return path if os.path.isfile(path) else None


def _stage_output(state: dict, stage_id: str) -> dict:
    return (state.get("stages", {}).get(stage_id) or {}).get("output") or {}


def list_runs(db: Session, email: Optional[str], limit: int = 200, batch_ids: Optional[list] = None) -> list:
    """Batches uploaded by `email`, newest first, with their run status and measured results."""
    from backend.database.models import RawUpload, GeneratedReport
    query = db.query(RawUpload).filter(RawUpload.uploaded_by == email)
    if batch_ids is not None:
        query = query.filter(RawUpload.batch_id.in_(batch_ids))
    uploads = query.order_by(RawUpload.upload_time.desc()).limit(max(1, min(limit, 1000))).all()
    batch_ids = [u.batch_id for u in uploads if u.batch_id]
    runs = {p.pipeline_id: p for p in db.query(PipelineLog).filter(PipelineLog.pipeline_id.in_([f"pipe_{b}" for b in batch_ids])).all()} if batch_ids else {}
    reports = {}
    if batch_ids:
        for r in db.query(GeneratedReport).filter(GeneratedReport.batch_id.in_(batch_ids)).order_by(GeneratedReport.created_at.asc()).all():
            reports[r.batch_id] = r

    history = []
    for u in uploads:
        if not u.batch_id or not is_valid_batch_id(u.batch_id):
            continue
        pipeline_id = f"pipe_{u.batch_id}"
        run = runs.get(pipeline_id)
        state = read_pipeline_state(pipeline_id) if pipeline_state_exists(pipeline_id) else {}
        intake, transform, storage = _stage_output(state, "intake"), _stage_output(state, "transformation"), _stage_output(state, "storage")
        report = reports.get(u.batch_id)
        history.append({
            "batch_id": u.batch_id,
            "pipeline_id": pipeline_id,
            "filename": u.filename,
            "source": u.source,
            "file_type": u.file_type,
            "uploaded_at": u.upload_time.isoformat() if u.upload_time else None,
            "status": run.status if run else ("Not Run" if not state else state.get("status")),
            "started_at": run.start_time.isoformat() if run and run.start_time else None,
            "ended_at": run.end_time.isoformat() if run and run.end_time else None,
            "execution_time": run.execution_time if run else None,
            "rows": intake.get("rows"),
            "columns": intake.get("columns"),
            "rows_loaded": storage.get("rows_loaded"),
            "rows_rejected": storage.get("rows_rejected"),
            "quality_before": transform.get("quality_before"),
            "quality_after": transform.get("quality_after"),
            "format_selected": storage.get("format_selected"),
            "clean_file": transform.get("clean_dataset_path"),
            "raw_file": _existing_raw_path(u.uploaded_by, u.filename),
            "reports": {
                fmt: bool(getattr(report, col, None)) and os.path.isfile(getattr(report, col))
                for fmt, col in (("pdf", "pdf_path"), ("docx", "docx_path"), ("markdown", "markdown_path"), ("json", "json_path"))
            } if report else {},
            "error": state.get("error"),
        })
    return history


@router.get("/history")
def get_run_history(limit: int = 200, db: Session = Depends(get_db), x_user_email: Optional[str] = Header(None)):
    """Every batch the caller uploaded, newest first, with its run status and measured results."""
    return list_runs(db, x_user_email, limit)


@router.get("/history/{batch_id}/log")
def get_run_log(batch_id: str, download: bool = False, db: Session = Depends(get_db), x_user_email: Optional[str] = Header(None)):
    """The full process log of one run, rendered from its recorded stage timeline (works while running too)."""
    from fastapi.responses import PlainTextResponse
    _require_batch_access(db, batch_id, x_user_email)
    row = db.execute(text("SELECT filename, uploaded_by FROM raw_uploads WHERE batch_id = :b LIMIT 1"), {"b": batch_id}).first()
    filename = row[0] if row else batch_id
    pipeline_id = f"pipe_{batch_id}"
    if not pipeline_state_exists(pipeline_id):
        content = f"No pipeline run has been started for {filename} (batch {batch_id}) yet.\n"
    else:
        agent_rows = db.execute(
            text("SELECT timestamp, agent_name, reasoning FROM agent_logs WHERE batch_id = :b ORDER BY timestamp ASC"), {"b": batch_id}
        ).fetchall()
        summary = [f"[{r[0]}] {r[1]}: {r[2]}" for r in agent_rows]
        content = build_process_log(pipeline_id, batch_id, filename, row[1] if row else None, summary)
    headers = {"Content-Disposition": f'attachment; filename="{filename}.log"'} if download else {}
    return PlainTextResponse(content, headers=headers)
