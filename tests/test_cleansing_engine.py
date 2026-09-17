import unittest
import pandas as pd
import numpy as np
from backend.utils.cleansing_engine import AutonomousCleansingEngine
from backend.database.schema_generator import DynamicSQLSchemaGenerator
from backend.utils.powerbi_dax import PowerBIDAXGenerator


class TestCleansingAndSchemas(unittest.TestCase):
    def test_autonomous_cleansing_engine(self):
        """Verify autonomous cleansing deduplicates rows and imputes missing values."""
        df = pd.DataFrame({
            "User Name": ["  John Doe ", "Jane Smith", "John Doe", None],
            "Order Amount": [100.0, None, 100.0, 50000.0],  # Outlier and null
            "Category": ["Electronics", "Clothing", "Electronics", None]
        })
        cleaned, audit_log, stats = AutonomousCleansingEngine.clean_dataframe(df, cap_outliers=True)

        # 1. Column names standardized
        self.assertIn("user_name", cleaned.columns)
        self.assertIn("order_amount", cleaned.columns)
        self.assertIn("category", cleaned.columns)

        # 2. No nulls remaining in string category (imputed with mode)
        self.assertEqual(int(cleaned["category"].isna().sum()), 0)

        # 3. Audit trail records transformations
        self.assertGreater(len(audit_log), 0)
        self.assertIn("duplicates_removed", stats)

    def test_dynamic_sql_schema_generator(self):
        """Verify dynamic SQL generator produces valid MySQL and SQLite DDL."""
        df = pd.DataFrame({
            "order_id": [1, 2, 3],
            "customer_email": ["a@b.com", "c@d.com", "e@f.com"],
            "total_price": [12.50, 45.00, 89.90]
        })
        ddl_mysql = DynamicSQLSchemaGenerator.generate_ddl("orders_test", df, dialect="mysql", primary_key="order_id")
        self.assertIn("CREATE TABLE IF NOT EXISTS `orders_test`", ddl_mysql)
        self.assertIn("`order_id`", ddl_mysql)
        self.assertIn("PRIMARY KEY", ddl_mysql)

        ddl_sqlite = DynamicSQLSchemaGenerator.generate_ddl("orders_test", df, dialect="sqlite")
        self.assertIn("CREATE TABLE IF NOT EXISTS `orders_test`", ddl_sqlite)

    def test_powerbi_dax_measures_generator(self):
        """Verify Power BI DAX generator returns essential business measures."""
        measures = PowerBIDAXGenerator.get_core_dax_measures()
        self.assertGreaterEqual(len(measures), 5)
        names = [m["name"] for m in measures]
        self.assertIn("Total Revenue", names)
        self.assertIn("Data Quality Pass Rate", names)


if __name__ == "__main__":
    unittest.main()
