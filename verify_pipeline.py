import os
import json
import shutil
import time
from fastapi.testclient import TestClient
from backend.main import app
from backend.database.mysql import Base, engine

def run_e2e_test():
    print("=== STARTING AGENTIC ETL PLATFORM E2E VERIFICATION ===")
    
    # 1. Clean previous runs
    folders_to_clear = ["data/raw", "cleaned data", "reports", "logs"]
    folders_to_remove = ["data/csv", "data/word", "data/sql", "data/processed", "data/clean"]
    for folder in folders_to_remove:
        if os.path.exists(folder):
            shutil.rmtree(folder, ignore_errors=True)
    for folder in folders_to_clear:
        os.makedirs(folder, exist_ok=True)
        # Clear files safely
        for f in os.listdir(folder):
            path = os.path.join(folder, f)
            if os.path.isfile(path):
                try:
                    os.remove(path)
                except Exception:
                    pass
                
    # 2. Reset database schema for clean run (SQLite fallback makes this instant)
    print("Re-creating database schemas...")
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    
    # 3. Generate raw dirty files
    import generate_sample_data
    generate_sample_data.generate_data()
    
    client = TestClient(app)
    
    # Verify health
    res_health = client.get("/api/v1/health")
    print(f"Health Check: {res_health.status_code} - {res_health.json()}")
    
    # List of files to process sequentially in different formats to check all of them:
    datasets = [
        "customers_dirty.xml",
        "orders_dirty.xlsx",
        "sales_dirty.tsv",
        "customers_dirty.json",
        "sales_dirty.csv"
    ]
    
    batch_ids = {}
    
    for filename in datasets:
        print(f"\n--- Processing dataset: {filename} ---")
        
        # Determine mime type dynamically
        mime_type = "text/csv"
        if filename.endswith(".json"):
            mime_type = "application/json"
        elif filename.endswith(".xml"):
            mime_type = "application/xml"
        elif filename.endswith(".xlsx"):
            mime_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        elif filename.endswith(".tsv"):
            mime_type = "text/tab-separated-values"

        # A. Upload file
        raw_path = f"data/raw/{filename}"
        with open(raw_path, "rb") as f:
            res_upload = client.post(
                "/api/v1/upload",
                files={"file": (filename, f, mime_type)}
            )
            
        assert res_upload.status_code == 200, f"Upload failed for {filename}"
        upload_data = res_upload.json()
        print(f"Upload Success: {upload_data}")
        batch_id = upload_data["batch_id"]
        batch_ids[filename] = batch_id
        uploaded_file_path = upload_data["file_path"]
        
        # B. Start Pipeline
        res_start = client.post(
            "/api/v1/pipeline/start",
            json={"file_path": uploaded_file_path, "batch_id": batch_id, "metadata": {"preserve_cleaned_dir": True}}
        )
        
        assert res_start.status_code == 200, f"Pipeline start failed for {filename}"
        start_data = res_start.json()
        print(f"Pipeline started successfully: {start_data}")
        pipeline_id = start_data["pipeline_id"]
        
        # C. Check Pipeline Status (wait until not Running)
        timeout = 10
        status_data = {}
        while timeout > 0:
            res_status = client.get(f"/api/v1/pipeline/status?pipeline_id={pipeline_id}")
            assert res_status.status_code == 200
            status_data = res_status.json()
            if status_data['status'] in ["Success", "Passed with Warnings", "Failed"]:
                break
            time.sleep(1)
            timeout -= 1

        print(f"Pipeline Execution Finished. Status: {status_data['status']}")
        print(f"Execution Duration: {status_data.get('execution_time', 0.0):.2f}s")
        print("Execution Steps Log:")
        for log in status_data.get("logs", []):
            print(f"  * {log}")
            
    # 4. Verify Reports Generation on Disk in Dedicated Dataset Folders with strictly 4 Formats
    print("\n--- Verifying Dedicated Reports Folders & Strictly 4 Formats ---")
    
    for filename, bid in batch_ids.items():
        dataset_report_dir = os.path.join("reports", filename)
        assert os.path.exists(dataset_report_dir), f"Dedicated report directory for dataset '{filename}' not found at {dataset_report_dir}!"
        
        files_in_dir = os.listdir(dataset_report_dir)
        print(f"Files in reports/{filename}/: {files_in_dir}")
        
        # Check presence of all 4 formats: JSON, Word (docx), Markdown (md), PDF
        has_json = any(f.endswith(".json") for f in files_in_dir)
        has_docx = any(f.endswith(".docx") for f in files_in_dir)
        has_md = any(f.endswith(".md") for f in files_in_dir)
        has_pdf = any(f.endswith(".pdf") for f in files_in_dir)
        has_txt = any(f.endswith(".txt") for f in files_in_dir)
        
        assert has_json, f"Missing JSON report in {dataset_report_dir}!"
        assert has_docx, f"Missing Word (DOCX) report in {dataset_report_dir}!"
        assert has_md, f"Missing Markdown (MD) report in {dataset_report_dir}!"
        assert has_pdf, f"Missing PDF report in {dataset_report_dir}!"
        assert not has_txt, f"Extraneous .txt report found in {dataset_report_dir}! Strictly only 4 formats allowed."

    # 4b. Verify Clean Datasets on Disk
    print("\n--- Verifying Clean Datasets Storage ---")
    clean_files = os.listdir("cleaned data")
    print(f"Clean Storage contains: {clean_files}")
    
    assert any("sales" in f for f in clean_files), "Sales clean dataset was not stored in cleaned data/ folder!"
    assert any("customers" in f for f in clean_files), "Customers clean dataset was not stored in cleaned data/ folder!"
    assert any("orders" in f for f in clean_files), "Orders clean dataset was not stored in cleaned data/ folder!"
    assert all(f.endswith((".csv", ".tsv", ".json", ".xml", ".xlsx", ".sql", ".docx")) for f in clean_files), "Extraneous non-dataset files found in cleaned data/ folder!"

    # 5. Verify API Dashboards Summary and Folders API
    print("\n--- Verifying Dashboard Analytics & Reports Folders API ---")
    res_dash = client.get("/api/v1/dashboard/summary")
    assert res_dash.status_code == 200
    dash_data = res_dash.json()
    print(f"Aggregated Dashboard Data: {json.dumps(dash_data, indent=2)}")
    
    res_folders = client.get("/api/v1/reports/folders")
    assert res_folders.status_code == 200
    folders_data = res_folders.json()
    print(f"Reports Folders API Response: {json.dumps(folders_data, indent=2)}")
    assert len(folders_data) > 0, "No folders returned from reports/folders API!"
    assert "pdf" in folders_data[0]["formats"]
    assert "docx" in folders_data[0]["formats"]
    assert "markdown" in folders_data[0]["formats"]
    assert "json" in folders_data[0]["formats"]
    
    # 6. Verify Responsive AI Chat Assistant
    print("\n--- Testing Responsive AI Chat Assistant Queries ---")
    sales_batch_id = batch_ids["sales_dirty.csv"]
    
    # Test A: Math query
    res_math = client.post("/api/v1/agent/chat", json={"message": "what is 25 * 4?"})
    assert res_math.status_code == 200
    math_reply = res_math.json()["response"]
    print(f"Chat Math Query Response:\n{math_reply}\n")
    assert "100" in math_reply, "Math query failed to calculate correctly!"
    
    # Test B: Root cause / Rejections query
    chat_payload = {
        "message": "Why were records rejected during validation?",
        "batch_id": sales_batch_id
    }
    res_chat = client.post("/api/v1/agent/chat", json=chat_payload)
    assert res_chat.status_code == 200
    chat_data = res_chat.json()
    print(f"AI Assistant RCA Response (Confidence={chat_data['confidence']}%):")
    print(chat_data["response"])
    assert "root cause" in chat_data["response"].lower() or "validation" in chat_data["response"].lower() or "finding" in chat_data["response"].lower()
    
    # Test C: Transformations query
    res_trans = client.post("/api/v1/agent/chat", json={"message": "What transformations were applied to this dataset?", "batch_id": sales_batch_id})
    assert res_trans.status_code == 200
    trans_reply = res_trans.json()["response"]
    print(f"Chat Transformations Response:\n{trans_reply}\n")
    assert "transformation" in trans_reply.lower() or "cleansing" in trans_reply.lower() or "snake_case" in trans_reply.lower()
    
    # Test D: Schema query
    res_schema = client.post("/api/v1/agent/chat", json={"message": "Explain the columns and schema data types", "batch_id": sales_batch_id})
    assert res_schema.status_code == 200
    schema_reply = res_schema.json()["response"]
    print(f"Chat Schema Response:\n{schema_reply}\n")
    assert "schema" in schema_reply.lower() or "column" in schema_reply.lower()
    
    # Test E: SQL query generation
    res_sql = client.post("/api/v1/agent/chat", json={"message": "Generate SQL queries for staging and production tables", "batch_id": sales_batch_id})
    assert res_sql.status_code == 200
    sql_reply = res_sql.json()["response"]
    print(f"Chat SQL Response:\n{sql_reply}\n")
    assert "SELECT" in sql_reply or "staging" in sql_reply.lower()
    
    # Test F: Explicit file download query
    log_chat_payload = {
        "message": 'Please send me the download link for cleaned data/clean_dataset.csv',
        "batch_id": sales_batch_id
    }
    res_log_chat = client.post("/api/v1/agent/chat", json=log_chat_payload)
    assert res_log_chat.status_code == 200
    log_chat_data = res_log_chat.json()
    print("AI Assistant Response to download request:")
    print(log_chat_data["response"])
    
    # 7. Cleanup E2E Test data from database and filesystem
    print("\n--- Cleaning up E2E Test batch data and files ---")
    from sqlalchemy.orm import sessionmaker
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    try:
        from sqlalchemy import text
        bids = list(batch_ids.values())
        if bids:
            bids_str = ", ".join(f"'{b}'" for b in bids)
            pids = [f"pipe_{b}" for b in bids]
            pids_str = ", ".join(f"'{p}'" for p in pids)
            
            # Clean up production tables (respecting FK constraints: sales -> orders -> customers)
            db.execute(text(f"DELETE FROM sales WHERE sale_id IN (SELECT sale_id FROM staging_sales WHERE batch_id IN ({bids_str}))"))
            db.execute(text(f"DELETE FROM orders WHERE order_id IN (SELECT order_id FROM staging_orders WHERE batch_id IN ({bids_str}))"))
            db.execute(text(f"DELETE FROM customers WHERE customer_id IN (SELECT customer_id FROM staging_customers WHERE batch_id IN ({bids_str}))"))
            
            # Clean up staging tables
            db.execute(text(f"DELETE FROM staging_customers WHERE batch_id IN ({bids_str})"))
            db.execute(text(f"DELETE FROM staging_orders WHERE batch_id IN ({bids_str})"))
            db.execute(text(f"DELETE FROM staging_sales WHERE batch_id IN ({bids_str})"))
            
            # Clean up other metadata tables
            db.execute(text(f"DELETE FROM raw_uploads WHERE batch_id IN ({bids_str})"))
            db.execute(text(f"DELETE FROM generated_reports WHERE batch_id IN ({bids_str})"))
            db.execute(text(f"DELETE FROM pipeline_logs WHERE pipeline_id IN ({pids_str})"))
            db.execute(text(f"DELETE FROM agent_logs WHERE batch_id IN ({bids_str})"))
            db.execute(text(f"DELETE FROM quality_reports WHERE batch_id IN ({bids_str})"))
            db.execute(text(f"DELETE FROM root_cause_reports WHERE batch_id IN ({bids_str})"))
            db.execute(text(f"DELETE FROM transformation_logs WHERE batch_id IN ({bids_str})"))
            db.execute(text(f"DELETE FROM validation_logs WHERE batch_id IN ({bids_str})"))
            db.commit()
            print("Database records for E2E test runs deleted successfully.")
    except Exception as e:
        db.rollback()
        print(f"Error cleaning database test data: {e}")
    finally:
        db.close()

    # Cleanup generated files
    for filename, bid in batch_ids.items():
        # Delete raw file
        raw_p = os.path.join("data/raw", filename)
        if os.path.exists(raw_p):
            os.remove(raw_p)
        
        # Delete cleaned file
        clean_p = os.path.join("cleaned data", filename)
        if os.path.exists(clean_p):
            os.remove(clean_p)
            
        # Delete logs file
        log_p = os.path.join("logs", f"{bid}.log")
        if os.path.exists(log_p):
            os.remove(log_p)
            
        # Delete reports directory
        report_dir = os.path.join("reports", filename)
        if os.path.exists(report_dir):
            shutil.rmtree(report_dir, ignore_errors=True)
            
    print("Filesystem cleanup for E2E test runs completed.")
    
    print("\n=== E2E PIPELINE RUN COMPLETED SUCCESSFULLY! ===")


if __name__ == "__main__":
    run_e2e_test()
