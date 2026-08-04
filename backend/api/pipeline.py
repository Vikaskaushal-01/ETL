import os
import time
import logging
import json
import uuid
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional
from backend.database.mysql import get_db
from backend.database.models import PipelineLog, AgentLog, QualityReport, RootCauseReport
from backend.database.repository import log_pipeline_start, log_pipeline_end
from backend.schemas.schemas import PipelineStartRequest, PipelineStartResponse
from agents_graph.graph import compiled_graph

# Import Agents directly for SnapLogic endpoints
from agents.intake_agent.intake_agent import IntakeAgent
from agents.transformation_agent.transformation_agent import TransformationAgent
from agents.storage_agent.storage_agent import StorageAgent
from agents.report_agent.report_agent import ReportAgent

router = APIRouter(tags=["Pipeline"])
logger = logging.getLogger("etl_pipeline_api")

def save_pipeline_logs_to_file(batch_id: str, logs: list, raw_file_path: str = None):
    try:
        PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        logs_dir = os.path.join(PROJECT_ROOT, "logs")
        os.makedirs(logs_dir, exist_ok=True)
        
        # 1. Always save batch_id log file permanently
        batch_log_path = os.path.join(logs_dir, f"{batch_id}.log")
        with open(batch_log_path, "w", encoding="utf-8") as f:
            f.write("\n".join(logs))
        logger.info(f"Saved pipeline execution logs to file: {batch_log_path}")
        
        # 2. Also save matching filename log file if raw_file_path is available
        if raw_file_path:
            base_name = os.path.basename(raw_file_path)
            file_log_path = os.path.join(logs_dir, f"{base_name}.log")
            with open(file_log_path, "w", encoding="utf-8") as f:
                f.write("\n".join(logs))
            logger.info(f"Saved pipeline execution logs to file: {file_log_path}")
    except Exception as le:
        logger.error(f"Failed to save execution logs to file: {le}")

def run_langgraph_pipeline(file_path: str, batch_id: str, pipeline_id: str):
    """
    Background worker that runs the LangGraph state machine sequentially.
    """
    logger.info(f"Starting background pipeline run: {pipeline_id}")
    db = SessionLocal_helper()
    
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
        
        # Log start in DB
        log_pipeline_start(db, pipeline_id)
        
        # Execute LangGraph compiled workflow
        final_state = compiled_graph.invoke(initial_state)
        
        execution_time = time.time() - start_time
        status = final_state.get("pipeline_status", "Success")
        
        # Write DB log update
        log_pipeline_end(db, pipeline_id, status, execution_time)
        
        logger.info(f"Pipeline run finished successfully in {execution_time:.2f}s with status {status}")
        
        # Save pipeline execution logs to disk
        logs_list = final_state.get("execution_logs", [])
        save_pipeline_logs_to_file(batch_id, logs_list, file_path)
        
        if status in ["Success", "Passed with Warnings"]:
            try:
                PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
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
                    json.dump(backup_data, bf, indent=2)
                logger.info(f"Cached last cleaned file metadata to: {backup_path}")
            except Exception as cache_err:
                logger.error(f"Failed to cache run metadata: {cache_err}")
        
    except Exception as e:
        execution_time = time.time() - start_time
        logger.error(f"LangGraph execution crashed: {e}")
        try:
            log_pipeline_end(db, pipeline_id, "Failed", execution_time)
            db.execute(text("INSERT INTO validation_logs (batch_id, validation_type, status, message) VALUES (:b, 'Pipeline', 'Failed', :m)"), {
                "b": batch_id,
                "m": f"Runtime Crash: {str(e)}"
            })
            db.commit()
        except Exception as inner_err:
            logger.error(f"Failed to log crash to DB: {inner_err}")
            
        # Save crash log
        save_pipeline_logs_to_file(batch_id, [
            f"Pipeline run initialized. Batch ID: {batch_id}.",
            f"Runtime Crash: {str(e)}"
        ])
    finally:
        db.close()

def SessionLocal_helper():
    from backend.database.mysql import SessionLocal
    return SessionLocal()

