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
