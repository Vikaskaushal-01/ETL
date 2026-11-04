"""
Column-level lineage of a run, and its export as OpenLineage events (the open standard used by Airflow,
Dagster, Spark, dbt, Marquez, DataHub, Atlan and Unity Catalog).

The lineage is rebuilt from what the run recorded: the raw column names profiled by the Intake Agent, every
change the Transformation Agent made (renames, date standardization, filled values, dropped columns), the
rows removed by de-duplication or data contracts, and the table the Storage Agent loaded.
"""
import json
import logging
import os
import threading
import uuid
from datetime import datetime
from typing import Optional

from agents.transformation_agent.transformation_agent import standardize_column_name

logger = logging.getLogger("etl_lineage")

PRODUCER = "https://github.com/Vikaskaushal-01/ETL"
RUN_EVENT_SCHEMA = "https://openlineage.io/spec/2-0-2/OpenLineage.json#/$defs/RunEvent"
COLUMN_LINEAGE_SCHEMA = "https://openlineage.io/spec/facets/1-2-0/ColumnLineageDatasetFacet.json"
SCHEMA_FACET_SCHEMA = "https://openlineage.io/spec/facets/1-1-1/SchemaDatasetFacet.json"
JOB_TYPE_SCHEMA = "https://openlineage.io/spec/facets/2-0-3/JobTypeJobFacet.json"
DQ_ASSERTIONS_SCHEMA = "https://openlineage.io/spec/facets/1-0-1/DataQualityAssertionsDatasetFacet.json"
NAMESPACE = os.getenv("OPENLINEAGE_NAMESPACE", "agentic-etl")
OPENLINEAGE_URL = os.getenv("OPENLINEAGE_URL", "").rstrip("/")
OPENLINEAGE_API_KEY = os.getenv("OPENLINEAGE_API_KEY", "")
TYPED_TABLES = {
    "customers": ["customer_id", "customer_name", "email", "phone", "region"],
    "orders": ["order_id", "customer_id", "order_date", "status", "total_amount"],
    "sales": ["sale_id", "order_id", "product_id", "quantity", "unit_price", "total_price", "sale_date"],
}


def _stage(state: dict, name: str) -> dict:
    return (state.get("stages") or {}).get(name) or {}


def _dataset_type(state: dict) -> Optional[str]:
    storage = _stage(state, "storage")
    found = (storage.get("output") or {}).get("dataset_type")
    if found:
        return found
    for line in storage.get("logs") or []:  # runs recorded before dataset_type was stored
        if "staging_" in line:
            return line.split("staging_", 1)[1].split()[0].rstrip(".")
    return None


def _classify(reason: str) -> tuple:
    """(OpenLineage subtype, short label) of a recorded transformation step."""
    text = (reason or "").lower()
    if "header" in text:
        return "IDENTITY", "renamed"
    if "date" in text:
        return "TRANSFORMATION", "dates standardized"
    if "recalculated" in text:
        return "TRANSFORMATION", "derived"
    if "imputed" in text or "fill" in text:
        return "TRANSFORMATION", "missing values filled"
    if "drop" in text:
        return "TRANSFORMATION", "dropped"
    return "TRANSFORMATION", "changed"


def build_lineage(state: dict, filename: str, owner: Optional[str]) -> dict:
    """Datasets, column mappings and dataset-level steps of a run."""
    transform = _stage(state, "transformation")
    raw_columns = list((transform.get("input") or {}).get("columns_to_process") or [])
    history = (transform.get("metadata") or {}).get("transformation_history") or []
    clean_path = (transform.get("output") or {}).get("clean_dataset_path")
    dataset_type = _dataset_type(state)
    loaded = _stage(state, "storage").get("status") == "completed"

    by_column, dropped, dataset_steps = {}, set(), []
    for step in history:
        col, reason = str(step.get("column_name") or ""), step.get("reason") or ""
        if col == "all":
            dataset_steps.append({"type": "INDIRECT", "subtype": "FILTER", "description": reason})
            continue
        subtype, label = _classify(reason)
        if label == "dropped":
            dropped.add(standardize_column_name(col))
        if label == "renamed":
            continue  # renames are the mapping itself
        by_column.setdefault(standardize_column_name(col), []).append(
            {"type": "DIRECT", "subtype": subtype, "description": reason, "label": label, "masking": False})

    contract_drops = ((state.get("contracts") or {}).get("summary") or {}).get("rows_dropped")
    if contract_drops and not any("contract" in s["description"].lower() for s in dataset_steps):
        dataset_steps.append({"type": "INDIRECT", "subtype": "FILTER",
                              "description": f"Data contract removed {contract_drops} rows"})

    table_columns = TYPED_TABLES.get(dataset_type or "")
    columns = []
    for raw in raw_columns:
        clean = standardize_column_name(raw)
        steps = [{"type": "DIRECT", "subtype": "IDENTITY", "description": "Header standardized to snake_case",
                  "label": "renamed", "masking": False}] if clean != raw else []
        steps += by_column.get(clean, [])
        is_dropped = clean in dropped
        if not loaded or is_dropped:
            target_table = None
        elif table_columns is None:
            target_table = "staging_dataset.data_json"
        else:
            target_table = f"staging_{dataset_type}" if clean in table_columns else None
        columns.append({
            "source": raw,
            "target": None if is_dropped else clean,
            "dropped": is_dropped,
            "loaded_to": target_table,
            "transformations": steps,
        })

    datasets = [{"id": "raw", "kind": "file", "name": f"data/raw/{filename}", "label": filename}]
    if clean_path:
        datasets.append({"id": "clean", "kind": "file", "name": f"cleaned data/{os.path.basename(clean_path)}",
                         "label": f"Cleaned {os.path.basename(clean_path)}"})
    if loaded and dataset_type:
        datasets.append({"id": "staging", "kind": "table", "name": f"staging_{dataset_type}", "label": f"staging_{dataset_type}"})
        production = dataset_type if dataset_type in TYPED_TABLES else "production_dataset"
        datasets.append({"id": "production", "kind": "table", "name": production, "label": production})
    if _stage(state, "pbi").get("status") == "completed":
        tables = list(((_stage(state, "pbi").get("output") or {}).get("tables") or {}).keys())
        datasets.append({"id": "powerbi", "kind": "export", "name": "powerbi", "label": "Power BI model",
                         "tables": tables})
    edges = [{"source": a["id"], "target": b["id"]} for a, b in zip(datasets, datasets[1:])]
    return {
        "owner": owner,
        "dataset_type": dataset_type,
        "datasets": datasets,
        "edges": edges,
        "columns": columns,
        "dataset_steps": dataset_steps,
        "stats": {
            "source_columns": len(raw_columns),
            "renamed": sum(1 for c in columns if c["target"] and c["target"] != c["source"]),
            "changed": sum(1 for c in columns if any(s["subtype"] == "TRANSFORMATION" for s in c["transformations"])),
            "dropped": sum(1 for c in columns if c["dropped"]),
            "loaded": sum(1 for c in columns if c["loaded_to"]),
        },
    }
