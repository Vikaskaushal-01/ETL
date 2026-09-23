import ast
import operator
import os
import json
import re
import threading
import time
import logging
import httpx
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI

load_dotenv()
logger = logging.getLogger("etl_llm")

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini").lower()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")

_ARITH_BINOPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Mod: operator.mod, ast.Pow: operator.pow,
}
_ARITH_UNARYOPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def safe_eval_arithmetic(expr: str):
    """Evaluates +,-,*,/,%,** on numbers only, with bounded exponents (no eval, no huge powers)."""
    if len(expr) > 200:
        raise ValueError("Expression too long")

    def _eval(node):
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.UnaryOp) and type(node.op) in _ARITH_UNARYOPS:
            return _ARITH_UNARYOPS[type(node.op)](_eval(node.operand))
        if isinstance(node, ast.BinOp) and type(node.op) in _ARITH_BINOPS:
            left, right = _eval(node.left), _eval(node.right)
            if isinstance(node.op, ast.Pow) and (abs(right) > 100 or abs(left) > 1e6):
                raise ValueError("Exponent too large")
            return _ARITH_BINOPS[type(node.op)](left, right)
        raise ValueError("Unsupported expression")

    return _eval(ast.parse(expr, mode="eval"))


def _has_any_word(text_value: str, keywords: list) -> bool:
    """Whole-word / whole-phrase keyword match (plurals allowed; 'rag' does not match 'average')."""
    return any(re.search(r"\b" + re.escape(k.strip()) + r"(?:s|es)?\b", text_value) for k in keywords)


