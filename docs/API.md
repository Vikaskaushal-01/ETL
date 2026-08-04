# API Gateway Documentation

The backend API gateway is built with **FastAPI** and is exposed at `http://localhost:8000`. 
Base endpoint path: `/api/v1`

---

## 1. Endpoints List

### File Ingestion
- **POST** `/upload`
  - **Description**: Upload a raw dataset (CSV, Excel, JSON, XML, TSV) to store under `/data/raw`.
  - **Payload**: Multipart Form-Data with key `file`.
  - **Response**:
    ```json
    {
      "status": "Success",
      "upload_id": 1,
      "batch_id": "batch_8673a2",
      "filename": "8673a2_sales.csv",
      "file_path": "data/raw/8673a2_sales.csv"
    }
    ```

---

### Pipeline Orchestration
- **POST** `/pipeline/start`
  - **Description**: Trigger the LangGraph multi-agent ETL workflow asynchronously.
  - **Payload (JSON)**:
    ```json
    {
      "file_path": "data/raw/8673a2_sales.csv",
      "batch_id": "batch_8673a2"
    }
    ```
  - **Response**:
    ```json
    {
      "pipeline_id": "pipe_batch_8673a2",
      "status": "Running",
      "batch_id": "batch_8673a2",
      "dataset_name": "sales.csv"
    }
    ```

- **GET** `/pipeline/status`
  - **Description**: Monitor a pipeline execution run, view active steps, and check logs.
  - **Query Params**: `pipeline_id`
  - **Response**:
    ```json
    {
      "pipeline_id": "pipe_batch_8673a2",
      "status": "Success",
      "start_time": "2026-07-26T11:00:00",
      "end_time": "2026-07-26T11:00:12",
      "execution_time": 12.4,
      "logs": [
        "[Data Intake Agent] Completed initial dataset profiling in 1.25s.",
        "[Transformation Agent] Cleansed dataset. Data Quality Score improved from 85% to 100%.",
        "[Validation & Load Agent] Verified constraints. Status: Success. Loaded=996, Rejected=4."
      ]
    }
    ```

---

### Analytics & Logging
- **GET** `/logs`
  - **Description**: Retrieve execution audit steps for all runs or a specific batch.
  - **Query Params**: `batch_id` (optional)

- **GET** `/root-cause`
  - **Description**: Fetch AI-generated Root Cause Analysis (RCA) records.
  - **Query Params**: `batch_id` (optional)

- **GET** `/data-quality`
  - **Description**: Fetch calculated data quality and assessment scores.
  - **Query Params**: `batch_id` (optional)

---

### Reports Download
- **GET** `/reports/history`
  - **Description**: List all generated executive analysis documents.
  - **Response**: List of report summaries.

- **GET** `/reports/latest`
  - **Description**: Direct download endpoint of the latest generated document.
  - **Query Params**: `format` (`pdf`, `docx`, `markdown`, `json`)

- **GET** `/reports/download/{batch_id}`
  - **Description**: Download the report corresponding to a specific batch run.
  - **Query Params**: `format` (`pdf`, `docx`, `markdown`, `json`)

---

### Interactive Support Chat
- **POST** `/agent/chat`
  - **Description**: Ask questions regarding data transformations, failures, or metrics.
  - **Payload (JSON)**:
    ```json
    {
      "message": "Why were 4 records rejected in the last run?",
      "batch_id": "batch_8673a2"
    }
    ```
  - **Response**:
    ```json
    {
      "response": "The 4 records were rejected because the customer_id was NULL, violating primary key constraints in the database.",
      "agent_name": "ETL Chat Support Agent",
      "confidence": 98.0
    }
    ```
