"""
Data observability in Human Review: sensitive data with masking fixes, and changes against the
previous upload of the same file (renamed, removed or retyped columns, far fewer rows).
"""
import json
import unittest

import pandas as pd

from backend.utils import data_editor, pii
from tests.test_platform_regressions import PlatformTestCase


def _csv(rows: list) -> bytes:
    return pd.DataFrame(rows).to_csv(index=False).encode()


def _sales(n: int, amount=lambda i: f"{100 + i % 7}.50", amount_col="amount", region_col="region") -> bytes:
    return _csv([{"order_ref": f"O{i}", amount_col: amount(i), region_col: ["North", "South"][i % 2], "units": i % 5 + 1}
                 for i in range(n)])


class TestDetection(unittest.TestCase):
    def kinds(self, values, column):
        return {f["kind"]: f for f in pii.scan_column(pd.Series(values), column)}

    def test_identifiers_are_found_and_lookalikes_are_not(self):
        self.assertIn("card", self.kinds(["4111 1111 1111 1111", "5500-0000-0000-0004", "6011111111111117"], "payment"))
        self.assertIn("aadhaar", self.kinds(["2341 2341 2346", "4991 1866 5246"], "aadhaar_no"))
        self.assertIn("pan", self.kinds(["ABCPE1234F", "AAACB1234C"], "pan"))
        self.assertIn("iban", self.kinds(["GB82 WEST 1234 5698 7654 32", "DE89370400440532013000"], "account"))
        self.assertIn("secret", self.kinds(["hunter2", "s3cret"], "user_password"))
        self.assertIn("phone", self.kinds(["555-0100", "555-0200"], "Phone"))
        # Order ids pass the card checksum one time in ten; dates, year ranges and codes are not phone numbers
        ids = [str(4000000000000000 + i * 7919) for i in range(300)]
        self.assertEqual(self.kinds(ids, "order_id"), {})
        self.assertEqual(self.kinds(["2024-01-05", "05/01/2024 10:00", "2024-01-05 10:00:00"] * 5, "release_date"), {})
        self.assertEqual(self.kinds(["Set in 1914-1918", "The 1990-2009 era"] * 3, "short_description"), {})
        self.assertEqual(self.kinds(["555-0100", "555-0200"], "product_code"), {})

    def test_masking_and_pseudonyms(self):
        df = pd.DataFrame({"notes": ["paid with 4111 1111 1111 1111", "none", "card 4111 1111 1111 1111 again"],
                           "email": ["ann@example.com", "", "bo@example.org"]})
        out, changes = data_editor.apply_ops(df.copy(), [
            {"op": "pseudonymize_values", "column": "notes", "pii": "card"},
            {"op": "mask_values", "column": "email", "pii": "email"},
        ])
        token = out.loc[0, "notes"].split()[-1]
        self.assertTrue(token.startswith("anon_"))
        self.assertIn(token, out.loc[2, "notes"])  # the same number gets the same pseudonym
        self.assertEqual(out.loc[1, "notes"], "none")
        self.assertEqual(out["email"].tolist(), ["a***@example.com", "", "b***@example.org"])
        self.assertEqual(len(changes), 2)
        self.assertEqual(pii.mask_text("card", "4111 1111 1111 1111"), "**** **** **** 1111")
        with self.assertRaises(data_editor.EditError):
            data_editor.apply_ops(df.copy(), [{"op": "mask_values", "column": "notes", "pii": "dna"}])


