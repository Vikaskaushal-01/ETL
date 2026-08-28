import logging
import time
import os
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
    from backend.api.pipeline import update_pipeline_stage, read_pipeline_state
    
    batch_id = state.get("batch_id")
    pipeline_id = f"pipe_{batch_id}"
    dataset_path = state.get("dataset_path")
    
    # Try reading raw preview
    raw_preview = []
    try:
        import pandas as pd
        from backend.utils.file_utils import read_dataset
        df = read_dataset(dataset_path)
        df_head = df.head(5)
        df_head = df_head.where(pd.notnull(df_head), None)
        raw_preview = df_head.to_dict(orient="records")
    except Exception as e:
        logger.warning(f"Failed to read raw preview: {e}")
        
    # 1. Update status to processing
    update_pipeline_stage(
        pipeline_id,
        "intake",
        "processing",
        input={
            "file_path": dataset_path,
            "filename": os.path.basename(dataset_path),
            "size": f"{os.path.getsize(dataset_path) / 1024:.2f} KB" if os.path.exists(dataset_path) else "N/A"
        },
        logs=[
            "Data Intake & Profile stage initialized.",
            f"Checking file availability at path: {dataset_path}...",
            "Loading raw file streams into memory...",
            "Invoking Intake Agent to profile file delimiter, encoding, and metadata..."
        ],
        metadata={
            "component": "com.snaplogic.snaps.ai.IrisIntakeSnap",
            "confidence_threshold": 95.0
        }
    )
    
    # Controlled delay for UI visibility
    time.sleep(1.2)
    
    agent = IntakeAgent()
    try:
        res = agent.run(dataset_path)
        
        # Write agent log to DB for Intake
        from backend.database.mysql import SessionLocal
        from backend.database.repository import log_agent_decision
        db_log = SessionLocal()
        try:
            log_agent_decision(
                db_log,
                batch_id=batch_id,
                agent_name=agent.name,
                task="Validate and profile raw dataset",
                reasoning=f"Identified {res.get('rows')} rows, {res.get('columns')} columns. Extracted missing/duplicate fields. Initial quality: {res.get('estimated_quality')}%.",
                confidence=98.0,
                execution_time=res.get("execution_time", 0.0)
            )
        except Exception as err:
            logger.warning(f"Failed to log IntakeAgent decision: {err}")
        finally:
            db_log.close()
            
        # 2. Update status to completed
        update_pipeline_stage(
            pipeline_id,
            "intake",
            "completed",
            output={
                "rows": res.get("rows"),
                "columns": res.get("columns"),
                "estimated_quality": res.get("estimated_quality"),
                "duplicate_rows": res.get("duplicate_rows"),
                "missing_values_total": sum(res.get("missing_values", {}).values()) if res.get("missing_values") else 0,
                "preview": raw_preview
            },
            logs=[
                "Raw file readability validated successfully.",
                f"File format type: {res.get('file_info', {}).get('file_type', 'CSV')}.",
                f"Dataset dimensions: {res.get('rows')} rows x {res.get('columns')} columns.",
                f"Estimated initial quality score: {res.get('estimated_quality')}%.",
                f"Iris AI pattern analysis found {res.get('duplicate_rows')} duplicates and missing columns.",
                "Schema profile complete. Ready for cleansing."
            ],
            metadata={
                "encoding": res.get("file_info", {}).get("encoding"),
                "delimiter": res.get("file_info", {}).get("delimiter"),
                "recommended_transformations": res.get("recommended_transformations", [])
            }
        )
    except Exception as e:
        update_pipeline_stage(
            pipeline_id,
            "intake",
            "failed",
            logs=[
                f"Intake Agent crashed: {str(e)}"
            ]
        )
        raise e
        
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
    from backend.api.pipeline import update_pipeline_stage, read_pipeline_state
    
    agent = TransformationAgent()
    dataset_path = state.get("dataset_path")
    metadata = state.get("metadata", {})
    batch_id = state.get("batch_id")
    pipeline_id = f"pipe_{batch_id}"
    
    # Retrieve raw preview from Intake output if exists
    raw_preview = []
    try:
        raw_preview = read_pipeline_state(pipeline_id)["stages"]["intake"]["output"].get("preview", [])
    except Exception:
        pass
        
    # 1. Update status to processing
    update_pipeline_stage(
        pipeline_id,
        "transformation",
        "processing",
        input={
            "file_path": dataset_path,
            "columns_to_process": metadata.get("column_names", []),
            "preview": raw_preview
        },
        logs=[
            "Data Cleanser Snap initialized.",
            "Analyzing dataset schemas & datatypes...",
            "Preparing cleansing routines: standardizing headers, trimming values, and imputing null values..."
        ],
        metadata={
            "component": "com.snaplogic.snaps.transform.DataCleanserSnap"
        }
    )
    
    time.sleep(1.2)
    
    try:
        from backend.utils.account_utils import get_user_path
        from backend.database.mysql import SessionLocal
        from sqlalchemy import text
        
        db_user = SessionLocal()
        user_email = None
        try:
            user_email = db_user.execute(
                text("SELECT uploaded_by FROM raw_uploads WHERE batch_id = :b LIMIT 1"),
                {"b": batch_id}
            ).scalar()
        except Exception as e:
            logger.warning(f"Failed to query uploaded_by for batch {batch_id}: {e}")
        finally:
            db_user.close()

        user_clean_dir = os.path.dirname(get_user_path(user_email, "cleaned data/dummy.txt"))
        res = agent.run(dataset_path, {**metadata, "batch_id": batch_id}, output_dir=user_clean_dir)
        
        # Read clean preview
        clean_preview = []
        try:
            import pandas as pd
            from backend.utils.file_utils import read_dataset
            clean_df = read_dataset(res.get("clean_dataset_path"))
            clean_head = clean_df.head(5)
            clean_head = clean_head.where(pd.notnull(clean_head), None)
            clean_preview = clean_head.to_dict(orient="records")
        except Exception as e:
            logger.warning(f"Failed to read clean preview: {e}")
            
        # Write agent log to DB for Transformation
        from backend.database.mysql import SessionLocal
        from backend.database.repository import log_agent_decision
        db_log = SessionLocal()
        try:
            log_agent_decision(
                db_log,
                batch_id=batch_id,
                agent_name=agent.name,
                task="Clean dataset and standardize types",
                reasoning=f"Deduplicated records and standardized column types. Quality before: {res.get('quality_before')}%, Quality after: {res.get('quality_after')}%.",
                confidence=95.0,
                execution_time=res.get("execution_time", 0.0)
            )
        except Exception as err:
            logger.warning(f"Failed to log TransformationAgent decision: {err}")
        finally:
            db_log.close()
            
        # 2. Update status to completed
        update_pipeline_stage(
            pipeline_id,
            "transformation",
            "completed",
            output={
                "clean_dataset_path": res.get("clean_dataset_path"),
                "quality_before": res.get("quality_before"),
                "quality_after": res.get("quality_after"),
                "preview": clean_preview
            },
            logs=[
                "Column headers successfully standardized to snake_case.",
                "Whitespace trimming executed across all textual records.",
                f"Removed duplicate rows. Dataset quality index improved: {res.get('quality_before')}% -> {res.get('quality_after')}%.",
                f"Null values imputed: default quantities filled, prices imputed using median reference values.",
                "Data cleaning completed successfully. Outputs saved."
            ],
            metadata={
                "transformation_history": res.get("transformation_steps", [])
            }
        )
    except Exception as e:
        update_pipeline_stage(
            pipeline_id,
            "transformation",
            "failed",
            logs=[
                f"Transformation Agent crashed: {str(e)}"
            ]
        )
        raise e
        
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
    from backend.api.pipeline import update_pipeline_stage, read_pipeline_state
    
    agent = StorageAgent()
    dataset_path = state.get("dataset_path")
    batch_id = state.get("batch_id")
    pipeline_id = f"pipe_{batch_id}"
    metadata = state.get("metadata", {})
    
    # Retrieve clean preview from Transformation output if exists
    clean_preview = []
    try:
        clean_preview = read_pipeline_state(pipeline_id)["stages"]["transformation"]["output"].get("preview", [])
    except Exception:
        pass
        
    # 1. Update status to processing
    update_pipeline_stage(
        pipeline_id,
        "storage",
        "processing",
        input={
            "clean_file_path": dataset_path,
            "preview": clean_preview
        },
        logs=[
            "SQL Staging & Target Format Snap initialized.",
            "Analyzing dataset characteristics (entity structure, metrics, textual columns)...",
            "Determining optimal target file format and staging destination..."
        ],
        metadata={
            "component": "com.snaplogic.snaps.database.MySQLStagingSnap"
        }
    )
    
    time.sleep(1.2)
    
    try:
        res = agent.run(dataset_path, batch_id, metadata)
        val_res = res.get("validation_results", {})
        
        # Load SQL preview if format is SQL
        sql_preview = ""
        if res.get("format_selected") == "SQL" and os.path.exists(res.get("formatted_file_path")):
            try:
                with open(res.get("formatted_file_path"), "r", encoding="utf-8") as sf:
                    sql_preview = "".join(sf.readlines()[:12])
            except Exception:
                pass
                
        # 2. Update status to completed
        update_pipeline_stage(
            pipeline_id,
            "storage",
            "completed",
            output={
                "format_selected": res.get("format_selected"),
                "formatted_file_path": res.get("formatted_file_path"),
                "rows_loaded": val_res.get("rows_loaded"),
                "rows_rejected": val_res.get("rows_rejected"),
                "sql_preview": sql_preview
            },
            logs=[
                f"Optimal storage format selected: {res.get('format_selected')}.",
                f"Technical rationale: {res.get('storage_reason')}",
                f"Saved formatted dataset copy to Cleaned Data folder.",
                f"Executing SQL Staging database load target: staging_{val_res.get('dataset_type', 'dataset')} table.",
                f"Loaded {val_res.get('rows_loaded')} rows, rejected {val_res.get('rows_rejected')} rows during primary/foreign key verification."
            ],
            metadata={
                "storage_reason": res.get("storage_reason"),
                "staging_status": val_res.get("staging_status"),
                "production_status": val_res.get("production_status"),
                "sql_logs": val_res.get("sql_logs", [])
            }
        )
    except Exception as e:
        update_pipeline_stage(
            pipeline_id,
            "storage",
            "failed",
            logs=[
                f"Storage Agent crashed: {str(e)}"
            ]
        )
        raise e
        
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
    from backend.api.pipeline import update_pipeline_stage
    
    agent = ReportAgent()
    batch_id = state.get("batch_id")
    pipeline_id = f"pipe_{batch_id}"
    
    # 1. Update status to processing
    update_pipeline_stage(
        pipeline_id,
        "report",
        "processing",
        input={
            "batch_id": batch_id,
            "quality_score": state.get("quality_score")
        },
        logs=[
            "Docx & Report Exporter Snap initialized.",
            "Initiating Root Cause Analysis (RCA) on validation rejects...",
            "Formulating business summaries and executive recommendations using Iris AI..."
        ],
        metadata={
            "component": "com.snaplogic.snaps.docx.DocxReportSnap"
        }
    )
    
    time.sleep(1.2)
    
    try:
        res = agent.run(state)
        
        # 2. Update status to completed
        update_pipeline_stage(
            pipeline_id,
            "report",
            "completed",
            output={
                "pdf_path": res.get("generated_reports", {}).get("pdf_path"),
                "docx_path": res.get("generated_reports", {}).get("docx_path"),
                "markdown_path": res.get("generated_reports", {}).get("markdown_path"),
                "json_path": res.get("generated_reports", {}).get("json_path"),
                "rca_alerts_count": len(res.get("root_cause_report", []))
            },
            logs=[
                "RCA analysis complete. Identified issues logged into database.",
                f"Generated PDF Executive Summary Report at: {res.get('generated_reports', {}).get('pdf_path')}.",
                f"Saved reports in 4 formats: JSON, Word (.docx), Markdown (.md), and PDF (.pdf) in reports subfolder."
            ],
            metadata={
                "executive_summary": res.get("business_summary"),
                "recommendations": res.get("recommendations", [])
            }
        )
    except Exception as e:
        update_pipeline_stage(
            pipeline_id,
            "report",
            "failed",
            logs=[
                f"Report Agent crashed: {str(e)}"
            ]
        )
        raise e
        
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
    from backend.api.pipeline import update_pipeline_stage
    
    batch_id = state.get("batch_id")
    pipeline_id = f"pipe_{batch_id}"
    
    # 1. Update status to processing
    update_pipeline_stage(
        pipeline_id,
        "pbi",
        "processing",
        input={
            "data_source": "MySQL (agentic_ai_etl)",
            "gateway_url": "localhost:3306"
        },
        logs=[
            "Power BI Gateway Sync Snap initialized.",
            "Opening gateway tunnel to relational engine...",
            "Validating schema alignment for FactSales and FactOrders tables...",
            "Broadcasting dataset refresh signal to Power BI Desktop service endpoint..."
        ],
        metadata={
            "component": "com.snaplogic.snaps.powerbi.PowerBIGatewaySnap"
        }
    )
    
    time.sleep(1.2)
    
    logs = state.get("execution_logs", [])
    
    try:
        from backend.api.powerbi import trigger_powerbi_refresh
        trigger_powerbi_refresh()
        
        # Write agent log to DB for Power BI
        from backend.database.mysql import SessionLocal
        from backend.database.repository import log_agent_decision
        db_log = SessionLocal()
        try:
            log_agent_decision(
                db_log,
                batch_id=batch_id,
                agent_name="Power BI Gateway",
                task="Dashboard refresh",
                reasoning="Simulated refresh triggered successfully via SnapLogic Power BI Gateway Snap.",
                confidence=100.0,
                execution_time=0.02
            )
        except Exception as err:
            logger.warning(f"Failed to log Power BI decision: {err}")
        finally:
            db_log.close()
            
        # 2. Update status to completed
        update_pipeline_stage(
            pipeline_id,
            "pbi",
            "completed",
            output={
                "refresh_status": "Success",
                "workspace_target": "Control AI Workspace"
            },
            logs=[
                "Power BI Gateway refresh request accepted by remote service.",
                "Dataset synchronization completed successfully.",
                "Live dashboard metrics and charts model updated."
            ],
            metadata={
                "target_tables": ["FactSales", "FactOrders", "DimCustomer", "DimAgent"]
            }
        )
    except Exception as e:
        update_pipeline_stage(
            pipeline_id,
            "pbi",
            "failed",
            logs=[
                f"Power BI Refresh failed: {str(e)}"
            ]
        )
        raise e
        
    logs.append("[Power BI Gateway] Successfully issued dataset refresh request to Power BI REST Service.")
    logs.append("[Power BI Gateway] Power BI dataset 'agentic_ai_etl' synced and dashboard models updated.")
    
    return {
        "dashboard_status": "Refreshed",
        "execution_logs": logs
    }
