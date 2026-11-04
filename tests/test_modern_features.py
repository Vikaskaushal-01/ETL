"""Unit tests for data contracts, observability baselines, the REST API connector and lineage."""
import json
from datetime import datetime, timedelta

import pandas as pd
import pytest

from backend.utils import contracts


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
