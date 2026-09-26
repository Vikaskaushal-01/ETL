"""Run details, rejected-row export, scheduled ingestion, run notifications and interrupted-run recovery."""
from datetime import datetime, timedelta
from unittest import mock

from backend.core import notify, scheduler
from backend.database.models import PipelineLog, Schedule
from backend.database.mysql import SessionLocal
from tests.test_platform_regressions import PlatformTestCase

# order_id is the key of the orders table: the duplicate O2 row and the O3 row without a date/total get rejected
ORDERS = (b"order_id,customer_id,order_date,status,total_amount\n"
          b"O1,C1,2026-01-05,Shipped,120.5\nO2,C2,2026-01-06,Pending,80\nO2,C2,2026-01-06,Pending,80\n"
          b"O3,,not-a-date,Shipped,\n")
CSV = b"id,name,amount\n1,Ann,10\n2,Bo,\n3,Cy,30\n"


class TestRunDetails(PlatformTestCase):
    def test_details_expose_the_report(self):
        batch = self.run_pipeline(self.alice, "details_orders.csv", ORDERS)["batch_id"]
        res = self.client.get(f"/api/v1/history/{batch}/details", headers=self.alice)
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertTrue(data["has_report"])
        self.assertEqual(data["run"]["batch_id"], batch)
        self.assertTrue(data["transformations"], "the cleaner records what it changed")
        self.assertIn("missing_values", data)
        self.assertGreaterEqual(data["rejected"]["count"], 1, "the fixture contains an invalid order")
        self.assertEqual(data["rejected"]["count"], len(data["rejected"]["sample"]))
        self.assertTrue(data["rejected"]["reasons"])
        self.assertEqual(self.client.get(f"/api/v1/history/{batch}/details", headers=self.bob).status_code, 404)

    def test_rejected_rows_csv(self):
        batch = self.run_pipeline(self.alice, "rejects.csv", ORDERS)["batch_id"]
        res = self.client.get(f"/api/v1/history/{batch}/rejected.csv", headers=self.alice)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.text.startswith("row_number,rejection_reason"))
        self.assertGreaterEqual(len(res.text.strip().splitlines()), 2, "at least one rejected row")
        self.assertIn('filename="rejects_rejected_rows.csv"', res.headers["content-disposition"])


class TestSchedules(PlatformTestCase):
    def create(self, headers, **overrides):
        body = {"name": "Nightly sales", "url": "https://example.com/sales.csv", "interval_minutes": 60, "run_now": False, **overrides}
        with mock.patch("backend.api.schedules.validate_public_url", return_value=body["url"]):
            return self.client.post("/api/v1/schedules", json=body, headers=headers)

    def test_create_list_pause_delete(self):
        res = self.create(self.alice)
        self.assertEqual(res.status_code, 200, res.text)
        sid = res.json()["id"]
        self.assertTrue(res.json()["enabled"])
        self.assertIn(sid, [s["id"] for s in self.client.get("/api/v1/schedules", headers=self.alice).json()])
        self.assertNotIn(sid, [s["id"] for s in self.client.get("/api/v1/schedules", headers=self.bob).json()])

        paused = self.client.patch(f"/api/v1/schedules/{sid}", json={"enabled": False}, headers=self.alice).json()
        self.assertFalse(paused["enabled"])
        self.assertIsNone(paused["next_run_at"])
        self.assertEqual(self.client.patch(f"/api/v1/schedules/{sid}", json={"enabled": True}, headers=self.bob).status_code, 404)
        self.assertEqual(self.client.delete(f"/api/v1/schedules/{sid}", headers=self.alice).status_code, 200)

    def test_rejects_bad_input(self):
        self.assertEqual(self.create(self.alice, interval_minutes=1).status_code, 422)
        res = self.client.post("/api/v1/schedules", json={"name": "x", "url": "http://127.0.0.1/data.csv", "interval_minutes": 60}, headers=self.alice)
        self.assertEqual(res.status_code, 400)

    def test_due_schedule_downloads_and_runs(self):
        sid = self.create(self.alice, name="Due feed").json()["id"]
        db = SessionLocal()
        db.get(Schedule, sid).next_run_at = datetime.utcnow() - timedelta(minutes=1)
        db.commit()
        db.close()
        with mock.patch("backend.api.upload.download_dataset", return_value=(CSV, "due_feed.csv")), \
             mock.patch.object(scheduler, "trigger", side_effect=scheduler.run_schedule):
            self.assertEqual(scheduler.tick(), 1)
            self.assertEqual(scheduler.tick(), 0, "the occurrence was claimed and moved forward")
        schedule = next(s for s in self.client.get("/api/v1/schedules", headers=self.alice).json() if s["id"] == sid)
        self.assertEqual(schedule["run_count"], 1)
        self.assertIn(schedule["last_status"], ("Success", "Passed with Warnings"))
        history = {r["batch_id"]: r for r in self.client.get("/api/v1/history", headers=self.alice).json()}
        self.assertEqual(history[schedule["last_batch_id"]]["source"], "Scheduled")

    def test_download_failure_is_recorded(self):
        from backend.api.upload import DatasetFetchError
        sid = self.create(self.alice, name="Broken feed").json()["id"]
        with mock.patch("backend.api.upload.download_dataset", side_effect=DatasetFetchError("Status code: 404")):
            scheduler.run_schedule(sid)
        schedule = next(s for s in self.client.get("/api/v1/schedules", headers=self.alice).json() if s["id"] == sid)
        self.assertEqual(schedule["last_status"], "Failed")
        self.assertIn("404", schedule["last_error"])


