# Production Operations & Disaster Recovery Runbook

This runbook provides step-by-step procedures for operating, troubleshooting, and recovering the **Intelligent Autonomous Agentic AI ETL Platform**.

---

## 1. System Health Monitoring & Diagnostics

### Key Health Checks
- **FastAPI Backend Health**: `GET /api/v1/health`
  - Healthy response: `{"status": "Healthy", "database": "Healthy"}`
- **Power BI Connectivity**: `GET /api/v1/powerbi/status`
- **Database Latency**: Evaluated automatically on every health query.

### Diagnostic Commands
```bash
# Verify all multi-container services
docker-compose ps

# Check backend container logs
docker-compose logs -f etl_backend

# Check MySQL database connection
mysql -h localhost -u etl_user -p agentic_ai_etl -e "SELECT COUNT(*) FROM raw_uploads;"
```

---

## 2. Standard Operating Procedures (SOPs)

### SOP-01: Manual Power BI Refresh Trigger
1. Open the web dashboard at `http://localhost:8000/`.
2. Click the **Power BI Integration** drawer button in the top navigation bar.
3. Click **Trigger Dataset Refresh**.
4. Confirm success notification and check the console logs drawer for timestamp confirmation.

### SOP-02: Offline Verification & Simulation Test
When deploying to air-gapped or offline development environments:
```bash
# 1. Generate realistic mock datasets
python generate_sample_data.py

# 2. Run offline end-to-end integration test runner
python verify_pipeline.py

# 3. Verify clean dataset outputs in ./cleaned data/
ls "cleaned data"
```

---

## 3. Incident Management & Recovery

### Incident 1: Database Connection Timeout / Disconnection
- **Symptom**: `MySQL connection failed: Connection timed out`.
- **Automatic Fallback**: The backend automatically falls back to local SQLite embedded storage (`agentic_ai_etl.db`) with WAL mode enabled.
- **Remediation**:
  1. Inspect `MYSQL_HOST` and `MYSQL_PORT` in `.env`.
  2. If using Docker: `docker-compose restart etl_mysql`.
  3. Run `python verify_pipeline.py` to confirm connection restoration.

### Incident 2: Gemini API Rate Limit / Quota Exceeded (429 / 404)
- **Symptom**: `Error calling model 'gemini'`.
- **Automatic Fallback**: The platform invokes the deterministic programmatic heuristics engine to perform schema profiling, median imputation, and report compilation without downtime.
- **Remediation**:
  1. Verify `GEMINI_API_KEY` in `.env`.
  2. If running Ollama locally: ensure `http://localhost:11434` is active.

### Incident 3: Corrupt or Stale Pipeline State
- **Remediation**:
  ```bash
  # Execute full clean reset script
  python cleanup_all.py
  ```

---

## 4. Backup & Disaster Recovery (DR)
- **Automated State Backups**: `.last_cleaned_backup.json` automatically snapshots the latest valid pipeline batch state.
- **MySQL Nightly Dump**:
  ```bash
  mysqldump -u etl_user -p agentic_ai_etl > "backup_$(date +%Y%m%d).sql"
  ```
- **Storage Volume Retention**:
  - `data/raw/`: 30-day retention.
  - `cleaned data/`: 60-day retention.
  - `reports/`: Permanent audit archive.