class TestSensitiveDataReview(PlatformTestCase):
    def test_card_numbers_need_a_decision_and_can_be_masked(self):
        rows = [{"customer_id": f"C{i}", "customer_name": f"Name {i}", "email": f"user{i}@example.com",
                 "card_number": ["4111 1111 1111 1111", "5500 0000 0000 0004", "6011 1111 1111 1117"][i % 3]} for i in range(12)]
        batch = self.run_pipeline(self.alice, "pii_customers.csv", _csv(rows))["batch_id"]
        item = self.client.get(f"/api/v1/review/{batch}", headers=self.alice).json()
        self.assertEqual(item["status"], "open")
        issues = {(i["code"], i["column"]): i for i in item["issues"]}
        card = issues[("sensitive_data", "card_number")]
        self.assertEqual(card["severity"], "high")
        self.assertEqual(card["category"], "Sensitive data")
        self.assertNotIn("4111 1111 1111 1111", json.dumps(item))  # examples are shown masked
        self.assertEqual(issues[("personal_data", "email")]["severity"], "medium")
        # Run details list what arrived, including the notes that do not need a person
        observed = self.client.get(f"/api/v1/history/{batch}/details", headers=self.alice).json()["observations"]
        self.assertEqual({(o["category"], o["column"], o["severity"]) for o in observed},
                         {("Sensitive data", "card_number", "high"), ("Sensitive data", "email", "medium")})

        data = self.client.get(f"/api/v1/review/{batch}/data", params={"filter": json.dumps(card["rows"])}, headers=self.alice).json()
        self.assertEqual(data["matched"], 12)
        mask = next(f for f in card["fixes"] if f["op"]["op"] == "mask_values")
        res = self.client.post(f"/api/v1/review/{batch}/data", json={"version": data["version"], "ops": [mask["op"]]}, headers=self.alice)
        self.assertEqual(res.status_code, 200, res.text)
        after = self.client.get(f"/api/v1/review/{batch}/data", headers=self.alice).json()
        cards = [r["values"][after["columns"].index("card_number")] for r in after["rows"]]
        self.assertTrue(all(c.startswith("**** **** ****") for c in cards), cards)

        # Processing the masked file no longer finds card numbers
        self.client.post("/api/v1/pipeline/start", json={"file_path": item["raw_file"], "batch_id": batch}, headers=self.alice)
        rerun = self.client.get(f"/api/v1/review/{batch}", headers=self.alice).json()
        self.assertNotIn("sensitive_data", [i["code"] for i in rerun["issues"]])


class TestChangesSinceLastUpload(PlatformTestCase):
    def test_renamed_retyped_columns_and_fewer_rows(self):
        first = self.run_pipeline(self.alice, "drift_sales.csv", _sales(60))["batch_id"]
        first_item = self.client.get(f"/api/v1/review/{first}", headers=self.alice)
        self.assertEqual(first_item.status_code, 404, first_item.text)  # nothing to compare with yet, nothing wrong

        # Next export: 'region' renamed, 'amount' has text in it, and most rows are missing
        changed = _sales(20, amount=lambda i: "TBD" if i % 4 == 0 else f"{100 + i}.50", region_col="sales_region")
        second = self.run_pipeline(self.alice, "drift_sales.csv", changed)["batch_id"]
        item = self.client.get(f"/api/v1/review/{second}", headers=self.alice).json()
        codes = {i["code"]: i for i in item["issues"]}
        renamed = codes["column_renamed"]
        self.assertEqual(renamed["severity"], "high")
        self.assertEqual((renamed["evidence"]["old"], renamed["evidence"]["new"]), ("region", "sales_region"))
        self.assertEqual(codes["type_changed"]["severity"], "high")
        self.assertEqual(codes["type_changed"]["column"], "amount")
        self.assertEqual(codes["volume_drop"]["severity"], "high")
        self.assertNotIn("columns_removed", codes)

        # The suggested fix renames the column back
        data = self.client.get(f"/api/v1/review/{second}/data", headers=self.alice).json()
        res = self.client.post(f"/api/v1/review/{second}/data", json={"version": data["version"], "ops": [renamed["fixes"][0]["op"]]}, headers=self.alice)
        self.assertEqual(res.status_code, 200, res.text)
        self.assertIn("region", self.client.get(f"/api/v1/review/{second}/data", headers=self.alice).json()["columns"])

    def test_same_file_again_is_not_flagged(self):
        first = self.run_pipeline(self.alice, "steady_sales.csv", _sales(40))["batch_id"]
        second = self.run_pipeline(self.alice, "steady_sales.csv", _sales(40))["batch_id"]
        for batch in (first, second):
            self.assertEqual(self.client.get(f"/api/v1/review/{batch}", headers=self.alice).status_code, 404)
        log = self.client.get(f"/api/v1/history/{second}/log", headers=self.alice).text
        self.assertNotIn("since the last upload", log)

    def test_other_owners_files_are_not_compared(self):
        self.run_pipeline(self.bob, "shared_name.csv", _sales(60))
        batch = self.run_pipeline(self.alice, "shared_name.csv", _sales(10))["batch_id"]
        self.assertEqual(self.client.get(f"/api/v1/review/{batch}", headers=self.alice).status_code, 404)
