from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)
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

class ReportSummary(BaseModel):
    id: int
    batch_id: str
    pdf_path: Optional[str] = None
    docx_path: Optional[str] = None
    txt_path: Optional[str] = None
    markdown_path: Optional[str] = None
    json_path: Optional[str] = None
    created_at: Optional[datetime] = None

class DashboardSummary(BaseModel):
    total_rows_processed: int
    success_rate: float
    failed_records: int
    processing_time_avg: float
    quality_score_avg: float
    active_pipelines: int
    recent_runs: List[Dict[str, Any]]