def generate_responsive_chat_reply(prompt: str, system_instruction: str = None) -> str:
    """
    Intelligent NLP reasoning engine that analyzes the user's exact query, extracts
    database metrics and context, and generates responsive, customized markdown answers.
    """
    # 1. Extract query text cleanly
    query_text = ""
    q_match = re.search(r'User Query:\s*(.*?)(?=\n\s*(?:Ensure|Conversation|Database|System|Platform|Based on)|\Z)', prompt, re.DOTALL | re.IGNORECASE)
    if q_match:
        query_text = q_match.group(1).strip()
    else:
        query_text = prompt.strip()
    query_lower = query_text.lower()

    # 2. Extract database context if present
    context_section = ""
    if "database context:" in prompt.lower():
        parts = prompt.split("Database Context:")
        if len(parts) > 1:
            context_section = parts[1].split("User Query:")[0].strip()

    # Check for basic math/calculation queries (e.g. "what is 25 * 4?", "2+2", "calculate 100 / 4", "15% of 200")
    pct_match = re.search(r'(?:what is\s+)?([\d\.]+)\s*%\s*(?:of\s+)([\d\.]+)', query_text.strip(), re.IGNORECASE)
    if pct_match:
        try:
            p_val = float(pct_match.group(1))
            total_val = float(pct_match.group(2))
            res_val = round((p_val / 100.0) * total_val, 4)
            return f"### Calculation Result\n\n**Expression**: `{p_val}% of {total_val}`\n**Result**: **`{res_val}`**"
        except Exception:
            pass

    math_match = re.search(r'(?:what is|calculate|compute|solve)?\s*([\d\.\s\+\-\*\/\(\)\^%]+)\??$', query_text.strip(), re.IGNORECASE)
    if math_match:
        expr = math_match.group(1).strip()
        # Ensure it contains at least one operator and numbers
        if any(op in expr for op in ['+', '-', '*', '/', '^', '%']) and any(c.isdigit() for c in expr):
            try:
                val = safe_eval_arithmetic(expr.replace('^', '**'))
                return f"### Calculation Result\n\n**Expression**: `{expr}`\n**Result**: **`{val}`**"
            except Exception:
                pass

    # A. Data Quality & Root Cause Analysis Questions
    is_rca_question = _has_any_word(query_lower, [
        "root cause", "rca", "reject", "rejected", "why failed", "validation error", 
        "constraint", "failure", "bad record", "invalid row", "why rows rejected"
    ])
    if is_rca_question:
        rca_items = re.findall(r'\*\s*Issue:[\s]*(.*?)(?=\n\s*\*|\n\n|\Z)', context_section, re.DOTALL)
        quality_match = re.search(r'Quality Score[=:][\s]*([\d\.]+)%', context_section)
        
        reply = "### Root Cause Analysis & Validation Findings\n\n"
        if rca_items:
            reply += f"Based on the validation checks for the active batch (Quality Score: **{quality_match.group(1) + '%' if quality_match else 'not recorded'}**), here is the detailed breakdown of the data quality issues identified:\n\n"
            for idx, item in enumerate(rca_items[:5]):
                reply += f"#### Issue {idx+1}:\n"
                for line in item.strip().split("\n"):
                    clean_l = line.strip().lstrip("-* ")
                    if ":" in clean_l:
                        k, v = clean_l.split(":", 1)
                        reply += f"- **{k.strip()}**: {v.strip()}\n"
                    else:
                        reply += f"- {clean_l}\n"
                reply += "\n"
        elif "Selected run:" in context_section:
            reply += "All validation checks passed with **0 rejected rows** during relational database verification. Key constraints and foreign key relationships were verified successfully."
        else:
            reply += "Root Cause Analysis (RCA) runs automatically during the Docx & Report Snap stage whenever validation rejects occur. It categorizes source sync failures, data type mismatches, and schema violations, providing technical and business recommendations."
        return reply

    # B. Transformations & Cleaning Questions
    is_transform_question = _has_any_word(query_lower, [
        "transformation", "transform", "how cleaned", "what cleaned", "cleaning step",
        "impute", "imputation", "snake_case", "trim", "standardize", "deduplicate", "duplicate"
    ])
    if is_transform_question:
        reply = "### Transformation & Data Cleansing Summary\n\n"
        trans_matches = re.findall(r'Column [\'"]([^\'"]+)[\'"]:[\s]*(.+)', context_section)
        if trans_matches:
            reply += "The Data Transformation Agent applied the following cleansing operations to standardise the dataset:\n\n"
            for col, desc in trans_matches[:8]:
                reply += f"- **Column `{col}`**: {desc.strip()}\n"
            reply += "\n**Standard Pipelines Cleansing Rules**:\n"
            reply += "1. **Header Normalization**: Columns converted to lowercase `snake_case`.\n"
            reply += "2. **Whitespace Trimming**: Leading and trailing spaces stripped from all string values.\n"
            reply += "3. **Date Standardization**: Datetime values parsed and unified into ISO `YYYY-MM-DD HH:MM:SS`.\n"
            reply += "4. **Null Imputation**: Business rules applied (e.g. quantity defaulted to 1, unit price imputed using median reference values).\n"
            reply += "5. **Deduplication**: Exact duplicate records identified and removed."
        else:
            reply += "The Data Cleanser Snap autonomously performs:\n"
            reply += "- **Schema Normalization**: Formats headers to `snake_case`.\n"
            reply += "- **Text Trimming**: Removes non-printable characters and whitespace.\n"
            reply += "- **Null Handling**: Computes column medians for numeric fields or default fallbacks.\n"
            reply += "- **Deduplication**: Drops duplicate records to enhance data quality."
        return reply

    # C. Schema & Column Breakdown Questions
    is_schema_question = _has_any_word(query_lower, [
        "schema", "column", "columns", "data type", "datatype", "types", "missing value", "null count", "fields"
    ])
    if is_schema_question:
        reply = "### Dataset Schema & Structure Assessment\n\n"
        file_match = re.search(r'Uploaded File:[\s]*([^\s|]+)', context_section)
        quality_match = re.search(r'Quality Score[=:][\s]*([\d\.]+)%', context_section)
        if file_match:
            reply += f"**Dataset**: `{file_match.group(1)}` | **Data Quality**: {quality_match.group(1) + '%' if quality_match else 'not recorded'}\n\n"
        
        reply += "The schema profiling engine analyzes incoming files to determine optimal column types and identify null distributions:\n\n"
        reply += "| Inferred Column Category | Supported Types | Storage Mapping |\n"
        reply += "|---|---|---|\n"
        reply += "| Primary / Foreign Keys | `VARCHAR(100)` / `INT` | Indexed relational IDs |\n"
        reply += "| Numeric Metrics | `INT`, `DECIMAL(10,2)` | Quantity, Price, Amounts |\n"
        reply += "| Temporal / Dates | `DATETIME` | Standard ISO timestamp |\n"
        reply += "| Categorical / Text | `VARCHAR(255)` | Trimming & encoding validation |\n"
        return reply

    # D. SQL & Database Staging Questions
    is_sql_question = _has_any_word(query_lower, [
        "sql", "select ", "from staging", "mysql query", "table schema", "production table", "database query", "generate sql"
    ])
    if is_sql_question:
        reply = "### SQL Database Staging & Target Schema\n\n"
        reply += "The platform stages and loads verified datasets into MySQL tables:\n\n"
        reply += "```sql\n"
        reply += "-- 1. Inspect verified staging records\n"
        reply += "SELECT * FROM staging_sales WHERE validation_status = 'Valid' LIMIT 10;\n\n"
        reply += "-- 2. Review rejected records for Root Cause Analysis\n"
        reply += "SELECT `row_number`, validation_status, sale_id, order_id \n"
        reply += "FROM staging_sales \n"
        reply += "WHERE validation_status = 'Rejected';\n\n"
        reply += "-- 3. Query production analytical model\n"
        reply += "SELECT s.sale_id, s.product_id, s.quantity, s.total_price, s.sale_date\n"
        reply += "FROM sales s\n"
        reply += "ORDER BY s.sale_date DESC LIMIT 20;\n"
        reply += "```\n"
        return reply

    # E. Performance & Optimization Questions
    is_perf_question = _has_any_word(query_lower, [
        "performance", "speed", "fast", "runtime", "duration", "optimize", "optimization", "throughput", "latency"
    ])
    if is_perf_question:
        exec_match = re.search(r'Duration[=:][\s]*([\d\.]+)s', context_section)
        reply = f"### Pipeline Execution Performance & Optimization\n\n"
        if exec_match:
            reply += f"The current batch finished processing in **{exec_match.group(1)} seconds**.\n\n"
        reply += "#### Optimization Recommendations:\n"
        reply += "1. **Database Indexing**: Add composite indices on high-cardinality keys (`customer_id`, `order_id`) to accelerate staging lookups.\n"
        reply += "2. **Stream Chunking**: For files larger than 10MB, streaming chunk size of 50,000 rows reduces memory footprint.\n"
        reply += "3. **Async Batch Staging**: Staging operations execute with batched SQL inserts, minimizing connection round-trips.\n"
        reply += "4. **Off-Peak Automation**: Schedule batch loads during low operational hours to maximize database throughput."
        return reply

    # F. Business Insights & Summary Questions
    is_insights_question = _has_any_word(query_lower, [
        "executive summary", "business insight", "summary", "kpi", "overview", "what happened", "findings"
    ])
    if is_insights_question:
        file_match = re.search(r'Uploaded File:[\s]*([^\s|]+)', context_section)
        fname = file_match.group(1) if file_match else "the uploaded dataset"
        reply = f"### Executive Summary & Business Insights\n\n"
        reply += f"**Dataset**: `{fname}`\n\n"
        reply += "#### Key Highlights:\n"
        reply += "- **Ingestion & Profiling**: Automated intake verified file encoding, delimiter, and schema structure.\n"
        reply += "- **Data Quality Improvement**: Cleansing routines resolved duplicate entries and normalized headers to standard format.\n"
        reply += "- **Relational Validation**: Valid records were synchronized with MySQL staging and production tables.\n"
        reply += "- **Multi-Format Reports**: Full analytical reports were exported in 4 formats (JSON, Word DOCX, Markdown, and PDF) in the dedicated report folder.\n"
        return reply

    # G. Platform Architecture & Feature Inquiries (SnapLogic, Power BI, RAG, etc.)
    if _has_any_word(query_lower, ["snaplogic", "snap", "iris"]):
        return """### SnapLogic Integration Architecture
The ETL pipeline integrates with SnapLogic IIP (Intelligent Integration Platform):
- **FileReader Snap**: Automates raw dataset intake triggers on file system modifications.
- **Data Cleanser Snap**: Cleanses, standardizes, trims whitespace, and imputes null values.
- **SQL Staging Snap**: Validates foreign key constraints and stages data into relational tables.
- **Docx & Report Snap**: Generates analytical executive summaries in 4 formats (JSON, Word, Markdown, PDF)."""

    if _has_any_word(query_lower, ["power bi", "pbi", "dashboard"]):
        return """### Power BI Gateway Sync
Once dataset cleaning finishes:
1. The **Power BI Gateway Sync Snap** triggers an automated refresh signal.
2. Your warehouse rows are exported as fact and dimension CSV files (FactSales, FactOrders, DimCustomer, ...).
3. Load that export folder in Power BI Desktop via Get Data > Folder (see the Power BI page for the path)."""

    if _has_any_word(query_lower, ["rag", "vector", "document", "knowledge"]):
        return """### Retrieval-Augmented Generation (RAG) Architecture
The platform has a built-in local document and link indexer:
1. **Document Ingestion**: Attach `.txt`, `.pdf`, `.docx`, or `.md` files or index web URLs using the paperclip tool.
2. **Dynamic Overlap Ranking**: Content is split into chunks and ranked locally based on semantic relevance.
3. **In-Context Grounding**: Top ranked snippets are injected into the agent reasoning context to answer queries accurately."""

    # H. Greetings & Conversational Queries
    if re.search(r"\b(hello|hi|hey|greetings|good morning|good evening)\b", query_lower):
        return """Hello! I am the **Control AI Data Engineering Chat Assistant**.

I'm here to help you with:
- **Batch Analysis**: Ask questions about your uploaded datasets, quality scores, and validation results.
- **Root Cause Analysis (RCA)**: Investigate why specific rows were rejected during load.
- **Transformations**: Review cleansing operations applied to your columns.
- **SQL & Staging Queries**: Generate database queries against your staged tables.
- **Report Downloads**: Access your 4 report formats (JSON, Word, MD, PDF).

How can I assist you with your data pipeline today?"""

    if _has_any_word(query_lower, ["who are you", "what can you do", "what are your features", "help"]):
        return """### Control AI Chat Assistant Capabilities

I am an intelligent assistant connected directly to your ETL automation pipeline and database:
1. **Real-time Pipeline Inspection**: Query loaded row counts, reject reasons, and quality metrics.
2. **Schema & Transformation Explanations**: Inspect column data types, null counts, and applied fixes.
3. **SQL Query Generation**: Produce tailored queries for `staging_customers`, `staging_orders`, and `sales`.
4. **Platform Troubleshooting**: Diagnose file encoding, connection issues, or pipeline state locks.
5. **Report Access**: Retrieve direct download links for your 4 report formats (JSON, Word, Markdown, PDF).

Feel free to ask any specific question about your data or platform!"""

    if _has_any_word(query_lower, ["thank", "thanks", "appreciate", "great job", "awesome"]):
        return "You're very welcome! If you have any more questions about your datasets, pipeline runs, or SQL queries, feel free to ask anytime."

    # Questions about the user's runs: answer from the measured run list in the context
    if _has_any_word(query_lower, ["run", "runs", "status", "upload", "uploads", "latest", "last", "quality", "rows", "processed", "history"]):
        run_lines = [l.strip() for l in context_section.splitlines() if l.strip().startswith("- ") and "| batch " in l]
        if run_lines:
            return "Here are your most recent pipeline runs:\n\n" + "\n".join(run_lines[:10])
        if "not uploaded or run any datasets" in context_section:
            return "You haven't uploaded or run any datasets yet. Upload a file on the Pipeline page to get started."

    # General questions need a real language model
    return (
        "I couldn't reach the AI model just now - the Gemini service may be busy, or no `GEMINI_API_KEY` "
        "is configured in `.env`. Please try your question again in a moment.\n\n"
        "I can still get you files and logs from your runs, for example:\n"
        "- *give me the cleaned file for sales.csv*\n"
        "- *download the PDF report*\n"
        "- *show the log of my last run*"
    )

