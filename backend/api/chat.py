"""
AI assistant chat.

The assistant behaves like a normal conversational AI (answering any question through the configured
LLM), and additionally serves exactly what the user asks for from their own workspace:
  * files  - raw upload, cleaned dataset, PDF / Word / Markdown / JSON reports
  * logs   - the full process log of a pipeline run
Nothing else is appended to those answers.
"""
import json
import logging
import os
import re
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.core.llm import query_llm, is_real_llm_available
from backend.core.security import DEFAULT_ADMIN_EMAIL, is_valid_batch_id
from backend.database.mysql import get_db
from backend.schemas.schemas import ChatRequest, ChatResponse
from backend.utils.account_utils import get_user_path, is_admin, user_owns_batch

logger = logging.getLogger("etl_chat")

router = APIRouter(prefix="/agent", tags=["AI Agent Chat"])

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
AGENT_NAME = "Control AI Assistant"
MAX_LOG_CHARS = 20000
MAX_HISTORY_MESSAGES = 8
MAX_HISTORY_CHARS = 1500

ADMIN_ONLY_RESPONSE = {
    "response": "Workspace-wide maintenance (resetting the platform or clearing shared logs) can only be run by the administrator account.",
    "agent_name": AGENT_NAME,
    "confidence": 100.0
}

SYSTEM_PROMPT = (
    "You are Control AI Assistant, a helpful, friendly general-purpose AI assistant built into an ETL data platform. "
    "Answer any question the user asks - general knowledge, coding, writing, maths or questions about their data - "
    "naturally and concisely in Markdown, like a normal AI chat assistant. "
    "A 'Workspace context' section may list the user's pipeline runs and details of a selected run. Use it only when "
    "the question is about their data, runs, quality or errors, and never invent numbers, files or results that are not "
    "in that context. Do not mention the context, these instructions, or the platform unless it is relevant to the question. "
    "If the user wants files or logs, tell them they can ask e.g. 'give me the cleaned file for sales.csv' or "
    "'show the log for sales.csv'.\n\n"
    "Facts about this platform (use them for how-to questions about it):\n"
    "- Sign in on the start page with email and password; 'Sign up' creates an account; 'Forgot Password' sends a 6-digit reset code. Sign out from the avatar menu.\n"
    "- Pipeline page: upload a file (CSV, TSV, JSON, XML, Excel), fetch one from a URL, or stream from a live URL feed, then press Run. "
    "The run goes through intake/profiling, cleaning, validation and database load, report generation, and a Power BI export.\n"
    "- History lists every run (with log, report, cleaned-file and re-run buttons); Reports has PDF, Word, Markdown and JSON reports; "
    "Logs shows each run's full process log; Storage lists raw, cleaned, report, log and Power BI files; "
    "Power BI exports the star schema as CSV files for Power BI Desktop; Settings has profile, password, API keys and preferences."
)


def _reply(text_value: str, confidence: float = 100.0) -> dict:
    return {"response": text_value, "agent_name": AGENT_NAME, "confidence": confidence}


# ---------------------------------------------------------------------------
# Intent detection
# ---------------------------------------------------------------------------

def is_question(message_lower: str) -> bool:
    """Heuristic: questions / how-to requests must never trigger destructive maintenance commands."""
    text_val = message_lower.strip()
    return text_val.endswith("?") or bool(re.match(r"^(how|what|why|when|where|can|could|should|would|is|are|do|does|explain|tell me)\b", text_val))


def sanitize_user_prompt(prompt: str) -> str:
    """Removes control characters and neutralizes explicit prompt-override phrases."""
    if not prompt:
        return ""
    sanitized = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", prompt)
    for pattern in [
        r"(?i)ignore\s+(all\s+)?(previous|prior)\s+instructions?",
        r"(?i)system\s*:\s*you\s+are\s+now",
        r"(?i)reveal\s+(your\s+)?(system\s+prompt|secret\s+key|api\s+key)",
        r"(?i)disregard\s+(all\s+)?(prior|previous)\s+rules"
    ]:
        sanitized = re.sub(pattern, "[FILTERED_INSTRUCTION]", sanitized)
    return sanitized.strip()


