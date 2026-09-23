"""
End-to-end regression tests for the API: authentication, per-user isolation, file safety,
and the full LangGraph pipeline (upload -> intake -> transform -> storage -> report -> Power BI).
Runs against the throwaway database configured in the repo-root conftest.py.
"""
import os
import time
import unittest
import uuid

from fastapi.testclient import TestClient
from backend.main import app
from backend.core.llm import safe_eval_arithmetic
from agents.transformation_agent.transformation_agent import is_date_column_name
from agents.storage_agent.storage_agent import detect_dataset_type

ADMIN = ("admin@controlai.net", "admin")


def _signup_and_login(client: TestClient, email: str, password: str = "secret123") -> dict:
    client.post("/api/v1/auth/signup", json={"email": email, "password": password})
    res = client.post("/api/v1/auth/login", json={"username": email, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['token']}"}


class PlatformTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        res = cls.client.post("/api/v1/auth/login", json={"username": ADMIN[0], "password": ADMIN[1]})
        cls.admin = {"Authorization": f"Bearer {res.json()['token']}"}
        suffix = uuid.uuid4().hex[:6]
        cls.alice = _signup_and_login(cls.client, f"alice_{suffix}@example.com")
        cls.bob = _signup_and_login(cls.client, f"bob_{suffix}@example.com")

    def upload(self, headers, name, content: bytes):
        return self.client.post("/api/v1/upload", files={"file": (name, content)}, headers=headers)

    def run_pipeline(self, headers, name, content: bytes) -> dict:
        up = self.upload(headers, name, content)
        self.assertEqual(up.status_code, 200, up.text)
        up = up.json()
        start = self.client.post("/api/v1/pipeline/start", json={"file_path": up["file_path"], "batch_id": up["batch_id"]}, headers=headers)
        self.assertEqual(start.status_code, 200, start.text)
        # TestClient runs background tasks before returning, but poll defensively
        for _ in range(50):
            status = self.client.get(f"/api/v1/pipeline/status?pipeline_id=pipe_{up['batch_id']}", headers=headers).json()
            if status["status"] != "Running":
                break
            time.sleep(0.1)
        status["batch_id"] = up["batch_id"]
        return status


class TestAuthentication(PlatformTestCase):
    def test_protected_endpoints_require_token(self):
        for path in ["/api/v1/dashboard/summary", "/api/v1/reports/history", "/api/v1/logs"]:
            self.assertEqual(self.client.get(path).status_code, 401, path)

    def test_spoofed_email_header_is_ignored(self):
        res = self.client.get("/api/v1/dashboard/summary", headers={"X-User-Email": ADMIN[0]})
        self.assertEqual(res.status_code, 401)

    def test_invalid_token_rejected(self):
        res = self.client.get("/api/v1/dashboard/summary", headers={"Authorization": "Bearer forged.token"})
        self.assertEqual(res.status_code, 401)

    def test_login_returns_token_and_me(self):
        me = self.client.get("/api/v1/auth/me", headers=self.admin)
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["email"], ADMIN[0])

    def test_passwords_are_hashed(self):
        from backend.database.mysql import SessionLocal
        from backend.database.models import User
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.email == ADMIN[0]).first()
            self.assertTrue(user.password.startswith("pbkdf2_sha256$"))
        finally:
            db.close()

    def test_social_login_cannot_take_over_password_account(self):
        res = self.client.post("/api/v1/auth/social-login", json={"provider": "google", "email": ADMIN[0], "name": "Mallory"})
        self.assertEqual(res.status_code, 409)

    def test_reset_code_flow(self):
        code = self.client.post("/api/v1/auth/forgot-password", json={"email": ADMIN[0]}).json()["demo_code"]
        self.assertEqual(self.client.post("/api/v1/auth/verify-reset-code", json={"email": ADMIN[0], "code": "000000" if code != "000000" else "111111"}).status_code, 400)
        self.assertEqual(self.client.post("/api/v1/auth/verify-reset-code", json={"email": ADMIN[0], "code": code}).status_code, 200)


