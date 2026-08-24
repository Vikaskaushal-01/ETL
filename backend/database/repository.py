import logging
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime
from backend.database.models import (
    RawUpload, StagingDataset, ProductionDataset, Customer, StagingCustomer,
    Order, StagingOrder, Sale, StagingSale, TransformationLog, ValidationLog,
    PipelineLog, AgentLog, QualityReport, RootCauseReport, GeneratedReport
)

logger = logging.getLogger("etl_repository")

def create_raw_upload(db: Session, filename: str, source: str, file_type: str, batch_id: str = None, uploaded_by: str = None) -> RawUpload:
    upload = RawUpload(filename=filename, source=source, file_type=file_type, status="Pending", batch_id=batch_id, uploaded_by=uploaded_by)
    db.add(upload)
    db.commit()
    db.refresh(upload)
    return upload

def update_raw_upload_status(db: Session, upload_id: int, status: str):
    upload = db.query(RawUpload).filter(RawUpload.id == upload_id).first()
    if upload:
        upload.status = status
        db.commit()
    return upload

def log_pipeline_start(db: Session, pipeline_id: str) -> PipelineLog:
    log = PipelineLog(pipeline_id=pipeline_id, start_time=datetime.utcnow(), status="Running")
    db.merge(log)
    db.commit()
    return log

def log_pipeline_end(db: Session, pipeline_id: str, status: str, execution_time: float) -> PipelineLog:
    log = db.query(PipelineLog).filter(PipelineLog.pipeline_id == pipeline_id).first()
    if log:
        log.end_time = datetime.utcnow()
        log.status = status
        log.execution_time = execution_time
        db.commit()
    return log

def log_agent_decision(db: Session, batch_id: str, agent_name: str, task: str, reasoning: str, confidence: float, execution_time: float):
    log = AgentLog(
        batch_id=batch_id,
        agent_name=agent_name,
        task=task,
        reasoning=reasoning,
        confidence=confidence,
        execution_time=execution_time
    )
    db.add(log)
    db.commit()
    return log

def log_transformation(db: Session, batch_id: str, agent_name: str, column_name: str, old_value: str, new_value: str, reason: str):
    log = TransformationLog(
        batch_id=batch_id,
        agent_name=agent_name,
        column_name=column_name,
        old_value=str(old_value),
        new_value=str(new_value),
        reason=reason
    )
    db.add(log)
    db.commit()
    return log

def log_validation(db: Session, batch_id: str, validation_type: str, status: str, message: str):
    log = ValidationLog(
        batch_id=batch_id,
        validation_type=validation_type,
        status=status,
        message=message
    )
    db.add(log)
    db.commit()
    return log

def save_quality_report(db: Session, batch_id: str, missing_values: int, duplicate_count: int, quality_score: float, schema_match: bool):
    report = QualityReport(
        batch_id=batch_id,
        missing_values=missing_values,
        duplicate_count=duplicate_count,
        quality_score=quality_score,
        schema_match=schema_match
    )
    db.add(report)
    db.commit()
    return report

def save_root_cause_report(db: Session, batch_id: str, issue: str, root_cause: str, business_impact: str, technical_impact: str, recommendation: str, confidence: float):
    report = RootCauseReport(
        batch_id=batch_id,
        issue=issue,
        root_cause=root_cause,
        business_impact=business_impact,
        technical_impact=technical_impact,
        recommendation=recommendation,
        confidence=confidence
    )
    db.add(report)
    db.commit()
    return report

def save_generated_reports(db: Session, batch_id: str, pdf_path: str, docx_path: str, json_path: str, markdown_path: str, txt_path: str = None):
    report = GeneratedReport(
        batch_id=batch_id,
        pdf_path=pdf_path,
        docx_path=docx_path,
        txt_path=txt_path,
        json_path=json_path,
        markdown_path=markdown_path
    )
    db.add(report)
    db.commit()
    return report

def clear_staging_by_batch(db: Session, batch_id: str, table_model):
    """
    Clears out any staging data for a given batch ID to avoid duplicate staging records
    """
    db.query(table_model).filter(table_model.batch_id == batch_id).delete()
    db.commit()
