import unittest
from fastapi.testclient import TestClient
from backend.main import app


class TestExtendedEndpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        login = cls.client.post("/api/v1/auth/login", json={"username": "admin@controlai.net", "password": "admin"})
        cls.client.headers.update({"Authorization": f"Bearer {login.json()['token']}"})

    def test_dashboard_metrics_endpoint(self):
        """Verify dashboard extended telemetry returns operational metrics."""
        response = self.client.get("/api/v1/dashboard/metrics")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("telemetry", data)
        self.assertIn("system_availability_pct", data["telemetry"])
        self.assertIn("engine_status", data["telemetry"])
        self.assertEqual(data["telemetry"]["engine_status"], "Operational")

    def test_powerbi_measures_endpoint(self):
        """Verify Power BI DAX calculation measures endpoint."""
        response = self.client.get("/api/v1/powerbi/measures")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("measures", data)
        self.assertGreaterEqual(len(data["measures"]), 1)
        self.assertTrue(any(m["name"] == "Total Revenue" for m in data["measures"]))

    def test_rag_search_endpoint(self):
        """Verify RAG knowledge base search endpoint handles empty/populated queries."""
        payload = {"query": "customer sales", "top_k": 3}
        response = self.client.post("/api/v1/rag/search", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("results", data)
        self.assertIn("total_matches", data)


if __name__ == "__main__":
    unittest.main()