class TestFileSafety(PlatformTestCase):
    def test_upload_filename_traversal_is_neutralized(self):
        res = self.upload(self.alice, "../../../evil.csv", b"a,b\n1,2\n")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["file_path"].endswith("/data/raw/evil.csv"))
        self.assertEqual(res.json()["filename"], "evil.csv")

    def test_pickle_upload_rejected(self):
        self.assertEqual(self.upload(self.alice, "payload.pkl", b"\x80\x04").status_code, 400)

    def test_empty_upload_rejected(self):
        self.assertEqual(self.upload(self.alice, "empty.csv", b"").status_code, 400)

    def test_cannot_download_database_or_env(self):
        for path in ["agentic_ai_etl.db", ".env", "backend/main.py"]:
            self.assertEqual(self.client.get(f"/api/v1/dashboard/download?file_path={path}", headers=self.alice).status_code, 404, path)
            self.assertEqual(self.client.get(f"/api/v1/reports/download-file?path={path}", headers=self.alice).status_code, 404, path)

    def test_pipeline_cannot_read_arbitrary_files(self):
        target = os.path.abspath(__file__)
        res = self.client.post("/api/v1/pipeline/start", json={"file_path": target}, headers=self.alice)
        self.assertEqual(res.status_code, 404)

    def test_url_upload_blocks_internal_addresses(self):
        res = self.client.post("/api/v1/upload/url", json={"url": "http://127.0.0.1:8000/api/v1/health"}, headers=self.alice)
        self.assertEqual(res.status_code, 400)
        res = self.client.post("/api/v1/rag/upload/url", json={"url": "file:///etc/passwd"}, headers=self.alice)
        self.assertEqual(res.status_code, 400)


class TestPipelineEndToEnd(PlatformTestCase):
    def test_customer_file_loads(self):
        status = self.run_pipeline(self.alice, "customers.csv", b"Customer ID,Customer Name,Email\nC1,Ann,a@x.io\nC2,Bob,b@x.io\nC1,Ann,a@x.io\n")
        self.assertEqual(status["status"], "Success")
        storage = status["stages"]["storage"]["output"]
        self.assertEqual((storage["rows_loaded"], storage["rows_rejected"]), (2, 0))
        self.assertEqual(status["stages"]["pbi"]["status"], "completed")

    def test_missing_optional_columns_do_not_reject_batch(self):
        status = self.run_pipeline(self.alice, "cust_min.csv", b"customer_id,customer_name\nC10,Ann\nC11,Bob\n")
        self.assertEqual(status["stages"]["storage"]["output"]["rows_loaded"], 2)

    def test_one_bad_value_rejects_only_that_row(self):
        csv = b"sale_id,order_id,product_id,quantity,unit_price,total_price,sale_date\nS1,O1,P1,abc,2.5,5,2024-01-01\nS2,O1,P2,3,1.0,3,2024-01-02\n"
        status = self.run_pipeline(self.alice, "sales_bad.csv", csv)
        self.assertEqual(status["status"], "Passed with Warnings")
        storage = status["stages"]["storage"]["output"]
        self.assertEqual((storage["rows_loaded"], storage["rows_rejected"]), (1, 1))
        rca = self.client.get(f"/api/v1/root-cause?batch_id={status['batch_id']}", headers=self.alice).json()
        self.assertGreaterEqual(len(rca), 1)

    def test_empty_dataset_fails_cleanly(self):
        status = self.run_pipeline(self.alice, "header_only.csv", b"a,b,c\n")
        self.assertEqual(status["status"], "Failed")
        self.assertEqual(status["stages"]["intake"]["status"], "failed")

    def test_realtime_streams_load_all_rows(self):
        for stream in ["transactions", "iot_sensors", "ecommerce_orders"]:
            up = self.client.post("/api/v1/upload/realtime", json={"stream_type": stream, "record_count": 20}, headers=self.alice).json()
            self.client.post("/api/v1/pipeline/start", json={"file_path": up["file_path"], "batch_id": up["batch_id"]}, headers=self.alice)
            status = self.client.get(f"/api/v1/pipeline/status?pipeline_id=pipe_{up['batch_id']}", headers=self.alice).json()
            storage = status["stages"]["storage"]["output"]
            self.assertEqual(status["status"], "Success", stream)
            self.assertGreaterEqual(storage["rows_loaded"], 20, stream)

    def test_reports_generated_and_downloadable(self):
        status = self.run_pipeline(self.alice, "orders.csv", b"order_id,customer_id,order_date,status,total_amount\nO1,C1,2024-01-05,Shipped,10.5\n")
        bid = status["batch_id"]
        for fmt in ["pdf", "docx", "json", "markdown"]:
            res = self.client.get(f"/api/v1/reports/download/{bid}?format={fmt}", headers=self.alice)
            self.assertEqual(res.status_code, 200, fmt)
            self.assertGreater(len(res.content), 100, fmt)
        # Status carries the batch id / file name the UI uses to build report links
        self.assertEqual(status["batch_id"], bid)
        self.assertEqual(status["filename"], "orders.csv")
        # Reports are also saved under the project's reports/<file name>/ folder
        from backend.core.security import PROJECT_ROOT
        root_dir = os.path.join(PROJECT_ROOT, "reports", "orders.csv")
        for ext in ("pdf", "docx", "md", "json"):
            self.assertTrue(os.path.isfile(os.path.join(root_dir, f"{bid}_report.{ext}")), ext)
        # The process log is stored under the file name and listed in the Storage explorer
        with open(os.path.join(PROJECT_ROOT, "logs", "orders.csv.log"), encoding="utf-8") as f:
            process_log = f.read()
        self.assertIn(bid, process_log)
        self.assertIn("STORAGE, STAGING & DATABASE LOAD", process_log)
        files = self.client.get("/api/v1/dashboard/datasets", headers=self.alice).json()["files"]
        self.assertIn("orders.csv.log", [f["name"] for f in files if f["format"] == "LOG"])
        # Plain links carry the token as a query parameter
        token = self.alice["Authorization"].split(" ", 1)[1]
        self.assertEqual(self.client.get(f"/api/v1/reports/download/{bid}?format=pdf&token={token}").status_code, 200)

    def test_dashboard_reflects_runs(self):
        self.run_pipeline(self.bob, "bob_customers.csv", b"customer_id,customer_name\nB1,Zed\n")
        summary = self.client.get("/api/v1/dashboard/summary", headers=self.bob).json()
        self.assertGreaterEqual(len(summary["recent_runs"]), 1)
        self.assertGreaterEqual(summary["total_rows_processed"], 1)
        metrics = self.client.get("/api/v1/dashboard/metrics", headers=self.bob).json()["telemetry"]
        self.assertGreaterEqual(metrics["successful_runs"], 1)
        self.assertEqual(metrics["system_availability_pct"], 100.0)

    def test_unknown_pipeline_is_404(self):
        res = self.client.get("/api/v1/pipeline/status?pipeline_id=pipe_batch_00000000", headers=self.alice)
        self.assertEqual(res.status_code, 404)


