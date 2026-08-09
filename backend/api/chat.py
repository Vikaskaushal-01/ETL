from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from backend.database.mysql import get_db
from backend.schemas.schemas import ChatRequest, ChatResponse
from backend.core.llm import query_llm
import json
import re
import os

router = APIRouter(prefix="/agent", tags=["AI Agent Chat"])

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

def extract_batch_id(message: str, req_batch_id: str = None) -> str:
    if req_batch_id:
        return req_batch_id
    # 1. Match batch_xxxx
    batch_matches = re.findall(r'\bbatch_[a-f0-9]{8}\b', message, re.IGNORECASE)
    if batch_matches:
        return batch_matches[0].lower()
    # 2. Match pipe_batch_xxxx
    pipe_matches = re.findall(r'\bpipe_batch_[a-f0-9]{8}\b', message, re.IGNORECASE)
    if pipe_matches:
        return pipe_matches[0].lower().replace("pipe_", "")
    # 3. Match 8-character hex string (e.g. 05ce9ae4)
    hex_matches = re.findall(r'\b[a-f0-9]{8}\b', message, re.IGNORECASE)
    if hex_matches:
        return f"batch_{hex_matches[0].lower()}"
    return None

def get_latest_batch_id(db) -> str:
    # Try database
    try:
        latest_run = db.execute(text("SELECT pipeline_id FROM pipeline_logs WHERE status IN ('Success', 'Passed with Warnings') ORDER BY start_time DESC LIMIT 1")).first()
        if latest_run:
            return latest_run[0].replace("pipe_", "")
    except Exception:
        pass
    
    # Try persistent cache
    backup_path = os.path.abspath(".last_cleaned_backup.json")
    if os.path.exists(backup_path):
        try:
            with open(backup_path, "r", encoding="utf-8") as bf:
                return json.load(bf).get("batch_id")
        except Exception:
            pass
            
    # Try logs dir files
    try:
        logs_dir = os.path.abspath("logs")
        if os.path.exists(logs_dir):
            log_files = [f for f in os.listdir(logs_dir) if f.startswith("batch_") and f.endswith(".log")]
            if log_files:
                log_files.sort(key=lambda x: os.path.getmtime(os.path.join(logs_dir, x)), reverse=True)
                return log_files[0].replace(".log", "")
    except Exception:
        pass
        
    return None

def get_logs_for_batch(db, batch_id: str) -> tuple[str, str]:
    if not batch_id:
        return "", ""
        
    log_path = os.path.join(PROJECT_ROOT, "logs", f"{batch_id}.log")
    if os.path.exists(log_path):
        try:
            with open(log_path, "r", encoding="utf-8") as lf:
                return lf.read(), f"Process Logs for Batch `{batch_id}`"
        except Exception:
            pass

    logs_dir = os.path.join(PROJECT_ROOT, "logs")
    if os.path.exists(logs_dir):
        for f in os.listdir(logs_dir):
            if f.endswith(".log") and (batch_id in f or batch_id.replace("batch_", "") in f):
                try:
                    with open(os.path.join(logs_dir, f), "r", encoding="utf-8") as lf:
                        return lf.read(), f"Process Logs for `{f}`"
                except Exception:
                    pass
            
    # Try database pipeline logs
    try:
        agent_logs = db.execute(
            text("SELECT agent_name, task, reasoning, confidence FROM agent_logs WHERE batch_id = :b ORDER BY timestamp ASC"),
            {"b": batch_id}
        ).fetchall()
        if agent_logs:
            content = "\n".join([f"[{al[0]}] {al[1]}: {al[2]} (confidence: {al[3]}%)" for al in agent_logs])
            return content, f"Database Pipeline Logs for Batch `{batch_id}`"
    except Exception:
        pass
        
    # Try from backup file
    backup_path = os.path.abspath(".last_cleaned_backup.json")
    if os.path.exists(backup_path):
        try:
            with open(backup_path, "r", encoding="utf-8") as bf:
                data = json.load(bf)
                if data.get("batch_id") == batch_id:
                    return data.get("logs", ""), f"Cached Logs for Batch `{batch_id}` (from persistent cache)"
        except Exception:
            pass
            
    return "", ""

