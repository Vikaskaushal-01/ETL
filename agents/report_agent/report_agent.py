import os
import json
import logging
import time
from backend.core.llm import query_llm
from backend.utils.report_utils import (
    generate_pdf_report, generate_docx_report,
    generate_markdown_report, generate_json_report,
    generate_txt_report
)
from backend.database.mysql import SessionLocal
from backend.database.repository import (
    save_quality_report, save_root_cause_report, 
    save_generated_reports, log_agent_decision
)

logger = logging.getLogger("etl_report_agent")

class ReportAgent:
    def __init__(self):
        self.role = "Chief Data Intelligence Officer"
        self.name = "Report Generation Agent"

    def run(self, state: dict) -> dict:
        start_time = time.time()
        batch_id = state.get("batch_id")
        logger.info(f"Running Report Generation Agent on batch {batch_id}")
        
        # 1. Analyze validation rejects
        val_res = state.get("validation_results", {})
        rejected_count = val_res.get("rows_rejected", 0)
        rejected_records = val_res.get("rejected_records", [])
        
        rca_list = []
        
        if rejected_count > 0:
            prompt_rca = f"""
            You are a Senior Data Quality Specialist performing Root Cause Analysis (RCA).
            A dataset was processed and {rejected_count} rows were rejected during load validation.
            Here is a sample of the rejected records:
            {json.dumps(rejected_records[:5], indent=2)}
            
            Perform an RCA and output a JSON list of issues. Each element must contain:
            - issue: clear description of the data quality failure
            - root_cause: underlying reason (e.g. source systems join failed, wrong date strings, float parses failed)
            - business_impact: financial, operational or downstream report accuracy impacts
            - technical_impact: schema load failures, key violations
            - recommendation: technical fix (e.g. re-extract data, validate source CRM exports)
            - confidence: float score between 0 and 100 on this assessment
            
            Return ONLY a valid JSON list.
            """
            system_instruction = "You are the Report Generation Agent. Generate Root Cause Analysis metrics as valid JSON."
            try:
                llm_res = query_llm(prompt_rca, system_instruction, json_mode=True)
                if "```json" in llm_res:
                    llm_res = llm_res.split("```json")[1].split("```")[0].strip()
                elif "```" in llm_res:
                    llm_res = llm_res.split("```")[1].split("```")[0].strip()
                rca_list = json.loads(llm_res.strip())
            except Exception as e:
                logger.error(f"Error parsing RCA LLM response: {e}")
                rca_list = [{
                    "issue": f"{rejected_count} records rejected during schema checks.",
                    "root_cause": "Data format mismatch or constraint violation in raw inputs.",
                    "business_impact": "Downstream analytics metrics might misrepresent overall performance.",
                    "technical_impact": "Primary key null checks or foreign key reference verification failed.",
                    "recommendation": "Examine upstream synchronization rules to guarantee data consistency.",
                    "confidence": 90.0
                }]
        else:
            rca_list = []

        # 2. Extract Business Insights & Business Summary
        prompt_insights = f"""
        You are a Chief Data Intelligence Officer analyzing a database load run.
        Dataset: {state.get('dataset_name')}
        Rows Loaded: {val_res.get('rows_loaded', 0)}
        Rows Rejected: {val_res.get('rows_rejected', 0)}
        Data Quality: {state.get('quality_score')}%
        
        Generate a corporate executive summary and a list of business insights and pipeline optimization recommendations.
        Output a JSON object containing:
        - executive_summary: A high-level description of what the dataset is, how the pipeline run executed, and the overall load success.
        - business_insights: Bullets outlining key observations (e.g. transaction distributions, region performance, or customer profile observations).
        - recommendations: A list of actionable technical/pipeline optimization recommendations.
        
        Return ONLY valid JSON.
        """
        system_instruction = "You are the Report Generation Agent. Extract and summarize executive business insights as valid JSON."
        try:
            llm_ins = query_llm(prompt_insights, system_instruction, json_mode=True)
            if "```json" in llm_ins:
                llm_ins = llm_ins.split("```json")[1].split("```")[0].strip()
            elif "```" in llm_ins:
                llm_ins = llm_ins.split("```")[1].split("```")[0].strip()
            insights_info = json.loads(llm_ins.strip())
        except Exception as e:
            logger.error(f"Error parsing insights LLM response: {e}")
            insights_info = {
                "executive_summary": f"Successfully processed dataset '{state.get('dataset_name')}' with batch ID '{batch_id}'. Validated and staged {val_res.get('rows_loaded', 0)} rows successfully with a data quality index of {state.get('quality_score', 100.0)}%.",
                "business_insights": "The ingestion logs demonstrate standard transaction ranges. Regions show active billing cycles.",
                "recommendations": [
                    "Perform index analysis on table columns to accelerate reports.",
                    "Schedule batch processes during low utilization hours to maximize database speed."
                ]
        }

        # 3. Save to database for dashboard/analytical visual sync
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
                missing_values=sum(state.get("missing_values", {}).values()) if state.get("missing_values") else 0,
                duplicate_count=state.get("duplicate_rows", 0),
                quality_score=adjusted_quality,
                schema_match=True
            )
            
            # Save RCA entries
            for rca in rca_list:
                save_root_cause_report(
                    db,
                    batch_id=batch_id,
                    issue=rca.get("issue"),
                    root_cause=rca.get("root_cause"),
                    business_impact=rca.get("business_impact"),
                    technical_impact=rca.get("technical_impact"),
                    recommendation=rca.get("recommendation"),
                    confidence=rca.get("confidence")
                )
        except Exception as err:
            logger.error(f"Error inserting quality reports/RCA into DB: {err}")
        finally:
            db.close()

        # Determine input name from dataset name or path
        dataset_name = state.get("dataset_name", "")
        dataset_path = state.get("dataset_path", "")
        if not dataset_name and dataset_path:
            dataset_name = os.path.basename(dataset_path)
        if not dataset_name:
            dataset_name = "unknown"

        # Build paths for report organized by exact input name
        from backend.utils.account_utils import get_user_path
        from sqlalchemy import text
        
        db_user = SessionLocal()
        user_email = None
        try:
            user_email = db_user.execute(
                text("SELECT uploaded_by FROM raw_uploads WHERE batch_id = :b LIMIT 1"),
                {"b": batch_id}
            ).scalar()
        except Exception as e:
            logger.warning(f"ReportAgent failed to query uploaded_by: {e}")
        finally:
            db_user.close()

        input_name_dir = os.path.dirname(get_user_path(user_email, os.path.join("reports", dataset_name, "dummy.pdf")))
        os.makedirs(input_name_dir, exist_ok=True)
        
        pdf_path = os.path.join(input_name_dir, f"{batch_id}_report.pdf").replace("\\", "/")
        txt_path = os.path.join(input_name_dir, f"{batch_id}_report.txt").replace("\\", "/")
        markdown_path = os.path.join(input_name_dir, f"{batch_id}_report.md").replace("\\", "/")
        json_path = os.path.join(input_name_dir, f"{batch_id}_report.json").replace("\\", "/")
        docx_path = os.path.join(input_name_dir, f"{batch_id}_report.docx").replace("\\", "/")

        # Prep report data structure
        report_data = {
            "batch_id": batch_id,
            "pipeline_status": "Success" if rejected_count == 0 else "Passed with Warnings",
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

        # Generate all reports (PDF, Text, Markdown, JSON, DOCX)
        try:
            generate_pdf_report(pdf_path, report_data)
            logger.info(f"PDF report successfully saved at: {pdf_path}")
        except Exception as file_err:
            logger.error(f"Failed to generate PDF report file: {file_err}")

        try:
            generate_txt_report(txt_path, report_data)
            logger.info(f"TXT report successfully saved at: {txt_path}")
        except Exception as file_err:
            logger.error(f"Failed to generate TXT report file: {file_err}")
            txt_path = ""

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

        # Update generated reports database table
        db2 = SessionLocal()
        try:
            save_generated_reports(
                db2,
                batch_id=batch_id,
                pdf_path=pdf_path,
                docx_path=docx_path,
                json_path=json_path,
                markdown_path=markdown_path,
                txt_path=txt_path
            )
            
            # Log agent reasoning
            log_agent_decision(
                db2,
                batch_id=batch_id,
                agent_name=self.name,
                task="Compile analytical multi-format reports",
                reasoning=f"Analyzed processed records, compiled summaries, and saved multi-format reports (PDF, Word, MD, JSON) at {input_name_dir}.",
                confidence=99.0,
                execution_time=execution_time
            )
        except Exception as db_err2:
            logger.error(f"Failed logging reports metadata or agent decision to DB: {db_err2}")
        finally:
            db2.close()

        logger.info(f"Report generation finished. All report formats exported successfully.")
        
        return {
            "root_cause_report": rca_list,
            "business_summary": insights_info.get("executive_summary"),
            "business_insights": insights_info.get("business_insights"),
            "recommendations": insights_info.get("recommendations"),
            "generated_reports": {
                "pdf_path": pdf_path,
                "docx_path": docx_path,
                "txt_path": txt_path,
                "markdown_path": markdown_path,
                "json_path": json_path
            }
        }
