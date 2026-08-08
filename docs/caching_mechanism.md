# Pipeline Caching & Backup Mechanism

To optimize performance and enable resilient recovery, the ETL engine implements a localized caching mechanism that records execution metadata and report paths of the last successful run.

---

## The Cache Store

When a pipeline execution finishes successfully, its final execution state is serialized to a JSON payload and written to `.last_cleaned_backup.json` in the project root:

- **Path**: `PROJECT_ROOT/.last_cleaned_backup.json`
- **Updated on**: Complete success of all pipeline stages (Intake -> Transformation -> Storage -> Reporting -> Power BI Gateway sync).

---

## Schema Structure

The cache store contains the following metadata:

1. **`batch_id`** (`string`)
   - The unique UUID/hash assigned to the execution batch.
2. **`filename`** (`string`)
   - The name of the file parsed during the execution run.
3. **`timestamp`** (`float`)
   - Epoch timestamp recording the completion time.
4. **`quality_score`** (`float`)
   - The final estimated quality score of the processed dataset.
5. **`logs`** (`string`)
   - A aggregated log block tracking messages from all agent stages.
6. **`reports`** (`object`)
   - Key-value pairs mapping document formats to their absolute paths on disk:
     - `pdf_path`
     - `docx_path`
     - `txt_path`
     - `markdown_path`
     - `json_path`

---

## Usage Patterns in the Platform

1. **Chatbot Retrieval**
   - When users query the chatbot about the "last cleaned run" or "recent logs", the chatbot engine reads from `.last_cleaned_backup.json` instead of executing heavy database queries.
2. **Reports Exporter**
   - The API endpoints use the report paths cached in the backup file to instantly serve files for download when users request reports.
3. **State Resiliency**
   - Serves as an offline local checkpoint of the latest operational execution if database connections are temporarily interrupted.