def get_files_for_batch(db, batch_id: str) -> tuple[str, str]:
    # 1. Get raw file info from DB
    raw_filename = None
    file_type = None
    
    try:
        upload_row = db.execute(
            text("SELECT filename, file_type FROM raw_uploads WHERE batch_id = :b LIMIT 1"),
            {"b": batch_id}
        ).first()
        if upload_row:
            raw_filename, file_type = upload_row[0], upload_row[1]
    except Exception:
        pass
        
    # Try from persistent cache fallback
    if not raw_filename:
        backup_path = os.path.abspath(".last_cleaned_backup.json")
        if os.path.exists(backup_path):
            try:
                with open(backup_path, "r", encoding="utf-8") as bf:
                    data = json.load(bf)
                    if data.get("batch_id") == batch_id:
                        raw_filename = data.get("filename")
                        _, ext = os.path.splitext(raw_filename.lower())
                        file_type = ext[1:]
            except Exception:
                pass
                
    if not raw_filename:
        return "No files or report logs could be retrieved for this ID. It might have been cleared or does not exist.", ""
        
    available_files_context = f"Available files for download/viewing for Batch `{batch_id}`:\n"
    
    # A. Raw file path
    raw_path = f"data/raw/{raw_filename}"
    if os.path.exists(os.path.join(PROJECT_ROOT, raw_path)):
        raw_url = f"/api/v1/reports/download-file?path={raw_path}"
        available_files_context += f"- **Raw Uploaded File**: [Download {raw_filename}]({raw_url})\n"
        
    # B. Clean file path
    clean_path = f"cleaned data/{raw_filename}"
    if os.path.exists(os.path.join(PROJECT_ROOT, clean_path)):
        clean_url = f"/api/v1/reports/download-file?path={clean_path}"
        available_files_context += f"- **Cleaned Dataset File**: [Download {raw_filename}]({clean_url})\n"
        
    # C. Reports
    reports_added = False
    try:
        report_row = db.execute(
            text("SELECT pdf_path, docx_path, json_path, markdown_path, txt_path FROM generated_reports WHERE batch_id = :b"),
            {"b": batch_id}
        ).first()
        if report_row:
            pdf_p, docx_p, json_p, md_p, txt_p = report_row
            if pdf_p and os.path.exists(os.path.join(PROJECT_ROOT, pdf_p)):
                available_files_context += f"- **PDF Report**: [Download PDF Report](/api/v1/reports/download/{batch_id}?format=pdf)\n"
            if docx_p and os.path.exists(os.path.join(PROJECT_ROOT, docx_p)):
                available_files_context += f"- **Word (DOCX) Report**: [Download Word Report](/api/v1/reports/download/{batch_id}?format=docx)\n"
            if md_p and os.path.exists(os.path.join(PROJECT_ROOT, md_p)):
                available_files_context += f"- **Markdown Report**: [Download Markdown Report](/api/v1/reports/download/{batch_id}?format=markdown)\n"
            if json_p and os.path.exists(os.path.join(PROJECT_ROOT, json_p)):
                available_files_context += f"- **JSON Report**: [Download JSON Report](/api/v1/reports/download/{batch_id}?format=json)\n"
            if txt_p and os.path.exists(os.path.join(PROJECT_ROOT, txt_p)):
                available_files_context += f"- **TXT Report**: [Download TXT Report](/api/v1/reports/download/{batch_id}?format=txt)\n"
            reports_added = True
    except Exception:
        pass
        
    if not reports_added:
        # Check backup cache reports
        backup_path = os.path.abspath(".last_cleaned_backup.json")
        if os.path.exists(backup_path):
            try:
                with open(backup_path, "r", encoding="utf-8") as bf:
                    data = json.load(bf)
                    if data.get("batch_id") == batch_id:
                        reps = data.get("reports", {})
                        for fmt, path in reps.items():
                            if path and os.path.exists(os.path.join(PROJECT_ROOT, path)):
                                clean_fmt = fmt.replace("_path", "")
                                available_files_context += f"- **{clean_fmt.upper()} Report**: [Download {clean_fmt.upper()} Report](/api/v1/reports/download/{batch_id}?format={clean_fmt})\n"
            except Exception:
                pass
                
    return available_files_context, raw_filename

