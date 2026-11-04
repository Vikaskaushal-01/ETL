"""Unit tests for data contracts, observability baselines, the REST API connector and lineage."""
import json
from datetime import datetime, timedelta

import pandas as pd
import pytest

from backend.utils import contracts, lineage, observability


# ---------- data contracts ----------

def _df():
    return pd.DataFrame({
        "order_id": ["A1", "A2", "A3", "A3", None],
        "amount": [10, -5, "abc", 20, 30],
        "status": ["paid", "PAID", "refunded", "lost", "paid"],
        "email": ["a@x.com", "bad", "c@y.org", None, "e@z.io"],
    })


def test_validate_rejects_bad_rules():
    with pytest.raises(contracts.ContractError):
        contracts.validate_rules([{"type": "nope", "column": "x"}])
    with pytest.raises(contracts.ContractError):
        contracts.validate_rules([{"type": "row_count_min", "params": {"value": 1}, "action": "drop"}])
    with pytest.raises(contracts.ContractError):
        contracts.validate_rules([{"type": "between", "column": "x", "params": {"min": 5, "max": 1}}])
    with pytest.raises(contracts.ContractError):
        contracts.validate_rules([{"type": "regex", "column": "x", "params": {"pattern": "("}}])


def test_warn_drop_and_fail_actions():
    rules = contracts.validate_rules([
        {"type": "not_null", "column": "order_id", "action": "drop"},
        {"type": "unique", "column": "order_id", "action": "warn"},
        {"type": "between", "column": "amount", "params": {"min": 0}, "action": "drop"},
        {"type": "allowed_values", "column": "status", "params": {"values": "paid, refunded"}, "action": "warn"},
        {"type": "row_count_min", "params": {"value": 2}, "action": "fail"},
    ])
    out, results, failed = contracts.evaluate(_df(), rules)
    by_type = {r["type"]: r for r in results}
    assert not failed
    assert by_type["not_null"]["status"] == "dropped" and by_type["not_null"]["failed_rows"] == 1
    assert by_type["unique"]["failed_rows"] == 2  # both A3 rows; the empty id is not a duplicate
    assert by_type["between"]["failed_rows"] == 2  # -5 and the text "abc"
    assert by_type["allowed_values"]["failed_rows"] == 1  # "lost" (case-insensitive by default)
    assert by_type["row_count_min"]["status"] == "passed"
    # Rows dropped by both drop rules: the null id and amounts -5 / "abc"
    assert len(out) == 2
    summary = contracts.summarize(results, 5, len(out))
    assert summary["rows_dropped"] == 3 and summary["dropped"] == 2 and summary["warned"] == 2


def test_fail_rule_and_missing_column():
    rules = contracts.validate_rules([
        {"type": "column_exists", "column": "customer_id", "action": "fail"},
        {"type": "not_null", "column": "Order ID", "action": "warn"},  # matched to order_id
    ])
    _, results, failed = contracts.evaluate(_df(), rules)
    assert failed and results[0]["status"] == "failed"
    assert results[1]["status"] == "warned" and results[1]["failed_rows"] == 1


def test_regex_type_and_null_pct():
    rules = contracts.validate_rules([
        {"type": "regex", "column": "email", "params": {"pattern": r"[^@\s]+@[^@\s]+\.\w+"}},
        {"type": "type", "column": "amount", "params": {"kind": "numeric"}},
        {"type": "max_null_pct", "column": "email", "params": {"max": 10}},
    ])
    _, results, _ = contracts.evaluate(_df(), rules)
    assert [r["failed_rows"] for r in results[:2]] == [1, 1]
    assert results[2]["status"] == "warned" and results[2]["detail"] == "20% empty"


def test_suggest_rules_pass_on_their_own_data():
    df = pd.DataFrame({
        "customer_id": [f"C{i}" for i in range(40)],
        "region": ["North", "South", "East", "West"] * 10,
        "spend": [float(i) for i in range(40)],
        "email": [f"u{i}@example.com" for i in range(40)],
    })
    rules = contracts.suggest_rules(df)
    types = {(r["type"], r["column"]) for r in rules}
    assert ("unique", "customer_id") in types
    assert ("allowed_values", "region") in types
    assert ("between", "spend") in types
    assert ("regex", "email") in types
    _, results, failed = contracts.evaluate(df, rules)
    assert not failed and all(r["status"] == "passed" for r in results)


def test_dataset_pattern_matching():
    assert contracts.matches_dataset("sales_*.csv", "Sales_2026.CSV")
    assert not contracts.matches_dataset("sales_*.csv", "orders.csv")
    assert not contracts.matches_dataset("", "orders.csv")


# ---------- observability ----------

