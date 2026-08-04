# Deployment & Production Orchestration Guide

This document describes how to deploy the **Intelligent Autonomous Agentic AI ETL Platform** into a production container environment.

---

## 1. Prerequisites
Ensure you have the following installed on the target server:
- **Docker** (v20.10 or higher)
- **Docker Compose** (v2.0 or higher)

---

## 2. Setting Up Environment Secrets
Create a `.env` file in the root directory:
```bash
# Database parameters
MYSQL_HOST=db
MYSQL_PORT=3306
MYSQL_DB=agentic_ai_etl
MYSQL_USER=etl_user
MYSQL_PASSWORD=etl_password

# Staging database parameters
STAGING_MYSQL_DB=agentic_ai_etl_staging
STAGING_MYSQL_USER=etl_user
STAGING_MYSQL_PASSWORD=etl_password

# LLM setup
GEMINI_API_KEY=your_gemini_api_key_here
LLM_PROVIDER=gemini # fallback to ollama or mock if empty
OLLAMA_HOST=http://ollama:11434
```

---

## 3. Running with Docker Compose

To build images and launch all containers (the SnapLogic container compiles locally using `docker/Dockerfile.snaplogic` to bypass external registry credentials):
```bash
cd docker
docker-compose up --build -d
```

### Container Status Verification:
```bash
docker ps
```
Verify that all 5 services are running:
- `etl_backend` (port 8000)
- `etl_mysql` (port 3306)
- `etl_redis` (port 6379)
- `etl_snaplogic` (port 8080)
- `etl_ollama` (port 11434)

---

## 4. SnapLogic IIP Workflow Configuration

SnapLogic (Commercial Intelligent Integration Platform - SnapLogic IIP) acts as the scheduled trigger, Iris AI assistant coordinator, and visual pipeline orchestrator.

### Snaps Configuration:
1. **File Reader Snap**: Configure a `FileReader` snap pointing to `/data/raw` to scan files every 5 seconds.
2. **Iris AI Intake Snap**: Resolves file formats and triggers Agent 1 schema profiling via `http://backend:8000/api/v1/pipeline/intake`.
3. **Data Transformation Snap**: Cleans datasets, standardizes headers, and imputes nulls via `http://backend:8000/api/v1/pipeline/transform`.
4. **SQL Staging & Format Snap**: Selects optimal storage format and loads MySQL staging tables via `http://backend:8000/api/v1/pipeline/store`.
5. **Word Docx Exporter & AI Report Snap**: Exports cleaned Word `.docx` files and compiles analytical reports via `http://backend:8000/api/v1/pipeline/report`.
6. **Power BI Gateway Snap**: Triggers automated Power BI dataset synchronization via `http://backend:8000/api/v1/powerbi/refresh`.
7. **FileWriter Archive Snap**: Move the completed raw inputs to `/data/archive`.
