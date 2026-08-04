import os
import sys
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))
import shutil
import time
import pandas as pd
from fastapi.testclient import TestClient
from backend.main import app
from backend.utils.file_utils import clear_cleaned_data_folder

def test_user_upload_and_cleaning():
    print("=== TESTING USER UPLOAD & CLEANING STORAGE ===")
    
    # 1. Clear cleaned data folder first
    clear_cleaned_data_folder("cleaned data")
    print(f"Cleaned data directory initialized. Files currently in cleaned data/: {os.listdir('cleaned data')}")
    assert len(os.listdir("cleaned data")) == 0, "cleaned data directory should be empty initially"

    # 2. Create a sample dirty user raw dataset file
    test_raw_filename = "user_input_sales.csv"
    raw_dir = "data/raw"
    os.makedirs(raw_dir, exist_ok=True)
    raw_file_path = os.path.join(raw_dir, test_raw_filename)
    
    dirty_data = """Sale ID , Order ID,Product ID ,Quantity,Unit Price,Total Price,Sale Date
S001, O001, P100, 2, 15.50, 31.00, 2026-01-01
S002, O002, P101, , 20.00, , 2026-01-02
S001, O001, P100, 2, 15.50, 31.00, 2026-01-01
"""
    with open(raw_file_path, "w", encoding="utf-8") as f:
        f.write(dirty_data)
        
    print(f"Created raw dirty file at {raw_file_path}")

    # 3. Upload file using FastAPI TestClient
    client = TestClient(app)
    with open(raw_file_path, "rb") as f:
        res_upload = client.post(
            "/api/v1/upload",
            files={"file": (test_raw_filename, f, "text/csv")}
        )
    assert res_upload.status_code == 200, f"Upload failed: {res_upload.text}"
    upload_info = res_upload.json()
    batch_id = upload_info["batch_id"]
    uploaded_path = upload_info["file_path"]
    print(f"Upload successful. Batch ID: {batch_id}, Path: {uploaded_path}")

    # 4. Trigger pipeline start
    res_start = client.post(
        "/api/v1/pipeline/start",
        json={"file_path": uploaded_path, "batch_id": batch_id}
    )
    assert res_start.status_code == 200, f"Pipeline start failed: {res_start.text}"
    pipeline_id = res_start.json()["pipeline_id"]
    print(f"Pipeline started with ID: {pipeline_id}")

    # 5. Wait for pipeline to finish
    timeout = 15
    while timeout > 0:
        res_status = client.get(f"/api/v1/pipeline/status?pipeline_id={pipeline_id}")
        assert res_status.status_code == 200
        st = res_status.json()
        if st["status"] in ["Success", "Passed with Warnings", "Failed"]:
            print(f"Pipeline finished with status: {st['status']}")
            break
        time.sleep(1)
        timeout -= 1

    # 6. Verify contents of 'cleaned data' folder
    cleaned_files = os.listdir("cleaned data")
    print(f"\nFiles in cleaned data/ folder: {cleaned_files}")
    
    # Assertions:
    assert test_raw_filename in cleaned_files, f"Expected {test_raw_filename} in cleaned data folder, found: {cleaned_files}"
    
    # Read the cleaned file
    clean_filepath = os.path.join("cleaned data", test_raw_filename)
    clean_df = pd.read_csv(clean_filepath)
    print("\nCleaned Dataset Content:")
    print(clean_df)
    
    # Verify cleaning quality: column headers in snake_case, deduplicated rows
    assert "sale_id" in clean_df.columns, "Columns were not standardized to snake_case!"
    assert len(clean_df) == 2, f"Expected 2 rows after deduplication, got {len(clean_df)}"
    assert clean_df["quantity"].isnull().sum() == 0, "Missing quantity was not handled!"
    
    print("\n=== ALL TEST ASSERTIONS PASSED SUCCESSFULLY! ===")

if __name__ == "__main__":
    test_user_upload_and_cleaning()