class TestUserIsolation(PlatformTestCase):
    def test_users_cannot_see_each_others_batches(self):
        status = self.run_pipeline(self.alice, "alice_private.csv", b"customer_id,customer_name\nA9,Private\n")
        bid = status["batch_id"]
        self.assertEqual(self.client.get(f"/api/v1/pipeline/status?pipeline_id=pipe_{bid}", headers=self.bob).status_code, 404)
        self.assertEqual(self.client.get(f"/api/v1/reports/download/{bid}?format=pdf", headers=self.bob).status_code, 404)
        bob_reports = self.client.get("/api/v1/reports/folders", headers=self.bob).json()
        self.assertNotIn(bid, [r["batch_id"] for r in bob_reports])
        clean_path = status["stages"]["transformation"]["output"]["clean_dataset_path"]
        self.assertEqual(self.client.get(f"/api/v1/reports/download-file?path={clean_path}", headers=self.bob).status_code, 404)
        self.assertEqual(self.client.get(f"/api/v1/reports/download-file?path={clean_path}", headers=self.alice).status_code, 200)

    def test_chat_question_does_not_trigger_reset(self):
        res = self.client.post("/api/v1/agent/chat", json={"message": "how do I clear data?"}, headers=self.alice).json()
        self.assertNotIn("Project Reset", res["response"])

    def test_non_admin_cannot_reset_workspace(self):
        res = self.client.post("/api/v1/agent/chat", json={"message": "reset workspace"}, headers=self.alice).json()
        self.assertIn("administrator", res["response"])


class TestHelpers(unittest.TestCase):
    def test_safe_eval(self):
        self.assertEqual(safe_eval_arithmetic("2+3*4"), 14)
        with self.assertRaises(ValueError):
            safe_eval_arithmetic("9**9**9**9")
        with self.assertRaises(ValueError):
            safe_eval_arithmetic("__import__('os')")

    def test_date_column_detection(self):
        for col in ["order_date", "timestamp", "created_at", "sale_date", "battle_date"]:
            self.assertTrue(is_date_column_name(col), col)
        for col in ["runtime_sec", "candidate", "update_count", "region", "format"]:
            self.assertFalse(is_date_column_name(col), col)

    def test_dataset_type_detection(self):
        self.assertEqual(detect_dataset_type(["transaction_id", "customer_id", "customer_name"]), "dataset")
        self.assertEqual(detect_dataset_type(["customer_id", "customer_name"]), "customers")
        self.assertEqual(detect_dataset_type(["order_id", "customer_email"]), "orders")
        self.assertEqual(detect_dataset_type(["sale_id", "order_id"]), "sales")


