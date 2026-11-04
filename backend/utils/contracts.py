"""
Data contracts: declarative expectations a dataset must meet, checked on the cleaned data before it is loaded.

Modeled on Databricks Lakeflow expectations, Great Expectations / Soda checks and dbt model contracts.
Every rule has an action:
  warn - the run continues and the violation is recorded (default)
  drop - rows that break a row-level rule are removed before loading and counted
  fail - the run stops before anything is loaded

Rules never run code supplied by the user: each rule type is a fixed check with typed parameters.
"""
import fnmatch
import re
from typing import Optional

import pandas as pd

from agents.transformation_agent.transformation_agent import parse_dates, standardize_column_name

ACTIONS = ("warn", "drop", "fail")
# Rules checked value by value (can drop the offending rows)
ROW_RULES = ("not_null", "unique", "between", "allowed_values", "regex", "type")
# Rules about the dataset as a whole (warn or fail only)
DATASET_RULES = ("column_exists", "max_null_pct", "row_count_min", "row_count_max")
RULE_TYPES = ROW_RULES + DATASET_RULES
TYPE_KINDS = ("numeric", "integer", "date", "text")
MAX_RULES = 200
MAX_REGEX_LENGTH = 300
MAX_ALLOWED_VALUES = 500
SAMPLE_VALUES = 5

RULE_LABELS = {
    "not_null": "Never empty",
    "unique": "Unique values",
    "between": "Within range",
    "allowed_values": "One of a set of values",
    "regex": "Matches a pattern",
    "type": "Has a data type",
    "column_exists": "Column is present",
    "max_null_pct": "At most N% empty",
    "row_count_min": "At least N rows",
    "row_count_max": "At most N rows",
}


class ContractError(ValueError):
    """A rule definition is invalid."""


class ContractViolation(RuntimeError):
    """A rule with action 'fail' was broken; the run must stop before loading."""

    def __init__(self, message: str, outcome: dict):
        super().__init__(message)
        self.outcome = outcome


def _number(value, field: str) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ContractError(f"'{field}' must be a number.")


def validate_rule(rule: dict) -> dict:
    """Normalizes one rule definition or raises ContractError."""
    if not isinstance(rule, dict):
        raise ContractError("Each rule must be an object.")
    rtype = str(rule.get("type") or "").strip()
    if rtype not in RULE_TYPES:
        raise ContractError(f"Unknown rule type '{rtype}'. Use one of: {', '.join(RULE_TYPES)}.")
    action = str(rule.get("action") or "warn").strip().lower()
    if action not in ACTIONS:
        raise ContractError(f"Unknown action '{action}'. Use warn, drop or fail.")
    if action == "drop" and rtype in DATASET_RULES:
        raise ContractError(f"'{rtype}' checks the whole dataset, so its action can only be warn or fail.")
    column = str(rule.get("column") or "").strip()
    if rtype not in ("row_count_min", "row_count_max") and not column:
        raise ContractError(f"Rule '{rtype}' needs a column.")
    params = rule.get("params") or {}
    if not isinstance(params, dict):
        raise ContractError("'params' must be an object.")

    clean = {}
    if rtype == "between":
        lo, hi = _number(params.get("min"), "min"), _number(params.get("max"), "max")
        if lo is None and hi is None:
            raise ContractError("A range rule needs a min, a max, or both.")
        if lo is not None and hi is not None and lo > hi:
            raise ContractError("min must not be greater than max.")
        clean = {"min": lo, "max": hi}
    elif rtype == "allowed_values":
        values = params.get("values")
        if isinstance(values, str):
            values = [v.strip() for v in values.split(",")]
        if not isinstance(values, list) or not [v for v in values if str(v).strip()]:
            raise ContractError("An allowed-values rule needs at least one value.")
        if len(values) > MAX_ALLOWED_VALUES:
            raise ContractError(f"At most {MAX_ALLOWED_VALUES} allowed values.")
        clean = {"values": [str(v).strip() for v in values if str(v).strip()],
                 "case_sensitive": bool(params.get("case_sensitive", False))}
    elif rtype == "regex":
        pattern = str(params.get("pattern") or "")
        if not pattern or len(pattern) > MAX_REGEX_LENGTH:
            raise ContractError(f"A pattern rule needs a regular expression of 1-{MAX_REGEX_LENGTH} characters.")
        try:
            re.compile(pattern)
        except re.error as e:
            raise ContractError(f"Invalid regular expression: {e}")
        clean = {"pattern": pattern}
    elif rtype == "type":
        kind = str(params.get("kind") or "").lower()
        if kind not in TYPE_KINDS:
            raise ContractError(f"A type rule needs a kind: {', '.join(TYPE_KINDS)}.")
        clean = {"kind": kind}
    elif rtype == "max_null_pct":
        pct = _number(params.get("max"), "max")
        if pct is None or not 0 <= pct <= 100:
            raise ContractError("max_null_pct needs 'max' between 0 and 100.")
        clean = {"max": pct}
    elif rtype in ("row_count_min", "row_count_max"):
        n = _number(params.get("value"), "value")
        if n is None or n < 0:
            raise ContractError(f"{rtype} needs a non-negative 'value'.")
        clean = {"value": int(n)}

    return {
        "type": rtype,
        "column": column or None,
        "params": clean,
        "action": action,
        "description": str(rule.get("description") or "").strip()[:300] or None,
    }


def validate_rules(rules) -> list:
    if not isinstance(rules, list) or not rules:
        raise ContractError("A contract needs at least one rule.")
    if len(rules) > MAX_RULES:
        raise ContractError(f"A contract can have at most {MAX_RULES} rules.")
    out = []
    for n, rule in enumerate(rules, 1):
        try:
            out.append(validate_rule(rule))
        except ContractError as e:
            raise ContractError(f"Rule {n}: {e}")
    return out


def matches_dataset(pattern: str, filename: str) -> bool:
    """Case-insensitive glob on the file name ('sales_*.csv', '*orders*', or an exact name)."""
    pattern = (pattern or "").strip().lower()
    return bool(pattern) and fnmatch.fnmatchcase((filename or "").lower(), pattern)


def describe_rule(rule: dict) -> str:
    p, col = rule.get("params") or {}, rule.get("column")
    t = rule["type"]
    if t == "not_null":
        return f"{col} is never empty"
    if t == "unique":
        return f"{col} has no repeated values"
    if t == "between":
        if p.get("min") is not None and p.get("max") is not None:
            return f"{col} is between {p['min']:g} and {p['max']:g}"
        return f"{col} is at least {p['min']:g}" if p.get("min") is not None else f"{col} is at most {p['max']:g}"
    if t == "allowed_values":
        shown = ", ".join(p.get("values", [])[:6]) + (" ..." if len(p.get("values", [])) > 6 else "")
        return f"{col} is one of: {shown}"
    if t == "regex":
        return f"{col} matches /{p.get('pattern')}/"
    if t == "type":
        return f"{col} is {p.get('kind')}"
    if t == "column_exists":
        return f"column {col} is present"
    if t == "max_null_pct":
        return f"{col} is at most {p.get('max'):g}% empty"
    if t == "row_count_min":
        return f"the file has at least {p.get('value'):,} rows"
    if t == "row_count_max":
        return f"the file has at most {p.get('value'):,} rows"
    return t
