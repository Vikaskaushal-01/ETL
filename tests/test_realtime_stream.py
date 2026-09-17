import unittest
import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.api.upload import generate_realtime_stream_dataset


class TestRealtimeStreamGenerators(unittest.TestCase):
    def test_transactions_stream_generator(self):
        filename, data = generate_realtime_stream_dataset(stream_type="transactions", count=20, cycle=1)
        self.assertTrue(filename.startswith("realtime_transactions_"))
        self.assertTrue(filename.endswith(".csv"))
        
        decoded = data.decode("utf-8")
        lines = decoded.strip().split("\n")
        self.assertGreaterEqual(len(lines), 21) # Header + >=20 rows
        self.assertIn("transaction_id", lines[0])
        self.assertIn("TXN_001_", lines[1])

    def test_iot_sensors_stream_generator(self):
        filename, data = generate_realtime_stream_dataset(stream_type="iot_sensors", count=25, cycle=2)
        self.assertTrue(filename.startswith("realtime_iot_telemetry_"))
        self.assertTrue(filename.endswith(".csv"))
        
        decoded = data.decode("utf-8")
        lines = decoded.strip().split("\n")
        self.assertGreaterEqual(len(lines), 26)
        self.assertIn("reading_id", lines[0])
        self.assertIn("temperature_c", lines[0])
        self.assertIn("IOT_002_", lines[1])

    def test_ecommerce_orders_stream_generator(self):
        filename, data = generate_realtime_stream_dataset(stream_type="ecommerce_orders", count=15, cycle=3)
        self.assertTrue(filename.startswith("realtime_orders_"))
        self.assertTrue(filename.endswith(".csv"))
        
        decoded = data.decode("utf-8")
        lines = decoded.strip().split("\n")
        self.assertGreaterEqual(len(lines), 16)
        self.assertIn("order_id", lines[0])
        self.assertIn("customer_email", lines[0])
        self.assertIn("ORD_003_", lines[1])

    def test_custom_data_stream_generator(self):
        custom_csv = "id,name,val\n1,alpha,100\n2,beta,200\n"
        filename, data = generate_realtime_stream_dataset(stream_type="custom", custom_data=custom_csv)
        self.assertTrue(filename.startswith("realtime_custom_"))
        decoded = data.decode("utf-8")
        self.assertEqual(decoded, custom_csv.strip())


if __name__ == "__main__":
    unittest.main()
