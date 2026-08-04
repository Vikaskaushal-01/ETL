from typing import TypedDict, List, Dict, Any, Optional

class PipelineState(TypedDict):
    dataset_name: str
    dataset_path: str
    batch_id: str
    metadata: Dict[str, Any]
    schema: Dict[str, Any]
    column_types: Dict[str, str]
    missing_values: Dict[str, int]
    duplicate_rows: int
    transformation_history: List[Dict[str, Any]]
    validation_results: Dict[str, Any]
    staging_status: str
    mysql_status: str
    quality_score: float
    root_cause_report: List[Dict[str, Any]]
    business_summary: str
    generated_reports: Dict[str, str]
    dashboard_status: str
    execution_logs: List[str]
    pipeline_status: str
    format_selected: str
    formatted_file_path: str
    storage_reason: str
    storage_status: str

