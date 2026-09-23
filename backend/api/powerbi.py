import csv
import json
import os
import logging
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session
from sqlalchemy import text, bindparam
from backend.database.mysql import get_db, check_database_health, engine, SessionLocal
from backend.core.security import DEFAULT_ADMIN_EMAIL
from backend.utils.account_utils import get_user_path, get_user_batch_ids

router = APIRouter(prefix="/powerbi", tags=["Power BI"])
logger = logging.getLogger("etl_powerbi_api")

# Star-schema tables exported for Power BI: name -> (SQL, how rows are scoped to the caller)
EXPORT_TABLES = {
    "FactSales": ("SELECT sale_id, order_id, product_id, quantity, unit_price, total_price, sale_date FROM sales WHERE uploaded_by = :email", "user"),
    "FactOrders": ("SELECT order_id, customer_id, order_date, status, total_amount FROM orders WHERE uploaded_by = :email", "user"),
    "DimCustomer": ("SELECT customer_id, customer_name, email, phone, region FROM customers WHERE uploaded_by = :email", "user"),
    "FactExecution": ("SELECT pipeline_id, start_time, end_time, execution_time, status FROM pipeline_logs WHERE pipeline_id IN :pids", "pipelines"),
    "FactDataQuality": ("SELECT batch_id, missing_values, duplicate_count, quality_score, schema_match FROM quality_reports WHERE batch_id IN :bids", "batches"),
    "DimAgent": ("SELECT batch_id, agent_name, task, confidence, execution_time, timestamp FROM agent_logs WHERE batch_id IN :bids", "batches"),
}


def _export_dir(email: str) -> str:
    return os.path.dirname(get_user_path(email, "powerbi/dummy.txt"))


def _refresh_meta_path(email: str) -> str:
    return os.path.join(_export_dir(email), "refresh_history.json")


def _read_refresh_meta(email: str) -> dict:
    try:
        with open(_refresh_meta_path(email), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"last_refresh": None, "refresh_count": 0, "tables": {}}


def _query_table(db: Session, name: str, email: str, batch_ids: list):
    sql, scope = EXPORT_TABLES[name]
    stmt = text(sql)
    params = {"email": email}
    if scope == "pipelines":
        if not batch_ids:
            return [], []
        stmt = stmt.bindparams(bindparam("pids", expanding=True))
        params = {"pids": [f"pipe_{b}" for b in batch_ids]}
    elif scope == "batches":
        if not batch_ids:
            return [], []
        stmt = stmt.bindparams(bindparam("bids", expanding=True))
        params = {"bids": batch_ids}
    result = db.execute(stmt, params)
    return list(result.keys()), result.fetchall()


