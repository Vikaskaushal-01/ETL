from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from sqlalchemy import text
from backend.database.mysql import get_db
from backend.schemas.schemas import ChatRequest, ChatResponse
from backend.core.llm import query_llm
from typing import Optional
import json
import re
import os
import logging

logger = logging.getLogger("etl_chat")

router = APIRouter(prefix="/agent", tags=["AI Agent Chat"])

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

PLATFORM_TROUBLESHOOTING_GUIDE = """
=== Platform Troubleshooting Reference (Causes & Solutions) ===
1. Live Logs Console / Terminal Issues:
   - Possible Causes:
     * Pipeline execution has not been started yet.
     * The `logs/` directory in the project root is missing or doesn't have write permissions.
     * MySQL connection is down, preventing DB logs from writing.
   - Recommended Solutions:
     * Make sure you paste/upload a dataset and click "Start Automation" to spawn a run.
     * Verify that the `logs` folder exists in the project root. If missing, create it: `mkdir logs`.
     * Check if the API is active by hitting GET `/api/health`.

2. Staging / Database Load / SQL Sync Problems:
   - Possible Causes:
     * MySQL service (`etl_mysql` container) is offline or crashed.
     * Mismatched host, port, or password in the `.env` settings.
     * Database tables structure is corrupt or uninitialized.
   - Recommended Solutions:
     * Run `docker ps` to verify that `etl_mysql` is up and running.
     * Verify connection using the database verification script `verify_pipeline.py`.
     * Run `cleanup_all.py` to reset and automatically recreate all stage schema and production tables.
     * Double-check credentials in the `.env` file (`MYSQL_HOST`, `MYSQL_PORT`, etc.).

3. File Ingestion & File System Issues:
   - Possible Causes:
     * The file paths `data/raw` or `cleaned data` are missing or locked by Windows process handlers.
     * Invalid delimiter or encoding in the raw file.
   - Recommended Solutions:
     * Ensure the project root path is resolved to absolute paths.
     * Clear process handlers or run a clean reset if files are locked.
     * Verify delimiter properties (should be comma, semicolon, tab, or pipe).

4. SnapLogic / Container Network / LLM Connection Errors:
   - Possible Causes:
     * Docker service container names cannot resolve each other.
     * Gemini API Key is missing or expired in `.env`.
   - Recommended Solutions:
     * Rebuild and restart services: `docker-compose up --build -d`.
     * Ensure `GEMINI_API_KEY` is set and valid in `.env`.
"""

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

def get_latest_batch_id(db, user_email: Optional[str] = None) -> str:
    email = user_email or "admin@controlai.net"
    # Try database
    try:
        latest_run = db.execute(
            text("SELECT pipeline_id FROM pipeline_logs WHERE status IN ('Success', 'Passed with Warnings') AND pipeline_id IN (SELECT CONCAT('pipe_', batch_id) FROM raw_uploads WHERE uploaded_by = :email) ORDER BY start_time DESC LIMIT 1"),
            {"email": email}
        ).first()
        if latest_run:
            return latest_run[0].replace("pipe_", "")
    except Exception:
        pass
    
    # Try persistent cache (only if user email is admin)
    if email == "admin@controlai.net":
        backup_path = os.path.abspath(".last_cleaned_backup.json")
        if os.path.exists(backup_path):
            try:
                with open(backup_path, "r", encoding="utf-8") as bf:
                    return json.load(bf).get("batch_id")
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
    from backend.utils.account_utils import get_user_path
    # 1. Get raw file info from DB
    raw_filename = None
    file_type = None
    uploaded_by = None
    
    try:
        upload_row = db.execute(
            text("SELECT filename, file_type, uploaded_by FROM raw_uploads WHERE batch_id = :b LIMIT 1"),
            {"b": batch_id}
        ).first()
        if upload_row:
            raw_filename, file_type, uploaded_by = upload_row[0], upload_row[1], upload_row[2]
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
    
    # Resolve user isolated paths
    raw_full_path = get_user_path(uploaded_by, f"data/raw/{raw_filename}")
    clean_full_path = get_user_path(uploaded_by, f"cleaned data/{raw_filename}")
    
    # A. Raw file path
    if os.path.exists(raw_full_path):
        rel_raw = raw_full_path.replace(PROJECT_ROOT, "").strip("/\\").replace("\\", "/")
        raw_url = f"/api/v1/reports/download-file?path={rel_raw}"
        available_files_context += f"- **Raw Uploaded File**: [Download {raw_filename}]({raw_url})\n"
        
    # B. Clean file path
    if os.path.exists(clean_full_path):
        rel_clean = clean_full_path.replace(PROJECT_ROOT, "").strip("/\\").replace("\\", "/")
        clean_url = f"/api/v1/reports/download-file?path={rel_clean}"
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
            
            def check_file_path(p):
                if not p:
                    return False
                if os.path.isabs(p):
                    return os.path.exists(p)
                return os.path.exists(os.path.join(PROJECT_ROOT, p))
                
            if pdf_p and check_file_path(pdf_p):
                available_files_context += f"- **PDF Report**: [Download PDF Report](/api/v1/reports/download/{batch_id}?format=pdf)\n"
            if docx_p and check_file_path(docx_p):
                available_files_context += f"- **Word (DOCX) Report**: [Download Word Report](/api/v1/reports/download/{batch_id}?format=docx)\n"
            if md_p and check_file_path(md_p):
                available_files_context += f"- **Markdown Report**: [Download Markdown Report](/api/v1/reports/download/{batch_id}?format=markdown)\n"
            if json_p and check_file_path(json_p):
                available_files_context += f"- **JSON Report**: [Download JSON Report](/api/v1/reports/download/{batch_id}?format=json)\n"
            if txt_p and check_file_path(txt_p):
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
                            if path and (os.path.exists(path) if os.path.isabs(path) else os.path.exists(os.path.join(PROJECT_ROOT, path))):
                                clean_fmt = fmt.replace("_path", "")
                                available_files_context += f"- **{clean_fmt.upper()} Report**: [Download {clean_fmt.upper()} Report](/api/v1/reports/download/{batch_id}?format={clean_fmt})\n"
            except Exception:
                pass
                
    return available_files_context, raw_filename

