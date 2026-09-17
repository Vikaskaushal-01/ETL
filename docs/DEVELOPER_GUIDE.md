# Developer Setup & Custom Agent Extension Guide

Welcome to the **Intelligent Autonomous Agentic AI ETL Platform** developer documentation. This guide details local environment setup, testing guidelines, and instructions for extending the multi-agent graph with custom agents.

---

## 1. Local Development Setup

### Prerequisites
- **Python 3.10+** (Python 3.11 recommended)
- **Node.js 18+** (Optional, for tooling)
- **Docker & Docker Compose** (For full containerized multi-service deployment)
- **Git**

### Installation
```bash
# Clone repository
git clone https://github.com/Vikaskaushal-01/ETL.git
cd ETL

# Create and activate virtual environment
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

---

## 2. Running Locally

### Option A: Local FastAPI Server (SQLite Embedded Fallback)
```bash
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```
- Web UI: [http://localhost:8000/](http://localhost:8000/)
- API Docs: [http://localhost:8000/docs](http://localhost:8000/docs)

### Option B: Docker Compose Full Multi-Service Stack
```bash
cd docker
docker-compose up --build
```

---

## 3. Running Automated Tests

```bash
# Execute entire test suite
python -m unittest discover -s tests -p "test_*.py" -v

# Run verification pipeline script
python verify_pipeline.py
```

---

## 4. How to Create a Custom Agent

To introduce a new cognitive agent into the LangGraph state machine:

### Step 1: Define Agent Class in `agents/`
Create `agents/my_custom_agent/my_custom_agent.py`:
```python
import logging
import time
from typing import Dict, Any

logger = logging.getLogger("etl_custom_agent")

class CustomEnrichmentAgent:
    def __init__(self):
        self.role = "Data Enrichment Specialist"
        self.name = "Custom Enrichment Agent"

    def run(self, df, metadata: Dict[str, Any] = None) -> Dict[str, Any]:
        start = time.time()
        logger.info("Executing custom enrichment logic...")
        
        # Apply custom logic here (e.g. GeoIP lookup, currency conversion)
        
        return {
            "status": "Success",
            "enriched_records": len(df),
            "execution_time": time.time() - start
        }
```

### Step 2: Register Node in `agents_graph/nodes.py`
```python
def custom_enrichment_node(state: PipelineState) -> PipelineState:
    agent = CustomEnrichmentAgent()
    # Call agent and update state
    return state
```

### Step 3: Wire into StateGraph in `agents_graph/graph.py`
```python
workflow.add_node("custom_enrichment", custom_enrichment_node)
workflow.add_edge("transformation", "custom_enrichment")
workflow.add_edge("custom_enrichment", "storage")
```

---

## 5. Coding Standards & Conventions
- **Clean Architecture**: Domain logic must not depend on UI or web frameworks.
- **Graceful Fallbacks**: Every external service call (Gemini LLM, MySQL, Redis) must have a reliable local fallback.
- **Commit Messages**: Follow Conventional Commits format (`feat(...)`, `test(...)`, `docs(...)`, `fix(...)`, `refactor(...)`).
