"""
Scheduled ingestion: every due schedule downloads its URL, registers the file as an upload of the
schedule's owner and runs the full pipeline. A schedule is claimed with a conditional UPDATE on its
next_run_at, so several server processes never run the same occurrence twice.
"""
import logging
import os
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from sqlalchemy import update

from backend.database.models import PipelineLog, Schedule
from backend.database.mysql import SessionLocal

logger = logging.getLogger("etl_scheduler")

TICK_SECONDS = int(os.getenv("SCHEDULER_TICK_SECONDS", "30"))
MAX_PARALLEL_RUNS = int(os.getenv("SCHEDULER_WORKERS", "2"))
# A run still marked Running after this long is assumed lost (e.g. the server restarted mid-run)
RUN_STALE_AFTER = timedelta(hours=2)

_executor = ThreadPoolExecutor(max_workers=MAX_PARALLEL_RUNS, thread_name_prefix="schedule")
_stop = threading.Event()
_thread = None


def _file_stem(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "scheduled_data"


def claim(db, schedule: Schedule, now: datetime) -> bool:
    """Moves the schedule to its next occurrence; False when another process claimed it first."""
    result = db.execute(
        update(Schedule)
        .where(Schedule.id == schedule.id, Schedule.next_run_at == schedule.next_run_at)
        .values(next_run_at=now + timedelta(minutes=schedule.interval_minutes), last_status="Running", last_error=None)
    )
    db.commit()
    return result.rowcount == 1


def run_schedule(schedule_id: int) -> None:
    """Downloads, registers and runs one occurrence of a schedule (blocking)."""
    from backend.api.pipeline import _new_pipeline_state, _state_lock, run_langgraph_pipeline, write_pipeline_state
    from backend.api.upload import DatasetFetchError, _store_upload, download_dataset
    from fastapi import HTTPException

    db = SessionLocal()
    try:
        schedule = db.get(Schedule, schedule_id)
        if not schedule:
            return
        batch_id = f"batch_{uuid.uuid4().hex[:8]}"
        pipeline_id = f"pipe_{batch_id}"
        schedule.last_run_at = datetime.utcnow()
        schedule.last_batch_id = batch_id
        schedule.run_count = (schedule.run_count or 0) + 1
        db.commit()
        try:
            content, filename = download_dataset(schedule.source_url, default_stem=_file_stem(schedule.name))
            upload = _store_upload(db, content, filename, "Scheduled", schedule.user_email, batch_id)
        except (DatasetFetchError, HTTPException) as e:
            schedule.last_status = "Failed"
            schedule.last_error = getattr(e, "detail", None) or str(e)
            schedule.last_batch_id = None
            db.commit()
            logger.warning(f"Schedule {schedule_id} ({schedule.name}) could not download its source: {schedule.last_error}")
            return

        with _state_lock:
            write_pipeline_state(pipeline_id, _new_pipeline_state(pipeline_id))
        run_langgraph_pipeline(upload["file_path"], batch_id, pipeline_id)

        db.expire_all()
        schedule = db.get(Schedule, schedule_id)
        if schedule:
            status = db.query(PipelineLog.status).filter(PipelineLog.pipeline_id == pipeline_id).scalar()
            schedule.last_status = status or "Failed"
            db.commit()
    except Exception as e:
        logger.exception(f"Schedule {schedule_id} crashed: {e}")
        db.rollback()
        schedule = db.get(Schedule, schedule_id)
        if schedule:
            schedule.last_status, schedule.last_error = "Failed", str(e)[:500]
            db.commit()
    finally:
        db.close()


def trigger(schedule_id: int) -> None:
    _executor.submit(run_schedule, schedule_id)


def tick() -> int:
    """Starts every due, enabled schedule. Returns how many were started."""
    now = datetime.utcnow()
    db = SessionLocal()
    started = 0
    try:
        due = db.query(Schedule).filter(Schedule.enabled == True, Schedule.next_run_at <= now).all()  # noqa: E712
        for schedule in due:
            # One occurrence at a time: a slow run delays the next one instead of overlapping it
            busy = schedule.last_status == "Running" and schedule.last_run_at and schedule.last_run_at > now - RUN_STALE_AFTER
            if not busy and claim(db, schedule, now):
                trigger(schedule.id)
                started += 1
    except Exception as e:
        logger.error(f"Scheduler tick failed: {e}")
        db.rollback()
    finally:
        db.close()
    return started


def recover_interrupted_runs() -> None:
    from backend.api.pipeline import recover_stale_runs
    db = SessionLocal()
    try:
        recover_stale_runs(db)
    except Exception as e:
        logger.error(f"Stale run recovery failed: {e}")
        db.rollback()
    finally:
        db.close()


def _loop() -> None:
    logger.info(f"Scheduler started (every {TICK_SECONDS}s, up to {MAX_PARALLEL_RUNS} parallel runs)")
    while not _stop.wait(TICK_SECONDS):
        recover_interrupted_runs()
        tick()


def start() -> None:
    global _thread
    if os.getenv("SCHEDULER_ENABLED", "true").lower() != "true" or (_thread and _thread.is_alive()):
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="scheduler", daemon=True)
    _thread.start()


def stop() -> None:
    _stop.set()
