"""
Run notifications: when a run finishes, POST a short summary to the owner's webhook.
The payload carries the message as `text` (Slack, Mattermost, Teams workflows) and `content` (Discord),
plus a structured `run` object for custom receivers.
"""
import logging
import os
import threading
from typing import Optional

from backend.core.security import validate_public_url

logger = logging.getLogger("etl_notify")

APP_BASE_URL = os.getenv("APP_BASE_URL", "").rstrip("/")
TIMEOUT_SECONDS = 8


def _post(url: str, payload: dict) -> tuple:
    """(ok, detail). Never follows redirects and never sends to private addresses."""
    import httpx
    try:
        validate_public_url(url)
        response = httpx.post(url, json=payload, timeout=TIMEOUT_SECONDS, follow_redirects=False)
    except ValueError as e:
        return False, str(e)
    except Exception as e:
        return False, f"Could not reach the webhook: {e}"
    if response.status_code >= 300:
        return False, f"The webhook answered HTTP {response.status_code}."
    return True, f"Delivered (HTTP {response.status_code})."


def build_message(run: dict) -> str:
    icon = {"Success": "✅", "Passed with Warnings": "⚠️", "Failed": "❌"}.get(run.get("status"), "ℹ️")
    parts = [f"{icon} {run.get('filename')} finished: {run.get('status')}"]
    if run.get("rows_loaded") is not None:
        parts.append(f"{run['rows_loaded']:,} rows loaded, {run.get('rows_rejected') or 0:,} rejected")
    if run.get("quality_after") is not None:
        parts.append(f"quality {run['quality_after']}%")
    if run.get("execution_time") is not None:
        parts.append(f"{run['execution_time']:.1f}s")
    message = " · ".join(parts)
    if run.get("error"):
        message += f"\nError: {run['error']}"
    if APP_BASE_URL:
        message += f"\n{APP_BASE_URL}/"
    return message


def send(url: str, run: dict) -> tuple:
    payload = {"text": build_message(run), "content": build_message(run), "event": "run.finished", "run": run}
    return _post(url, payload)


def notify_run_finished(batch_id: str) -> None:
    """Looks up the run's owner and, if they set a webhook, delivers the summary in the background."""
    from backend.api.pipeline import list_runs
    from backend.database.models import RawUpload, User
    from backend.database.mysql import SessionLocal

    db = SessionLocal()
    try:
        owner = db.query(RawUpload.uploaded_by).filter(RawUpload.batch_id == batch_id).scalar()
        user: Optional[User] = db.query(User).filter(User.email == owner).first() if owner else None
        if not user or not user.webhook_url:
            return
        runs = list_runs(db, owner, batch_ids=[batch_id])
        if not runs:
            return
        run = {k: runs[0].get(k) for k in ("batch_id", "filename", "status", "rows", "rows_loaded", "rows_rejected",
                                            "quality_before", "quality_after", "execution_time", "error")}
        if (user.notify_on or "all") == "failures" and run["status"] != "Failed":
            return
        url = user.webhook_url
    except Exception as e:
        logger.error(f"Could not prepare the notification for {batch_id}: {e}")
        return
    finally:
        db.close()

    def deliver():
        ok, detail = send(url, run)
        (logger.info if ok else logger.warning)(f"Webhook for {batch_id}: {detail}")

    threading.Thread(target=deliver, name=f"notify-{batch_id}", daemon=True).start()
