"""
Human Review queue: runs the Review Agent flagged because a person has to decide something
(the file was not processed, or the automatic cleaning changed what the data says).
"""
import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from backend.api.pipeline import (
    _existing_raw_path, _require_batch_access, _stage_output, _user_batch_filter, read_pipeline_state, set_pipeline_review
)
from backend.database.models import PipelineLog, RawUpload, ReviewItem
from backend.database.mysql import SessionLocal, get_db
from backend.schemas.schemas import ReviewDecisionRequest

router = APIRouter(prefix="/review", tags=["Human Review"])
logger = logging.getLogger("etl_review_api")

STAGE_NAMES = {"intake": "intake", "transformation": "cleaning", "storage": "storage and load", "report": "reporting", "pbi": "Power BI export"}


def review_run(batch_id: str, raw_path: Optional[str], final_state: Optional[dict] = None, error: Optional[str] = None) -> Optional[dict]:
    """
    Runs the Review Agent on a finished (or crashed) run and records the result in the run state, so
    the process log lists every problem. Only runs with a critical or high problem go to the review
    queue; a re-run without one closes the open review item of its batch.
    """
    from agents.review_agent.review_agent import ReviewAgent
    from backend.database.repository import log_agent_decision

    pipeline_id = f"pipe_{batch_id}"
    final_state = final_state or {}
    state = read_pipeline_state(pipeline_id)
    stages = state.get("stages") or {}
    failed_stage = next((STAGE_NAMES.get(sid, sid) for sid, s in stages.items() if s.get("status") == "failed"), None)
    clean_path = _stage_output(state, "transformation").get("clean_dataset_path")
    history = final_state.get("transformation_history") or \
        ((stages.get("transformation") or {}).get("metadata") or {}).get("transformation_history") or []

    agent = ReviewAgent()
    review = agent.run(
        raw_path, clean_path,
        transformation_history=history,
        validation_results=final_state.get("validation_results") or {},
        pipeline_status=final_state.get("pipeline_status"),
        error=error or state.get("error"),
        failed_stage=failed_stage,
    )
    review["checked_at"] = datetime.utcnow().isoformat()
    set_pipeline_review(pipeline_id, review)

    db = SessionLocal()
    try:
        upload = db.query(RawUpload).filter(RawUpload.batch_id == batch_id).first()
        item = db.query(ReviewItem).filter(ReviewItem.batch_id == batch_id).first()
        issues = review["issues"]
        now = datetime.utcnow()
        if review["required"]:
            if not item:
                item = ReviewItem(batch_id=batch_id)
                db.add(item)
            item.user_email = upload.uploaded_by if upload else None
            item.filename = upload.filename if upload else None
            item.status = "open"
            item.kind = review["kind"]
            item.severity = review["severity"]
            item.issue_count = len(issues)
            item.issues_json = json.dumps(issues, default=str)
            item.resolved_by = None
            item.resolved_at = None
            item.updated_at = now
        elif item and item.status == "open":
            item.status = "resolved"
            item.kind = "clear"
            item.severity = None
            item.issue_count = 0
            item.issues_json = "[]"
            item.resolved_by = agent.name
            item.resolved_at = now
            item.updated_at = now
            item.note = (f"Re-run on {now:%Y-%m-%d %H:%M} UTC no longer needs a human decision"
                         + (f" ({len(issues)} minor note(s) are in the process log)." if issues else "."))
        db.commit()

        if review["required"]:
            reasoning = (f"Sent to Human Review ({review['kind'].replace('_', ' ')}), {len(issues)} issue(s): "
                         + "; ".join(i["title"] for i in issues[:5]))
        elif issues:
            reasoning = f"No human decision needed; {len(issues)} minor note(s) written to the process log."
        else:
            reasoning = "No problems found."
        log_agent_decision(db, batch_id=batch_id, agent_name=agent.name, task="Decide whether the run needs a human",
                           reasoning=reasoning, confidence=100.0, execution_time=review["execution_time"])
    finally:
        db.close()
    return review


