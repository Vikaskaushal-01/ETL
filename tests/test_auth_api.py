import unittest
from fastapi.testclient import TestClient
from backend.main import app


class TestAuthAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_health_endpoint(self):
        """Verify backend health check returns 200 and healthy DB status."""
        response = self.client.get("/api/v1/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get("status"), "Healthy")

    def test_auth_login_admin(self):
        """Verify default administrator credentials allow successful sign-in."""
        payload = {
            "username": "admin@controlai.net",
            "password": "admin"
        }
        response = self.client.post("/api/v1/auth/login", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get("status"), "Success")
        self.assertIn("user", data)

    def test_auth_invalid_login(self):
        """Verify bad passwords fail with 400 or 401."""
        payload = {
            "username": "admin@controlai.net",
            "password": "wrong_password_123"
        }
        response = self.client.post("/api/v1/auth/login", json=payload)
        self.assertIn(response.status_code, [400, 401])

    def test_forgot_password_flow(self):
        """Verify request verification code endpoint returns a valid response."""
        payload = {"email": "admin@controlai.net"}
        response = self.client.post("/api/v1/auth/forgot-password", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue("status" in data or "demo_code" in data)


if __name__ == "__main__":
    unittest.main()
