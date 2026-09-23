"""
End-to-end verification of the full platform through its HTTP API.

Runs in isolation: a throwaway SQLite database, the offline LLM engine (unless LLM_PROVIDER is set),
and a dedicated verification account whose workspace is deleted afterwards. It never touches your
real database, uploads, reports or other accounts.
"""
import os
import shutil
import sys
import tempfile
import time
import uuid

_tmp_dir = tempfile.mkdtemp(prefix="etl_verify_")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{os.path.join(_tmp_dir, 'verify.db')}")
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("PBI_REFRESH_DELAY", "0")

from fastapi.testclient import TestClient  # noqa: E402
from backend.main import app  # noqa: E402
from backend.utils.account_utils import get_user_dir  # noqa: E402

PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
DATASETS = [
    "customers_dirty.xml",
    "orders_dirty.xlsx",
    "sales_dirty.tsv",
    "customers_dirty.json",
    "sales_dirty.csv",
]


def run_e2e_test():
    print("=== STARTING AGENTIC ETL PLATFORM E2E VERIFICATION ===")
    print(f"Database: {os.environ['DATABASE_URL']} | LLM provider: {os.environ['LLM_PROVIDER']}")

    # Sample files are generated into a temporary folder, not the project's data/raw
    import generate_sample_data
    sample_dir = os.path.join(_tmp_dir, "samples")
    os.makedirs(sample_dir, exist_ok=True)
    cwd = os.getcwd()
    os.chdir(sample_dir)
    try:
        generate_sample_data.generate_data()
    finally:
        os.chdir(cwd)
    sample_raw_dir = os.path.join(sample_dir, "data", "raw")

    client = TestClient(app)
    health = client.get("/api/v1/health")
    print(f"Health Check: {health.status_code} - {health.json()}")
    assert health.status_code == 200

    email = f"verify_{uuid.uuid4().hex[:8]}@controlai.net"
    client.post("/api/v1/auth/signup", json={"email": email, "password": "verify-pass"})
    login = client.post("/api/v1/auth/login", json={"username": email, "password": "verify-pass"})
    assert login.status_code == 200, login.text
    client.headers.update({"Authorization": f"Bearer {login.json()['token']}"})
    workspace = get_user_dir(email)

    try:
        batch_ids = {}
        for filename in DATASETS:
            print(f"\n--- Processing dataset: {filename} ---")
            with open(os.path.join(sample_raw_dir, filename), "rb") as f:
                res_upload = client.post("/api/v1/upload", files={"file": (filename, f)})
            assert res_upload.status_code == 200, f"Upload failed for {filename}: {res_upload.text}"
            upload_data = res_upload.json()
            batch_ids[filename] = upload_data["batch_id"]

            res_start = client.post("/api/v1/pipeline/start", json={"file_path": upload_data["file_path"], "batch_id": upload_data["batch_id"]})
            assert res_start.status_code == 200, f"Pipeline start failed for {filename}: {res_start.text}"
            pipeline_id = res_start.json()["pipeline_id"]

            status_data = {}
            for _ in range(30):
                status_data = client.get(f"/api/v1/pipeline/status?pipeline_id={pipeline_id}").json()
                if status_data["status"] in ["Success", "Passed with Warnings", "Failed"]:
                    break
                time.sleep(1)

            storage = status_data["stages"]["storage"]["output"]
            print(f"Status: {status_data['status']} | Duration: {status_data.get('execution_time') or 0.0:.2f}s | "
                  f"Loaded: {storage.get('rows_loaded')} | Rejected: {storage.get('rows_rejected')}")
            assert status_data["status"] in ["Success", "Passed with Warnings"], f"{filename} failed: {status_data.get('logs')}"

        # Reports: exactly 4 formats per dataset, in the account's workspace
        print("\n--- Verifying Dedicated Reports Folders & Strictly 4 Formats ---")
        for filename in batch_ids:
            report_dir = os.path.join(workspace, "reports", filename)
            files_in_dir = os.listdir(report_dir)
            print(f"reports/{filename}/: {files_in_dir}")
            for ext in (".json", ".docx", ".md", ".pdf"):
                assert any(f.endswith(ext) for f in files_in_dir), f"Missing {ext} report in {report_dir}"
            assert not any(f.endswith(".txt") for f in files_in_dir), f"Extraneous .txt report in {report_dir}"

        print("\n--- Verifying Clean Datasets Storage ---")
        clean_files = os.listdir(os.path.join(workspace, "cleaned data"))
        print(f"Clean Storage contains: {clean_files}")
        for entity in ("sales", "customers", "orders"):
            assert any(entity in f for f in clean_files), f"{entity} clean dataset missing"

        print("\n--- Verifying Dashboard Analytics & Reports Folders API ---")
        dash = client.get("/api/v1/dashboard/summary").json()
        print(f"Dashboard: rows={dash['total_rows_processed']} success_rate={dash['success_rate']}% runs={len(dash['recent_runs'])}")
        assert dash["total_rows_processed"] > 0 and len(dash["recent_runs"]) == len(DATASETS)
        folders = client.get("/api/v1/reports/folders").json()
        assert len(folders) == len(DATASETS)
        for fmt in ("pdf", "docx", "markdown", "json"):
            assert folders[0]["formats"][fmt], f"Missing {fmt} in reports/folders"
            res = client.get(f"/api/v1/reports/download/{folders[0]['batch_id']}?format={fmt}")
            assert res.status_code == 200, f"Download of {fmt} report failed"

        print("\n--- Testing AI Chat Assistant Queries ---")
        sales_batch_id = batch_ids["sales_dirty.csv"]
        checks = [
            ({"message": "what is 25 * 4?"}, lambda r: "100" in r),
            ({"message": "Why were records rejected during validation?", "batch_id": sales_batch_id}, lambda r: "validation" in r.lower() or "root cause" in r.lower()),
            ({"message": "What transformations were applied to this dataset?", "batch_id": sales_batch_id}, lambda r: "transformation" in r.lower() or "cleansing" in r.lower()),
            ({"message": "Explain the columns and schema data types", "batch_id": sales_batch_id}, lambda r: "schema" in r.lower() or "column" in r.lower()),
            ({"message": "Generate SQL queries for staging and production tables", "batch_id": sales_batch_id}, lambda r: "SELECT" in r),
            ({"message": "give me the download link", "batch_id": sales_batch_id}, lambda r: "/api/v1/" in r),
        ]
        for payload, check in checks:
            res = client.post("/api/v1/agent/chat", json=payload)
            assert res.status_code == 200
            reply = res.json()["response"]
            assert check(reply), f"Unexpected chat reply to {payload['message']!r}: {reply[:300]}"
            print(f"OK: {payload['message']}")
    finally:
        # Only the verification account's own workspace is removed
        shutil.rmtree(workspace, ignore_errors=True)

    print("\n=== E2E PIPELINE RUN COMPLETED SUCCESSFULLY! ===")


if __name__ == "__main__":
    try:
        run_e2e_test()
    except AssertionError as err:
        print(f"\nVERIFICATION FAILED: {err}")
        sys.exit(1)
