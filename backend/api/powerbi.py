import time
import logging
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from backend.database.mysql import get_db
from typing import Dict, Any

router = APIRouter(prefix="/powerbi", tags=["Power BI"])
logger = logging.getLogger("etl_powerbi_api")

# State tracker for Power BI refresh
powerbi_state = {
    "last_refresh": datetime.now().isoformat(),
    "refresh_count": 0,
    "status": "Online / Synced"
}

@router.get("/status")
def get_powerbi_status(db: Session = Depends(get_db)):
    """
    Returns Power BI connection metrics, database source status, and dataset refresh history.
    """
    customers_cnt = 0
    orders_cnt = 0
    sales_cnt = 0
    pipelines_cnt = 0
    
    try:
        customers_cnt = db.execute(text("SELECT COUNT(*) FROM customers")).scalar() or 0
    except Exception:
        pass
    try:
        orders_cnt = db.execute(text("SELECT COUNT(*) FROM orders")).scalar() or 0
    except Exception:
        pass
    try:
        sales_cnt = db.execute(text("SELECT COUNT(*) FROM sales")).scalar() or 0
    except Exception:
        pass
    try:
        pipelines_cnt = db.execute(text("SELECT COUNT(*) FROM pipeline_logs")).scalar() or 0
    except Exception:
        pass

    return {
        "connector": {
            "server": "localhost:3306",
            "database": "agentic_ai_etl",
            "driver": "MySQL Connector / Python Engine",
            "status": "Connected"
        },
        "dataset": {
            "status": powerbi_state["status"],
            "last_refresh": powerbi_state["last_refresh"],
            "total_refreshes": powerbi_state["refresh_count"],
            "target_workspace": "Control AI Workspace"
        },
        "metrics": {
            "fact_sales_rows": sales_cnt,
            "fact_orders_rows": orders_cnt,
            "dim_customer_rows": customers_cnt,
            "fact_execution_rows": pipelines_cnt
        }
    }

@router.post("/refresh")
def trigger_powerbi_refresh():
    """
    Triggers a manual refresh event for Power BI datasets.
    """
    powerbi_state["last_refresh"] = datetime.now().isoformat()
    powerbi_state["refresh_count"] += 1
    powerbi_state["status"] = "Refreshing..."
    
    logger.info(f"Triggered manual Power BI dataset refresh request #{powerbi_state['refresh_count']}")
    
    # Simulate async gateway sync completion
    powerbi_state["status"] = "Online / Synced"
    
    return {
        "status": "Success",
        "message": "Power BI dataset refresh issued successfully.",
        "last_refresh": powerbi_state["last_refresh"],
        "total_refreshes": powerbi_state["refresh_count"]
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
                "relationships": [{"target": "DimDate", "fk": "sale_date"}]
            },
            {
                "name": "FactOrders",
                "source": "orders",
                "columns": ["order_id", "customer_id", "order_date", "status", "total_amount"],
                "relationships": [{"target": "DimCustomer", "fk": "customer_id"}, {"target": "DimDate", "fk": "order_date"}]
            },
            {
                "name": "FactExecution",
                "source": "pipeline_logs & agent_logs",
                "columns": ["pipeline_id", "start_time", "end_time", "execution_time", "status"],
                "relationships": [{"target": "DimAgent", "fk": "agent_name"}]
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
                "columns": ["agent_id", "agent_name", "role"]
            },
            {
                "name": "DimDate",
                "source": "DAX CALENDAR",
                "columns": ["Date", "Year", "Month", "Quarter", "DayOfWeek"]
            }
        ]
    }
