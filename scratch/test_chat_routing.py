import os
import sys
from sqlalchemy.orm import Session
from sqlalchemy import text

sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

from backend.database.mysql import SessionLocal
from backend.api.chat import get_latest_batch_id, get_logs_for_batch

def test_routing():
    db = SessionLocal()
    try:
        latest_batch = get_latest_batch_id(db)
        print(f"Latest batch ID: {latest_batch}")
        if latest_batch:
            log_content, log_source = get_logs_for_batch(db, latest_batch)
            print(f"Log source: {log_source}")
            print(f"Log content length: {len(log_content)}")
            print(f"Log content preview:\n{log_content[:200]}")
    finally:
        db.close()

if __name__ == "__main__":
    test_routing()
