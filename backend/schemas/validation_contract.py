from pydantic import BaseModel, Field, field_validator
from typing import List, Dict, Any, Optional
from enum import Enum
from datetime import datetime


class ConstraintType(str, Enum):
    NOT_NULL = "NOT_NULL"
    UNIQUE = "UNIQUE"
    REGEX_MATCH = "REGEX_MATCH"
    RANGE = "RANGE"
    IN_SET = "IN_SET"
    TYPE_CHECK = "TYPE_CHECK"


class ColumnRule(BaseModel):
    column_name: str
    constraint_type: ConstraintType
    params: Optional[Dict[str, Any]] = Field(default_factory=dict)
    severity: str = Field(default="ERROR", description="ERROR or WARNING")
    error_message: Optional[str] = None


class DataContract(BaseModel):
    contract_name: str
    version: str = "1.0.0"
    target_table: str
    min_quality_score_threshold: float = Field(default=80.0, ge=0.0, le=100.0)
    max_rejection_rate_percent: float = Field(default=5.0, ge=0.0, le=100.0)
    rules: List[ColumnRule] = Field(default_factory=list)


class RuleEvaluationResult(BaseModel):
    column_name: str
    constraint_type: str
    passed: bool
    violations_count: int = 0
    violation_sample_indices: List[int] = Field(default_factory=list)
    details: str


class ContractValidationSummary(BaseModel):
    contract_name: str
    evaluated_at: datetime = Field(default_factory=datetime.utcnow)
    total_records: int
    passed_records: int
    rejected_records: int
    overall_quality_score: float
    sla_breached: bool = False
    rule_results: List[RuleEvaluationResult] = Field(default_factory=list)