_REQUEST_VERB = r"\b(give|send|share|get|fetch|download|provide|attach|export|show|display|view|open|print|see|want|need|where|link|links)\b"
_DELIVERY_VERB = r"\b(download|send|give|share|attach|link|links|export|fetch)\b"
# Questions about the content of a run are answered, not served as files
_CONTENT_QUESTION = r"\b(quality|how many|count|rows|columns|statistics|stats|insights?|trend|average|total|errors?|issues?|rejected|rejections)\b"
_LOG_WORD = r"\b(logs?|log\s*file|process\s*log|execution\s*log|run\s*log|pipeline\s*log)\b"
_ANALYSIS_WORDS = r"\b(why|explain|summari[sz]e|summary|analy[sz]e|what\s+(happened|went|caused)|tell me about|understand|meaning|mean)\b"

# Requested file kinds, matched against the message
_FILE_KINDS = [
    ("raw", r"\b(raw|original|uploaded|source|input)\b"),
    ("cleaned", r"\b(clean|cleaned|cleansed|processed|transformed|output)\b"),
    ("pdf", r"\bpdf\b"),
    ("docx", r"\b(word|docx|doc)\b"),
    ("markdown", r"\b(markdown|md)\b"),
    ("json", r"\bjson\b"),
]
_FILE_NOUN = r"\b(files?|csv|excel|xlsx|dataset|datasets|report|reports|pdf|word|docx|markdown|json|document|documents|downloads?)\b"
_ALL_FILE_KINDS = ["raw", "cleaned", "pdf", "docx", "markdown", "json"]


_SOFT_VERB = r"\b(show|get|see|view|open|want|need|where|display|print|provide)\b"
_WORKSPACE_REF = r"\b(my|our|the|this|that|these|those|its|batch_\w+)\b"
_GENERAL_TOPIC = r"\b(script|code|function|program|example|snippet|python|javascript|sql query|regex|tutorial|how to|template)\b"


def wants_log(message_lower: str) -> bool:
    if re.search(r"\blog\s*(in|out|on)\b|\blogin\b|\blogout\b", message_lower) and not re.search(r"\blogs\b|\blog\s+(file|of|for)\b", message_lower):
        return False
    return bool(re.search(_LOG_WORD, message_lower)) and not re.search(_GENERAL_TOPIC, message_lower)


def requested_file_kinds(message_lower: str, mentions_upload: bool = False) -> list:
    """
    File kinds the user asked for from their workspace, or [] when the message is not a file request
    (e.g. "give me a python script that writes a csv file" is a normal question).
    """
    if not re.search(_FILE_NOUN, message_lower) and not mentions_upload:
        return []
    if re.search(_GENERAL_TOPIC, message_lower) and not mentions_upload:
        return []
    if not (mentions_upload or re.search(_WORKSPACE_REF, message_lower)):
        return []
    kinds = [kind for kind, pattern in _FILE_KINDS if re.search(pattern, message_lower)]
    delivery = re.search(_DELIVERY_VERB, message_lower)
    if not delivery:
        if not (re.search(_SOFT_VERB, message_lower) and (kinds or re.search(r"\breports?\b", message_lower))):
            return []
        if re.search(_ANALYSIS_WORDS, message_lower) or re.search(_CONTENT_QUESTION, message_lower):
            return []
    report_formats = {"pdf", "docx", "markdown", "json"}
    if re.search(r"\breports?\b", message_lower) and not report_formats & set(kinds):
        kinds += ["pdf", "docx", "markdown", "json"]
    if not kinds or re.search(r"\b(all|every|everything)\s+(the\s+)?files?\b", message_lower):
        kinds = list(_ALL_FILE_KINDS)
    return kinds