if __name__ == "__main__":
    unittest.main()


class TestRealDataFeatures(PlatformTestCase):
    """History, process logs, account settings, API keys, Power BI exports and data-derived reports."""

    def test_history_and_process_log(self):
        status = self.run_pipeline(self.alice, "hist_sales.csv", b"sale_id,order_id,product_id,quantity,unit_price,total_price,sale_date\nS1,O1,P1,2,2.5,5,2024-01-01\nS2,O1,P2,x,1.0,3,2024-01-02\n")
        bid = status["batch_id"]
        history = self.client.get("/api/v1/history", headers=self.alice).json()
        run = next(r for r in history if r["batch_id"] == bid)
        self.assertEqual(run["status"], "Passed with Warnings")
        self.assertEqual((run["rows_loaded"], run["rows_rejected"]), (1, 1))
        self.assertTrue(run["reports"]["pdf"] and run["reports"]["docx"])
        self.assertTrue(run["raw_file"].endswith("hist_sales.csv"))
        log = self.client.get(f"/api/v1/history/{bid}/log", headers=self.alice)
        self.assertEqual(log.status_code, 200)
        self.assertIn("ETL PROCESS LOG  |  File: hist_sales.csv", log.text)
        self.assertIn("Invalid numeric value in 'quantity'", self.client.get(f"/api/v1/root-cause?batch_id={bid}", headers=self.alice).text)
        # Other users can neither list nor read it
        self.assertNotIn(bid, [r["batch_id"] for r in self.client.get("/api/v1/history", headers=self.bob).json()])
        self.assertEqual(self.client.get(f"/api/v1/history/{bid}/log", headers=self.bob).status_code, 404)

    def test_report_content_is_derived_from_data(self):
        import json as _json
        status = self.run_pipeline(self.alice, "regions.csv", b"customer_id,customer_name,region\nC1,Ann,North\nC2,Bob,North\nC3,Cy,South\n")
        res = self.client.get(f"/api/v1/reports/download/{status['batch_id']}?format=json", headers=self.alice)
        report = _json.loads(res.content)
        insights = " ".join(report.get("business_insights") or [])
        self.assertIn("3 rows across 3 columns", insights)
        self.assertIn("North (67%)", insights)
        self.assertNotIn("45%", res.text)

    def test_profile_and_password_change(self):
        headers = _signup_and_login(self.client, f"carol_{uuid.uuid4().hex[:6]}@example.com", "first-pass")
        res = self.client.put("/api/v1/auth/profile", json={"display_name": "Carol D", "date_of_birth": "1990-05-01"}, headers=headers)
        self.assertEqual(res.json()["display_name"], "Carol D")
        self.assertEqual(self.client.get("/api/v1/auth/profile", headers=headers).json()["date_of_birth"], "1990-05-01")
        bad = self.client.post("/api/v1/auth/change-password", json={"current_password": "wrong", "new_password": "second-pass"}, headers=headers)
        self.assertEqual(bad.status_code, 400)
        ok = self.client.post("/api/v1/auth/change-password", json={"current_password": "first-pass", "new_password": "second-pass"}, headers=headers)
        self.assertEqual(ok.status_code, 200)
        email = self.client.get("/api/v1/auth/me", headers=headers).json()["email"]
        self.assertEqual(self.client.post("/api/v1/auth/login", json={"username": email, "password": "second-pass"}).status_code, 200)

    def test_api_keys_authenticate_and_revoke(self):
        created = self.client.post("/api/v1/auth/api-keys", json={"name": "CI bot", "environment": "Staging"}, headers=self.alice).json()
        secret = created["secret"]
        self.assertTrue(secret.startswith("cai_"))
        res = self.client.get("/api/v1/dashboard/summary", headers={"X-API-Key": secret})
        self.assertEqual(res.status_code, 200)
        keys = self.client.get("/api/v1/auth/api-keys", headers=self.alice).json()
        key = next(k for k in keys if k["id"] == created["id"])
        self.assertEqual(key["request_count"], 1)
        self.assertNotIn("secret", key)
        self.assertEqual(self.client.delete(f"/api/v1/auth/api-keys/{created['id']}", headers=self.alice).status_code, 200)
        self.assertEqual(self.client.get("/api/v1/dashboard/summary", headers={"X-API-Key": secret}).status_code, 401)
        self.assertEqual(self.client.delete(f"/api/v1/auth/api-keys/{created['id']}", headers=self.bob).status_code, 404)

    def test_powerbi_export_writes_real_files(self):
        self.run_pipeline(self.bob, "pbi_orders.csv", b"order_id,customer_id,order_date,status,total_amount\nPO1,PC1,2024-02-01,Shipped,12.5\nPO2,PC1,2024-02-02,Open,7\n")
        res = self.client.post("/api/v1/powerbi/refresh", headers=self.bob).json()
        orders = res["tables"]["FactOrders"]
        self.assertGreaterEqual(orders["rows"], 2)
        with open(orders["file"], encoding="utf-8") as f:
            content = f.read()
        self.assertIn("PO1", content)
        status = self.client.get("/api/v1/powerbi/status", headers=self.bob).json()
        self.assertEqual(status["dataset"]["status"], "Exported")
        files = self.client.get("/api/v1/dashboard/datasets", headers=self.bob).json()["files"]
        categories = {f["category"] for f in files}
        self.assertTrue({"raw", "cleaned", "report", "log", "powerbi"} <= categories, categories)

    def test_kaggle_pages_are_not_faked(self):
        res = self.client.post("/api/v1/upload/url", json={"url": "https://www.kaggle.com/datasets/some/dataset"}, headers=self.alice)
        self.assertEqual(res.status_code, 400)
        self.assertIn("Kaggle", res.json()["detail"])

    def test_live_stream_url_is_validated(self):
        res = self.client.post("/api/v1/upload/realtime", json={"stream_url": "http://127.0.0.1:9/feed.csv"}, headers=self.alice)
        self.assertEqual(res.status_code, 400)