@router.post("/chat", response_model=ChatResponse)
def agent_chat(req: ChatRequest, db: Session = Depends(get_db), x_user_email: Optional[str] = Header(None)):
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

    # Dynamic batch resolution based on filename keywords or substrings
    email = x_user_email or "admin@controlai.net"
    matched_batch_id = None
    try:
        uploads = db.execute(
            text("SELECT batch_id, filename FROM raw_uploads WHERE uploaded_by = :e ORDER BY upload_time DESC"),
            {"e": email}
        ).fetchall()
        for bid, fn in uploads:
            fn_base = os.path.splitext(fn.lower())[0]
            # Match if they type "pokemon", "titanic", "customers", etc.
            words_in_fn = [w for w in re.split(r'\W+', fn_base) if len(w) > 2]
            if fn.lower() in message_lower or fn_base in message_lower or any(w in message_lower for w in words_in_fn):
                matched_batch_id = bid
                break
    except Exception:
        pass

    if matched_batch_id:
        batch_id = matched_batch_id
    elif not batch_id:
        batch_id = get_latest_batch_id(db, x_user_email)

    # Format history
    formatted_history = ""
    if req.history:
        for msg in req.history:
            role_label = "User" if msg.role == "user" else "Assistant"
            formatted_history += f"{role_label}: {msg.content}\n"

    # 2. Check if this is a request to regenerate a document directly from process logs
    is_log_regen = ("access" in message_lower or "directly" in message_lower) and \
                   ("regenerate" in message_lower or "re-generate" in message_lower or "recreate" in message_lower or "previous document" in message_lower)
                   
    if is_log_regen and batch_id:
        # We parse the logs and call ReportAgent to regenerate reports
        log_path = os.path.join(PROJECT_ROOT, "logs", f"{batch_id}.log")
        log_content = ""
        if os.path.exists(log_path):
            with open(log_path, "r", encoding="utf-8") as lf:
                log_content = lf.read()
                
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

        # Query metadata from DB
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

    # 3. Check logs query specifically
    is_log_query = ("log" in message_lower or "logs" in message_lower) and not is_log_regen
    if is_log_query and batch_id:
        log_content, log_source = get_logs_for_batch(db, batch_id)
        if log_content:
            response_msg = f"Here are the process logs you requested ({log_source}):\n\n```text\n{log_content}\n```"
            
            # Wrap standard logs query with a nice LLM response
            prompt_with_logs = f"""
            You are the Senior Data Engineering Chat Assistant for the Agentic AI ETL Platform.
            The user asked a question regarding process logs.
            Here is the process logs content we retrieved:
            {log_content}
            
            Conversation History:
            {formatted_history if formatted_history else "No previous conversation history."}
            
            User Query: {req.message}
            
            Based on the logs and conversation history above, answer the user's question. Output a detailed markdown response that includes the logs content if requested or relevant.
            """
            try:
                llm_res = query_llm(prompt_with_logs, "You are the ETL Chat Support Agent. Summarize logs clearly in markdown.", json_mode=False)
                if "```" not in llm_res:
                    llm_res = f"{llm_res}\n\n{response_msg}"
                return {
                    "response": llm_res,
                    "agent_name": "ETL Chat Support Agent",
                    "confidence": 100.0
                }
            except Exception:
                return {
                    "response": response_msg,
                    "agent_name": "ETL Chat Support Agent",
                    "confidence": 95.0
                }
        else:
            return {
                "response": f"I could not locate any process logs or database logs for batch `{batch_id}`.",
                "agent_name": "ETL Chat Support Agent",
                "confidence": 80.0
            }

    # 4. Explicit File Download / Link Retrieval Mode
    from backend.utils.account_utils import get_user_path
    
    log_paths = re.findall(r'\b(?:data/raw|cleaned data|reports|logs)/[\w\.-]+\b', req.message, re.IGNORECASE)
    
    explicit_file_download_keywords = [
        "download the file", "send me the file", "download file", "send file", "get the file", 
        "download link", "where is the file", "give me the file", "send the cleaned file",
        "download cleaned file", "download raw file", "get download link"
    ]
    is_explicit_file_request = any(k in message_lower for k in explicit_file_download_keywords) or len(log_paths) > 0

    if is_explicit_file_request and not any(k in message_lower for k in ["why", "how", "what is", "explain", "describe", "calculate"]):
        matches = []
        
        # A. Add explicit paths found in prompt (e.g. from cleaning logs shared by user)
        for lp in log_paths:
            full_check = get_user_path(email, lp)
            parts = lp.replace("\\", "/").split("/")
            fname = parts[-1]
            folder = "/".join(parts[:-1]) if len(parts) > 1 else "cleaned data"
            
            rel_path_clean = full_check.replace(PROJECT_ROOT, "").strip("/\\").replace("\\", "/")
            download_url = f"/api/v1/reports/download-file?path={rel_path_clean}"
            
            matches.append({
                "label": folder,
                "filename": fname,
                "download_url": download_url
            })
            
        if batch_id:
            links, raw_fn = get_files_for_batch(db, batch_id)
            if raw_fn:
                response_msg = f"### File Access for Batch `{batch_id}`\n\nHere are the downloadable assets for the requested run:\n\n{links}"
                return {
                    "response": response_msg,
                    "agent_name": "ETL Chat Support Agent",
                    "confidence": 100.0
                }
                
        if matches:
            response_msg = "### File Access & Download Links\n\nHere are the files you requested:\n\n"
            for m in matches:
                response_msg += f"- **{m['filename']}** ({m['label']}): [Download {m['filename']}]({m['download_url']})\n"
            return {
                "response": response_msg,
                "agent_name": "ETL Chat Support Agent",
                "confidence": 100.0
            }
    context = ""
    if batch_id:
        context += f"Context for Batch ID: {batch_id}\n"
        try:
            # Raw
            upload_row = db.execute(
                text("SELECT filename, status, file_type, upload_time FROM raw_uploads WHERE batch_id = :b LIMIT 1"),
                {"b": batch_id}
            ).first()
            if upload_row:
                context += f"- Uploaded File: {upload_row[0]} | Status: {upload_row[1]} | Type: {upload_row[2]} | Time: {upload_row[3]}\n"
                
            # Pipeline
            pipe_row = db.execute(
                text("SELECT status, execution_time, start_time, end_time FROM pipeline_logs WHERE pipeline_id = :p"),
                {"p": f"pipe_{batch_id}"}
            ).first()
            if pipe_row:
                exec_time = pipe_row[1] if pipe_row[1] is not None else 0.0
                context += f"- Pipeline Execution: status={pipe_row[0]} | Duration={exec_time:.2f}s | Range={pipe_row[2]} to {pipe_row[3]}\n"
                
            # Quality
            quality_row = db.execute(
                text("SELECT quality_score, missing_values, duplicate_count, schema_match FROM quality_reports WHERE batch_id = :b"),
                {"b": batch_id}
            ).first()
            if quality_row:
                context += f"- Quality Report Metrics: Quality Score={quality_row[0]}% | Missing Values={quality_row[1]} | Duplicate Count={quality_row[2]} | Schema Match={quality_row[3]}\n"
                
            # RCA
            rcas = db.execute(
                text("SELECT issue, root_cause, business_impact, technical_impact, recommendation, confidence FROM root_cause_reports WHERE batch_id = :b"),
                {"b": batch_id}
            ).fetchall()
            if rcas:
                context += "- Root Cause / Quality Issues Discovered:\n"
                for rca in rcas:
                    context += f"  * Issue: {rca[0]}\n    - Root Cause: {rca[1]}\n    - Business Impact: {rca[2]}\n    - Technical Impact: {rca[3]}\n    - Recommendation: {rca[4]}\n    - Confidence: {rca[5]}%\n"
        except Exception:
            pass

    # RAG Context
    rag_context = ""
    try:
        from backend.database.models import RagDocument
        rag_docs = db.query(RagDocument).filter(RagDocument.uploaded_by == email).all()
        if rag_docs:
            query_words = set(re.findall(r'\w+', req.message.lower()))
            matching_chunks = []
            for doc in rag_docs:
                if doc.content:
                    paragraphs = [p.strip() for p in doc.content.split('\n') if p.strip()]
                    for p in paragraphs:
                        sub_chunks = [p[i:i+500] for i in range(0, len(p), 500)]
                        for chunk in sub_chunks:
                            chunk_words = set(re.findall(r'\w+', chunk.lower()))
                            intersection = query_words.intersection(chunk_words)
                            if intersection:
                                score = len(intersection) / (len(query_words) + 1)
                                matching_chunks.append((score, doc.filename, chunk))
            matching_chunks.sort(key=lambda x: x[0], reverse=True)
            top_chunks = matching_chunks[:5]
            if top_chunks:
                rag_context += "\n=== Relevant Information from User Documents (RAG Context) ===\n"
                for score, filename, chunk in top_chunks:
                    rag_context += f"[Document Reference: {filename}] (Score: {score:.2f}):\n{chunk}\n\n"
    except Exception as rag_err:
        logger.error(f"Error querying RAG context: {rag_err}")

    if rag_context:
        context += rag_context

    # Troubleshooting guidelines
    is_platform_issue = any(k in message_lower for k in [
        "log", "logs", "terminal", "console", "bug", "error", "crash", "fail", "broken",
        "database", "mysql", "db", "conn", "schema", "table", "download", "file", "ingest",
        "snaplogic", "docker", "compose", "api key", "gemini", "problem", "solve", "solution"
    ])
    
    troubleshooting_context = ""
    if is_platform_issue:
        troubleshooting_context = f"\nPlatform Troubleshooting Reference (Causes & Solutions):\n{PLATFORM_TROUBLESHOOTING_GUIDE}\n"

    prompt = f"""
    You are the Senior Data Engineering Chat Assistant for the Agentic AI ETL Platform.
    Using the database context, troubleshooting guidelines, and conversation history below, answer the user's questions regarding their ETL runs, data quality issues, database structure, or general ETL pipeline behavior.
    
    Database Context:
    {context if context else "No specific batch context loaded. Provide general info on the pipeline architecture."}
    
    {troubleshooting_context}
    
    Conversation History:
    {formatted_history if formatted_history else "No previous conversation history."}
    
    User Query: {req.message}
    
    Ensure you analyze the user's text patterns and understand their actual intent. 
    If the user's query is platform-related (such as file-related problems, logs and execution issues, or internal platform bugs), you must structure your response to provide:
    1. The possible causes of the issue.
    2. Recommended solutions.
    """
    
    system_instruction = (
        "You are the senior intelligent ETL Chat Support Agent. "
        "Before generating a response, analyze the user's text patterns and understand their actual intent. "
        "Formulate your response based on the identified intent rather than doing simple keyword matching. "
        "If the user is experiencing platform-related issues (such as file-related problems, logs and execution issues, "
        "or internal platform bugs), you must identify possible causes and provide clear recommended solutions."
    )
    
    try:
        llm_res = query_llm(prompt, system_instruction, json_mode=False)
        return {
            "response": llm_res,
            "agent_name": "ETL Chat Support Agent",
            "confidence": 95.0
        }
    except Exception as e:
        return {
            "response": f"I processed your request, but experienced an issue generating the detailed analysis: {str(e)}. Direct query: '{req.message}'",
            "agent_name": "ETL Chat Support Agent (Fallback Mode)",
            "confidence": 70.0
        }

