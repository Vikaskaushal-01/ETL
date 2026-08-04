from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from datetime import datetime

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    message: str
    batch_id: Optional[str] = None
    history: Optional[List[ChatMessage]] = None

class ChatResponse(BaseModel):
    response: str
    agent_name: str
    confidence: float

class PipelineStartRequest(BaseModel):
    file_path: str
    batch_id: Optional[str] = None

class PipelineStartResponse(BaseModel):
    pipeline_id: str
    status: str
    batch_id: str
    dataset_name: str

class PipelineStatusResponse(BaseModel):
    pipeline_id: str
    status: str
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    execution_time: Optional[float] = None
    logs: List[str]

class ReportSummary(BaseModel):
    id: int
    batch_id: str
    pdf_path: str
    docx_path: Optional[str] = None
    txt_path: Optional[str] = None
    markdown_path: str
    json_path: str
    created_at: datetime

class DashboardSummary(BaseModel):
    total_rows_processed: int
    success_rate: float
    failed_records: int
    processing_time_avg: float
    quality_score_avg: float
    active_pipelines: int
    recent_runs: List[Dict[str, Any]]
