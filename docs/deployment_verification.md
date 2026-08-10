# Deployment & Pipeline Verification Guide

This document describes the utilities and workflows available to verify deployment sanity, run end-to-end (E2E) automated pipeline checks, and clean the local workspace.

---

## 1. Workspace Cleanup & Reset

To restore the development environment to a pristine state, use the `cleanup_all.py` script. 

### What it does:
1. **Directory Clearance**:
   - Completely clears files under `data/raw`, `cleaned data`, `reports`, and `logs`.
   - Removes deprecated folders (e.g., `data/csv`, `data/word`, `data/sql`, `data/processed`).
2. **Database Reset**:
   - Executes SQLAlchemy metadata drops (`Base.metadata.drop_all`) to clear tables.
   - Recreates empty tables with the correct target database models (`Base.metadata.create_all`).

### Command:
```powershell
python cleanup_all.py
```

---

## 2. End-to-End Pipeline Verification

To ensure that all FastAPI routes, agent logic, database loading, and chat systems are running correctly, run the `verify_pipeline.py` script.

### What it does:
1. Runs the workspace cleanup routine.
2. Invokes `generate_sample_data.py` to write raw dirty test files in multiple formats (CSV, TSV, JSON, XML, XLSX).
3. Spins up a FastAPI `TestClient` to run mock integrations:
   - **Upload**: Uploads each dirty file and checks that a unique `batch_id` is assigned.
   - **Pipeline Execution**: Requests `POST /api/v1/pipeline/start` to run Intake, Transformation, and Validation agents.
   - **Status Polling**: Checks status until it marks execution as complete.
   - **Database Load Check**: Verifies that cleaned rows match expected thresholds and duplicates are dropped.
   - **Report Check**: Assures PDF, DOCX, TXT, MD, and JSON reports are compiled.
   - **Chat Assistant Query Check**: Asserts the Chatbot can load conversation history and retrieve specific run summaries by ID.

### Command:
```powershell
python verify_pipeline.py
```

---

## Technical Details

- **Cleanup Script**: `cleanup_all.py` in [cleanup_all.py](file:///c:/Users/User/Documents/ETL-A/cleanup_all.py)
- **E2E Tester**: `verify_pipeline.py` in [verify_pipeline.py](file:///c:/Users/User/Documents/ETL-A/verify_pipeline.py)
- **Data Generator**: `generate_sample_data.py` in [generate_sample_data.py](file:///c:/Users/User/Documents/ETL-A/generate_sample_data.py)
