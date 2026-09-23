# Changelog

All notable changes to the **Intelligent Autonomous Agentic AI ETL Platform** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [2.3.0] - 2026-09-24

### 🚀 Added
- Dedicated **History**, **Reports**, **Logs**, **Storage** and **Power BI** pages (previously History/Reports/Storage all opened one drawer whose tables never loaded). History shows every upload with status, rows loaded/rejected, quality and runtime, with log, report, cleaned-file and re-run actions; Logs shows the full process log of any run (live while running) with copy/download.
- `/api/v1/history` and `/api/v1/history/{batch_id}/log` endpoints.
- Server-side **API keys** (hashed, per user, usable via `X-API-Key`, with real usage counts), **profile** and **password change** endpoints; Settings now uses them instead of browser-only fake data.
- **Power BI export**: refresh writes the user's star schema (facts + dimensions) as CSV files for Power BI Desktop; the Power BI stage of every pipeline run performs this export.
- **URL ingestion** tab and a **live URL feed** source for real-time streaming (polled on an interval); the synthetic generators remain, labelled as simulators.
- Header notifications for finished runs; working "Remember me", console log level, audio alert and glass-intensity preferences.

### 🐛 Fixed / Changed
- Reports no longer contain invented insights: dataset insights, root cause analysis and recommendations are computed from the cleaned data and the actual rejection reasons; the LLM only narrates those facts.
- Kaggle links no longer silently return a generated sample dataset.
- Pipeline monitor could freeze on "processing" at the end of a run; raw-file links used a wrong account folder; selecting a batch overwrote the dashboard's global totals.
- Duplicate `recent-runs-table` id and wrong explorer table id that left tables empty; login form no longer pre-fills credentials.

---

## [2.2.0] - 2026-09-23

### 🔐 Security
- **Real authentication**: login issues signed, expiring session tokens; all API routes except auth/health require one. The caller's identity comes from the token, so the spoofable `X-User-Email` header no longer grants access to other accounts.
- Passwords are stored as salted PBKDF2 hashes (legacy plaintext rows are upgraded on next login).
- Password reset codes expire after 15 minutes and lock after 5 wrong attempts; demo codes and demo social login are disabled when `ENV=production`. Social login can no longer take over a password account.
- Removed arbitrary file read: `/dashboard/download` served any workspace file (including the SQLite database with passwords and `.env`); `/pipeline/start` and the SnapLogic agent endpoints accepted any server path. All file access is now confined to the caller's workspace.
- Upload filenames are sanitized (`../` path traversal wrote outside the upload folder); executable/pickle uploads are blocked and `.pkl` reading removed (unpickling uploads allowed code execution); uploads are size-limited.
- URL ingestion (`/upload/url`, `/rag/upload/url`) rejects private/loopback addresses (SSRF).
- Chat maintenance commands: questions such as "how do I clear data?" no longer wipe the platform; workspace reset / log clearing are administrator-only, and "clear cleaned data" only clears the caller's own folder.
- Replaced `eval` in the chat calculator with a bounded AST evaluator (`9**9**9**9` could hang the server).
- Chat answers are HTML-escaped in the UI (scraped RAG content could inject script).
- Reports are no longer copied into the shared `reports/` folder, and report listings no longer fall back to other users' data.

### 🐛 Fixed
- Storage load: files missing optional columns (e.g. customers without `email`) and the real-time *transactions* / *e-commerce orders* streams had **every row rejected** due to SQL bind errors; one bad value (e.g. `quantity=abc`) rolled back the whole batch. Rows are now validated individually and rejected with a reason.
- Transaction logs containing `customer_id` were misclassified as customer master data and overwrote customers with fabricated `_dup_` IDs.
- Date standardization no longer destroys columns whose names merely contain "date"/"time" (e.g. `runtime_sec`) or values that do not parse.
- Transformation crashed when `total_price` had nulls but `unit_price`/`quantity` columns were absent.
- Row counts, rows loaded and quality scores are measured from the data instead of being taken from LLM output.
- Empty / header-only files reported `Success`; they now fail at intake with a clear message. Runs with zero loaded rows report `Failed`.
- Dashboard: recent runs, active pipelines, average runtime and telemetry were always empty (tuple `IN` binding + SQLite datetime handling), availability counted a non-existent `Completed` status, and generic datasets were missing from row totals.
- Unknown pipeline IDs reported `Running` forever (now 404); runs longer than 60s were marked `Failed` when another run started; concurrent status polling could read a half-written state file.
- `raw_uploads.status` now moves through `Processing` → `Processed`/`Failed`.
- Report download fell back to *any* report whose name contained `_report`; report history crashed on reports with a missing format path.
- Power BI status reported a hard-coded MySQL connection; DAX success-rate measure used a status value that never occurs.
- Chat: latest-batch lookup used MySQL-only `CONCAT`; log-question answers used the wrong intent; download links with spaces were broken.
- `cleanup_all.py` deleted all user accounts and depended on the working directory.
- `verify_pipeline.py` dropped the real database and emptied real data folders; it now runs fully isolated.

### ⚙️ Changed
- Added `.env.example`, `.dockerignore` (the image previously bundled `.env`, the virtualenv and the database), persistent `Accounts/` volume and `.env` loading in Docker Compose.
- CI runs `pytest` against an isolated database with the offline LLM; added `tests/test_platform_regressions.py` (auth, isolation, file safety, full pipeline).

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
