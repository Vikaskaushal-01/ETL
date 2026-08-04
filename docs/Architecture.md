# System Architecture Documentation

This document describes the software design and integration patterns implemented in the **Intelligent Autonomous Agentic AI ETL Platform**.

---

## 1. Architectural Patterns
The application follows **Clean Architecture** principles to isolate the core domain logic, agents, and storage boundaries:

- **Entity / State Layer (`langgraph/state.py`)**: Stores the global data schemas and progress state during the pipeline lifecycle.
- **Service/Agent Layer (`agents/`)**: Contains cognitive agents executing tasks independently (Intake, Transformation, Validation, and Reporting).
- **Interface Adapters (`backend/api/`)**: FastAPI HTTP endpoints receiving uploads, starting/monitoring jobs, and serving reporting downloads.
- **Frameworks & Drivers (`backend/database/`)**: Concrete implementations of MySQL repository operations and external ReportLab generators.

---

## 2. Component Design & Interactions

```text
               +-------------------+
               |    React Client   |
               +---------+---------+
                         | (1) Upload dataset
                         v
               +---------+---------+
               |  FastAPI Web App  | <---+
               +----+---------+----+     | (3) Invoke /pipeline/start
                    |         |          |
   (2) Store File   |         |          |
   under /data/raw  |         |          |
                    v         v          |
             +------+--+   +--+----------+--+
             | Raw dir |   | SnapLogic IIP | (SnapLogic automatically scans folder
             +---------+   +------+---------+  and coordinates ingestion/routing)
                                  |
                                  | (4) Launch Multi-Agent flow
                                  v
                       +----------+----------+
                       |  LangGraph Workflow |
                       +----------+----------+
                                  |
            +---------------------+---------------------+
            |                     |                     |
            v                     v                     v
     [Intake Agent]     [Transformation Agent]  [Validation Agent]
      - Infer delimiter   - Clean formatting     - Unique constraints
      - Quality scores    - Trim whitespaces     - Staging loading
      - Schema profiles   - Standardize dates    - Reject rows
            |                     |                     |
            +---------------------+---------------------+
                                  |
                                  v
                       [Intelligence Agent]
                        - Root Cause Analysis (RCA)
                        - Export PDF, Word (.docx), MD
                        - Trigger Power BI refresh API
```

---

## 3. Microservice Containers
The platform is designed to be fully containerized in a production environment:
1. **`etl_backend`**: FastAPI application executing APIs and LangGraph state.
2. **`etl_mysql`**: Relational store for production target data and ETL metadata log files.
3. **`etl_redis`**: Key-value cache layer tracking job locks.
4. **`etl_snaplogic`**: SnapLogic IIP processing engine.
5. **`etl_ollama`**: Local inference framework hosting llama3/offline LLM logic.