@pytest.mark.parametrize("name,key", [
    ("realtime_orders_20260916_183805_c2346c.csv", "realtime_orders.csv"),
    ("pokemon_episodes_2026_08_01.csv", "pokemon_episodes.csv"),
    ("Sales (2).xlsx", "sales.xlsx"),
    ("customers.csv", "customers.csv"),
])
def test_dataset_key(name, key):
    assert observability.dataset_key(name) == key


def test_anomalies_use_robust_baseline():
    history = [{"rows": r, "quality_after": q, "missing_pct": 1.0} for r, q in
               [(1000, 98), (1010, 97.5), (990, 98.2), (1005, 97.9), (995, 98.1)]]
    assert observability.detect_anomalies({"rows": 1002, "quality_after": 98.0, "missing_pct": 1.0}, history) == []
    found = observability.detect_anomalies({"rows": 120, "quality_after": 99.9, "missing_pct": 1.0}, history)
    assert [a["metric"] for a in found] == ["rows"]  # higher quality is never an anomaly
    assert found[0]["direction"] == "down" and found[0]["severity"] == "high"
    # Too little history: nothing is judged
    assert observability.detect_anomalies({"rows": 1}, history[:2]) == []


def test_freshness_late_detection():
    now = datetime(2026, 11, 4, 12, 0)
    hourly = [now - timedelta(hours=h) for h in (10, 9, 8, 7, 6)]
    fresh = observability.freshness(hourly, now)
    assert fresh["expected_every_s"] == 3600 and fresh["late"]
    assert not observability.freshness(hourly + [now - timedelta(minutes=30)], now)["late"]


def test_run_metrics_from_state():
    state = {"status": "Success", "execution_time": 4.2, "stages": {
        "intake": {"output": {"rows": 100, "columns": 4, "missing_values_total": 8, "duplicate_rows": 5}},
        "transformation": {"output": {"quality_after": 97.5}},
        "storage": {"output": {"rows_loaded": 90, "rows_rejected": 10}},
    }}
    m = observability.run_metrics(state)
    assert m == {"rows": 100, "columns": 4, "missing_pct": 2.0, "duplicate_pct": 5.0, "rejected_pct": 10.0,
                 "quality_after": 97.5, "execution_time": 4.2}


# ---------- lineage ----------

def _state():
    return {
        "status": "Success", "start_time": "2026-11-04T10:00:00", "end_time": "2026-11-04T10:00:05",
        "contracts": {"summary": {"rows_dropped": 2}, "results": [
            {"rule": "order_id is never empty", "status": "dropped", "column": "order_id"}]},
        "stages": {
            "transformation": {
                "input": {"columns_to_process": ["Order ID", "Order Date", "Notes", "total_amount"]},
                "output": {"clean_dataset_path": "/x/cleaned data/orders.csv"},
                "metadata": {"transformation_history": [
                    {"column_name": "Order ID", "reason": "Standardized column header naming format"},
                    {"column_name": "order_date", "reason": "Standardized date values"},
                    {"column_name": "notes", "reason": "Applied custom rule: drop column"},
                    {"column_name": "all", "reason": "Removed 3 duplicate records"},
                ]},
            },
            "storage": {"status": "completed", "output": {"dataset_type": "orders"}},
            "pbi": {"status": "completed", "output": {"tables": {"FactOrders": 10}}},
        },
    }


def test_column_lineage_and_openlineage_events():
    lin = lineage.build_lineage(_state(), "orders.csv", "a@b.com")
    cols = {c["source"]: c for c in lin["columns"]}
    assert cols["Order ID"]["target"] == "order_id" and cols["Order ID"]["loaded_to"] == "staging_orders"
    assert cols["Notes"]["dropped"] and cols["Notes"]["target"] is None
    assert any(t["label"] == "dates standardized" for t in cols["Order Date"]["transformations"])
    assert [d["id"] for d in lin["datasets"]] == ["raw", "clean", "staging", "production", "powerbi"]
    assert len(lin["dataset_steps"]) == 2  # dedupe + contract drop

    events = lineage.openlineage_events("batch_1", _state(), lin, "orders.csv")
    assert [e["eventType"] for e in events] == ["START", "COMPLETE"]
    assert events[0]["run"]["runId"] == events[1]["run"]["runId"]
    clean_out = events[1]["outputs"][0]
    fields = clean_out["facets"]["columnLineage"]["fields"]
    assert fields["order_id"]["inputFields"][0]["field"] == "Order ID"
    assert "notes" not in fields
    assert clean_out["facets"]["dataQualityAssertions"]["assertions"][0]["success"] is False
    assert events[1]["eventTime"].endswith("Z")
