"""Human Review queue: the Review Agent flags runs a person must decide on, and reviewers fix and resolve them."""
import json
import os
import tempfile
import unittest

import pandas as pd

from agents.review_agent.review_agent import ReviewAgent
from tests.test_platform_regressions import PlatformTestCase

CLEAN = b"customer_id,customer_name,email,region\nC1,Ann Lee,ann@example.com,North\nC2,Bo Chan,bo@example.com,South\n"
# Income is missing for most South rows and never for North rows: missing not at random
BIASED = ("respondent,region,income,score\n" + "".join(
    f"R{i},{'South' if i % 2 else 'North'},{'' if i % 2 and i % 10 != 1 else 30000 + i * 1000},{50 + i % 7}\n"
    for i in range(40))).encode()
MISSING_NAMES = b"customer_id,customer_name,email,region\nC1,Ann Lee,ann@example.com,North\nC2,,bo@example.com,South\nC3,,cy@example.com,East\n"
HEADER_ONLY = b"customer_id,customer_name,email,region\n"


class TestReviewAgent(PlatformTestCase):
    def test_clean_file_is_not_flagged(self):
        batch = self.run_pipeline(self.alice, "review_clean.csv", CLEAN)["batch_id"]
        self.assertEqual(self.client.get(f"/api/v1/review/{batch}", headers=self.alice).status_code, 404)
        run = next(r for r in self.client.get("/api/v1/history", headers=self.alice).json() if r["batch_id"] == batch)
        self.assertIsNone(run["review"])

    def test_biased_missing_values_need_a_decision(self):
        batch = self.run_pipeline(self.alice, "review_biased.csv", BIASED)["batch_id"]
        res = self.client.get(f"/api/v1/review/{batch}", headers=self.alice)
        self.assertEqual(res.status_code, 200, res.text)
        item = res.json()
        self.assertEqual(item["status"], "open")
        self.assertEqual(item["kind"], "needs_decision")
        codes = {i["code"]: i for i in item["issues"]}
        self.assertIn("missing_imputed", codes)
        mnar = codes["missing_not_at_random"]
        self.assertEqual(mnar["column"], "income")
        self.assertEqual(mnar["evidence"]["group_column"], "region")
        self.assertEqual(mnar["evidence"]["group"], "South")
        for issue in item["issues"]:
            self.assertTrue(issue["problem"] and issue["impact"] and issue["action"])

        # The process log spells out every problem
        log = self.client.get(f"/api/v1/history/{batch}/log", headers=self.alice).text
        self.assertIn("HUMAN REVIEW REQUIRED", log)
        self.assertIn("Missing 'income' values are concentrated in region = 'South'", log)
        self.assertIn("Why it matters", log)

        run = next(r for r in self.client.get("/api/v1/history", headers=self.alice).json() if r["batch_id"] == batch)
        self.assertEqual(run["review"]["status"], "open")

    def test_rejected_rows_are_flagged(self):
        batch = self.run_pipeline(self.alice, "review_rejects.csv", MISSING_NAMES)["batch_id"]
        item = self.client.get(f"/api/v1/review/{batch}", headers=self.alice).json()
        rejected = next(i for i in item["issues"] if i["code"] == "rows_rejected")
        self.assertEqual(rejected["severity"], "high")
        self.assertIn("customer_name", rejected["problem"])

    def test_unprocessable_file_is_not_processed(self):
        status = self.run_pipeline(self.alice, "review_empty.csv", HEADER_ONLY)
        item = self.client.get(f"/api/v1/review/{status['batch_id']}", headers=self.alice).json()
        self.assertEqual(item["kind"], "not_processed")
        self.assertEqual(item["severity"], "critical")
        self.assertEqual(item["run_status"], "Failed")

    def test_decisions_and_access(self):
        batch = self.run_pipeline(self.alice, "review_decide.csv", BIASED)["batch_id"]
        self.assertEqual(self.client.get(f"/api/v1/review/{batch}", headers=self.bob).status_code, 404)
        self.assertNotIn(batch, [i["batch_id"] for i in self.client.get("/api/v1/review", headers=self.bob).json()["items"]])
        self.assertEqual(self.client.post(f"/api/v1/review/{batch}", json={"action": "resolve"}, headers=self.bob).status_code, 404)
        # The administrator sees every account's queue
        self.assertIn(batch, [i["batch_id"] for i in self.client.get("/api/v1/review", headers=self.admin).json()["items"]])

        before = self.client.get("/api/v1/review", headers=self.alice).json()["counts"]["open"]
        res = self.client.post(f"/api/v1/review/{batch}", json={"action": "resolve", "note": "Filled income per region in the source."}, headers=self.alice)
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["status"], "resolved")
        self.assertEqual(res.json()["note"], "Filled income per region in the source.")
        queue = self.client.get("/api/v1/review", headers=self.alice).json()
        self.assertEqual(queue["counts"]["open"], before - 1)
        self.assertNotIn(batch, [i["batch_id"] for i in queue["items"]])
        resolved = self.client.get("/api/v1/review?status=resolved", headers=self.alice).json()["items"]
        self.assertIn(batch, [i["batch_id"] for i in resolved])

        self.assertEqual(self.client.post(f"/api/v1/review/{batch}", json={"action": "dismiss"}, headers=self.alice).json()["status"], "dismissed")
        self.assertEqual(self.client.post(f"/api/v1/review/{batch}", json={"action": "reopen"}, headers=self.alice).json()["status"], "open")
        self.assertEqual(self.client.post(f"/api/v1/review/{batch}", json={"action": "approve"}, headers=self.alice).status_code, 422)

    def test_deleting_a_run_removes_its_review(self):
        batch = self.run_pipeline(self.alice, "review_delete.csv", BIASED)["batch_id"]
        self.assertEqual(self.client.delete(f"/api/v1/history/{batch}", headers=self.alice).status_code, 200)
        self.assertNotIn(batch, [i["batch_id"] for i in self.client.get("/api/v1/review?status=all", headers=self.alice).json()["items"]])


class TestReviewChecks(PlatformTestCase):
    def test_crash_is_explained(self):
        review = ReviewAgent().run(None, error="Error tokenizing data. C error: Expected 3 fields in line 7, saw 5", failed_stage="intake")
        self.assertEqual(review["kind"], "not_processed")
        issue = review["issues"][0]
        self.assertEqual(issue["code"], "pipeline_crash")
        self.assertIn("delimiter", issue["problem"])


# Only an extreme value: a note in the log, not a reason to involve a person
OUTLIER_ONLY = ("order_ref,amount\n" + "".join(f"O{i},{100 + i % 9}\n" for i in range(39)) + "O39,99999\n").encode()


class TestReviewQueueThreshold(PlatformTestCase):
    def test_minor_problems_stay_out_of_the_queue(self):
        batch = self.run_pipeline(self.alice, "review_minor.csv", OUTLIER_ONLY)["batch_id"]
        self.assertEqual(self.client.get(f"/api/v1/review/{batch}", headers=self.alice).status_code, 404)
        log = self.client.get(f"/api/v1/history/{batch}/log", headers=self.alice).text
        self.assertIn("REVIEW NOTES", log)
        self.assertIn("extreme values in 'amount'", log)
        self.assertNotIn("HUMAN REVIEW REQUIRED", log)
