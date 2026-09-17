import unittest
import os
import pandas as pd
from agents.intake_agent.intake_agent import IntakeAgent
from agents.transformation_agent.transformation_agent import TransformationAgent
from backend.utils.type_inference import SemanticTypeInferenceEngine
from backend.utils.rca_generator import RootCauseAnalysisReportGenerator


class TestPipelineE2E(unittest.TestCase):
    def setUp(self):
        self.test_csv_path = "test_sample_dataset.csv"
        # Create a sample test dataset with intentional nulls and duplicates
        data = {
            "customer_id": ["C101", "C102", "C103", "C101", None],
            "customer_name": ["Alice Smith", "Bob Jones", "Charlie Brown", "Alice Smith", "Dana White"],
            "email": ["alice@example.com", "bob@example.com", "charlie@example.com", "alice@example.com", "dana@example.com"],
            "spend_amount": [120.50, 45.00, None, 120.50, 89.00]
        }
        df = pd.DataFrame(data)
        df.to_csv(self.test_csv_path, index=False)

    def tearDown(self):
        if os.path.exists(self.test_csv_path):
            os.remove(self.test_csv_path)

    def test_semantic_type_inference(self):
        """Verify type inference correctly identifies email and numerical types."""
        df = pd.read_csv(self.test_csv_path)
        profile = SemanticTypeInferenceEngine.profile_dataframe(df)
        self.assertEqual(profile["total_rows"], 5)
        self.assertEqual(profile["total_columns"], 4)
        self.assertIn("columns", profile)
        self.assertEqual(profile["columns"]["email"]["inferred_type"], "email")

    def test_intake_and_transformation_pipeline(self):
        """Verify Intake and Transformation agents execute and clean dataset."""
        intake = IntakeAgent()
        intake_res = intake.run(self.test_csv_path)
        self.assertIn("rows", intake_res)
        self.assertGreater(intake_res["rows"], 0)

        transform = TransformationAgent()
        transform_res = transform.run(self.test_csv_path, metadata=intake_res)
        self.assertIn("clean_dataset_path", transform_res)
        self.assertTrue(os.path.exists(transform_res["clean_dataset_path"]))

    def test_rca_report_generation(self):
        """Verify Root Cause Analysis report generator produces valid Markdown and JSON."""
        md = RootCauseAnalysisReportGenerator.generate_markdown_rca(
            batch_id="batch_test_123",
            dataset_name="test_data.csv",
            total_rows=100,
            rejected_rows=2,
            quality_score=98.0,
            errors=[{"column": "email", "reason": "Null email", "count": 2, "severity": "MEDIUM"}],
            transformations=[{"column_name": "spend_amount", "operation": "IMPUTE", "reason": "Median fill"}]
        )
        self.assertIn("# Autonomous Agentic AI ETL — Executive RCA Report", md)
        self.assertIn("batch_test_123", md)


if __name__ == "__main__":
    unittest.main()
