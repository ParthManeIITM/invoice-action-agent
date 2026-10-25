"""
Integration tests for A2A 1.0 Invoice Action Agent.
"""

import unittest
from fastapi.testclient import TestClient
from app import app, A2A_MEDIA

client = TestClient(app)

class TestInvoiceActionAgent(unittest.TestCase):
    def test_health(self):
        resp = client.get("/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get("status"), "ok")

    def test_agent_card(self):
        resp = client.get("/.well-known/agent-card.json")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("application/a2a+json", resp.headers.get("content-type", ""))
        data = resp.json()
        self.assertTrue(data.get("name"))
        self.assertTrue(data.get("description"))
        self.assertEqual(data.get("version"), "1.0.0")
        self.assertIsInstance(data.get("capabilities"), dict)
        self.assertIsInstance(data.get("skills"), list)
        self.assertGreater(len(data.get("skills")), 0)
        skill = data["skills"][0]
        self.assertEqual(skill.get("id"), "invoice_action_agent")
        self.assertTrue(skill.get("name"))
        self.assertTrue(skill.get("description"))
        self.assertIsInstance(skill.get("tags"), list)
        self.assertIsInstance(data.get("supportedInterfaces"), list)
        self.assertGreater(len(data.get("supportedInterfaces")), 0)

    def test_missing_version_returns_400(self):
        resp = client.get(
            "/tasks",
            headers={"Authorization": "Bearer test-token"}
        )
        self.assertEqual(resp.status_code, 400)

    def test_missing_auth_returns_401(self):
        resp = client.get(
            "/tasks",
            headers={"A2A-Version": "1.0"}
        )
        self.assertEqual(resp.status_code, 401)

    def test_tasks_list_authenticated(self):
        resp = client.get(
            "/tasks",
            headers={
                "Authorization": "Bearer test-token",
                "A2A-Version": "1.0"
            }
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("application/a2a+json", resp.headers.get("content-type", ""))
        self.assertIn("tasks", resp.json())

    def test_tasks_list_prefixed_a2a(self):
        resp = client.get(
            "/a2a/tasks",
            headers={
                "Authorization": "Bearer test-token",
                "A2A-Version": "1.0"
            }
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("application/a2a+json", resp.headers.get("content-type", ""))
        self.assertIn("tasks", resp.json())

    def test_task_not_found(self):
        resp = client.get(
            "/tasks/task_nonexistent_12345",
            headers={
                "Authorization": "Bearer test-token",
                "A2A-Version": "1.0"
            }
        )
        self.assertEqual(resp.status_code, 404)

    def test_cancel_nonexistent_task(self):
        resp = client.post(
            "/tasks/task_nonexistent_12345:cancel",
            headers={
                "Authorization": "Bearer test-token",
                "A2A-Version": "1.0",
                "Content-Type": "application/a2a+json"
            }
        )
        self.assertEqual(resp.status_code, 404)

if __name__ == "__main__":
    unittest.main()