def mentions_an_upload(db: Session, message_lower: str, email: str) -> bool:
    for _, filename, _ in _user_uploads(db, email):
        name = (filename or "").lower()
        if name and (name in message_lower or (len(os.path.splitext(name)[0]) >= 4 and os.path.splitext(name)[0] in message_lower)):
            return True
    return bool(re.search(r"\bbatch_(?:rt_)?[a-f0-9]{8}\b", message_lower))


# ---------------------------------------------------------------------------
# Batch resolution (always limited to the caller's own uploads)
# ---------------------------------------------------------------------------

_GENERIC_TOKENS = {"data", "file", "files", "dataset", "report", "reports", "clean", "cleaned", "dirty", "test",
                   "final", "copy", "csv", "json", "xlsx", "xml", "tsv", "new", "latest", "sample"}


def _user_uploads(db: Session, email: str) -> list:
    return db.execute(
        text("SELECT batch_id, filename, upload_time FROM raw_uploads WHERE uploaded_by = :e ORDER BY upload_time DESC"),
        {"e": email}
    ).fetchall()


def resolve_batch(db: Session, message: str, email: str, context_batch: Optional[str], history) -> Optional[str]:
    """
    Which run the message refers to: an explicit batch id, a mentioned file name, the batch selected in
    the chat's context picker, one mentioned earlier in the conversation, or the most recent run.
    """
    message_lower = message.lower()
    candidates = re.findall(r"\bbatch_(?:rt_)?[a-f0-9]{8}\b", message_lower)
    for candidate in candidates:
        if user_owns_batch(db, candidate, email):
            return candidate

    uploads = _user_uploads(db, email)
    # Exact file name or file stem mentioned (longest match wins, newest upload first)
    best = None
    for bid, filename, _ in uploads:
        name = (filename or "").lower()
        stem = os.path.splitext(name)[0]
        for needle in (name, stem):
            if len(needle) >= 3 and needle in message_lower and (best is None or len(needle) > best[1]):
                best = (bid, len(needle))
    if best:
        return best[0]
    # Distinctive word of a file name (e.g. "pokemon" for pokemon_battles_2026.csv)
    words = set(re.findall(r"[a-z0-9]{4,}", message_lower)) - _GENERIC_TOKENS
    for bid, filename, _ in uploads:
        tokens = set(re.findall(r"[a-z0-9]{4,}", os.path.splitext((filename or "").lower())[0])) - _GENERIC_TOKENS
        if words & tokens:
            return bid

    if context_batch and is_valid_batch_id(context_batch) and user_owns_batch(db, context_batch, email):
        return context_batch
    for msg in reversed(history or []):
        for candidate in re.findall(r"\bbatch_(?:rt_)?[a-f0-9]{8}\b", (msg.content or "").lower()):
            if user_owns_batch(db, candidate, email):
                return candidate
    return uploads[0][0] if uploads else None


def _batch_info(db: Session, batch_id: str) -> dict:
    row = db.execute(
        text("SELECT filename, uploaded_by FROM raw_uploads WHERE batch_id = :b LIMIT 1"), {"b": batch_id}
    ).first()
    run = db.execute(
        text("SELECT status, execution_time FROM pipeline_logs WHERE pipeline_id = :p"), {"p": f"pipe_{batch_id}"}
    ).first()
    return {
        "filename": row[0] if row else batch_id,
        "uploaded_by": row[1] if row else None,
        "status": run[0] if run else "Not Run",
        "execution_time": run[1] if run else None,
    }


# ---------------------------------------------------------------------------
# Files & logs
# ---------------------------------------------------------------------------

def _file_link(path: str) -> str:
    rel = os.path.relpath(path, PROJECT_ROOT).replace("\\", "/")
    return f"/api/v1/reports/download-file?path={quote(rel)}"


