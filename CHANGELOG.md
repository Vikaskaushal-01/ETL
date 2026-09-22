# Changelog

All notable changes to the **Intelligent Autonomous Agentic AI ETL Platform** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [2.1.0] - 2026-09-22

### 🚀 Added
- **Gemini 3.6 Flash LLM Integration**:
  - Upgraded Google GenAI client to use `gemini-3.6-flash` as primary LLM engine with fallback circuit breakers.
  - Added structured text and dictionary response extraction helpers for LangChain GenAI 4.2+.
- **Extended API Telemetry & Endpoints**:
  - Added `/api/v1/dashboard/metrics` providing pipeline throughput, uptime availability %, and node execution state.
  - Added `/api/v1/powerbi/measures` providing pre-configured DAX business formulas (Total Revenue, AOV, Success Rate, Units Sold).
  - Added `/api/v1/rag/search` providing token-scored keyword search and relevance ranking across uploaded knowledge base documents.
- **Enhanced Data Ingestion & Sanitization**:
  - Delimiter detection resilience and header whitespace normalization in `IntakeAgent`.
  - Advanced semantic type inference for Currency ($ / € / £ / ¥) and IP addresses.
  - Chat prompt injection defense filters and NLP fallback handling for data engineering queries.
- **Automated Regression Testing**:
  - Added unit test coverage for extended dashboard telemetry, PowerBI measures, and RAG search in `tests/test_extended_endpoints.py`.

### 🛡️ Security & Performance
- Suppressed legacy pandas datetime format inference warnings in semantic type detection.
- Configured client retry policies and 60-second circuit breaker recovery for LLM service endpoints.
- Auto-provisioning logic for relational parent stubs in SQLite and MySQL storage engines.

---

## [2.0.0] - 2026-09-17


### 🚀 Added
- **Real-Time Streaming Ingestion Engine**:
  - Synthetic streaming generators for Financial & Payment Transactions, Industrial IoT Telemetry, and Global E-Commerce Orders.
  - Interactive stream mode switcher and batch size selectors (15, 30, 60, 100 rows/cycle) in frontend UI.
  - Telemetry streaming endpoints `/api/v1/upload/realtime` and `/api/v1/upload/realtime/presets`.
- **Advanced Semantic Type Inference Engine**:
  - Auto-detection for Email, Phone, IP Address, UUID, Currency, Datetime, and Categorical types.
  - Statistical Z-score and IQR anomaly and outlier detection (`backend/utils/type_inference.py`).
- **Autonomous Data Cleansing & Imputation**:
  - Deterministic whitespace trimming, casing normalization, mode/median statistical imputation, and Winsorization (`backend/utils/cleansing_engine.py`).
- **Dynamic SQL Schema & DDL Generator**:
  - Dynamic MySQL and SQLite DDL generation with primary key candidates and metadata column tracking (`backend/database/schema_generator.py`).
- **Power BI Semantic Modeling & DAX Generator**:
  - Star/Snowflake schema data modeling contracts and automated DAX business measures (`backend/utils/powerbi_dax.py`).
- **Multi-Format Root Cause Analysis Exporters**:
  - Formatted Markdown and structured JSON executive audit reports (`backend/utils/rca_generator.py`).
- **Automated CI/CD & Testing**:
  - GitHub Actions CI matrix workflow (`.github/workflows/ci.yml`).
  - Unit and integration test suites for Authentication, Multi-Agent Pipeline E2E, and Cleansing Engines (`tests/`).
- **Developer & Operations Documentation**:
  - Developer Setup & Custom Agent Extension Guide (`docs/DEVELOPER_GUIDE.md`).
  - Production Operations & Disaster Recovery Runbook (`docs/RUNBOOK.md`).

### 🛡️ Security & Reliability
- Added prompt injection sanitization and control token filtering for AI Assistant Chatbot.
- Enhanced database connection pool health diagnostics and SQLite WAL mode concurrency tuning.
- Stateful LangGraph circuit breaker and SLA threshold tracking.

### 🎨 Frontend UI / UX
- Custom Glassmorphism Design System with dynamic theme accent glows (Cyan, Emerald, Violet).
- HTML5 Canvas particle flow engine and real-time SVG Bezier connectors between pipeline stages.
- Component Stage Inspector modal with before/after dataframe comparisons and transformation audit logs.
