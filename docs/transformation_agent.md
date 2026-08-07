# Data Transformation Agent

The **Data Transformation Agent** cleans, standardizes, and validates dataset columns. It is executed following the Data Intake phase, converting inconsistent values into structured, staging-ready rows.

---

## Cleaning Operations

The agent performs standard cleaning rules automatically on ingestion:

1. **Header Standardization**
   - Strips leading/trailing whitespaces.
   - Standardizes headers to lower `snake_case`.
   - Replaces spaces, dots, and hyphens with underscores.

2. **Whitespace Trimming**
   - Iterates through string (`object`) columns.
   - Trims whitespaces.
   - Converts standard text representations of empty entries (e.g., `""`, `"nan"`, `"None"`) into Python `None` values.

3. **Deduplication**
   - Automatically drops duplicate records if the file size is under the 10 MB threshold.
   - Logs details of removed rows in transformation history.

4. **Date Standardization**
   - Parses date fields using a robust multi-format matching parser.
   - Converts dates to ISO 8601 standard (`YYYY-MM-DD`).

5. **Type Casting and Coercion**
   - Infers and casts float, integer, and boolean values.
   - Cleans common numeric noise (e.g., dollar signs `$`, commas `,`, percent signs `%`).

---

## Technical Details

- **Class**: `TransformationAgent` in [transformation_agent.py](file:///c:/Users/User/Documents/ETL-A/agents/transformation_agent/transformation_agent.py)
- **Primary Dependencies**:
  - `pandas` and `numpy` for vector-based clean mappings.
  - `backend.core.llm` for dynamic anomaly handling if schema structures break.

### Transformation History Schema
Each modification records a transaction trace returned inside the response payload:
```json
{
  "column_name": "total_cost",
  "old_value": "$1,250.00",
  "new_value": 1250.00,
  "reason": "Coerced string representation into a float data type and removed currency symbols"
}
```
