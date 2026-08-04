import os
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

from fastapi.testclient import TestClient
from backend.main import app

def test_user_file_persistence():
    print("=== FORCEFULLY VERIFYING USER UPLOAD DATA & LOG PERSISTENCE ===")
    client = TestClient(app)
    
    # Create test user csv file content
    user_filename = "user_input_sales_records.csv"
    raw_path = f"data/raw/{user_filename}"
    csv_data = "sale_id,order_id,product_id,quantity,unit_price,total_price,sale_date\nS001,O001,P100,2,15.50,31.00,2026-01-01\nS002,O002,P101,1,20.00,20.00,2026-01-02\n"
    
    with open(raw_path, "w", encoding="utf-8") as f:
        f.write(csv_data)
        
    print(f"Created user input file at: {raw_path}")
    
    # 1. Start pipeline for user file
    res = client.post("/api/v1/pipeline/start", json={
        "file_path": raw_path,
        "batch_id": "batch_user_test_99"
    })
    assert res.status_code == 200, f"Failed: {res.text}"
    print(f"Pipeline start response: {res.json()}")
    
    import time
    time.sleep(3)
    
    # 2. Check cleaned data folder
    cleaned_files = os.listdir("cleaned data")
    print(f"Cleaned Data Folder Contents: {cleaned_files}")
    assert user_filename in cleaned_files, f"Expected {user_filename} in cleaned data folder, found {cleaned_files}"
    
    cleaned_file_path = os.path.join("cleaned data", user_filename)
    with open(cleaned_file_path, "r", encoding="utf-8") as cf:
        clean_content = cf.read()
    print(f"\nCleaned File Content ({user_filename}):\n{clean_content}")
    assert len(clean_content) > 0, "Cleaned file is empty!"
    
    # 3. Check logs folder
    log_files = os.listdir("logs")
    print(f"Logs Folder Contents: {log_files}")
    expected_file_log = f"{user_filename}.log"
    expected_batch_log = "batch_user_test_99.log"
    
    assert expected_file_log in log_files, f"Expected {expected_file_log} in logs folder!"
    assert expected_batch_log in log_files, f"Expected {expected_batch_log} in logs folder!"
    
    with open(os.path.join("logs", expected_file_log), "r", encoding="utf-8") as lf:
        file_log_content = lf.read()
    print(f"\nLog File Content ({expected_file_log}):\n{file_log_content}")
    assert len(file_log_content) > 0, "Log file is empty!"
    
    print("\n=== FORCEFUL VERIFICATION COMPLETED: ALL DATA & LOGS STORED PROPERLY! ===")

if __name__ == "__main__":
    test_user_file_persistence()
