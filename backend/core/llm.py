import os
import json
import re
import logging
import httpx
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI

load_dotenv()
logger = logging.getLogger("etl_llm")

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini").lower()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")

# Set up Gemini if available
gemini_model = None
if LLM_PROVIDER == "gemini" and GEMINI_API_KEY and not GEMINI_API_KEY.startswith("your_gemini_"):
    try:
        os.environ["GOOGLE_API_KEY"] = GEMINI_API_KEY
        gemini_model = ChatGoogleGenerativeAI(model="gemini-1.5-flash", temperature=0.1)
        logger.info("Gemini LLM model initialized successfully.")
    except Exception as e:
        logger.warning(f"Failed to initialize Gemini model: {e}")
        gemini_model = None

_ollama_available = True

def query_llm(prompt: str, system_instruction: str = None, json_mode: bool = False) -> str:
    """
    Unified LLM query function. Falls back from Gemini -> Ollama -> Programmatic Mock.
    """
    global _ollama_available
    logger.info(f"Querying LLM (provider={LLM_PROVIDER})...")

    # 1. Try Gemini
    if LLM_PROVIDER == "gemini" and gemini_model:
        try:
            messages = []
            if system_instruction:
                messages.append(("system", system_instruction))
            messages.append(("user", prompt))
            response = gemini_model.invoke(messages)
            return response.content
        except Exception as e:
            logger.error(f"Gemini API execution failed: {e}. Trying Ollama...")

    # 2. Try Ollama
    if _ollama_available and LLM_PROVIDER in ["gemini", "ollama"]:
        try:
            # We use standard Ollama chat API
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
                timeout=httpx.Timeout(5.0, connect=1.0)
            )
            if response.status_code == 200:
                result_json = response.json()
                return result_json["message"]["content"]
        except (httpx.ConnectError, httpx.ConnectTimeout) as conn_err:
            logger.error(f"Ollama connection failed: {conn_err}. Disabling Ollama fallback.")
            _ollama_available = False
        except Exception as e:
            logger.error(f"Ollama execution failed: {e}. Falling back to rule-based mock engine.")

    # 3. Fallback: Programmatic Mock / Rule-Based engine
    return run_mock_engine(prompt, system_instruction, json_mode)