class TestNotifications(PlatformTestCase):
    def test_settings_roundtrip_and_validation(self):
        with mock.patch("backend.core.security.validate_public_url", side_effect=lambda u: u):
            res = self.client.put("/api/v1/auth/notifications", json={"webhook_url": "https://hooks.example.com/x", "notify_on": "failures"}, headers=self.alice)
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(self.client.get("/api/v1/auth/notifications", headers=self.alice).json()["notify_on"], "failures")
        bad = self.client.put("/api/v1/auth/notifications", json={"webhook_url": "http://10.0.0.5/hook"}, headers=self.alice)
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(self.client.get("/api/v1/auth/notifications").status_code, 401)

    def test_finished_run_posts_to_webhook(self):
        sent = []
        with mock.patch("backend.core.security.validate_public_url", side_effect=lambda u: u):
            self.client.put("/api/v1/auth/notifications", json={"webhook_url": "https://hooks.example.com/bob", "notify_on": "all"}, headers=self.bob)
        with mock.patch.object(notify, "send", side_effect=lambda url, run: sent.append((url, run)) or (True, "ok")), \
             mock.patch.object(notify.threading, "Thread", side_effect=lambda target, **kw: mock.Mock(start=target)):
            batch = self.run_pipeline(self.bob, "notify_me.csv", CSV)["batch_id"]
        self.assertEqual(len(sent), 1)
        url, run = sent[0]
        self.assertEqual(url, "https://hooks.example.com/bob")
        self.assertEqual(run["batch_id"], batch)
        self.assertIn("notify_me.csv", notify.build_message(run))


class TestInterruptedRuns(PlatformTestCase):
    def test_stale_running_runs_are_marked_failed(self):
        batch = self.run_pipeline(self.alice, "stuck.csv", CSV)["batch_id"]
        db = SessionLocal()
        log = db.get(PipelineLog, f"pipe_{batch}")
        log.status, log.start_time = "Running", datetime.utcnow() - timedelta(days=1)
        db.commit()
        db.close()
        scheduler.recover_interrupted_runs()
        run = next(r for r in self.client.get("/api/v1/history", headers=self.alice).json() if r["batch_id"] == batch)
        self.assertEqual(run["status"], "Failed")
        self.assertIn("interrupted", run["error"])
        self.assertIsNone(run["execution_time"], "downtime must not be reported as runtime")
