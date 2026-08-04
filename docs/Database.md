# Database Design Documentation

This document describes the schema design for the **agentic_ai_etl** MySQL database.

---

## 1. Schema Tables Overview

The schema is divided into three key boundaries: Ingestion logs, Staging tables, and Production tables.

```text
  Raw Uploads ---> Staging Tables (staging_*) ---> Production Tables (sales, customers, orders)
                          |
                          v
                    Validation Logs
```

---

## 2. Table Schemas

### 1. `raw_uploads`
Stores metadata about uploaded files.
- `id` (INT, AUTO_INCREMENT, PK)
- `filename` (VARCHAR(255))
- `source` (VARCHAR(100)): e.g. "API_Upload", "SnapLogic_Inbound"
- `file_type` (VARCHAR(50)): e.g. "csv", "xlsx", "json"
- `upload_time` (TIMESTAMP)
- `status` (VARCHAR(50)): "Pending", "Running", "Success", "Failed"

### 2. `customers` (Production)
Defines primary customer entities.
- `customer_id` (VARCHAR(100), PK)
- `customer_name` (VARCHAR(255))
- `email` (VARCHAR(255))
- `phone` (VARCHAR(50))
- `region` (VARCHAR(100))
- `created_at` / `updated_at` (TIMESTAMP)

### 3. `staging_customers` (Staging)
Replicates customers structure without primary key locks to facilitate staging validation.
- `customer_id` (VARCHAR(100))
- `customer_name` (VARCHAR(255))
- `email` (VARCHAR(255))
- `phone` (VARCHAR(50))
- `region` (VARCHAR(100))
- `batch_id` (VARCHAR(100))
- `row_number` (INT)
- `validation_status` (VARCHAR(50)): "Valid", "Rejected"

### 4. `orders` (Production)
Customer orders.
- `order_id` (VARCHAR(100), PK)
- `customer_id` (VARCHAR(100), FK to customers)
- `order_date` (DATETIME)
- `status` (VARCHAR(50))
- `total_amount` (DECIMAL(15, 2))

### 5. `sales` (Production)
Order item sales transactions.
- `sale_id` (VARCHAR(100), PK)
- `order_id` (VARCHAR(100), FK to orders)
- `product_id` (VARCHAR(100))
- `quantity` (INT)
- `unit_price` (DECIMAL(15, 2))
- `total_price` (DECIMAL(15, 2))
- `sale_date` (DATETIME)

---

## 3. Logs & Analytics Tables

- **`transformation_logs`**: Tracks column cleaning operations. Columns: `batch_id`, `agent_name`, `column_name`, `old_value`, `new_value`, `reason`, `timestamp`.
- **`validation_logs`**: Logs step-by-step loading validation records. Columns: `batch_id`, `validation_type`, `status`, `message`.
- **`pipeline_logs`**: Aggregates job run durations. Columns: `pipeline_id`, `start_time`, `end_time`, `execution_time`, `status`.
- **`agent_logs`**: Audits agent thoughts and confidence. Columns: `batch_id`, `agent_name`, `task`, `reasoning`, `confidence`, `execution_time`.
- **`quality_reports`**: Completeness metrics. Columns: `batch_id`, `missing_values`, `duplicate_count`, `quality_score`, `schema_match`.
- **`root_cause_reports`**: AI-generated error diagnostic summaries. Columns: `batch_id`, `issue`, `root_cause`, `business_impact`, `technical_impact`, `recommendation`, `confidence`.
- **`generated_reports`**: Maps paths to generated PDF/DOCX summaries. Columns: `batch_id`, `pdf_path`, `docx_path`, `json_path`, `markdown_path`.
