"""Run management (compare, export, preview, delete) and the dashboard trends / system status endpoints."""
import os

from tests.test_platform_regressions import PlatformTestCase

CUSTOMERS = b"customer_id,customer_name,email,region\nC1,Ann Lee,ann@example.com,North\nC2,Bo Chan,bo@example.com,South\nC3,Cy Diaz,,East\n"
CUSTOMERS_V2 = b"customer_id,customer_name,email,region,tier\nC1,Ann Lee,ann@example.com,North,Gold\nC2,Bo Chan,bo@example.com,South,Silver\n"


class TestRunManagement(PlatformTestCase):
    def test_compare_two_runs(self):
        a = self.run_pipeline(self.alice, "cmp_a.csv", CUSTOMERS)["batch_id"]
        b = self.run_pipeline(self.alice, "cmp_b.csv", CUSTOMERS_V2)["batch_id"]
        res = self.client.get(f"/api/v1/history/compare?a={a}&b={b}", headers=self.alice)
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        metrics = {m["key"]: m for m in data["metrics"]}
        self.assertEqual(metrics["rows"]["a"], 3)
        self.assertEqual(metrics["rows"]["b"], 2)
        self.assertEqual(metrics["rows"]["delta"], -1)
        self.assertEqual(data["schema"]["only_in_b"], ["tier"])
        self.assertEqual(self.client.get(f"/api/v1/history/compare?a={a}&b={a}", headers=self.alice).status_code, 400)
        # Another user cannot compare Alice's runs
        self.assertEqual(self.client.get(f"/api/v1/history/compare?a={a}&b={b}", headers=self.bob).status_code, 404)

    def test_preview_profiles_the_dataset(self):
        batch = self.run_pipeline(self.alice, "preview_me.csv", CUSTOMERS)["batch_id"]
        res = self.client.get(f"/api/v1/history/{batch}/preview?rows=2", headers=self.alice)
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertEqual(len(data["rows"]), 2)
        self.assertEqual(data["profiled_rows"], 3)
        names = [c["name"] for c in data["columns"]]
        self.assertIn("customer_id", names)
        self.assertEqual(self.client.get(f"/api/v1/history/{batch}/preview", headers=self.bob).status_code, 404)

    def test_export_history_csv(self):
        batch = self.run_pipeline(self.alice, "export_me.csv", CUSTOMERS)["batch_id"]
        res = self.client.get("/api/v1/history/export", headers=self.alice)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.headers["content-type"].startswith("text/csv"))
        self.assertTrue(res.text.startswith("batch_id,filename"))
        self.assertIn(batch, res.text)
        self.assertNotIn(batch, self.client.get("/api/v1/history/export", headers=self.bob).text)

    def test_delete_run_keeps_files_shared_with_other_runs(self):
        first = self.run_pipeline(self.alice, "delete_me.csv", CUSTOMERS)["batch_id"]
        second = self.run_pipeline(self.alice, "delete_me.csv", CUSTOMERS)["batch_id"]
        runs = {r["batch_id"]: r for r in self.client.get("/api/v1/history", headers=self.alice).json()}
        raw_file = runs[second]["raw_file"]
        self.assertTrue(raw_file and os.path.isfile(raw_file))

        self.assertEqual(self.client.delete(f"/api/v1/history/{first}", headers=self.bob).status_code, 404)
        res = self.client.delete(f"/api/v1/history/{first}", headers=self.alice)
        self.assertEqual(res.status_code, 200, res.text)
        history = [r["batch_id"] for r in self.client.get("/api/v1/history", headers=self.alice).json()]
        self.assertNotIn(first, history)
        self.assertIn(second, history)
        # The second run still uses the same uploaded file
        self.assertTrue(os.path.isfile(raw_file))

        self.assertEqual(self.client.delete(f"/api/v1/history/{second}", headers=self.alice).status_code, 200)
        self.assertFalse(os.path.isfile(raw_file))
        self.assertEqual(self.client.get(f"/api/v1/pipeline/status?pipeline_id=pipe_{second}", headers=self.alice).status_code, 404)


class TestDashboardInsights(PlatformTestCase):
    def test_trends_cover_every_day(self):
        self.run_pipeline(self.bob, "trend.csv", CUSTOMERS)
        res = self.client.get("/api/v1/dashboard/trends?days=7", headers=self.bob)
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertEqual(len(data["series"]), 7)
        self.assertGreaterEqual(data["series"][-1]["runs"], 1)
        self.assertEqual(data["totals"]["runs"], sum(d["runs"] for d in data["series"]))

    def test_system_status(self):
        res = self.client.get("/api/v1/dashboard/system", headers=self.alice)
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertTrue(data["database"]["connected"])
        self.assertEqual(data["llm"]["active_engine"], "offline")
        self.assertIn("version", data)
        self.assertEqual(self.client.get("/api/v1/dashboard/system").status_code, 401)