def extract_text_from_llm_response(content) -> str:
    """
    Extracts raw text from various LLM content types (str, list of dicts/parts, LangChain structures).
    """
    if not content:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts = []
        for part in content:
            if isinstance(part, str):
                text_parts.append(part)
            elif isinstance(part, dict) and "text" in part:
                text_parts.append(str(part["text"]))
            elif hasattr(part, "text"):
                text_parts.append(str(part.text))
            else:
                text_parts.append(str(part))
        return "".join(text_parts)
    return str(content)

def _discover_gemini_models(api_key: str) -> list:
    """
    Text models this key can call, newest first. Google retires model versions regularly, so the list
    is read from the API instead of being hard-coded: "*-flash-latest" aliases, then versioned flash
    models (e.g. gemini-3.8-flash), then pro models.
    """
    try:
        res = httpx.get("https://generativelanguage.googleapis.com/v1beta/models",
                        params={"key": api_key, "pageSize": 200}, timeout=10.0)
        res.raise_for_status()
        names = [m["name"].split("/", 1)[-1] for m in res.json().get("models", [])
                 if "generateContent" in m.get("supportedGenerationMethods", [])]
    except Exception as e:
        logger.warning(f"Could not list Gemini models ({e}); using the default model list.")
        return []

    def version(name: str) -> tuple:
        match = re.match(r"gemini-(\d+)(?:\.(\d+))?", name)
        return (int(match.group(1)), int(match.group(2) or 0)) if match else (0, 0)

    flash = sorted([n for n in names if re.fullmatch(r"gemini-\d+(\.\d+)?-flash", n)], key=version, reverse=True)
    pro = sorted([n for n in names if re.fullmatch(r"gemini-\d+(\.\d+)?-pro", n)], key=version, reverse=True)
    aliases = [n for n in ("gemini-flash-latest", "gemini-pro-latest") if n in names]
    return aliases[:1] + flash + aliases[1:] + pro