def build_file_response(db: Session, batch_id: str, kinds: list) -> str:
    info = _batch_info(db, batch_id)
    filename = info["filename"]
    lines, missing = [], []

    if "raw" in kinds:
        raw_path = get_user_path(info["uploaded_by"], f"data/raw/{filename}")
        if os.path.isfile(raw_path):
            lines.append(f"- [Raw upload - {filename}]({_file_link(raw_path)})")
        else:
            missing.append("raw upload")

    if "cleaned" in kinds:
        clean_path = None
        try:
            from backend.api.pipeline import read_pipeline_state, pipeline_state_exists
            if pipeline_state_exists(f"pipe_{batch_id}"):
                clean_path = (read_pipeline_state(f"pipe_{batch_id}").get("stages", {}).get("transformation", {}).get("output") or {}).get("clean_dataset_path")
        except Exception:
            clean_path = None
        clean_path = clean_path or get_user_path(info["uploaded_by"], f"cleaned data/{filename}")
        if os.path.isfile(clean_path):
            lines.append(f"- [Cleaned data - {os.path.basename(clean_path)}]({_file_link(clean_path)})")
        else:
            missing.append("cleaned file")

    report_kinds = [k for k in ("pdf", "docx", "markdown", "json") if k in kinds]
    if report_kinds:
        report = db.execute(
            text("SELECT pdf_path, docx_path, markdown_path, json_path FROM generated_reports WHERE batch_id = :b ORDER BY created_at DESC LIMIT 1"),
            {"b": batch_id}
        ).first()
        paths = dict(zip(("pdf", "docx", "markdown", "json"), report)) if report else {}
        labels = {"pdf": "PDF report", "docx": "Word report", "markdown": "Markdown report", "json": "JSON report"}
        for kind in report_kinds:
            path = paths.get(kind)
            if path and os.path.isfile(path if os.path.isabs(path) else os.path.join(PROJECT_ROOT, path)):
                lines.append(f"- [{labels[kind]} - {os.path.basename(path)}](/api/v1/reports/download/{batch_id}?format={kind})")
            else:
                missing.append(labels[kind])

    header = f"Files for **{filename}** (batch `{batch_id}`):"
    if not lines:
        return f"I couldn't find the requested file(s) for **{filename}** (batch `{batch_id}`, status: {info['status']}). " \
               "If the run hasn't finished yet, try again once it completes."
    body = "\n".join([header, ""] + lines)
    if missing:
        body += f"\n\nNot available for this run: {', '.join(missing)}."
    return body


def get_process_log(db: Session, batch_id: str) -> tuple:
    """(filename, status, log text) for a run, built from its recorded stage timeline."""
    from backend.api.pipeline import build_process_log, pipeline_state_exists
    info = _batch_info(db, batch_id)
    if not pipeline_state_exists(f"pipe_{batch_id}"):
        return info["filename"], info["status"], None
    agent_rows = db.execute(
        text("SELECT timestamp, agent_name, reasoning FROM agent_logs WHERE batch_id = :b ORDER BY timestamp ASC"), {"b": batch_id}
    ).fetchall()
    summary = [f"[{r[0]}] {r[1]}: {r[2]}" for r in agent_rows]
    return info["filename"], info["status"], build_process_log(f"pipe_{batch_id}", batch_id, info["filename"], info["uploaded_by"], summary)


def build_log_response(db: Session, batch_id: str) -> str:
    filename, status, log_text = get_process_log(db, batch_id)
    if not log_text:
        return f"There is no process log for **{filename}** yet - its pipeline has not been run."
    truncated = ""
    if len(log_text) > MAX_LOG_CHARS:
        log_text = log_text[-MAX_LOG_CHARS:]
        truncated = "\n_(Showing the end of the log; download it for the full text.)_"
    return (
        f"Process log for **{filename}** (batch `{batch_id}`, status: {status}):\n\n"
        f"```text\n{log_text.rstrip()}\n```{truncated}\n\n"
        f"[Download {filename}.log](/api/v1/history/{batch_id}/log?download=true)"
    )


# ---------------------------------------------------------------------------
# Conversational answers
# ---------------------------------------------------------------------------