def export_powerbi_dataset(email: Optional[str]) -> dict:
    """
    Writes the caller's star schema (facts + dimensions) as CSV files under
    Accounts/<user>/powerbi/, which Power BI Desktop can load via Get Data > Folder or Text/CSV.
    """
    email = email or DEFAULT_ADMIN_EMAIL
    db = SessionLocal()
    try:
        batch_ids = get_user_batch_ids(db, email)
        export_dir = _export_dir(email)
        tables = {}
        for name in EXPORT_TABLES:
            columns, rows = _query_table(db, name, email, batch_ids)
            path = os.path.join(export_dir, f"{name}.csv")
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(columns or [])
                writer.writerows(rows)
            tables[name] = {"rows": len(rows), "file": path.replace("\\", "/")}
    finally:
        db.close()

    meta = _read_refresh_meta(email)
    meta.update({
        "last_refresh": datetime.utcnow().isoformat(),
        "refresh_count": int(meta.get("refresh_count") or 0) + 1,
        "tables": tables,
    })
    with open(_refresh_meta_path(email), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    summary = ", ".join(f"{name}={info['rows']}" for name, info in tables.items())
    logger.info(f"Exported Power BI dataset for {email}: {summary}")
    return meta


@router.get("/status")
def get_powerbi_status(db: Session = Depends(get_db), x_user_email: Optional[str] = Header(None)):
    """Live connector status, the caller's row counts per model table and the last export."""
    email = x_user_email or DEFAULT_ADMIN_EMAIL
    batch_ids = get_user_batch_ids(db, email)
    counts = {}
    for name in EXPORT_TABLES:
        try:
            counts[name] = len(_query_table(db, name, email, batch_ids)[1])
        except Exception as e:
            logger.warning(f"Could not count {name}: {e}")
            counts[name] = 0

    db_health = check_database_health()
    url = engine.url
    is_mysql = db_health.get("dialect") == "mysql"
    meta = _read_refresh_meta(email)
    return {
        "connector": {
            "server": f"{url.host}:{url.port or 3306}" if is_mysql else "local file",
            "database": url.database if is_mysql else os.path.basename(url.database or "agentic_ai_etl.db"),
            "driver": "MySQL" if is_mysql else "SQLite (local fallback)",
            "status": "Connected" if db_health.get("connected") else "Disconnected",
            "latency_ms": db_health.get("latency_ms"),
        },
        "dataset": {
            "status": "Exported" if meta.get("last_refresh") else "Never exported",
            "last_refresh": meta.get("last_refresh"),
            "total_refreshes": meta.get("refresh_count", 0),
            "export_folder": _export_dir(email).replace("\\", "/"),
        },
        "metrics": {
            "fact_sales_rows": counts.get("FactSales", 0),
            "fact_orders_rows": counts.get("FactOrders", 0),
            "dim_customer_rows": counts.get("DimCustomer", 0),
            "fact_execution_rows": counts.get("FactExecution", 0),
        },
        "tables": [
            {"name": name, "rows": counts.get(name, 0), "file": (meta.get("tables", {}).get(name) or {}).get("file")}
            for name in EXPORT_TABLES
        ],
    }


@router.post("/refresh")
def trigger_powerbi_refresh(x_user_email: Optional[str] = Header(None)):
    """Re-exports the caller's Power BI dataset files from the current warehouse contents."""
    meta = export_powerbi_dataset(x_user_email)
    return {
        "status": "Success",
        "message": "Power BI dataset exported successfully.",
        "last_refresh": meta["last_refresh"],
        "total_refreshes": meta["refresh_count"],
        "tables": meta["tables"],
    }


@router.get("/schema")
def get_powerbi_schema():
    """
    Exposes Power BI Star/Snowflake schema definitions and model relationships.
    """
    return {
        "fact_tables": [
            {
                "name": "FactSales",
                "source": "sales",
                "columns": ["sale_id", "order_id", "product_id", "quantity", "unit_price", "total_price", "sale_date"],
                "relationships": [{"target": "FactOrders", "fk": "order_id"}]
            },
            {
                "name": "FactOrders",
                "source": "orders",
                "columns": ["order_id", "customer_id", "order_date", "status", "total_amount"],
                "relationships": [{"target": "DimCustomer", "fk": "customer_id"}]
            },
            {
                "name": "FactExecution",
                "source": "pipeline_logs",
                "columns": ["pipeline_id", "start_time", "end_time", "execution_time", "status"],
                "relationships": []
            },
            {
                "name": "FactDataQuality",
                "source": "quality_reports",
                "columns": ["batch_id", "missing_values", "duplicate_count", "quality_score", "schema_match"],
                "relationships": [{"target": "DimAgent", "fk": "batch_id"}]
            }
        ],
        "dimension_tables": [
            {
                "name": "DimCustomer",
                "source": "customers",
                "columns": ["customer_id", "customer_name", "email", "phone", "region"]
            },
            {
                "name": "DimAgent",
                "source": "agent_logs",
                "columns": ["batch_id", "agent_name", "task", "confidence", "execution_time", "timestamp"]
            }
        ]
    }


@router.get("/measures")
def get_powerbi_dax_measures():
    """
    Returns pre-configured DAX calculation measures and metadata for semantic model consumption.
    """
    return {
        "measures": [
            {
                "name": "Total Revenue",
                "formula": "SUM(FactSales[total_price])",
                "category": "Sales Intelligence",
                "format_string": "$#,##0.00"
            },
            {
                "name": "Average Order Value",
                "formula": "DIVIDE(SUM(FactOrders[total_amount]), COUNTROWS(FactOrders), 0)",
                "category": "Order Metrics",
                "format_string": "$#,##0.00"
            },
            {
                "name": "Pipeline Success Rate",
                "formula": "DIVIDE(CALCULATE(COUNTROWS(FactExecution), FactExecution[status] IN {\"Success\", \"Passed with Warnings\"}), COUNTROWS(FactExecution), 0)",
                "category": "Data Ops Telemetry",
                "format_string": "0.0%"
            },
            {
                "name": "Total Units Sold",
                "formula": "SUM(FactSales[quantity])",
                "category": "Inventory & Volume",
                "format_string": "#,##0"
            },
            {
                "name": "Average Data Quality",
                "formula": "AVERAGE(FactDataQuality[quality_score])",
                "category": "Data Quality",
                "format_string": "0.0"
            }
        ]
    }