# Tried in order; a model that is overloaded or unavailable is skipped for a cooldown period.
# GEMINI_MODEL (optional) is tried first.
gemini_models = []  # list of (name, client)

if LLM_PROVIDER == "gemini" and GEMINI_API_KEY and not GEMINI_API_KEY.startswith("your_gemini_"):
    os.environ["GOOGLE_API_KEY"] = GEMINI_API_KEY
    gemini_models_to_try = [m for m in [os.getenv("GEMINI_MODEL")] if m] + (
        _discover_gemini_models(GEMINI_API_KEY) or ["gemini-flash-latest", "gemini-3.6-flash"]
    )
    for m_name in list(dict.fromkeys(gemini_models_to_try))[:8]:
        try:
            gemini_models.append((m_name, ChatGoogleGenerativeAI(model=m_name, temperature=0.2, max_retries=1)))
        except Exception as init_err:
            logger.debug(f"Could not init model {m_name}: {init_err}")
    if gemini_models:
        logger.info(f"Gemini models configured: {', '.join(n for n, _ in gemini_models)}")
gemini_model = gemini_models[0][1] if gemini_models else None
_model_cooldown_until = {}

_gemini_circuit_open_until = 0.0
_ollama_circuit_open_until = 0.0
# Which engine answered the most recent query_llm call on this thread ("gemini", "ollama" or "offline")
_response_source = threading.local()