def build_workspace_context(db: Session, email: str, batch_id: Optional[str], message: str) -> str:
    """Compact, factual context about the user's runs (and RAG documents) for the LLM."""
    lines = []
    try:
        from backend.api.pipeline import get_run_history
        runs = get_run_history(limit=10, db=db, x_user_email=email)
    except Exception as e:
        logger.warning(f"Could not load run history for chat context: {e}")
        runs = []
    if runs:
        lines.append("Recent pipeline runs (newest first):")
        for r in runs:
            lines.append(
                f"- {r['filename']} | batch {r['batch_id']} | status {r['status']} | rows loaded {r['rows_loaded']} | "
                f"rejected {r['rows_rejected']} | quality {r['quality_before']}% -> {r['quality_after']}%"
            )
    else:
        lines.append("The user has not uploaded or run any datasets yet.")

    if batch_id:
        info = _batch_info(db, batch_id)
        lines.append(f"\nSelected run: {info['filename']} (batch {batch_id}), status {info['status']}.")
        quality = db.execute(
            text("SELECT quality_score, missing_values, duplicate_count FROM quality_reports WHERE batch_id = :b ORDER BY id DESC LIMIT 1"), {"b": batch_id}
        ).first()
        if quality:
            lines.append(f"Quality Score={quality[0]}% | Missing Values={quality[1]} | Duplicates removed={quality[2]}")
        for rca in db.execute(
            text("SELECT issue, root_cause, recommendation FROM root_cause_reports WHERE batch_id = :b"), {"b": batch_id}
        ).fetchall():
            lines.append(f"  * Issue: {rca[0]}\n    - Root Cause: {rca[1]}\n    - Recommendation: {rca[2]}")
        report = db.execute(text("SELECT json_path FROM generated_reports WHERE batch_id = :b ORDER BY created_at DESC LIMIT 1"), {"b": batch_id}).first()
        if report and report[0] and os.path.isfile(report[0]):
            try:
                with open(report[0], "r", encoding="utf-8") as f:
                    insights = json.load(f).get("business_insights") or []
                if insights:
                    lines.append("Measured facts about the cleaned data:")
                    lines.extend(f"  - {i}" for i in insights[:10])
            except (OSError, json.JSONDecodeError):
                pass

    rag = build_rag_context(db, email, message)
    if rag:
        lines.append("\n" + rag)
    return "\n".join(lines)


def build_rag_context(db: Session, email: str, message: str) -> str:
    try:
        from backend.database.models import RagDocument
        docs = db.query(RagDocument).filter(RagDocument.uploaded_by == email).all()
    except Exception:
        return ""
    query_words = set(re.findall(r"\w{3,}", message.lower()))
    scored = []
    for doc in docs:
        for para in [p.strip() for p in (doc.content or "").split("\n") if p.strip()]:
            for chunk in [para[i:i + 500] for i in range(0, len(para), 500)]:
                overlap = query_words & set(re.findall(r"\w{3,}", chunk.lower()))
                if overlap:
                    scored.append((len(overlap) / (len(query_words) + 1), doc.filename, chunk))
    scored.sort(key=lambda x: x[0], reverse=True)
    if not scored:
        return ""
    return "Relevant excerpts from the user's knowledge-base documents:\n" + "\n".join(
        f"[{name}] {chunk}" for _, name, chunk in scored[:4]
    )


def format_history(history) -> str:
    recent = (history or [])[-MAX_HISTORY_MESSAGES:]
    lines = []
    for msg in recent:
        role = "User" if msg.role == "user" else "Assistant"
        content = (msg.content or "")
        if len(content) > MAX_HISTORY_CHARS:
            content = content[:MAX_HISTORY_CHARS] + " ...[truncated]"
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def answer_conversationally(db: Session, email: str, batch_id: Optional[str], message: str, history, extra: str = "") -> dict:
    context = build_workspace_context(db, email, batch_id, message)
    prompt = (
        "AI chat conversation.\n"
        f"Database Context:\n{context}\n\n"
        f"{extra}"
        f"Conversation History:\n{format_history(history) or 'None'}\n\n"
        f"User Query: {message}\n"
    )
    answer = query_llm(prompt, SYSTEM_PROMPT, json_mode=False)
    return _reply(answer, 95.0 if is_real_llm_available() else 70.0)


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

