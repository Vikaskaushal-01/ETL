"""Scheduled ingestion: run a public dataset URL through the pipeline on an interval."""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.core import scheduler
from backend.core.security import validate_public_url
from backend.database.models import Schedule
from backend.database.mysql import get_db

router = APIRouter(prefix="/schedules", tags=["Schedules"])

MIN_INTERVAL_MINUTES = 5
MAX_INTERVAL_MINUTES = 7 * 24 * 60
MAX_SCHEDULES_PER_USER = 20


class ScheduleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    url: str = Field(..., min_length=8, max_length=2000)
    interval_minutes: int = Field(..., ge=MIN_INTERVAL_MINUTES, le=MAX_INTERVAL_MINUTES)
    run_now: bool = True


class ScheduleUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=120)
    interval_minutes: Optional[int] = Field(None, ge=MIN_INTERVAL_MINUTES, le=MAX_INTERVAL_MINUTES)
    enabled: Optional[bool] = None


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _serialize(s: Schedule) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "url": s.source_url,
        "interval_minutes": s.interval_minutes,
        "enabled": bool(s.enabled),
        "created_at": _iso(s.created_at),
        "next_run_at": _iso(s.next_run_at) if s.enabled else None,
        "last_run_at": _iso(s.last_run_at),
        "last_batch_id": s.last_batch_id,
        "last_status": s.last_status,
        "last_error": s.last_error,
        "run_count": s.run_count or 0,
    }


def _owned(db: Session, schedule_id: int, email: Optional[str]) -> Schedule:
    schedule = db.get(Schedule, schedule_id)
    if not schedule or schedule.user_email != email:
        raise HTTPException(status_code=404, detail="Schedule not found.")
    return schedule


def _check_url(url: str) -> str:
    url = url.strip()
    try:
        validate_public_url(url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return url


@router.get("")
def list_schedules(db: Session = Depends(get_db), x_user_email: Optional[str] = Header(None)):
    rows = db.query(Schedule).filter(Schedule.user_email == x_user_email).order_by(Schedule.created_at.desc()).all()
    return [_serialize(s) for s in rows]


@router.post("")
def create_schedule(req: ScheduleCreate, db: Session = Depends(get_db), x_user_email: Optional[str] = Header(None)):
    if not x_user_email:
        raise HTTPException(status_code=400, detail="Schedules belong to a user account.")
    if db.query(Schedule).filter(Schedule.user_email == x_user_email).count() >= MAX_SCHEDULES_PER_USER:
        raise HTTPException(status_code=400, detail=f"You can have at most {MAX_SCHEDULES_PER_USER} schedules.")
    now = datetime.utcnow()
    schedule = Schedule(
        user_email=x_user_email,
        name=req.name.strip(),
        source_url=_check_url(req.url),
        interval_minutes=req.interval_minutes,
        enabled=True,
        next_run_at=now + timedelta(minutes=req.interval_minutes),
        run_count=0,
    )
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    if req.run_now:
        schedule.last_status = "Running"
        db.commit()
        scheduler.trigger(schedule.id)
    return _serialize(schedule)


@router.patch("/{schedule_id}")
def update_schedule(schedule_id: int, req: ScheduleUpdate, db: Session = Depends(get_db), x_user_email: Optional[str] = Header(None)):
    schedule = _owned(db, schedule_id, x_user_email)
    if req.name is not None:
        schedule.name = req.name.strip()
    if req.interval_minutes is not None and req.interval_minutes != schedule.interval_minutes:
        schedule.interval_minutes = req.interval_minutes
        schedule.next_run_at = datetime.utcnow() + timedelta(minutes=req.interval_minutes)
    if req.enabled is not None and req.enabled != bool(schedule.enabled):
        schedule.enabled = req.enabled
        if req.enabled:
            # Resuming starts a fresh interval instead of firing all missed occurrences
            schedule.next_run_at = datetime.utcnow() + timedelta(minutes=schedule.interval_minutes)
    db.commit()
    return _serialize(schedule)


@router.post("/{schedule_id}/run")
def run_schedule_now(schedule_id: int, db: Session = Depends(get_db), x_user_email: Optional[str] = Header(None)):
    schedule = _owned(db, schedule_id, x_user_email)
    if schedule.last_status == "Running" and schedule.last_run_at and schedule.last_run_at > datetime.utcnow() - scheduler.RUN_STALE_AFTER:
        raise HTTPException(status_code=409, detail="This schedule is already running.")
    schedule.last_status = "Running"
    schedule.last_error = None
    db.commit()
    scheduler.trigger(schedule.id)
    return _serialize(schedule)


@router.delete("/{schedule_id}")
def delete_schedule(schedule_id: int, db: Session = Depends(get_db), x_user_email: Optional[str] = Header(None)):
    db.delete(_owned(db, schedule_id, x_user_email))
    db.commit()
    return {"status": "Deleted", "id": schedule_id}