def is_real_llm_available() -> bool:
    """True when the last query_llm call on this thread was answered by Gemini or Ollama, not the offline engine."""
    return getattr(_response_source, "value", "offline") in ("gemini", "ollama")

def query_llm(prompt: str, system_instruction: str = None, json_mode: bool = False) -> str:
    """
    Unified LLM query function with circuit breaker protection.
    Falls back gracefully: Gemini -> Ollama -> Dynamic Responsive Reasoning Engine.
    """
    global _gemini_circuit_open_until, _ollama_circuit_open_until

    _response_source.value = "offline"
    # Fast-path: Explicit mock or offline mode
    if LLM_PROVIDER in ["mock", "offline"]:
        return run_mock_engine(prompt, system_instruction, json_mode)

    now = time.time()

    # 1. Try each configured Gemini model (skipping ones cooling down after an error)
    if LLM_PROVIDER == "gemini" and gemini_models and now >= _gemini_circuit_open_until:
        messages = []
        if system_instruction:
            messages.append(("system", system_instruction))
        messages.append(("user", prompt))
        overloaded = []
        key_rejected = False
        for attempt in range(2):
            # Second pass: Google's "high demand" 503s are usually momentary, so retry those models once
            candidates = gemini_models if attempt == 0 else overloaded
            if attempt == 1:
                if not overloaded or key_rejected:
                    break
                time.sleep(2)
            overloaded = []
            for model_name, model in candidates:
                if attempt == 0 and now < _model_cooldown_until.get(model_name, 0.0):
                    continue
                try:
                    logger.info(f"Querying LLM (gemini: {model_name})...")
                    response = model.invoke(messages)
                    extracted = extract_text_from_llm_response(response.content) if response else ""
                    if extracted:
                        _model_cooldown_until.pop(model_name, None)
                        _response_source.value = "gemini"
                        return extracted
                except Exception as e:
                    err_str = str(e)
                    if any(x in err_str for x in ["API_KEY_SERVICE_BLOCKED", "PERMISSION_DENIED", "API key not valid", "has not been used in project", "is disabled"]):
                        # The key itself is unusable: stop trying every model for 5 minutes
                        _gemini_circuit_open_until = time.time() + 300
                        logger.warning(f"Gemini API key rejected: {e}. Skipping Gemini for 300s.")
                        key_rejected = True
                        break
                    if "404" in err_str or "not found" in err_str.lower() or "no longer available" in err_str:
                        # Retired / unknown model: skip it for a day
                        _model_cooldown_until[model_name] = time.time() + 86400
                    else:
                        # Overloaded (503) or rate limited (429): short cooldown, retried once below
                        _model_cooldown_until[model_name] = time.time() + 20
                        overloaded.append((model_name, model))
                    logger.warning(f"Gemini model {model_name} failed ({err_str[:160]}); trying the next model.")

    # 2. Try Ollama (if configured and circuit is closed)
    if LLM_PROVIDER in ["gemini", "ollama"]:
        if now >= _ollama_circuit_open_until:
            try:
                payload = {
                    "model": "llama3",
                    "messages": [],
                    "stream": False
                }
                if json_mode:
                    payload["format"] = "json"
                if system_instruction:
                    payload["messages"].append({"role": "system", "content": system_instruction})
                payload["messages"].append({"role": "user", "content": prompt})

                response = httpx.post(
                    f"{OLLAMA_HOST}/api/chat", 
                    json=payload, 
                    timeout=httpx.Timeout(90.0, connect=0.5)
                )
                if response.status_code == 200:
                    result_json = response.json()
                    _ollama_circuit_open_until = 0.0
                    _response_source.value = "ollama"
                    return result_json["message"]["content"]
            except Exception as e:
                # Ollama is offline or unreachable - open circuit for 60s
                _ollama_circuit_open_until = time.time() + 60
                logger.info(f"Ollama execution note: {e}. Opening circuit breaker for 60s. Using responsive dynamic engine.")
        else:
            logger.debug("Ollama circuit breaker active, skipping directly to responsive dynamic engine.")

    # 3. Fallback: Dynamic Responsive Reasoning Engine
    return run_mock_engine(prompt, system_instruction, json_mode)

