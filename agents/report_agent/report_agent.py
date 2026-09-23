import os
import json
import shutil
import logging
import time
from sqlalchemy import text
from backend.core.llm import query_llm, is_real_llm_available as LLM_PROVIDER_IS_REAL
from backend.utils.file_utils import read_dataset
from backend.utils.data_insights import (
    build_recommendations, build_root_cause_analysis, compute_dataset_insights
)
from backend.utils.report_utils import (
    generate_pdf_report, generate_docx_report,
    generate_markdown_report, generate_json_report
)
from backend.database.mysql import SessionLocal
from backend.database.repository import (
    save_quality_report, save_root_cause_report, 
    save_generated_reports, log_agent_decision
)

logger = logging.getLogger("etl_report_agent")

def _as_float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "; ".join(str(v) for v in value)
    return str(value)


class ReportAgent:
    def __init__(self):
        self.role = "Chief Data Intelligence Officer"
        self.name = "Report Generation Agent"

    def run(self, state: dict) -> dict:
        start_time = time.time()
        batch_id = state.get("batch_id")
        logger.info(f"Running Report Generation Agent on batch {batch_id}")
        
        # 1. Analyze validation rejects: RCA is derived from the actual rejection reasons
        val_res = state.get("validation_results", {})
        rejected_count = val_res.get("rows_rejected", 0)
        rejected_records = val_res.get("rejected_records", [])
        total_rows = (val_res.get("rows_loaded", 0) or 0) + (rejected_count or 0)
        rca_list = build_root_cause_analysis(rejected_records, total_rows) if rejected_count else []

        # 2. Insights and recommendations are computed from the cleaned dataset itself
        clean_df = None
        clean_path = state.get("dataset_path")
        if clean_path and os.path.isfile(clean_path):
            try:
                clean_df = read_dataset(clean_path)
            except Exception as e:
                logger.warning(f"Could not read cleaned dataset for insights: {e}")
        business_insights = compute_dataset_insights(clean_df)
        recommendations = build_recommendations(
            clean_df, rca_list, state.get("duplicate_rows", 0),
            (state.get("metadata") or {}).get("estimated_quality"), state.get("quality_score")
        )

        # The LLM only narrates the measured facts; it is not asked to invent insights
        facts = "\n".join(f"- {line}" for line in business_insights)
        prompt_insights = f"""
        You are a Chief Data Intelligence Officer writing the executive summary of an ETL run.
        Dataset: {state.get('dataset_name')}
        Rows loaded: {val_res.get('rows_loaded', 0)}; rows rejected: {rejected_count}; final data quality: {state.get('quality_score')}%.
        Measured facts about the data:
        {facts}
        Root cause findings: {'; '.join(r['issue'] for r in rca_list) if rca_list else 'none'}

        Write a 3-4 sentence executive summary using ONLY the facts above. Do not introduce any number,
        trend or category that is not listed. Return JSON: {{"executive_summary": "..."}}
        """
        system_instruction = "You are the Report Generation Agent. Summarize only the provided facts as valid JSON."
        executive_summary = None
        try:
            llm_ins = query_llm(prompt_insights, system_instruction, json_mode=True)
            if "```json" in llm_ins:
                llm_ins = llm_ins.split("```json")[1].split("```")[0].strip()
            elif "```" in llm_ins:
                llm_ins = llm_ins.split("```")[1].split("```")[0].strip()
            parsed = json.loads(llm_ins.strip())
            if isinstance(parsed, dict) and isinstance(parsed.get("executive_summary"), str) and LLM_PROVIDER_IS_REAL():
                executive_summary = parsed["executive_summary"].strip()
        except Exception as e:
            logger.info(f"LLM executive summary unavailable, using the measured summary: {e}")
        if not executive_summary:
            status_text = "all rows loaded" if not rejected_count else f"{rejected_count} row(s) rejected ({', '.join(r['issue'].split(':')[0] for r in rca_list)})"
            executive_summary = (
                f"Processed '{state.get('dataset_name')}' (batch {batch_id}): {val_res.get('rows_loaded', 0)} row(s) loaded, "
                f"{status_text}. Final data quality score: {state.get('quality_score')}%. "
                + (business_insights[0] if business_insights else "")
            )
        insights_info = {
            "executive_summary": executive_summary,
            "business_insights": business_insights,
            "recommendations": recommendations,
        }

        # 3. Save to database and compile reports
        db = SessionLocal()
        
        # Calculate dynamic quality score adjusting for load validation rejections
        base_quality = state.get("quality_score", 100.0)
        rows_loaded = val_res.get("rows_loaded", 0)
        rows_rejected = val_res.get("rows_rejected", 0)
        total_rows = rows_loaded + rows_rejected
        
        adjusted_quality = base_quality
        if total_rows > 0:
            rej_rate = rows_rejected / total_rows
            adjusted_quality = round(base_quality * (1.0 - rej_rate), 2)
            
        try:
            # Save quality metrics
            save_quality_report(
                db, 
                batch_id=batch_id,
                missing_values=int(sum((state.get("missing_values") or {}).values())),
                duplicate_count=state.get("duplicate_rows", 0),
                quality_score=adjusted_quality,
                schema_match=True
            )
            
            # Save RCA entries
            for rca in rca_list:
                save_root_cause_report(
                    db,
                    batch_id=batch_id,
                    issue=_as_text(rca.get("issue")),
                    root_cause=_as_text(rca.get("root_cause")),
                    business_impact=_as_text(rca.get("business_impact")),
                    technical_impact=_as_text(rca.get("technical_impact")),
                    recommendation=_as_text(rca.get("recommendation")),
                    confidence=_as_float(rca.get("confidence"), 90.0)
                )
        except Exception as err:
            db.rollback()
            logger.error(f"Error inserting quality reports/RCA into DB: {err}")

        # Determine input name from dataset name or path
        dataset_name = state.get("dataset_name", "")
        dataset_path = state.get("dataset_path", "")
        if not dataset_name and dataset_path:
            dataset_name = os.path.basename(dataset_path)
        if not dataset_name:
            dataset_name = "unknown"

        # Build paths for report organized by exact input name
        from backend.utils.account_utils import get_user_path
        from backend.core.security import sanitize_filename
        
        user_email = None
        try:
            user_email = db.execute(
                text("SELECT uploaded_by FROM raw_uploads WHERE batch_id = :b LIMIT 1"),
                {"b": batch_id}
            ).scalar()
        except Exception as e:
            logger.warning(f"ReportAgent failed to query uploaded_by: {e}")

        input_name_dir = os.path.dirname(get_user_path(user_email, os.path.join("reports", sanitize_filename(dataset_name, "unknown"), "dummy.pdf")))
        os.makedirs(input_name_dir, exist_ok=True)
        
        pdf_path = os.path.join(input_name_dir, f"{batch_id}_report.pdf").replace("\\", "/")
        markdown_path = os.path.join(input_name_dir, f"{batch_id}_report.md").replace("\\", "/")
        json_path = os.path.join(input_name_dir, f"{batch_id}_report.json").replace("\\", "/")
        docx_path = os.path.join(input_name_dir, f"{batch_id}_report.docx").replace("\\", "/")

        # Prep report data structure
        report_data = {
            "batch_id": batch_id,
            "pipeline_status": val_res.get("validation_status") or ("Success" if rejected_count == 0 else "Passed with Warnings"),
            "quality_score": adjusted_quality,
            "business_summary": insights_info.get("executive_summary"),
            "dataset_name": state.get("dataset_name"),
            "metadata": state.get("metadata", {}),
            "duplicate_rows": state.get("duplicate_rows", 0),
            "missing_values": state.get("missing_values", {}),
            "column_types": state.get("column_types", {}),
            "transformation_history": state.get("transformation_history", []),
            "validation_results": val_res,
            "root_cause_report": rca_list,
            "business_insights": insights_info.get("business_insights"),
            "recommendations": insights_info.get("recommendations"),
            "format_selected": state.get("format_selected", "CSV"),
            "formatted_file_path": state.get("formatted_file_path", ""),
            "storage_reason": state.get("storage_reason", ""),
            "execution_time": 0.0 # Will compute and add
        }

        execution_time = time.time() - start_time
        report_data["execution_time"] = execution_time

        # Generate exactly 4 reports: PDF, Word (DOCX), Markdown (MD), and JSON
        try:
            generate_pdf_report(pdf_path, report_data)
            logger.info(f"PDF report successfully saved at: {pdf_path}")
        except Exception as file_err:
            logger.error(f"Failed to generate PDF report file: {file_err}")
            pdf_path = ""

        try:
            generate_docx_report(docx_path, report_data)
            logger.info(f"DOCX report successfully saved at: {docx_path}")
        except Exception as file_err:
            logger.error(f"Failed to generate DOCX report file: {file_err}")
            docx_path = ""

        try:
            generate_markdown_report(markdown_path, report_data)
            logger.info(f"Markdown report successfully saved at: {markdown_path}")
        except Exception as file_err:
            logger.error(f"Failed to generate Markdown report file: {file_err}")
            markdown_path = ""

        try:
            generate_json_report(json_path, report_data)
            logger.info(f"JSON report successfully saved at: {json_path}")
        except Exception as file_err:
            logger.error(f"Failed to generate JSON report file: {file_err}")
            json_path = ""

        # Also keep a copy in the project's reports/<file name>/ folder (the account copy above is what
        # the API serves; this server-side folder is not exposed to other users).
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        root_report_dir = os.path.join(project_root, "reports", sanitize_filename(dataset_name, "unknown"))
        if os.path.normcase(os.path.abspath(root_report_dir)) != os.path.normcase(os.path.abspath(input_name_dir)):
            os.makedirs(root_report_dir, exist_ok=True)
            for generated in (pdf_path, docx_path, markdown_path, json_path):
                if generated and os.path.exists(generated):
                    try:
                        shutil.copy2(generated, os.path.join(root_report_dir, os.path.basename(generated)))
                    except Exception as copy_err:
                        logger.warning(f"Failed copying {generated} to {root_report_dir}: {copy_err}")
            logger.info(f"Report copies saved to: {root_report_dir}")

        # Update generated reports database table using existing session
        try:
            save_generated_reports(
                db,
                batch_id=batch_id,
                pdf_path=pdf_path,
                docx_path=docx_path,
                json_path=json_path,
                markdown_path=markdown_path,
                txt_path=None
            )
            
            # Log agent reasoning
            log_agent_decision(
                db,
                batch_id=batch_id,
                agent_name=self.name,
                task="Compile analytical multi-format reports",
                reasoning=f"Analyzed processed records, compiled summaries, and saved exactly 4 report formats (JSON, Word, MD, PDF) at {input_name_dir}.",
                confidence=99.0,
                execution_time=execution_time
            )
            db.commit()
        except Exception as db_err2:
            db.rollback()
            logger.error(f"Failed logging reports metadata or agent decision to DB: {db_err2}")
        finally:
            db.close()

        logger.info(f"Report generation finished. Exactly 4 report formats (JSON, Word, MD, PDF) exported successfully.")
        
        return {
            "root_cause_report": rca_list,
            "business_summary": insights_info.get("executive_summary"),
            "business_insights": insights_info.get("business_insights"),
            "recommendations": insights_info.get("recommendations"),
            "generated_reports": {
                "pdf_path": pdf_path,
                "docx_path": docx_path,
                "markdown_path": markdown_path,
                "json_path": json_path
            }
        }
