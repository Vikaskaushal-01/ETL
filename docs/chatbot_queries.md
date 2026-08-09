# Chatbot & Query Engine Architecture

The platform includes a context-aware chat assistant that serves as an interactive CLI and troubleshooting portal. It allows users to query pipeline logs, database tables, and run-time metadata.

---

## Capabilities

1. **System Troubleshooting Support**
   - Integrates a reference guide covering typical failures, including:
     - Live console/terminal log errors.
     - Staging, database load, and SQL sync errors.
     - File system permissions, locks, and ingestion configuration issues.
     - SnapLogic integration and Docker container network settings.

2. **Run Log Extraction**
   - Automatically detects and parses 8-character hex codes or UUIDs representing batch IDs (e.g., `batch_a02167fc`) from user queries.
   - Searches for logs using a tiered retrieval approach:
     1. Stored records in the database.
     2. Metadata in the `.last_cleaned_backup.json` cache.
     3. Raw logs stored under `logs/batch_<id>.log`.

3. **In-Database Query Parsing (SQL Agent)**
   - Allows users to search the staging and target tables using natural language.
   - Generates and runs read-only SQL queries on the active database connection to retrieve metrics (e.g., row counts, top records, rejected rows).

4. **Multi-Turn Dialogue Session**
   - Supports keeping track of conversation history in backend payload schemas, letting users follow up on previous answers.

---

## Technical Details

- **Module**: `backend.api.chat` in [chat.py](file:///c:/Users/User/Documents/ETL-A/backend/api/chat.py)
- **FastAPI Endpoints**:
  - `POST /agent/chat` - Main conversational endpoint accepting `ChatRequest` and returning `ChatResponse`.

### Request Schema
```json
{
  "message": "Can you check the logs for batch_a02167fc?",
  "history": [
    {"role": "user", "message": "Hi"},
    {"role": "assistant", "message": "Hello, how can I assist you with the ETL pipeline?"}
  ],
  "batch_id": "batch_a02167fc"
}
```