class TestChatAssistant(PlatformTestCase):
    """The assistant returns exactly the requested files/logs, and otherwise just answers."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dave = _signup_and_login(cls.client, f"dave_{uuid.uuid4().hex[:6]}@example.com")
        csv = b"sale_id,order_id,product_id,quantity,unit_price,total_price,sale_date\nS1,O1,P1,2,2.5,5,2024-01-01\nS2,O1,P2,x,1.0,3,2024-01-02\n"
        up = cls.client.post("/api/v1/upload", files={"file": ("chat_sales.csv", csv)}, headers=cls.dave).json()
        cls.client.post("/api/v1/pipeline/start", json={"file_path": up["file_path"], "batch_id": up["batch_id"]}, headers=cls.dave)
        cls.batch_id = up["batch_id"]

    def ask(self, message):
        res = self.client.post("/api/v1/agent/chat", json={"message": message}, headers=self.dave)
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()["response"]

    def test_pdf_request_returns_only_the_pdf(self):
        reply = self.ask("download the pdf report for chat_sales.csv")
        self.assertIn(f"/api/v1/reports/download/{self.batch_id}?format=pdf", reply)
        for other in ("format=docx", "format=json", "format=markdown", "cleaned data", "data/raw", "```"):
            self.assertNotIn(other, reply)

    def test_cleaned_file_request(self):
        reply = self.ask("give me the cleaned file")
        self.assertIn("Cleaned data - chat_sales.csv", reply)
        self.assertNotIn("format=pdf", reply)

    def test_all_reports_request(self):
        reply = self.ask("send me my reports")
        for fmt in ("pdf", "docx", "markdown", "json"):
            self.assertIn(f"format={fmt}", reply)
        self.assertNotIn("Raw upload", reply)

    def test_log_request_returns_the_process_log(self):
        reply = self.ask("show me the log of chat_sales.csv")
        self.assertIn("ETL PROCESS LOG  |  File: chat_sales.csv", reply)
        self.assertIn(f"/api/v1/history/{self.batch_id}/log?download=true", reply)
        self.assertNotIn("format=pdf", reply)

    def test_general_questions_are_answered_without_files(self):
        for message in ("how do I log in?", "give me a python script that writes a csv file", "what is the capital of France?"):
            reply = self.ask(message)
            self.assertNotIn("/api/v1/", reply, message)
            self.assertNotIn("ETL PROCESS LOG", reply, message)

    def test_other_users_files_are_never_served(self):
        reply = self.client.post("/api/v1/agent/chat", json={"message": f"download the pdf report for {self.batch_id}"}, headers=self.bob).json()["response"]
        self.assertNotIn(self.batch_id, reply)
