import json
from datetime import datetime
from typing import Dict, Any, List


class RootCauseAnalysisReportGenerator:
    """
    Automated Root Cause Analysis (RCA) executive report generator.
    Parses validation errors, rejections, and schema drift to produce
    actionable operational insights in Markdown and JSON formats.
    """

    @classmethod
    def generate_markdown_rca(
        cls,
        batch_id: str,
        dataset_name: str,
        total_rows: int,
        rejected_rows: int,
        quality_score: float,
        errors: List[Dict[str, Any]],
        transformations: List[Dict[str, Any]],
        recommendations: List[str] = None
    ) -> str:
        """Produces formatted Markdown executive audit report."""
        loss_rate = round((rejected_rows / max(total_rows + rejected_rows, 1)) * 100, 2)
        status = "PASSED" if rejected_rows == 0 else ("WARNING" if quality_score >= 80 else "CRITICAL")
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

        error_rows = ""
        if errors:
            for err in errors[:20]:
                col = err.get("column", "N/A")
                reason = err.get("reason", "Constraint violation")
                count = err.get("count", 1)
                severity = err.get("severity", "HIGH")
                error_rows += f"| `{col}` | {reason} | {count} | **{severity}** |\n"
        else:
            error_rows = "| None | No constraint violations detected | 0 | LOW |\n"

        trans_rows = ""
        if transformations:
            for t in transformations[:15]:
                col = t.get("column_name", "General")
                op = t.get("operation", "Auto-Clean")
                reason = t.get("reason", "Standardized format")
                trans_rows += f"- **[{col}]** `{op}`: {reason}\n"
        else:
            trans_rows = "- No automated transformations required.\n"

        recs_list = ""
        if recommendations:
            for r in recommendations:
                recs_list += f"1. {r}\n"
        else:
            recs_list = (
                "1. Maintain current upstream ingestion validation schema.\n"
                "2. Monitor downstream Power BI refresh latency.\n"
                "3. Review recurring null patterns in customer identification fields.\n"
            )

        return f"""# Autonomous Agentic AI ETL — Executive RCA Report
**Batch ID**: `{batch_id}`  
**Dataset Source**: `{dataset_name}`  
**Evaluation Timestamp**: {timestamp}  
**Pipeline Health Status**: **{status}**

---

## 1. Executive Summary & KPIs

| Metric | Recorded Value | Evaluation Benchmark |
| :--- | :--- | :--- |
| **Total Ingested Records** | {total_rows} | Target Volume |
| **Rejected / Lost Records** | {rejected_rows} | Zero-Loss Target |
| **Data Loss Rate** | {loss_rate}% | SLA Threshold < 2.0% |
| **Calculated Quality Score** | {quality_score}% | Target > 90.0% |

---

## 2. Root Cause Analysis & Anomaly Breakdown

| Column Identifier | Error Description | Affected Rows | Severity |
| :--- | :--- | :--- | :--- |
{error_rows}

---

## 3. Transformations Applied by Cleansing Agent

{trans_rows}

---

## 4. Remediation & Action Recommendations

{recs_list}
"""

    @classmethod
    def generate_json_rca(
        cls,
        batch_id: str,
        dataset_name: str,
        total_rows: int,
        rejected_rows: int,
        quality_score: float,
        errors: List[Dict[str, Any]],
        transformations: List[Dict[str, Any]],
        recommendations: List[str] = None
    ) -> Dict[str, Any]:
        """Produces structured JSON RCA payload for API and Power BI consumption."""
        return {
            "batch_id": batch_id,
            "dataset_name": dataset_name,
            "timestamp": datetime.utcnow().isoformat(),
            "kpis": {
                "total_rows": total_rows,
                "rejected_rows": rejected_rows,
                "loss_rate_percent": round((rejected_rows / max(total_rows + rejected_rows, 1)) * 100, 2),
                "quality_score": quality_score
            },
            "anomalies_detected": errors,
            "transformations_applied": transformations,
            "remediation_actions": recommendations or [
                "Verify upstream source format consistency",
                "Ensure primary key uniqueness prior to staging load"
            ]
        }