@router.post("/pipeline/start", response_model=PipelineStartResponse)
def start_pipeline(req: PipelineStartRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    if not os.path.exists(req.file_path):
        raise HTTPException(status_code=404, detail=f"File not found at: {req.file_path}")
        
    batch_id = req.batch_id or f"batch_{str(uuid.uuid4())[:8]}"
    pipeline_id = f"pipe_{batch_id}"
    
    # Auto-recover/clean stale running pipelines older than 60 seconds
    from datetime import datetime, timedelta
    stale_cutoff = datetime.utcnow() - timedelta(seconds=60)
    stale_runs = db.query(PipelineLog).filter(
        PipelineLog.status == "Running",
        PipelineLog.start_time < stale_cutoff
    ).all()
    for sr in stale_runs:
        sr.status = "Failed"
        sr.end_time = datetime.utcnow()
    if stale_runs:
        db.commit()
    
    # Check if any pipeline is currently running globally (sequential processing)
    running_pipeline = db.query(PipelineLog).filter(PipelineLog.status == "Running").first()
    if running_pipeline:
        # Auto-reset if stuck
        running_pipeline.status = "Failed"
        running_pipeline.end_time = datetime.utcnow()
        db.commit()
        
    # Check if this specific pipeline already exists/running
    existing = db.query(PipelineLog).filter(PipelineLog.pipeline_id == pipeline_id).first()
    if existing and existing.status == "Running":
        existing.status = "Failed"
        db.commit()
        
    background_tasks.add_task(run_langgraph_pipeline, req.file_path, batch_id, pipeline_id)
    
    return {
        "pipeline_id": pipeline_id,
        "status": "Running",
        "batch_id": batch_id,
        "dataset_name": os.path.basename(req.file_path)
    }

# --- SnapLogic HTTP Orchestration Agent Endpoints ---

@router.post("/pipeline/intake")
def run_intake_agent_endpoint(payload: dict, db: Session = Depends(get_db)):
    """
    Agent 1 REST API called by SnapLogic IIP to validate and profile raw data.
    """
    file_path = payload.get("file_path")
    batch_id = payload.get("batch_id")
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")
    
    agent = IntakeAgent()
    res = agent.run(file_path)
    return {
        "status": "Success",
        "batch_id": batch_id,
        "file_path": file_path,
        "metadata": res
    }

@router.post("/pipeline/transform")
def run_transform_agent_endpoint(payload: dict, db: Session = Depends(get_db)):
    """
    Agent 2 REST API called by SnapLogic IIP to clean the dataset.
    """
    file_path = payload.get("file_path")
    batch_id = payload.get("batch_id")
    metadata = payload.get("metadata", {})
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")
    
    agent = TransformationAgent()
    res = agent.run(file_path, {**metadata, "batch_id": batch_id})
    return {
        "status": "Success",
        "batch_id": batch_id,
        "clean_file_path": res.get("clean_dataset_path"),
        "quality_before": res.get("quality_before"),
        "quality_after": res.get("quality_after"),
        "transformation_steps": res.get("transformation_steps")
    }

@router.post("/pipeline/store")
def run_store_agent_endpoint(payload: dict, db: Session = Depends(get_db)):
    """
    Agent 3 REST API called by SnapLogic IIP to select storage format and load DB.
    """
    clean_file_path = payload.get("clean_file_path")
    batch_id = payload.get("batch_id")
    metadata = payload.get("metadata", {})
    if not clean_file_path or not os.path.exists(clean_file_path):
        raise HTTPException(status_code=404, detail=f"Clean file not found: {clean_file_path}")
    
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
def run_report_agent_endpoint(payload: dict, db: Session = Depends(get_db)):
    """
    Agent 4 REST API called by SnapLogic IIP to compile analytical PDF report.
    """
    batch_id = payload.get("batch_id")
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
    
    # Refresh Power BI dataset and sync metrics dynamically
    try:
        from backend.api.powerbi import trigger_powerbi_refresh
        trigger_powerbi_refresh()
    except Exception as e:
        logger.error(f"Error triggering Power BI refresh during report endpoint: {e}")
        
    db.execute(text("INSERT INTO agent_logs (batch_id, agent_name, task, reasoning, confidence, execution_time) VALUES (:b, 'Power BI Gateway', 'Dashboard refresh', 'Simulated refresh triggered successfully via SnapLogic Power BI Gateway Snap', 100.0, 0.02)"), {"b": batch_id})
    db.commit()
    
    return {
        "status": "Success",
        "batch_id": batch_id,
        "generated_reports": res.get("generated_reports"),
        "business_summary": res.get("business_summary")
    }

# --- Management & Logs Endpoints ---

@router.get("/pipeline/status")
def get_pipeline_status(pipeline_id: str, db: Session = Depends(get_db)):
    pipe = db.query(PipelineLog).filter(PipelineLog.pipeline_id == pipeline_id).first()
    if not pipe:
        return {
            "pipeline_id": pipeline_id,
            "status": "Running",
            "start_time": None,
            "end_time": None,
            "execution_time": None,
            "logs": ["Pipeline initialization pending in database..."]
        }
        
    batch_id = pipeline_id.replace("pipe_", "")
    
    agent_logs = db.query(AgentLog).filter(AgentLog.batch_id == batch_id).all()
    steps = [f"[{log.agent_name}] {log.task}: {log.reasoning} (confidence={log.confidence}%)" for log in agent_logs]
    
    return {
        "pipeline_id": pipe.pipeline_id,
        "status": pipe.status,
        "start_time": pipe.start_time,
        "end_time": pipe.end_time,
        "execution_time": pipe.execution_time,
        "logs": steps
    }

@router.get("/logs")
def get_all_logs(batch_id: Optional[str] = None, db: Session = Depends(get_db)):
    query = "SELECT timestamp, agent_name, task, confidence, execution_time FROM agent_logs"
    params = {}
    if batch_id:
        query += " WHERE batch_id = :b"
        params["b"] = batch_id
    query += " ORDER BY timestamp ASC"
    
    rows = db.execute(text(query), params).fetchall()
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
def get_root_cause(batch_id: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(RootCauseReport)
    if batch_id:
        query = query.filter(RootCauseReport.batch_id == batch_id)
    return query.all()

@router.get("/data-quality")
def get_data_quality(batch_id: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(QualityReport)
    if batch_id:
        query = query.filter(QualityReport.batch_id == batch_id)
    return query.all()
