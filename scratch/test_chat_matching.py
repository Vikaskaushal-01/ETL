import os
import sys
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

from backend.database.mysql import SessionLocal
from backend.schemas.schemas import ChatRequest
from backend.api.chat import agent_chat

def test_matching():
    db = SessionLocal()
    try:
        # Test case 1: The query user reported
        msg1 = "logs of logs of last file you cleaned"
        req1 = ChatRequest(message=msg1, history=[])
        res1 = agent_chat(req1, db)
        print(f"--- Query: '{msg1}' ---")
        print(f"Response:\n{res1.get('response')}\n")

        # Test case 2: Typical variant
        msg2 = "give me the logs of last file you cleaned"
        req2 = ChatRequest(message=msg2, history=[])
        res2 = agent_chat(req2, db)
        print(f"--- Query: '{msg2}' ---")
        print(f"Response:\n{res2.get('response')}\n")

        # Test case 3: Typical variant without "clean"
        msg3 = "give me the logs of the last file you processed"
        req3 = ChatRequest(message=msg3, history=[])
        res3 = agent_chat(req3, db)
        print(f"--- Query: '{msg3}' ---")
        print(f"Response:\n{res3.get('response')}\n")
        
    finally:
        db.close()

if __name__ == "__main__":
    test_matching()
