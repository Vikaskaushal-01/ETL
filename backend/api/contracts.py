"""
Data contracts API: declare what a dataset must look like and have every run check it before loading.

  GET    /contracts                       the caller's contracts
  POST   /contracts                       create one (name, dataset_pattern, rules)
  PATCH  /contracts/{id}                  rename, change pattern or rules, enable / disable
  DELETE /contracts/{id}
  GET    /contracts/rule-types            rule types, actions and labels (for the editor)
  GET    /contracts/suggest?batch_id=     rules proposed from a run's cleaned data
  POST   /contracts/{id}/test?batch_id=   dry-run a contract against a run's cleaned data
  GET    /contracts/results/{batch_id}    what the contracts decided during a run
"""
import json
import logging
import os
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.database.models import DataContract, RawUpload
from backend.database.mysql import SessionLocal, get_db
from backend.utils import contracts as engine
from backend.utils.file_utils import read_dataset

router = APIRouter(prefix="/contracts", tags=["Data Contracts"])
logger = logging.getLogger("etl_contracts")

MAX_CONTRACTS_PER_USER = 50


class ContractCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    dataset_pattern: str = Field(..., min_length=1, max_length=255)
    rules: list
    enabled: bool = True


class ContractUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=120)
    dataset_pattern: Optional[str] = Field(None, min_length=1, max_length=255)
    rules: Optional[list] = None
    enabled: Optional[bool] = None


def _serialize(c: DataContract) -> dict:
    rules = json.loads(c.rules_json or "[]")
    return {
        "id": c.id,
        "name": c.name,
        "dataset_pattern": c.dataset_pattern,
        "enabled": bool(c.enabled),
        "rules": [{**r, "summary": engine.describe_rule(r)} for r in rules],
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


def _owned(db: Session, contract_id: int, email: Optional[str]) -> DataContract:
    contract = db.get(DataContract, contract_id)
    if not contract or contract.user_email != email:
        raise HTTPException(status_code=404, detail="Contract not found.")
    return contract


def _checked_rules(rules: list) -> list:
    try:
        return engine.validate_rules(rules)
    except engine.ContractError as e:
        raise HTTPException(status_code=400, detail=str(e))


def _clean_dataset_of(db: Session, batch_id: str, email: Optional[str]) -> tuple:
    """(cleaned DataFrame, filename) of a run the caller can see."""
    from backend.api.pipeline import _require_batch_access, _stage_output, read_pipeline_state
    _require_batch_access(db, batch_id, email)
    path = _stage_output(read_pipeline_state(f"pipe_{batch_id}"), "transformation").get("clean_dataset_path")
    filename = db.query(RawUpload.filename).filter(RawUpload.batch_id == batch_id).scalar()
    if not path or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="This run has no cleaned data yet. Run it through the pipeline first.")
    return read_dataset(path), filename


@router.get("")
def list_contracts(db: Session = Depends(get_db), x_user_email: Optional[str] = Header(None)):
    rows = db.query(DataContract).filter(DataContract.user_email == x_user_email).order_by(DataContract.created_at.desc()).all()
    return [_serialize(c) for c in rows]


@router.get("/rule-types")
def rule_types():
    return {
        "types": [{"type": t, "label": engine.RULE_LABELS[t], "row_level": t in engine.ROW_RULES} for t in engine.RULE_TYPES],
        "actions": [
            {"action": "warn", "label": "Warn", "help": "Record the violation and keep loading."},
            {"action": "drop", "label": "Drop rows", "help": "Remove the rows that break the rule before loading."},
            {"action": "fail", "label": "Fail run", "help": "Stop the run before anything is loaded."},
        ],
        "type_kinds": list(engine.TYPE_KINDS),
    }


@router.post("")
def create_contract(req: ContractCreate, db: Session = Depends(get_db), x_user_email: Optional[str] = Header(None)):
    if not x_user_email:
        raise HTTPException(status_code=400, detail="Contracts belong to a user account.")
    if db.query(DataContract).filter(DataContract.user_email == x_user_email).count() >= MAX_CONTRACTS_PER_USER:
        raise HTTPException(status_code=400, detail=f"You can have at most {MAX_CONTRACTS_PER_USER} contracts.")
    contract = DataContract(
        user_email=x_user_email,
        name=req.name.strip(),
        dataset_pattern=req.dataset_pattern.strip(),
        rules_json=json.dumps(_checked_rules(req.rules)),
        enabled=req.enabled,
    )
    db.add(contract)
    db.commit()
    db.refresh(contract)
    return _serialize(contract)


@router.patch("/{contract_id}")
def update_contract(contract_id: int, req: ContractUpdate, db: Session = Depends(get_db), x_user_email: Optional[str] = Header(None)):
    contract = _owned(db, contract_id, x_user_email)
    if req.name is not None:
        contract.name = req.name.strip()
    if req.dataset_pattern is not None:
        contract.dataset_pattern = req.dataset_pattern.strip()
    if req.rules is not None:
        contract.rules_json = json.dumps(_checked_rules(req.rules))
    if req.enabled is not None:
        contract.enabled = req.enabled
    db.commit()
    db.refresh(contract)
    return _serialize(contract)


@router.delete("/{contract_id}")
def delete_contract(contract_id: int, db: Session = Depends(get_db), x_user_email: Optional[str] = Header(None)):
    db.delete(_owned(db, contract_id, x_user_email))
    db.commit()
    return {"status": "Deleted", "id": contract_id}


@router.get("/suggest")
def suggest_contract(batch_id: str, db: Session = Depends(get_db), x_user_email: Optional[str] = Header(None)):
    """Rules profiled from a run's cleaned data: a starting point the user edits before saving."""
    df, filename = _clean_dataset_of(db, batch_id, x_user_email)
    stem, ext = os.path.splitext(filename or "dataset.csv")
    rules = engine.suggest_rules(df)
    return {
        "name": f"{stem} contract",
        "dataset_pattern": filename or "*",
        "pattern_hint": f"{stem}*{ext}",
        "rows_profiled": len(df),
        "rules": [{**r, "summary": engine.describe_rule(r)} for r in rules],
    }


@router.post("/{contract_id}/test")
def test_contract(contract_id: int, batch_id: str, db: Session = Depends(get_db), x_user_email: Optional[str] = Header(None)):
    """What the contract would decide on a run's cleaned data, without changing anything."""
    contract = _owned(db, contract_id, x_user_email)
    df, _ = _clean_dataset_of(db, batch_id, x_user_email)
    out, results, failed = engine.evaluate(df, json.loads(contract.rules_json))
    return {"contract": contract.name, "failed": failed, "summary": engine.summarize(results, len(df), len(out)), "results": results}


@router.get("/results/{batch_id}")
def run_results(batch_id: str, db: Session = Depends(get_db), x_user_email: Optional[str] = Header(None)):
    from backend.api.pipeline import _require_batch_access, read_pipeline_state
    _require_batch_access(db, batch_id, x_user_email)
    return read_pipeline_state(f"pipe_{batch_id}").get("contracts") or {"applied": [], "results": [], "summary": None}
