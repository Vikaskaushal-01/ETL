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
            
    # 4. Verify Reports Generation on Disk
    print("\n--- Verifying Generated Documents ---")
    pdf_files = []
    docx_files = []
    md_files = []
    json_files = []
    
    for root, dirs, filenames in os.walk("reports"):
        for f in filenames:
            if f.endswith(".pdf"):
                pdf_files.append(os.path.join(root, f))
            elif f.endswith(".docx"):
                docx_files.append(os.path.join(root, f))
            elif f.endswith(".md"):
                md_files.append(os.path.join(root, f))
            elif f.endswith(".json"):
                json_files.append(os.path.join(root, f))
    
    print(f"Generated PDF files in reports/ structure: {pdf_files}")
    print(f"Generated Word (DOCX) files in reports/ structure: {docx_files}")
    print(f"Generated Markdown files in reports/ structure: {md_files}")
    print(f"Generated JSON files in reports/ structure: {json_files}")
    
    assert len(pdf_files) > 0, "No PDF reports were generated!"
    assert len(docx_files) > 0, "No Word (DOCX) reports were generated!"
    assert len(md_files) > 0, "No Markdown reports were generated!"
    assert len(json_files) > 0, "No JSON reports were generated!"

    # 4b. Verify Clean Datasets on Disk
    print("\n--- Verifying Clean Datasets Storage ---")
    clean_files = os.listdir("cleaned data")
    print(f"Clean Storage contains: {clean_files}")
    
    assert any("sales" in f for f in clean_files), "Sales clean dataset was not stored in cleaned data/ folder!"
    assert any("customers" in f for f in clean_files), "Customers clean dataset was not stored in cleaned data/ folder!"
    assert any("orders" in f for f in clean_files), "Orders clean dataset was not stored in cleaned data/ folder!"
    assert all(f.endswith((".csv", ".tsv", ".json", ".xml", ".xlsx", ".sql", ".docx")) for f in clean_files), "Extraneous non-dataset files found in cleaned data/ folder!"

    # 5. Verify API Dashboards Summary
    print("\n--- Verifying Dashboard Analytics ---")
    res_dash = client.get("/api/v1/dashboard/summary")
    assert res_dash.status_code == 200
    dash_data = res_dash.json()
    print(f"Aggregated Dashboard Data: {json.dumps(dash_data, indent=2)}")
    
    # 6. Verify AI Chat Assistant querying the validation failures
    print("\n--- Querying AI Chat Assistant ---")
    sales_batch_id = batch_ids["sales_dirty.csv"]
    chat_payload = {
        "message": "Explain the root causes and recommendations for any rejected records in this batch.",
        "batch_id": sales_batch_id
    }
    res_chat = client.post("/api/v1/agent/chat", json=chat_payload)
    assert res_chat.status_code == 200
    chat_data = res_chat.json()
    print(f"AI Assistant Response (Confidence={chat_data['confidence']}%):")
    print(chat_data["response"])
    
    # 6b. Verify AI Chat Assistant when user shares a log that refers to clean_dataset.csv
    print("\n--- Querying AI Chat Assistant with logs reference ---")
    log_chat_payload = {
        "message": 'Here is my cleaning log: {"transformation_steps": [], "clean_dataset_path": "cleaned data/clean_dataset.csv"}. Please send me the file.',
        "batch_id": None
    }
    res_log_chat = client.post("/api/v1/agent/chat", json=log_chat_payload)
    assert res_log_chat.status_code == 200
    log_chat_data = res_log_chat.json()
    print("AI Assistant Response to logs query:")
    print(log_chat_data["response"])
    
    # 6c. Verify AI Chat Assistant process logs direct regeneration
    print("\n--- Querying AI Chat Assistant to access process logs directly and regenerate report ---")
    regen_payload = {
        "message": f"I want you to access the process logs directly for batch {sales_batch_id} and regenerate the previous document",
        "batch_id": sales_batch_id
    }
    res_regen = client.post("/api/v1/agent/chat", json=regen_payload)
    assert res_regen.status_code == 200
    regen_data = res_regen.json()
    print("AI Assistant Response to regeneration query:")
    print(regen_data["response"])
    assert "regeneration successful" in regen_data["response"].lower() or "regenerated" in regen_data["response"].lower()
    
    # 6d. Verify AI Chat Assistant process logs retrieval
    print("\n--- Querying AI Chat Assistant regarding process logs retrieval ---")
    logs_query_payload = {
        "message": f"Show me the process logs for batch {sales_batch_id}",
        "batch_id": sales_batch_id
    }
    res_logs_query = client.post("/api/v1/agent/chat", json=logs_query_payload)
    assert res_logs_query.status_code == 200
    logs_query_data = res_logs_query.json()
    print("AI Assistant Response to logs query:")
    print(logs_query_data["response"])
    assert "process logs" in logs_query_data["response"].lower() or "log" in logs_query_data["response"].lower()
    
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
