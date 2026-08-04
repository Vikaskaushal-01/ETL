import os
import sys
import json

sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

from backend.utils.file_utils import clear_logs_folder, clear_cleaned_data_folder
from agents.transformation_agent.transformation_agent import TransformationAgent
from backend.api.pipeline import save_pipeline_logs_to_file

def test_per_process_logs_management():
    print("=== TESTING PER-PROCESS LOG MANAGEMENT ===")
    
    # 1. Clear logs folder first
    clear_logs_folder("logs")
    print(f"Cleared 'logs/' directory. Current contents: {os.listdir('logs')}")
    assert len(os.listdir("logs")) == 0, "logs directory should be empty initially"

    # 2. Simulate pipeline execution logs for user uploaded file
    raw_filename = "data-cleaning-challenge-json-txt-and-xls (1).ipynb"
    raw_file_path = os.path.join("data", "raw", raw_filename)
    batch_id = "batch_bec13617"
    
    sample_logs = [
        f"Pipeline initialized. Batch ID: {batch_id}.",
        "[Data Intake Agent] Validated and profiled raw dataset.",
        "[Transformation Agent] Cleansed dataset. Quality improved to 100.0%.",
        "[Intelligent Storage Agent] Intelligently formatted and stored dataset.",
        "[Report Generation Agent] PDF report generated successfully."
    ]
    
    # 3. Save logs to disk with filename
    save_pipeline_logs_to_file(batch_id, sample_logs, raw_file_path=raw_file_path)
    
    # 4. Verify log files created in logs/
    logs_files = os.listdir("logs")
    print(f"\nFiles created in logs/ directory: {logs_files}")
    
    expected_log_filename = f"{raw_filename}.log"
    assert expected_log_filename in logs_files, f"Expected log file '{expected_log_filename}' in logs/, found: {logs_files}"
    
    # Read log file contents
    file_log_path = os.path.join("logs", expected_log_filename)
    with open(file_log_path, "r", encoding="utf-8") as lf:
        log_content = lf.read()
        
    print(f"\nLog File Content ({expected_log_filename}):")
    print(log_content)
    
    assert f"Batch ID: {batch_id}" in log_content, "Log content missing batch ID!"
    assert "[Transformation Agent]" in log_content, "Log content missing transformation agent log!"
    
    print("\n=== PER-PROCESS LOG MANAGEMENT SUCCESSFUL! ===")

if __name__ == "__main__":
    test_per_process_logs_management()