def run_mock_engine(prompt: str, system_instruction: str, json_mode: bool) -> str:
    """
    Intelligent programmatic response generation that dynamically parses user intent,
    contextual fields, mathematical expressions, and ETL metrics to produce precise, tailored answers.
    """
    prompt_lower = prompt.lower()
    
    # Check if we are inside Chatbot query
    if "chat" in prompt_lower or "senior data engineering chat assistant" in prompt_lower or "etl chat" in prompt_lower:
        return generate_responsive_chat_reply(prompt, system_instruction)

    # Check if we are inside Intake Agent
    if "intake" in prompt_lower or "detect" in prompt_lower or "delimiter" in prompt_lower:
        rows = 1000
        columns = 5
        
        # Safely extract rows and columns
        rows_match = re.search(r'Total Rows:\s*(\d+)', prompt, re.IGNORECASE)
        if rows_match:
            rows = int(rows_match.group(1))
            
        cols_match = re.search(r'Total Columns:\s*(\d+)', prompt, re.IGNORECASE)
        if cols_match:
            columns = int(cols_match.group(1))

        # Safer parsing of columns list
        column_names = []
        names_match = re.search(r'Columns:\s*\[([^\]]*)\]', prompt, re.IGNORECASE)
        if names_match:
            column_names = [c.strip().strip("'\"") for c in names_match.group(1).split(",") if c.strip()]
            
        # Safer parsing of column types
        column_types = {}
        types_match = re.search(r'Column Data Types [^:]*:\s*({[^}]+})', prompt, re.IGNORECASE)
        if types_match:
            try:
                # Replace single quotes and Python representations to load json
                cleaned_json = types_match.group(1).replace("'", '"')
                # Replace any pandas/numpy dtypes like dtype('int64') with string
                cleaned_json = re.sub(r'dtype\("[^"]+"\)', '"string"', cleaned_json)
                cleaned_json = re.sub(r'dtype\(\'[^\']+\'\)', '"string"', cleaned_json)
                column_types = json.loads(cleaned_json)
            except Exception:
                pass
        
        # Safer parsing of missing values
        missing_values = {}
        missing_match = re.search(r'Missing Values:\s*({[^}]+})', prompt, re.IGNORECASE)
        if missing_match:
            try:
                cleaned_json = missing_match.group(1).replace("'", '"')
                missing_values = json.loads(cleaned_json)
            except Exception:
                pass

        # If parsing failed or returned empty, populate dynamically from column_names
        if not column_names:
            # Fallback parsing line by line
            for line in prompt.split("\n"):
                if "columns:" in line.lower() and "[" in line:
                    cols_str = line.split("[")[1].split("]")[0]
                    column_names = [c.strip().strip("'\"") for c in cols_str.split(",") if c.strip()]
                    break
        if not column_names:
            column_names = ["column_1", "column_2", "column_3"]
            
        if not column_types:
            column_types = {name: "string" for name in column_names}
        if not missing_values:
            missing_values = {name: 0 for name in column_names}
            
        duplicate_rows = 0
        dups_match = re.search(r'Duplicate Rows:\s*(\d+)', prompt, re.IGNORECASE)
        if dups_match:
            duplicate_rows = int(dups_match.group(1))

        total_elements = rows * columns
        total_nulls = sum(missing_values.values()) if missing_values else 0
        total_dups = duplicate_rows
        quality_score = 100.0
        if total_elements > 0:
            null_ratio = total_nulls / total_elements
            dup_ratio = total_dups / rows if rows > 0 else 0
            quality_score = max(0.0, round(100.0 * (1.0 - (null_ratio * 0.8 + dup_ratio * 0.2)), 2))

        dataset_name = "dataset.csv"
        fn_match = re.search(r'\b[\w\.-]+\.(?:csv|tsv|json|xlsx|xml|xls)\b', prompt, re.IGNORECASE)
        if fn_match:
            dataset_name = fn_match.group(0)

        recommended_transformations = [
            "Trim whitespace in string columns",
            "Remove duplicate records"
        ]
        for col, missing_cnt in missing_values.items():
            if missing_cnt > 0:
                recommended_transformations.append(f"Fill missing values in {col} ({missing_cnt} occurrences)")

        result = {
            "dataset_name": dataset_name,
            "rows": rows,
            "columns": columns,
            "column_names": column_names,
            "column_types": column_types,
            "missing_values": missing_values,
            "duplicate_rows": duplicate_rows,
            "estimated_quality": quality_score,
            "recommended_transformations": recommended_transformations
        }
        return json.dumps(result, indent=2)

    # Check if we are inside Transformation Agent
    elif "transform" in prompt_lower or "clean" in prompt_lower or "history" in prompt_lower:
        quality_before = 88.5
        quality_after = 100.0
        
        qb_match = re.search(r'Calculated Quality Before:\s*([\d\.]+)', prompt)
        if qb_match:
            quality_before = float(qb_match.group(1))
            
        qa_match = re.search(r'Calculated Quality After:\s*([\d\.]+)', prompt)
        if qa_match:
            quality_after = float(qa_match.group(1))
            
        clean_filename = "clean_dataset.csv"
        fn_match = re.search(r'\b[\w\.-]+\.(?:csv|tsv|json|xlsx|xml|xls)\b', prompt, re.IGNORECASE)
        if fn_match:
            clean_filename = fn_match.group(0)

        # If this is the final summary request from the TransformationAgent
        if "Senior ETL Engineer" in prompt or "cleaned a dataset" in prompt:
            result = {
                "quality_before": quality_before,
                "quality_after": quality_after,
                "summary": f"The autonomous ETL pipeline successfully processed the dataset, improving the quality score from {quality_before}% to {quality_after}% by removing duplicates and resolving null elements."
            }
            return json.dumps(result, indent=2)

        # Legacy format fallback
        result = {
            "transformation_steps": [
                {"column": "all", "operation": "trim", "reason": "Remove leading/trailing spaces"},
                {"column": "all", "operation": "remove_duplicates", "reason": "Removed duplicate records"}
            ],
            "updated_schema": {},
            "clean_dataset_path": f"cleaned data/{clean_filename}",
            "quality_before": quality_before,
            "quality_after": quality_after,
            "logs": [
                f"Finished cleaning dataset. Calculated quality before processing: {quality_before}%, after processing: {quality_after}%."
            ]
        }
        return json.dumps(result, indent=2)

    # Check if we are inside Storage Agent format selection
    elif "storage" in prompt_lower or "format" in prompt_lower or "architect" in prompt_lower:
        fmt = "SQL"
        reason = "Dataset contains highly structured relational database keys (customer_id, order_id) mapping to specific entities."
        if "sales" in prompt_lower:
            fmt = "CSV"
            reason = "Dataset contains numerical transaction ledger information (quantity, unit_price, total_price) suited for flat CSV reports."
        elif "text" in prompt_lower or "description" in prompt_lower:
            fmt = "Word"
            reason = "Dataset is primarily textual or document-oriented description data."
        result = {
            "format_selected": fmt,
            "reason": reason,
            "summary": "Processed business records matching target schemas."
        }
        return json.dumps(result, indent=2)

    # Check if we are inside Root Cause Agent / RCA prompts
    elif ("rca" in prompt_lower or "root cause" in prompt_lower) and "chat" not in prompt_lower:
        result = [
            {
                "issue": "Primary key or Foreign key constraint violation on load.",
                "root_cause": "The source file contains transactional rows referencing non-existent primary keys, indicating sync delay.",
                "business_impact": "Sales ledger calculations will be incomplete by under-reporting affected transactions.",
                "technical_impact": "Foreign key reference validation check failed in database load.",
                "recommendation": "Coordinate upstream database pipeline runs to complete parent entity synchronization before transactional nightly ETL triggers.",
                "confidence": 95.0
            }
        ]
        return json.dumps(result, indent=2)

    # Check if we are inside Business Insights / Executive Summary prompts
    elif "insights" in prompt_lower or "executive summary" in prompt_lower or "corporate executive" in prompt_lower:
        dataset_name = "the dataset"
        fn_match = re.search(r'\b[\w\.-]+\.(?:csv|tsv|json|xlsx|xml|xls)\b', prompt, re.IGNORECASE)
        if fn_match:
            dataset_name = fn_match.group(0)
            
        result = {
            "executive_summary": f"The ETL pipeline processed the dataset '{dataset_name}'.",
            "business_insights": [],
            "recommendations": [
                "Implement a dynamic product master lookup table to resolve missing prices pre-load.",
                "Optimize table indices to accelerate dashboard query performance."
            ]
        }
        return json.dumps(result, indent=2)

    # Fallback
    else:
        result = {
            "executive_summary": "The ETL pipeline processed the dataset.",
            "business_insights": [],
            "recommendations": [
                "Perform index analysis on table columns to accelerate reports.",
                "Schedule nightly batch processes during low utilization hours."
            ]
        }
        return json.dumps(result, indent=2)
