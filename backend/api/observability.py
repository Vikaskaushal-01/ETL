"""
Data observability and lineage API.

  GET /observability/datasets               health of every dataset: freshness, anomalies, metric history
  GET /observability/runs/{batch_id}        a run's metrics compared with its dataset's baseline
  GET /lineage/{batch_id}                   column-level lineage of a run
  GET /lineage/{batch_id}/openlineage       the run as OpenLineage RunEvents (import into Marquez, DataHub, ...)
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from backend.database.models import RawUpload
from backend.database.mysql import get_db
from backend.utils import lineage as lineage_utils
from backend.utils import observability

router = APIRouter(tags=["Observability & Lineage"])
logger = logging.getLogger("etl_observability_api")


@router.get("/observability/datasets")
def datasets_health(db: Session = Depends(get_db), x_user_email: Optional[str] = Header(None)):
    datasets = observability.dataset_health(db, x_user_email)
    counts = {}
    for d in datasets:
        counts[d["health"]] = counts.get(d["health"], 0) + 1
    return {"datasets": datasets, "counts": counts, "thresholds": {
        "min_history": observability.MIN_HISTORY, "z_threshold": observability.Z_THRESHOLD,
        "late_factor": observability.LATE_FACTOR}}


@router.get("/observability/runs/{batch_id}")
def run_observability(batch_id: str, db: Session = Depends(get_db), x_user_email: Optional[str] = Header(None)):
    from backend.api.pipeline import _require_batch_access, read_pipeline_state
    _require_batch_access(db, batch_id, x_user_email)
    stored = read_pipeline_state(f"pipe_{batch_id}").get("observability")
    return stored or observability.observe_run(batch_id) or {}


def _run_lineage(db: Session, batch_id: str, email: Optional[str]) -> tuple:
    from backend.api.pipeline import _require_batch_access, read_pipeline_state
    _require_batch_access(db, batch_id, email)
    upload = db.query(RawUpload).filter(RawUpload.batch_id == batch_id).first()
    filename = upload.filename if upload else batch_id
    state = read_pipeline_state(f"pipe_{batch_id}")
    return state, lineage_utils.build_lineage(state, filename, upload.uploaded_by if upload else None), filename


@router.get("/lineage/{batch_id}")
def run_lineage(batch_id: str, db: Session = Depends(get_db), x_user_email: Optional[str] = Header(None)):
    _, lineage, _ = _run_lineage(db, batch_id, x_user_email)
    return {"batch_id": batch_id, **lineage}


@router.get("/lineage/{batch_id}/openlineage")
def run_openlineage(batch_id: str, db: Session = Depends(get_db), x_user_email: Optional[str] = Header(None)):
    state, lineage, filename = _run_lineage(db, batch_id, x_user_email)
    return lineage_utils.openlineage_events(batch_id, state, lineage, filename)


def after_run(batch_id: str) -> None:
    """Called when a run finishes: baseline comparison, then OpenLineage emission (when configured)."""
    try:
        observability.observe_run(batch_id)
    except Exception as e:
        logger.exception(f"Observability check failed for {batch_id}: {e}")
    if not lineage_utils.OPENLINEAGE_URL:
        return
    from backend.database.mysql import SessionLocal
    db = SessionLocal()
    try:
        from backend.api.pipeline import read_pipeline_state
        upload = db.query(RawUpload).filter(RawUpload.batch_id == batch_id).first()
        filename = upload.filename if upload else batch_id
        state = read_pipeline_state(f"pipe_{batch_id}")
        lineage = lineage_utils.build_lineage(state, filename, upload.uploaded_by if upload else None)
        lineage_utils.emit_openlineage(lineage_utils.openlineage_events(batch_id, state, lineage, filename))
    except Exception as e:
        logger.warning(f"OpenLineage emission failed for {batch_id}: {e}")
    finally:
        db.close()
