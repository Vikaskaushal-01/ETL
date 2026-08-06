# Data Intake Agent

The **Data Intake Agent** is responsible for the ingestion, parsing, and structural analysis of incoming datasets. It acts as the first line of processing in the ETL pipeline, establishing the data quality profile before any transformation occurs.

---

## Key Features

1. **Automated File Format Detection**
   - Inferred delimiters (e.g., `,`, `\t`, `;`, `|`).
   - File encoding detection (e.g., `utf-8`, `latin1`, `cp1252`).
   - Handles multiple file formats (CSV, TSV, Excel, JSON, etc.) using unified utility readers.

2. **Performance Optimization for Large Datasets**
   - Automatically detects files larger than **10 MB**.
   - Streams row-count checks and limits profiling reads to the first **20,000 rows** to avoid high memory usage and latency.

3. **Statistical In-Memory Profiling**
   - Calculates missing values per column.
   - Identifies duplicate rows.
   - Profiles column data types using Pandas inference engine.
   - Extracts a small data preview (first 5 rows) for LLM cognitive context.

4. **LLM-Powered Data Profiling & Recommendations**
   - Formulates a system-guided prompt containing the profile metadata.
   - Utilizes `JSON mode` to enforce structural responses from the cognitive engine.
   - Automatically estimates a dataset quality score based on completeness and uniqueness.
   - Recommends custom transformations based on anomalies identified.

---

## Technical Details

- **Class**: `IntakeAgent` in [intake_agent.py](file:///c:/Users/User/Documents/ETL-A/agents/intake_agent/intake_agent.py)
- **Primary Dependencies**:
  - `pandas` for in-memory dataset handling and type parsing.
  - `backend.utils.file_utils` for format detection.
  - `backend.core.llm` for the LLM execution context.

### Example Intake Profile Schema
```json
{
  "dataset_name": "sales_records.csv",
  "rows": 5000,
  "columns": 7,
  "column_names": ["ID", "Date", "Customer", "Product", "Qty", "Price", "Status"],
  "column_types": {
    "ID": "int64",
    "Date": "object",
    "Customer": "object",
    "Product": "object",
    "Qty": "float64",
    "Price": "object",
    "Status": "object"
  },
  "missing_values": {
    "Customer": 3,
    "Qty": 1
  },
  "duplicate_rows": 0,
  "estimated_quality": 95.8,
  "recommended_transformations": [
    "Standardize dates in 'Date' column",
    "Clean and cast 'Price' to numeric type",
    "Fill missing customer names with placeholder values"
  ]
}
```
