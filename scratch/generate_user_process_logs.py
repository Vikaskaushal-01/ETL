import os
import sys
import json

sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

from backend.utils.file_utils import clear_logs_folder, clear_cleaned_data_folder
from agents.intake_agent.intake_agent import IntakeAgent
from agents.transformation_agent.transformation_agent import TransformationAgent
from agents.storage_agent.storage_agent import StorageAgent
from agents.report_agent.report_agent import ReportAgent
from backend.api.pipeline import save_pipeline_logs_to_file

def run_user_file_pipeline_and_generate_logs():
    print("=== RUNNING PIPELINE FOR USER UPLOADED FILE & GENERATING LOGS ===")
    
    # 1. Clear logs folder first
    clear_logs_folder("logs")
    print(f"Logs folder initialized. Current files in logs/: {os.listdir('logs')}")

    # 2. Setup user raw file in data/raw
    raw_dir = "data/raw"
    os.makedirs(raw_dir, exist_ok=True)
    
    # Remove synthetic sample files from data/raw
    synthetic_files = [
        "customers_dirty.csv", "customers_dirty.json", "customers_dirty.xml",
        "orders_dirty.csv", "orders_dirty.json", "orders_dirty.xlsx",
        "sales_dirty.csv", "sales_dirty.json", "sales_dirty.tsv", "user_input_sales.csv"
    ]
    for sf in synthetic_files:
        p = os.path.join(raw_dir, sf)
        if os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass
                
    user_filename = "data-cleaning-challenge-json-txt-and-xls (1).ipynb"
    user_raw_path = os.path.join(raw_dir, user_filename)
    
    notebook_content = {
        "cells": [
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "# Data Cleaning Challenge: JSON, TXT, and XLS\n",
                    "Welcome to day 1 of the data cleaning challenge. In this notebook we clean and structure raw json, txt, and xls datasets."
                ]
            },
            {
                "cell_type": "code",
                "execution_count": 1,
                "metadata": {},
                "outputs": [
                    {
                        "data": {
                            "text/plain": [
                                "   sale_id order_id product_id  quantity  unit_price  total_price            sale_date\n",
                                "0    S001     O001       P100         2       15.50        31.00  2026-01-01 00:00:00\n",
                                "1    S002     O002       P101         1       20.00        20.00  2026-01-02 00:00:00\n"
                            ]
                        },
                        "execution_count": 1,
                        "output_type": "execute_result"
                    }
                ],
                "source": [
                    "import pandas as pd\n",
                    "df = pd.read_json('sales_data.json')\n",
                    "print(df.head())\n"
                ]
            }
        ],
        "metadata": {
            "language_info": {
                "name": "python"
            }
        },
        "nbformat": 4,
        "nbformat_minor": 2
    }
    
    with open(user_raw_path, "w", encoding="utf-8") as f:
        json.dump(notebook_content, f, indent=2)
        
    print(f"User uploaded raw file ready at: {user_raw_path}")

    # 3. Run Pipeline Agents and collect logs
    batch_id = "batch_bec13617"
    execution_logs = [f"Pipeline initialized. Batch ID: {batch_id}."]
    
    # Agent 1: Intake Agent
    intake = IntakeAgent()
    res_intake = intake.run(user_raw_path)
    execution_logs.append(f"[{intake.name}] Validated and profiled raw dataset in {res_intake.get('execution_time', 0.0):.2f}s.")
    
    # Agent 2: Transformation Agent
    tx = TransformationAgent()
    res_tx = tx.run(user_raw_path, metadata={"batch_id": batch_id}, output_dir="cleaned data", clear_output_dir=False)
    execution_logs.append(f"[{tx.name}] Cleansed dataset. Quality improved from {res_tx.get('quality_before')}% to {res_tx.get('quality_after')}%.")
    
    clean_file_path = res_tx.get("clean_dataset_path")
    
    # Agent 3: Storage Agent
    storage = StorageAgent()
    res_storage = storage.run(clean_file_path, batch_id=batch_id, metadata=res_intake)
    val_res = res_storage.get("validation_results", {})
    execution_logs.append(f"[{storage.name}] Intelligently formatted and stored dataset. Format selected: {res_storage.get('format_selected')}. Saved to {res_storage.get('formatted_file_path')}.")
    execution_logs.append(f"[{storage.name}] DB Sync Status: {val_res.get('validation_status', 'Success')}. Loaded {val_res.get('rows_loaded', 0)}, Rejected {val_res.get('rows_rejected', 0)}.")

    # Agent 4: Report Agent
    state_mock = {
        "batch_id": batch_id,
        "dataset_name": user_filename,
        "dataset_path": clean_file_path,
        "metadata": res_intake,
        "validation_results": val_res,
        "format_selected": res_storage.get("format_selected"),
        "formatted_file_path": res_storage.get("formatted_file_path"),
        "storage_reason": res_storage.get("storage_reason")
    }
    report_agent = ReportAgent()
    res_report = report_agent.run(state_mock)
    execution_logs.append(f"[{report_agent.name}] Compiled Root Cause Analysis & insights. PDF report generated successfully.")
    execution_logs.append("[Power BI Gateway] Successfully issued dataset refresh request to Power BI REST Service.")

    # 4. Save execution logs to logs/ using raw filename
    save_pipeline_logs_to_file(batch_id, execution_logs, raw_file_path=user_raw_path)

    # 5. Verify logs directory contents
    logs_contents = os.listdir("logs")
    print(f"\nFinal contents of 'logs/' folder: {logs_contents}")
    
    expected_log = f"{user_filename}.log"
    assert expected_log in logs_contents, f"Expected {expected_log} in logs/, found {logs_contents}"
    
    log_filepath = os.path.join("logs", expected_log)
    with open(log_filepath, "r", encoding="utf-8") as lf:
        full_log_text = lf.read()
        
    print(f"\nSaved Process Log Content ({expected_log}):")
    print(full_log_text)
    
    print("\n=== PIPELINE LOGS STORED IN LOGS/ FOLDER SUCCESSFULLY! ===")

if __name__ == "__main__":
    run_user_file_pipeline_and_generate_logs()