def _maintenance_command(message_lower: str, email: str) -> Optional[dict]:
    """Explicit clean-up commands. Questions never trigger them."""
    if is_question(message_lower):
        return None
    if any(k in message_lower for k in ["clean cleaned data", "clear cleaned data", "clean the cleaned data", "clear the cleaned data"]):
        from backend.utils.file_utils import clear_cleaned_data_folder
        clear_cleaned_data_folder(os.path.dirname(get_user_path(email, "cleaned data/dummy.txt")))
        return _reply("Your `cleaned data/` folder has been emptied.")
    if any(k in message_lower for k in ["clean logs", "clear logs", "wipe logs", "clean the logs", "clear the logs"]):
        if not is_admin(email):
            return ADMIN_ONLY_RESPONSE
        from backend.utils.file_utils import clear_logs_folder
        clear_logs_folder()
        return _reply("The `logs/` folder has been emptied.")
    if any(k in message_lower for k in ["reset the workspace", "reset workspace", "wipe database", "wipe data", "delete all files", "delete all the files", "clean workspace"]):
        if not is_admin(email):
            return ADMIN_ONLY_RESPONSE
        from cleanup_all import reset_workspace
        reset_workspace()
        return _reply("All uploads, cleaned datasets, reports and logs were deleted and the data tables were reset. User accounts were kept.")
    return None


@router.post("/chat", response_model=ChatResponse)
def agent_chat(req: ChatRequest, db: Session = Depends(get_db), x_user_email: Optional[str] = Header(None)):
    """
    Normal AI assistant chat. Requests for files return only those files; requests for logs return
    only the process log. Questions about a log are answered using that log.
    """
    email = x_user_email or DEFAULT_ADMIN_EMAIL
    message = sanitize_user_prompt(req.message)
    message_lower = message.lower()

    try:
        maintenance = _maintenance_command(message_lower, email)
    except Exception as ex:
        return _reply(f"The maintenance command failed: {ex}", 50.0)
    if maintenance:
        return maintenance

    log_requested = wants_log(message_lower)
    file_kinds = requested_file_kinds(message_lower, mentions_an_upload(db, message_lower, email))
    batch_id = None
    if log_requested or file_kinds:
        batch_id = resolve_batch(db, message, email, req.batch_id, req.history)
        if not batch_id:
            return _reply("You haven't run any datasets yet, so there are no files or logs to share. Upload a file on the Pipeline page first.")

    if log_requested:
        # Questions about a log ("why did it fail?") are answered from the log; otherwise return the log itself
        if re.search(_ANALYSIS_WORDS, message_lower) and not re.search(r"\b(give|send|show|download|display|print|view|open|share|get)\b", message_lower):
            filename, _, log_text = get_process_log(db, batch_id)
            extra = f"Process log of {filename} (batch {batch_id}):\n{(log_text or 'No log available.')[-8000:]}\n\n"
            return answer_conversationally(db, email, batch_id, message, req.history, extra)
        response = build_log_response(db, batch_id)
        # "log and the pdf" -> both, nothing else
        if file_kinds and file_kinds != _ALL_FILE_KINDS:
            response += "\n\n" + build_file_response(db, batch_id, file_kinds)
        return _reply(response)

    if file_kinds:
        return _reply(build_file_response(db, batch_id, file_kinds))

    batch_id = resolve_batch(db, message, email, req.batch_id, req.history) if re.search(
        r"\b(batch|run|runs|pipeline|dataset|data|file|quality|reject|rejected|error|errors|fail|failed|rows?|columns?|report)\b", message_lower
    ) else (req.batch_id if req.batch_id and user_owns_batch(db, req.batch_id, email) else None)
    try:
        return answer_conversationally(db, email, batch_id, message, req.history)
    except Exception as e:
        logger.exception(f"Chat answer failed: {e}")
        return _reply("Sorry, I couldn't generate an answer right now. Please try again.", 0.0)