def _serialize(item: ReviewItem, run_status: Optional[str], uploaded_at, raw_file: Optional[str]) -> dict:
    try:
        issues = json.loads(item.issues_json or "[]")
    except json.JSONDecodeError:
        issues = []
    flagged_at = item.updated_at or item.created_at
    return {
        "batch_id": item.batch_id,
        "filename": item.filename,
        "owner": item.user_email,
        "status": item.status,
        "kind": item.kind,
        "severity": item.severity,
        "issue_count": item.issue_count,
        "issues": issues,
        "note": item.note,
        "resolved_by": item.resolved_by,
        "resolved_at": item.resolved_at.isoformat() if item.resolved_at else None,
        "flagged_at": flagged_at.isoformat() if flagged_at else None,
        "uploaded_at": uploaded_at.isoformat() if uploaded_at else None,
        "run_status": run_status,
        "raw_file": raw_file,
    }


def _items(db: Session, email: Optional[str], batch_ids: Optional[list] = None) -> list:
    """Review items visible to the caller (the administrator sees every account's), newest first."""
    query = db.query(ReviewItem)
    visible = _user_batch_filter(db, email)
    if visible is not None:
        query = query.filter(ReviewItem.batch_id.in_(visible or [""]))
    if batch_ids is not None:
        query = query.filter(ReviewItem.batch_id.in_(batch_ids or [""]))
    items = query.order_by(ReviewItem.updated_at.desc()).all()
    ids = [i.batch_id for i in items]
    statuses, uploads = {}, {}
    if ids:
        statuses = dict(db.query(PipelineLog.pipeline_id, PipelineLog.status)
                        .filter(PipelineLog.pipeline_id.in_([f"pipe_{b}" for b in ids])).all())
        uploads = {u.batch_id: u for u in db.query(RawUpload).filter(RawUpload.batch_id.in_(ids)).all()}
    out = []
    for item in items:
        upload = uploads.get(item.batch_id)
        out.append(_serialize(
            item, statuses.get(f"pipe_{item.batch_id}"), upload.upload_time if upload else None,
            _existing_raw_path(upload.uploaded_by, upload.filename) if upload else None,
        ))
    return out


@router.get("")
def list_review_items(status: str = Query("open", pattern="^(open|resolved|dismissed|all)$"), db: Session = Depends(get_db),
                      x_user_email: Optional[str] = Header(None)):
    """The review queue, filtered by status, with counts per status, kind and severity."""
    items = _items(db, x_user_email)
    open_items = [i for i in items if i["status"] == "open"]
    counts = {
        "open": len(open_items),
        "resolved": sum(i["status"] == "resolved" for i in items),
        "dismissed": sum(i["status"] == "dismissed" for i in items),
        "not_processed": sum(i["kind"] == "not_processed" for i in open_items),
        "needs_decision": sum(i["kind"] == "needs_decision" for i in open_items),
        "issues": sum(i["issue_count"] or 0 for i in open_items),
        "by_severity": {s: sum(i["severity"] == s for i in open_items) for s in ("critical", "high", "medium")},
    }
    return {"counts": counts, "items": items if status == "all" else [i for i in items if i["status"] == status]}


@router.get("/{batch_id}")
def get_review_item(batch_id: str, db: Session = Depends(get_db), x_user_email: Optional[str] = Header(None)):
    _require_batch_access(db, batch_id, x_user_email)
    items = _items(db, x_user_email, [batch_id])
    if not items:
        raise HTTPException(status_code=404, detail="This run has nothing waiting for review.")
    return items[0]


@router.post("/{batch_id}")
def decide_review_item(batch_id: str, req: ReviewDecisionRequest, db: Session = Depends(get_db),
                       x_user_email: Optional[str] = Header(None)):
    """Resolve (problem handled), dismiss (accept the data as it is) or reopen a review item, with an optional note."""
    _require_batch_access(db, batch_id, x_user_email)
    item = db.query(ReviewItem).filter(ReviewItem.batch_id == batch_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="This run has nothing waiting for review.")
    if req.action == "reopen":
        item.status, item.resolved_by, item.resolved_at = "open", None, None
    else:
        item.status = "resolved" if req.action == "resolve" else "dismissed"
        item.resolved_by = x_user_email
        item.resolved_at = datetime.utcnow()
    if req.note is not None:
        item.note = req.note.strip() or None
    db.commit()
    logger.info(f"Review item {batch_id} set to {item.status} by {x_user_email}")
    return _items(db, x_user_email, [batch_id])[0]