@router.post("/chat", response_model=ChatResponse)
def agent_chat(req: ChatRequest, db: Session = Depends(get_db)):
    """
    Interact with the multi-agent system regarding pipeline status, data issues, business metrics, or query logs/files.
    """
    message_lower = req.message.lower()
    
    # 1. Clean / Reset Workspace or Cleaned Data Folder Command
    is_cleaned_data_only = any(k in message_lower for k in [
        "clean cleaned data", "clear cleaned data", "clean the cleaned data", 
        "clear the cleaned data", "clean cleaned data folder", "clear cleaned data folder"
    ])
    if is_cleaned_data_only:
        try:
            from backend.utils.file_utils import clear_cleaned_data_folder
            clear_cleaned_data_folder()
            return {
                "response": "### Cleaned Data Folder Cleared\n\nI have successfully emptied the `cleaned data/` folder. All raw uploads to be cleaned will be processed fresh and stored together in this folder with filenames matching the raw data files.",
                "agent_name": "ETL Chat Support Agent",
                "confidence": 100.0
            }
        except Exception as ex:
            return {
                "response": f"Failed to clear cleaned data folder: {str(ex)}",
                "agent_name": "ETL Chat Support Agent",
                "confidence": 50.0
            }

    is_logs_clear_only = any(k in message_lower for k in [
        "clean logs", "clear logs", "wipe logs", "clean the logs", 
        "clear the logs", "clean logs folder", "clear logs folder"
    ])
    if is_logs_clear_only:
        try:
            from backend.utils.file_utils import clear_logs_folder
            clear_logs_folder()
            return {
                "response": "### Logs Folder Cleared\n\nI have successfully emptied the `logs/` directory. Each process or upload will now save its execution logs in a log file named after the uploaded file.",
                "agent_name": "ETL Chat Support Agent",
                "confidence": 100.0
            }
        except Exception as ex:
            return {
                "response": f"Failed to clear logs folder: {str(ex)}",
                "agent_name": "ETL Chat Support Agent",
                "confidence": 50.0
            }

    is_cleanup = any(k in message_lower for k in [
        "clean the project", "clean all", "reset the workspace", "delete all files", 
        "wipe database", "wipe data", "clear data", "clean workspace", "reset workspace", 
        "delete all the files", "clean all the files", "cleaned all hte data"
    ])
    if is_cleanup:
        try:
            from cleanup_all import reset_workspace
            reset_workspace()
            # Also clear the backup file
            backup_path = os.path.join(PROJECT_ROOT, ".last_cleaned_backup.json")
            if os.path.exists(backup_path):
                os.remove(backup_path)
            return {
                "response": "### Project Reset & Data Cleaned\n\nI have successfully deleted all raw uploads, cleaned datasets, generated reports, logs on disk, and reset all database tables to a clean, empty state.",
                "agent_name": "ETL Chat Support Agent",
                "confidence": 100.0
            }
        except Exception as ex:
            return {
                "response": f"Failed to clean/reset project data: {str(ex)}",
                "agent_name": "ETL Chat Support Agent",
                "confidence": 50.0
            }

    # Extract batch_id
    batch_id = extract_batch_id(req.message, req.batch_id)
    if not batch_id and req.history:
        for msg in reversed(req.history):
            extracted = extract_batch_id(msg.content)
            if extracted:
                batch_id = extracted
                break
    if not batch_id:
        batch_id = get_latest_batch_id(db)

    # Format history
    formatted_history = ""
    if req.history:
        for msg in req.history:
            role_label = "User" if msg.role == "user" else "Assistant"
            formatted_history += f"{role_label}: {msg.content}\n"

    # 2. Check logs of the last file cleaned
    is_last_cleaned_logs = ("last" in message_lower and "clean" in message_lower and ("log" in message_lower or "logs" in message_lower))
    if is_last_cleaned_logs:
        latest_batch = get_latest_batch_id(db)
        if not latest_batch:
            return {
                "response": "No datasets have been successfully cleaned in this workspace yet. Please upload and run a pipeline.",
                "agent_name": "ETL Chat Support Agent",
                "confidence": 95.0
            }
        log_content, log_source = get_logs_for_batch(db, latest_batch)
        if not log_content:
            return {
                "response": f"Found latest batch `{latest_batch}` but could not retrieve its logs on disk or database.",
                "agent_name": "ETL Chat Support Agent",
                "confidence": 90.0
            }
        response_msg = f"Here are the process logs for the last file cleaned ({log_source}):\n\n```text\n{log_content}\n```"
        return {
            "response": response_msg,
            "agent_name": "ETL Chat Support Agent",
            "confidence": 100.0
        }

    # 3. Check the last generated / previous file
    is_previous_file_request = any(k in message_lower for k in [
        "last generated file", "previous file", "latest generated file", 
        "last file", "latest file", "previous generated file", "most recently generated file",
        "last cleaned file", "latest cleaned file", "previous cleaned file"
    ]) or ("last" in message_lower and "clean" in message_lower and ("file" in message_lower or "dataset" in message_lower) and "log" not in message_lower)
    if is_previous_file_request:
        latest_batch = get_latest_batch_id(db)
        if not latest_batch:
            return {
                "response": "No datasets have been successfully processed in this workspace yet. Please upload and run a pipeline.",
                "agent_name": "ETL Chat Support Agent",
                "confidence": 95.0
            }
        
        raw_filename = None
        try:
            upload_row = db.execute(
                text("SELECT filename FROM raw_uploads WHERE batch_id = :b LIMIT 1"),
                {"b": latest_batch}
            ).first()
            if upload_row:
                raw_filename = upload_row[0]
        except Exception:
            pass

        if not raw_filename:
            backup_path = os.path.join(PROJECT_ROOT, ".last_cleaned_backup.json")
            if os.path.exists(backup_path):
                try:
                    with open(backup_path, "r", encoding="utf-8") as bf:
                        raw_filename = json.load(bf).get("filename")
                except Exception:
                    pass

        if raw_filename:
            clean_path = f"cleaned data/{raw_filename}"
            if os.path.exists(os.path.join(PROJECT_ROOT, clean_path)):
                clean_url = f"/api/v1/reports/download-file?path={clean_path}"
                response_msg = f"### Most Recently Generated File\n\nHere is the most recently generated (cleaned) file:\n\n- **Cleaned Dataset File**: [Download {raw_filename}]({clean_url})"
                return {
                    "response": response_msg,
                    "agent_name": "ETL Chat Support Agent",
                    "confidence": 100.0
                }
        
        try:
            report_row = db.execute(
                text("SELECT pdf_path FROM generated_reports WHERE batch_id = :b LIMIT 1"),
                {"b": latest_batch}
            ).first()
            if report_row and report_row[0]:
                pdf_path = report_row[0]
                pdf_name = os.path.basename(pdf_path)
                pdf_url = f"/api/v1/reports/download/{latest_batch}?format=pdf"
                response_msg = f"### Most Recently Generated File\n\nHere is the most recently generated report file:\n\n- **PDF Report**: [Download {pdf_name}]({pdf_url})"
                return {
                    "response": response_msg,
                    "agent_name": "ETL Chat Support Agent",
                    "confidence": 100.0
                }
        except Exception:
            pass

        return {
            "response": "Found the latest batch but could not locate the generated cleaned dataset or reports on disk.",
            "agent_name": "ETL Chat Support Agent",
            "confidence": 90.0
        }

    # 4. Check process logs (general/by process ID)
    is_log_query = False
    if "log" in message_lower or "logs" in message_lower:
        is_log_query = True
        
    if is_log_query:
        # Check if the query is related to process logs and requests direct access to regenerate reports
        is_log_regen = ("access" in message_lower or "directly" in message_lower) and \
                       ("regenerate" in message_lower or "re-generate" in message_lower or "recreate" in message_lower or "previous document" in message_lower)
            
        if not batch_id:
            return {
                "response": "I could not identify a valid batch ID for the logs. Please specify a batch/process ID.",
                "agent_name": "ETL Chat Support Agent",
                "confidence": 90.0
            }
            
        if is_log_regen:
            # 1. Read process logs directly from disk
            log_path = os.path.join(PROJECT_ROOT, "logs", f"{batch_id}.log")
            log_content = ""
            if os.path.exists(log_path):
                with open(log_path, "r", encoding="utf-8") as lf:
                    log_content = lf.read()
                    
            # 2. Parse log contents
            rows_loaded = 0
            rows_rejected = 0
            status_selected = "CSV"
            path_selected = ""
            storage_reason = "Dynamic selection based on constraints"
            
            if log_content:
                for line in log_content.split("\n"):
                    if "DB Sync Status:" in line:
                        match = re.search(r'Loaded\s+(\d+),\s+Rejected\s+(\d+)', line)
                        if match:
                            rows_loaded = int(match.group(1))
                            rows_rejected = int(match.group(2))
                    elif "Format selected:" in line:
                        fmt_match = re.search(r'Format selected:\s+(\w+)', line)
                        if fmt_match:
                            status_selected = fmt_match.group(1)
                        saved_match = re.search(r'Saved to\s+([^.]+)', line)
                        if saved_match:
                            path_selected = saved_match.group(1).strip()
                        elif "Database Table:" in line:
                            db_match = re.search(r'Database Table:\s+(\w+)', line)
                            if db_match:
                                path_selected = db_match.group(1)

            # 3. Query metadata from DB
            upload_row = db.execute(
                text("SELECT filename, file_type FROM raw_uploads WHERE batch_id = :b LIMIT 1"),
                {"b": batch_id}
            ).first()
            dataset_name = upload_row[0] if upload_row else "dataset"
            file_type = upload_row[1] if upload_row else "csv"
            
            quality_row = db.execute(
                text("SELECT quality_score, missing_values, duplicate_count FROM quality_reports WHERE batch_id = :b"),
                {"b": batch_id}
            ).first()
            quality_score = quality_row[0] if quality_row else 100.0
            missing_count = quality_row[1] if quality_row else 0
            duplicate_rows = quality_row[2] if quality_row else 0

            txs = db.execute(
                text("SELECT column_name, old_value, new_value, reason FROM transformation_logs WHERE batch_id = :b"),
                {"b": batch_id}
            ).fetchall()
            transformation_history = []
            for tx in txs:
                transformation_history.append({
                    "column_name": tx[0],
                    "old_value": tx[1],
                    "new_value": tx[2],
                    "reason": tx[3]
                })
                
            rejected_records = []
            table_name = None
            if "customer" in dataset_name.lower():
                table_name = "staging_customers"
            elif "order" in dataset_name.lower():
                table_name = "staging_orders"
            elif "sale" in dataset_name.lower():
                table_name = "staging_sales"
                
            if table_name:
                try:
                    rej_rows = db.execute(
                        text(f"SELECT * FROM {table_name} WHERE batch_id = :b AND validation_status = 'Rejected'"),
                        {"b": batch_id}
                    ).fetchall()
                    for r_idx, row in enumerate(rej_rows):
                        row_dict = dict(row._mapping)
                        rejected_records.append({
                            "row_number": row_dict.get("row_number", r_idx + 1),
                            "reason": "Value validation constraint failure",
                            "record": row_dict
                        })
                except Exception:
                    pass

            val_res = {
                "rows_loaded": rows_loaded,
                "rows_rejected": rows_rejected,
                "staging_status": "Success" if rows_rejected == 0 else "Passed with Warnings",
                "production_status": "Success" if rows_rejected == 0 else "Passed with Warnings",
                "sql_logs": ["SELECT * FROM staging_records;"],
                "rejected_records": rejected_records
            }
            
            state_mock = {
                "batch_id": batch_id,
                "dataset_name": dataset_name,
                "dataset_path": f"data/raw/{dataset_name}",
                "quality_score": quality_score,
                "metadata": {
                    "file_info": {"file_type": file_type, "encoding": "utf-8", "delimiter": ","},
                    "rows": rows_loaded + rows_rejected,
                    "columns": 5
                },
                "duplicate_rows": duplicate_rows,
                "missing_values": {},
                "column_types": {},
                "transformation_history": transformation_history,
                "validation_results": val_res,
                "format_selected": status_selected,
                "formatted_file_path": path_selected,
                "storage_reason": storage_reason
            }
            
            try:
                from agents.report_agent.report_agent import ReportAgent
                agent = ReportAgent()
                res = agent.run(state_mock)
                
                pdf_url = f"/api/v1/reports/download/{batch_id}?format=pdf"
                txt_url = f"/api/v1/reports/download/{batch_id}?format=txt"
                md_url = f"/api/v1/reports/download/{batch_id}?format=markdown"
                json_url = f"/api/v1/reports/download/{batch_id}?format=json"
                
                response_msg = f"""### Log-Based Document Regeneration Successful
    
I have accessed the process log file (`logs/{batch_id}.log`) directly and successfully regenerated the reports for **Batch ID**: `{batch_id}`.

The regenerated files are stored in the folder matching the input name (`reports/{dataset_name}/`):
- **PDF Report**: [Download PDF Report]({pdf_url})
- **TXT Report**: [Download TXT Report]({txt_url})
- **Markdown Report**: [Download Markdown Report]({md_url})
- **JSON Report**: [Download JSON Report]({json_url})

The reports reflect the exact metrics and run metadata parsed directly from the execution logs:
- **Rows Loaded**: {rows_loaded}
- **Rows Rejected**: {rows_rejected}
- **Selected Storage Format**: {status_selected}
- **Staging Quality Score**: {quality_score}%
"""
                return {
                    "response": response_msg,
                    "agent_name": "ETL Chat Support Agent",
                    "confidence": 100.0
                }
            except Exception as ex:
                return {
                    "response": f"Failed to dynamically regenerate report from process logs: {str(ex)}",
                    "agent_name": "ETL Chat Support Agent",
                    "confidence": 60.0
                }
        else:
            log_content, log_source = get_logs_for_batch(db, batch_id)
            if not log_content:
                return {
                    "response": f"I could not locate any process logs or database logs for batch `{batch_id}`.",
                    "agent_name": "ETL Chat Support Agent",
                    "confidence": 85.0
                }
            
            response_msg = f"Here are the process logs you requested ({log_source}):\n\n```text\n{log_content}\n```"
            
            prompt_with_logs = f"""
            You are the Senior Data Engineering Chat Assistant for the Agentic AI ETL Platform.
            The user asked a question regarding process logs.
            Here is the process logs content we retrieved:
            {log_content}
            
            Conversation History:
            {formatted_history if formatted_history else "No previous conversation history."}
            
            User Query: {req.message}
            
            Based on the logs and conversation history above, answer the user's question. Output a detailed markdown response that includes the logs content if requested or relevant.
            Format your response as a JSON object containing:
            - response: detailed, formatted markdown response answering the user.
            - agent_name: "ETL Chat Support Agent"
            - confidence: float between 0 and 100 on accuracy of answer.
            
            Return ONLY valid JSON.
            """
            try:
                llm_res = query_llm(prompt_with_logs, "You are the ETL Chat Support Agent.", json_mode=True)
                if "```json" in llm_res:
                    llm_res = llm_res.split("```json")[1].split("```")[0].strip()
                elif "```" in llm_res:
                    llm_res = llm_res.split("```")[1].split("```")[0].strip()
                data = json.loads(llm_res.strip())
                response_text = data.get("response") or response_msg
                if "```" not in response_text:
                    response_text = f"{response_text}\n\n{response_msg}"
                return {
                    "response": response_text,
                    "agent_name": data.get("agent_name", "ETL Chat Support Agent"),
                    "confidence": data.get("confidence", 95.0)
                }
            except Exception:
                return {
                    "response": response_msg,
                    "agent_name": "ETL Chat Support Agent",
                    "confidence": 95.0
                }

    # 5. File access query (general / by process ID)
    is_file_access = any(k in message_lower for k in [
        "access file", "access files", "get file", "get files", "download file", "download files", 
        "send me the file", "send me the files", "give me the file", "give me the files"
    ])
    if is_file_access and batch_id:
        links, raw_fn = get_files_for_batch(db, batch_id)
        if raw_fn:
            response_msg = f"### File Access for Batch `{batch_id}`\n\nHere are the downloadable assets for the requested run:\n\n{links}"
            return {
                "response": response_msg,
                "agent_name": "ETL Chat Support Agent",
                "confidence": 100.0
            }

    # 6. General Context-based chatbot query
    context = ""
    file_info = {}
    if batch_id:
        context += f"Context for Batch ID: {batch_id}\n"
        
        # A. Raw upload information
        upload_row = db.execute(
            text("SELECT filename, status, file_type, upload_time FROM raw_uploads WHERE batch_id = :b LIMIT 1"),
            {"b": batch_id}
        ).first()
        if upload_row:
            filename, upload_status, file_type, upload_time = upload_row
            context += f"- Uploaded File: {filename} | Status: {upload_status} | Type: {file_type} | Time: {upload_time}\n"
            file_info["raw_filename"] = filename
            file_info["raw_path"] = f"data/raw/{filename}"
        else:
            # Fallback check persistent backup
            backup_path = os.path.join(PROJECT_ROOT, ".last_cleaned_backup.json")
            if os.path.exists(backup_path):
                try:
                    with open(backup_path, "r", encoding="utf-8") as bf:
                        data = json.load(bf)
                        if data.get("batch_id") == batch_id:
                            filename = data.get("filename")
                            _, ext = os.path.splitext(filename.lower())
                            context += f"- Uploaded File: {filename} | Status: Success (From cache) | Type: {ext[1:]} | Time: Unknown\n"
                            file_info["raw_filename"] = filename
                            file_info["raw_path"] = f"data/raw/{filename}"
                except Exception:
                    pass

        # B. Pipeline Execution logs
        pipe_row = db.execute(
            text("SELECT status, execution_time, start_time, end_time FROM pipeline_logs WHERE pipeline_id = :p"),
            {"p": f"pipe_{batch_id}"}
        ).first()
        if pipe_row:
            exec_time = pipe_row[1] if pipe_row[1] is not None else 0.0
            context += f"- Pipeline Execution: status={pipe_row[0]} | Duration={exec_time:.2f}s | Range={pipe_row[2]} to {pipe_row[3]}\n"

        # C. Quality reports
        quality_row = db.execute(
            text("SELECT quality_score, missing_values, duplicate_count, schema_match FROM quality_reports WHERE batch_id = :b"),
            {"b": batch_id}
        ).first()
        if quality_row:
            context += f"- Quality Report Metrics: Quality Score={quality_row[0]}% | Missing Values={quality_row[1]} | Duplicate Count={quality_row[2]} | Schema Match={quality_row[3]}\n"

        # D. Root Cause reports (RCA)
        rcas = db.execute(
            text("SELECT issue, root_cause, business_impact, technical_impact, recommendation, confidence FROM root_cause_reports WHERE batch_id = :b"),
            {"b": batch_id}
        ).fetchall()
        if rcas:
            context += "- Root Cause / Quality Issues Discovered:\n"
            for rca in rcas:
                context += f"  * Issue: {rca[0]}\n    - Root Cause: {rca[1]}\n    - Business Impact: {rca[2]}\n    - Technical Impact: {rca[3]}\n    - Recommendation: {rca[4]}\n    - Confidence: {rca[5]}%\n"

        # E. Transformation logs
        txs = db.execute(
            text("SELECT column_name, old_value, new_value, reason FROM transformation_logs WHERE batch_id = :b"),
            {"b": batch_id}
        ).fetchall()
        if txs:
            context += "- Transformations applied during clean step:\n"
            for tx in txs:
                context += f"  * Column '{tx[0]}': '{tx[1]}' -> '{tx[2]}' | Reason: {tx[3]}\n"

        # F. Validation logs
        vals = db.execute(
            text("SELECT validation_type, status, message FROM validation_logs WHERE batch_id = :b"),
            {"b": batch_id}
        ).fetchall()
        if vals:
            context += "- Validation execution logs:\n"
            for val in vals:
                context += f"  * Check [{val[0]}]: status={val[1]} | message={val[2]}\n"

        # G. Agent detailed execution logs
        alogs = db.execute(
            text("SELECT agent_name, task, reasoning, confidence FROM agent_logs WHERE batch_id = :b"),
            {"b": batch_id}
        ).fetchall()
        if alogs:
            context += "- Multi-Agent workflow execution steps:\n"
            for al in alogs:
                context += f"  * [{al[0]}] {al[1]}: {al[2]} (confidence: {al[3]}%)\n"

        # H. Reports and Files
        links, raw_fn = get_files_for_batch(db, batch_id)
        if raw_fn:
            context += f"\nAvailable files for download/viewing for this batch:\n{links}\n"

    # I. Scan query for specific files
    query_file_matches = re.findall(r'\b[\w\.-]+\.(?:csv|tsv|json|xlsx|xml|xls)\b', req.message, re.IGNORECASE)
    custom_links_context = ""
    if query_file_matches:
        for f_match in query_file_matches:
            paths_to_check = [
                ("cleaned data", f"cleaned data/{f_match}"),
                ("data/raw", f"data/raw/{f_match}"),
                ("reports", f"reports/{f_match}"),
                ("logs", f"logs/{f_match}")
            ]
            for label, relative_path in paths_to_check:
                full_check_path = os.path.join(PROJECT_ROOT, relative_path)
                if os.path.exists(full_check_path):
                    download_url = f"/api/v1/reports/download-file?path={relative_path.replace(' ', '%20')}"
                    link_text = f"[Download {f_match}]({download_url})"
                    if download_url not in context:
                        custom_links_context += f"- File {f_match} ({label}): {link_text}\n"
                        break
                        
    if custom_links_context:
        if not context:
            context = "Context for requested files:\n"
        context += "\nDirectly matched files in the workspace filesystem:\n" + custom_links_context

    prompt = f"""
    You are the Senior Data Engineering Chat Assistant for the Agentic AI ETL Platform.
    Using the database context and conversation history below, answer the user's questions regarding their ETL runs, data quality issues, database structure, or general ETL pipeline behavior.
    
    Database Context:
    {context if context else "No specific batch context loaded. Provide general info on the pipeline architecture."}
    
    Conversation History:
    {formatted_history if formatted_history else "No previous conversation history."}
    
    User Query: {req.message}
    
    Ensure you analyze the user's text patterns and understand their actual intent. 
    If the user's query is platform-related (such as file-related problems, logs and execution issues, or internal platform bugs), you must structure your response to provide:
    1. The possible causes of the issue.
    2. Recommended solutions.
    
    Format your answer as a JSON object containing:
    - response: detailed, formatted markdown response answering the user, containing possible causes and recommended solutions if it is a platform-related issue.
    - agent_name: "ETL Chat Support Agent"
    - confidence: float between 0 and 100 on accuracy of answer.
    
    Return ONLY valid JSON.
    """
    
    system_instruction = (
        "You are the senior intelligent ETL Chat Support Agent. "
        "Before generating a response, analyze the user's text patterns and understand their actual intent. "
        "Formulate your response based on the identified intent rather than doing simple keyword matching. "
        "If the user is experiencing platform-related issues (such as file-related problems, logs and execution issues, "
        "or internal platform bugs), you must identify possible causes and provide clear recommended solutions. "
        "Keep this intelligence strictly limited to platform-related assistance. Do not modify unrelated chatbot features. "
        "If the user asks for files or downloads, you must output the appropriate markdown download links (e.g., [Download filename](url)) "
        "from the database context."
    )
    
    try:
        llm_res = query_llm(prompt, system_instruction, json_mode=True)
        if "```json" in llm_res:
            llm_res = llm_res.split("```json")[1].split("```")[0].strip()
        elif "```" in llm_res:
            llm_res = llm_res.split("```")[1].split("```")[0].strip()
            
        data = json.loads(llm_res.strip())
        
        response_text = ""
        agent_name = "ETL Chat Support Agent"
        confidence = 95.0
        
        if isinstance(data, dict):
            response_text = data.get("response") or data.get("executive_summary") or data.get("summary") or json.dumps(data)
            agent_name = data.get("agent_name", agent_name)
            confidence = data.get("confidence", confidence)
        elif isinstance(data, list):
            response_text = json.dumps(data, indent=2)
        else:
            response_text = str(data)
            
        return {
            "response": response_text,
            "agent_name": agent_name,
            "confidence": confidence
        }
    except Exception as e:
        return {
            "response": f"I processed your request, but experienced an issue parsing the detailed analysis: {str(e)}. Direct query: '{req.message}'",
            "agent_name": "ETL Chat Support Agent (Fallback Mode)",
            "confidence": 70.0
        }