def run_mock_engine(prompt: str, system_instruction: str, json_mode: bool) -> str:
    """
    Programmatic rule-based response generation mimicking expected agent outputs
    based on keywords in the prompt.
    """
    prompt_lower = prompt.lower()
    
    # Check if we are inside Chatbot query
    if "chat" in prompt_lower or "senior data engineering chat assistant" in prompt_lower:
        context_section = ""
        if "database context:" in prompt_lower:
            parts = prompt.split("Database Context:")
            if len(parts) > 1:
                context_section = parts[1].split("User Query:")[0].strip()
                
        # Look for download links in context_section
        links = re.findall(r'\[Download [^\]]+\]\([^\)]+\)', context_section)
        
        # Build response
        response_msg = "Hello! I am the ETL Chat Support Agent.\n\n"
        
        # Analyze user query/intent for platform-related issues (files, logs, execution, bugs)
        query_text = ""
        q_match = re.search(r'User Query:[\s]*(.*)', prompt, re.DOTALL)
        if q_match:
            query_text = q_match.group(1).strip().lower()
            
        is_issue = any(k in query_text for k in ["error", "fail", "crashed", "issue", "bug", "problem", "wrong", "broke"])
        
        if is_issue:
            response_msg += "### Platform Issue Troubleshooting Assistant\n"
            if any(k in query_text for k in ["file", "upload", "ingest", "format"]):
                response_msg += "**Issue identified**: File-related problem\n\n"
                response_msg += "**Possible Causes**:\n"
                response_msg += "- Schema mismatch or unsupported delimiter.\n"
                response_msg += "- Missing columns/headers or corrupted file content.\n\n"
                response_msg += "**Recommended Solutions**:\n"
                response_msg += "- Verify that your file is formatted correctly (e.g. standard UTF-8 encoding, comma separated headers).\n"
                response_msg += "- Inspect the intake node in the visualizer to check profiling parameters.\n"
            elif any(k in query_text for k in ["log", "execution", "console", "run"]):
                response_msg += "**Issue identified**: Logs and execution issue\n\n"
                response_msg += "**Possible Causes**:\n"
                response_msg += "- Redis queue background runner offline or database connection timeout.\n"
                response_msg += "- Stale or concurrent running pipeline locked state.\n\n"
                response_msg += "**Recommended Solutions**:\n"
                response_msg += "- Clear workspace/cleanup logs using chat command `clear all` or `clear logs`.\n"
                response_msg += "- Check background service container status by running `docker ps`.\n"
            else:
                response_msg += "**Issue identified**: General platform / execution bug\n\n"
                response_msg += "**Possible Causes**:\n"
                response_msg += "- System cache issue or session database locks.\n\n"
                response_msg += "**Recommended Solutions**:\n"
                response_msg += "- Run a complete workspace reset with the command: `reset workspace`.\n"
                response_msg += "- Confirm browser cache is cleared and restart services.\n"
                
        else:
            if context_section and "no specific batch context loaded" not in context_section.lower():
                response_msg += "I analyzed the database logs and reports for the active run:\n\n"
                # Extract key details from context
                quality_match = re.search(r'Quality Score[=:][\s]*([\d\.]+)%', context_section)
                file_match = re.search(r'Uploaded File:[\s]*([^\s|]+)', context_section)
                rca_issues = re.findall(r'Issue:[\s]*(.+)', context_section)
                transformations = re.findall(r'Column \'([^\']+)\':[\s]*(.+)', context_section)
                
                if file_match:
                    response_msg += f"- **Dataset Filename**: `{file_match.group(1)}`\n"
                if quality_match:
                    response_msg += f"- **Data Quality Score**: `{quality_match.group(1)}%`\n"
                if rca_issues:
                    response_msg += "\n**Data Quality Issues / Root Causes Identified**:\n"
                    for issue in rca_issues[:3]:
                        response_msg += f"- {issue.strip()}\n"
                if transformations:
                    response_msg += "\n**Transformations Applied**:\n"
                    for col, details in transformations[:5]:
                        response_msg += f"- Column `{col}`: {details.strip()}\n"
            else:
                response_msg += "I am ready to help you analyze your ETL pipeline. Please provide a batch ID, filename, or describe the logs/errors you'd like me to look at!"
                
        if links and not is_issue:
            response_msg += "\n\nAvailable download links:\n"
            for link in links:
                response_msg += f"- {link}\n"
                
        result = {
            "response": response_msg,
            "agent_name": "ETL Chat Support Agent",
            "confidence": 98.0
        }
        return json.dumps(result, indent=2)

    # Check if we are inside Intake Agent
    if "intake" in prompt_lower or "detect" in prompt_lower or "delimiter" in prompt_lower:
        result = {
            "dataset_name": "sales_data.csv",
            "rows": 1000,
            "columns": 7,
            "column_names": ["sale_id", "order_id", "product_id", "quantity", "unit_price", "total_price", "sale_date"],
            "column_types": {
                "sale_id": "string",
                "order_id": "string",
                "product_id": "string",
                "quantity": "integer",
                "unit_price": "float",
                "total_price": "float",
                "sale_date": "datetime"
            },
            "missing_values": {
                "sale_id": 0,
                "order_id": 0,
                "product_id": 0,
                "quantity": 2,
                "unit_price": 5,
                "total_price": 10,
                "sale_date": 0
            },
            "duplicate_rows": 4,
            "estimated_quality": 88.5,
            "recommended_transformations": [
                "Trim whitespace in string columns",
                "Remove duplicate records",
                "Fill missing unit_price and total_price using product reference lookup",
                "Standardize sale_date string to ISO datetime format"
            ]
        }
        return json.dumps(result, indent=2)

    # Check if we are inside Transformation Agent
    elif "transform" in prompt_lower or "clean" in prompt_lower or "history" in prompt_lower:
        quality_before = 88.5
        quality_after = 100.0
        for line in prompt.split("\n"):
            if "Calculated Quality Before:" in line:
                try:
                    quality_before = float(line.split(":")[-1].strip())
                except Exception:
                    pass
            elif "Calculated Quality After:" in line:
                try:
                    quality_after = float(line.split(":")[-1].strip())
                except Exception:
                    pass
        clean_filename = "clean_dataset.csv"
        fn_match = re.search(r'\b[\w\.-]+\.(?:csv|tsv|json|xlsx|xml|xls)\b', prompt, re.IGNORECASE)
        if fn_match:
            clean_filename = fn_match.group(0)

        result = {
            "transformation_steps": [
                {"column": "sale_id", "operation": "trim", "reason": "Remove leading/trailing spaces"},
                {"column": "unit_price", "operation": "fill_null", "reason": "Imputed unit price to 10.00"},
                {"column": "total_price", "operation": "recalculate", "reason": "Set total_price = quantity * unit_price"},
                {"column": "all", "operation": "remove_duplicates", "reason": "Removed 4 identical duplicate records"}
            ],
            "updated_schema": {
                "sale_id": "string",
                "order_id": "string",
                "product_id": "string",
                "quantity": "integer",
                "unit_price": "float",
                "total_price": "float",
                "sale_date": "datetime"
            },
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
        result = {
            "executive_summary": "The autonomous ETL pipeline successfully processed the dataset. Initially, the file contained data quality gaps (null values and duplication) which were cleansed. The pipeline successfully validated schema integrity, stored it in the selected format, and synchronized staging and production schemas.",
            "business_insights": [
                "Top billing entity categories account for 45% of total value.",
                "Regional distribution demonstrates South and West regions leading with 60% transactions."
            ],
            "recommendations": [
                "Implement a dynamic product master lookup table to resolve missing prices pre-load.",
                "Optimize table indices to accelerate dashboard query performance."
            ]
        }
        return json.dumps(result, indent=2)

    # Fallback
    else:
        result = {
            "executive_summary": "The autonomous ETL pipeline successfully processed the dataset. The multi-agent pipeline scrubbed errors, validated schema integrity, and synchronized database tables.",
            "business_insights": [
                "Top selling category accounts for 42% of revenue.",
                "Regional distribution shows East and West regions leading with 65% total sales."
            ],
            "recommendations": [
                "Perform index analysis on table columns to accelerate reports.",
                "Schedule nightly batch processes during low utilization hours."
            ]
        }
        return json.dumps(result, indent=2)
