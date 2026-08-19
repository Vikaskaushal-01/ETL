import traceback
try:
    import os
    import sys

    sys.path.append(r"c:\Users\User\Documents\ETL-A")

    from fastapi.testclient import TestClient
    from backend.main import app

    client = TestClient(app)

    # Let's find one of the state files in logs/ to get a real batch ID
    logs_dir = r"c:\Users\User\Documents\ETL-A\logs"
    batch_id = None
    for f in os.listdir(logs_dir):
        if f.startswith("pipe_batch_") and f.endswith("_state.json"):
            # e.g., pipe_batch_65d56231_state.json -> batch_id is batch_65d56231
            batch_id = f[5:-11]
            break

    if not batch_id:
        batch_id = "batch_65d56231" # fallback

    print("Testing with batch_id:", batch_id)

    url = f"/api/v1/pipeline/flowchart?batch_id={batch_id}"
    res = client.get(url)

    print("Status code:", res.status_code)
    print("Headers:", res.headers)
    print("Content length:", len(res.content))
    if res.status_code == 200:
        print("Content preview (first 500 chars):")
        print(res.text[:500])
    else:
        print("Error content:", res.text)
except Exception as e:
    traceback.print_exc()
