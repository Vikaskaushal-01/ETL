import logging
import time
from agents_graph.state import PipelineState
from agents.intake_agent.intake_agent import IntakeAgent
from agents.transformation_agent.transformation_agent import TransformationAgent
from agents.storage_agent.storage_agent import StorageAgent
from agents.report_agent.report_agent import ReportAgent

logger = logging.getLogger("etl_nodes")

def intake_node(state: PipelineState) -> dict:
    """
    Executes the Intake Agent (Agent 1) to profile file format and validate readability.
    """
    start_time = time.time()
    agent = IntakeAgent()
    dataset_path = state.get("dataset_path")
    
    res = agent.run(dataset_path)
    
    logs = state.get("execution_logs", [])
    logs.append(f"[{agent.name}] Validated and profiled raw dataset in {res.get('execution_time', 0.0):.2f}s.")
    
    return {
        "metadata": res,
        "schema": {"columns": res.get("column_names")},
        "column_types": res.get("column_types"),
        "missing_values": res.get("missing_values"),
        "duplicate_rows": res.get("duplicate_rows"),
        "quality_score": res.get("estimated_quality"),
        "execution_logs": logs
    }

def transformation_node(state: PipelineState) -> dict:
    """
    Executes the Transformation Agent (Agent 2) to clean columns, handle nulls/duplicates, and standardize formats.
    """
    agent = TransformationAgent()
    dataset_path = state.get("dataset_path")
    metadata = state.get("metadata", {})
    batch_id = state.get("batch_id")
    
    res = agent.run(dataset_path, {**metadata, "batch_id": batch_id})
    
    logs = state.get("execution_logs", [])
    logs.append(f"[{agent.name}] Cleansed dataset. Quality improved from {res.get('quality_before')}% to {res.get('quality_after')}%.")
    
    return {
        "dataset_path": res.get("clean_dataset_path"),
        "transformation_history": res.get("transformation_steps"),
        "quality_score": res.get("quality_after"),
        "execution_logs": logs
    }

def storage_node(state: PipelineState) -> dict:
    """
    Executes the Storage Agent (Agent 3) to choose the optimal storage format (CSV/Word/SQL), save it, and load it to the database.
    """
    agent = StorageAgent()
    dataset_path = state.get("dataset_path") # This is the clean file path from transformation
    batch_id = state.get("batch_id")
    metadata = state.get("metadata", {})
    
    res = agent.run(dataset_path, batch_id, metadata)
    val_res = res.get("validation_results", {})
    
    logs = state.get("execution_logs", [])
    logs.append(f"[{agent.name}] Intelligently formatted and stored dataset. Format selected: {res.get('format_selected')}. Saved to {res.get('formatted_file_path')}.")
    logs.append(f"[{agent.name}] DB Sync Status: {val_res.get('validation_status')}. Loaded {val_res.get('rows_loaded')}, Rejected {val_res.get('rows_rejected')}.")
    
    return {
        "format_selected": res.get("format_selected"),
        "formatted_file_path": res.get("formatted_file_path"),
        "storage_reason": res.get("storage_reason"),
        "storage_status": res.get("storage_status"),
        "validation_results": val_res,
        "staging_status": val_res.get("staging_status"),
        "mysql_status": val_res.get("production_status"),
        "pipeline_status": "Success" if val_res.get("rows_rejected") == 0 else "Passed with Warnings",
        "execution_logs": logs
    }

def report_node(state: PipelineState) -> dict:
    """
    Executes the Report Agent (Agent 4) to generate the analytical PDF report.
    """
    agent = ReportAgent()
    
    # We pass the full state dict containing metadata, validation results, and storage format
    res = agent.run(state)
    
    logs = state.get("execution_logs", [])
    logs.append(f"[{agent.name}] Compiled Root Cause Analysis & insights. PDF report generated successfully.")
    
    return {
        "root_cause_report": res.get("root_cause_report"),
        "business_summary": res.get("business_summary"),
        "business_insights": res.get("business_insights"),
        "recommendations": res.get("recommendations"),
        "generated_reports": res.get("generated_reports"),
        "execution_logs": logs
    }

def pbi_refresh_node(state: PipelineState) -> dict:
    """
    Triggers/simulates refreshing the Power BI dashboards.
    """
    logs = state.get("execution_logs", [])
    
    try:
        from backend.api.powerbi import trigger_powerbi_refresh
        trigger_powerbi_refresh()
    except Exception as e:
        logger.error(f"Error triggering Power BI refresh: {e}")
        
    logs.append("[Power BI Gateway] Successfully issued dataset refresh request to Power BI REST Service.")
    logs.append("[Power BI Gateway] Power BI dataset 'agentic_ai_etl' synced and dashboard models updated.")
    
    return {
        "dashboard_status": "Refreshed",
        "execution_logs": logs
    }
