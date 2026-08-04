import os
import sys
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)

# Query 1
payload1 = {
    "message": "hello",
    "history": []
}
res1 = client.post("/api/v1/agent/chat", json=payload1)
print("Res 1 Status:", res1.status_code)
print("Res 1 Response:", res1.json())

# Query 2
payload2 = {
    "message": "how are you?",
    "history": [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": res1.json().get("response", "") if res1.status_code == 200 else ""}
    ]
}
res2 = client.post("/api/v1/agent/chat", json=payload2)
print("Res 2 Status:", res2.status_code)
print("Res 2 Response:", res2.json())
