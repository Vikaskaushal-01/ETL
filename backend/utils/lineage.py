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


def _owner_namespace(owner: Optional[str]) -> str:
    return f"{NAMESPACE}://{(owner or 'shared').replace('@', '_at_')}"


def _facet(schema_url: str, **body) -> dict:
    return {"_producer": PRODUCER, "_schemaURL": schema_url, **body}


def _ol_transformations(steps: list) -> list:
    return [{k: s[k] for k in ("type", "subtype", "description", "masking")} for s in steps] or \
           [{"type": "DIRECT", "subtype": "IDENTITY", "description": "", "masking": False}]


def openlineage_events(batch_id: str, state: dict, lineage: dict, filename: str) -> list:
    """START and COMPLETE/FAIL RunEvents for the run, with schema, column lineage and quality facets."""
    ns = _owner_namespace(lineage.get("owner"))
    run_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{NAMESPACE}/{batch_id}"))
    job = {
        "namespace": NAMESPACE,
        "name": f"agentic_etl.{os.path.splitext(filename or 'dataset')[0]}",
        "facets": {"jobType": _facet(JOB_TYPE_SCHEMA, processingType="BATCH", integration="AGENTIC_ETL", jobType="JOB")},
    }
    by_id = {d["id"]: d for d in lineage["datasets"]}
    raw = by_id["raw"]
    inputs = [{
        "namespace": ns, "name": raw["name"],
        "facets": {"schema": _facet(SCHEMA_FACET_SCHEMA, fields=[{"name": c["source"]} for c in lineage["columns"]])},
    }]

    def column_facet(source_ds: dict, only_loaded: bool) -> dict:
        fields = {}
        for c in lineage["columns"]:
            if not c["target"] or (only_loaded and not c["loaded_to"]):
                continue
            fields[c["target"]] = {"inputFields": [{
                "namespace": ns, "name": source_ds["name"], "field": c["source"],
                "transformations": _ol_transformations(c["transformations"]),
            }]}
        body = {"fields": fields}
        if lineage["dataset_steps"]:
            body["dataset"] = [{"namespace": ns, "name": source_ds["name"], "field": c["source"],
                                "transformations": [{**s, "masking": False} for s in lineage["dataset_steps"]]}
                               for c in lineage["columns"] if c["target"]][:50]
        return _facet(COLUMN_LINEAGE_SCHEMA, **body)

    outputs = []
    target_fields = [{"name": c["target"]} for c in lineage["columns"] if c["target"]]
    if "clean" in by_id:
        facets = {"schema": _facet(SCHEMA_FACET_SCHEMA, fields=target_fields), "columnLineage": column_facet(raw, False)}
        contract_results = (state.get("contracts") or {}).get("results") or []
        if contract_results:
            facets["dataQualityAssertions"] = _facet(DQ_ASSERTIONS_SCHEMA, assertions=[
                {"assertion": r["rule"], "success": r["status"] == "passed", **({"column": r["column"]} if r.get("column") else {})}
                for r in contract_results])
        outputs.append({"namespace": ns, "name": by_id["clean"]["name"], "facets": facets})
    for table_id in ("staging", "production"):
        if table_id in by_id:
            outputs.append({"namespace": f"{NAMESPACE}://warehouse", "name": by_id[table_id]["name"],
                            "facets": {"columnLineage": column_facet(raw, True)}})

    status = state.get("status")
    start = state.get("start_time") or datetime.utcnow().isoformat()
    end = state.get("end_time") or datetime.utcnow().isoformat()
    base = {"producer": PRODUCER, "schemaURL": RUN_EVENT_SCHEMA, "run": {"runId": run_id}, "job": job}
    events = [{**base, "eventType": "START", "eventTime": _z(start), "inputs": inputs, "outputs": []}]
    if status and status != "Running":
        events.append({**base, "eventType": "FAIL" if status == "Failed" else "COMPLETE", "eventTime": _z(end),
                       "inputs": inputs, "outputs": outputs})
    return events


def _z(iso: str) -> str:
    return iso if iso.endswith("Z") or "+" in iso[10:] else f"{iso}Z"


def emit_openlineage(events: list) -> None:
    """POSTs events to OPENLINEAGE_URL (e.g. Marquez: http://marquez:5000) in the background, if configured."""
    if not OPENLINEAGE_URL or not events:
        return

    def send():
        import httpx
        headers = {"Content-Type": "application/json"}
        if OPENLINEAGE_API_KEY:
            headers["Authorization"] = f"Bearer {OPENLINEAGE_API_KEY}"
        for event in events:
            try:
                r = httpx.post(f"{OPENLINEAGE_URL}/api/v1/lineage", content=json.dumps(event), headers=headers, timeout=10)
                if r.status_code >= 300:
                    logger.warning(f"OpenLineage endpoint answered HTTP {r.status_code} for {event['eventType']}")
            except Exception as e:
                logger.warning(f"Could not send OpenLineage event: {e}")
                return

    threading.Thread(target=send, name="openlineage", daemon=True).start()
