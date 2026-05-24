"""
File-based persistence for clients, valuations, assumptions, and reports.
All data stored as JSON under gpv/data/.
"""
from __future__ import annotations
import csv
import io
import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from .models import (
    Assumptions, ClientData, ValuationResult,
    PortfolioValuation, ActuarialOpinion
)

BASE = Path(__file__).parent / "data"
CLIENTS_DIR = BASE / "clients"
VALUATIONS_DIR = BASE / "valuations"
REPORTS_DIR = BASE / "reports"
ASSUMPTIONS_FILE = BASE / "assumptions.json"


def _ensure_dirs():
    for d in [CLIENTS_DIR, VALUATIONS_DIR, REPORTS_DIR]:
        d.mkdir(parents=True, exist_ok=True)


# ── Assumptions ──────────────────────────────────────────────────────────────

def load_assumptions() -> Assumptions:
    with open(ASSUMPTIONS_FILE) as f:
        return Assumptions(**json.load(f))


def save_assumptions(asm: Assumptions) -> None:
    asm_dict = asm.model_dump()
    asm_dict["last_updated"] = date.today().isoformat()
    with open(ASSUMPTIONS_FILE, "w") as f:
        json.dump(asm_dict, f, indent=2)


def update_assumption_field(field_path: str, new_value, updated_by: str) -> Assumptions:
    """Update a single assumption field by dot-path (e.g. 'medical_trend.annual_rate')."""
    asm_dict = json.loads(ASSUMPTIONS_FILE.read_text())
    parts = field_path.split(".")
    node = asm_dict
    for part in parts[:-1]:
        node = node[part]
    node[parts[-1]] = new_value
    asm_dict["last_updated"] = date.today().isoformat()
    asm_dict["updated_by"] = updated_by
    ASSUMPTIONS_FILE.write_text(json.dumps(asm_dict, indent=2))
    return Assumptions(**asm_dict)


# ── Clients ───────────────────────────────────────────────────────────────────

def load_clients_from_csv(csv_content: str) -> list[ClientData]:
    reader = csv.DictReader(io.StringIO(csv_content))
    clients = []
    for row in reader:
        clients.append(ClientData(
            client_id=row["client_id"].strip(),
            client_name=row["client_name"].strip(),
            num_members=int(row["num_members"]),
            monthly_premium_pmpm=float(row["monthly_premium_pmpm"]),
            annual_expected_claims=float(row["annual_expected_claims"]),
            contract_end_date=date.fromisoformat(row["contract_end_date"].strip()),
            plan_type=row.get("plan_type", "").strip() or None,
            industry=row.get("industry", "").strip() or None,
            notes=row.get("notes", "").strip() or None,
        ))
    return clients


def save_clients(clients: list[ClientData]) -> None:
    _ensure_dirs()
    data = [c.model_dump() for c in clients]
    for d in data:
        if isinstance(d.get("contract_end_date"), date):
            d["contract_end_date"] = d["contract_end_date"].isoformat()
    (CLIENTS_DIR / "clients.json").write_text(json.dumps(data, indent=2, default=str))


def load_clients() -> list[ClientData]:
    _ensure_dirs()
    client_file = CLIENTS_DIR / "clients.json"
    if not client_file.exists():
        # Fall back to CSV
        csv_files = list(CLIENTS_DIR.glob("*.csv"))
        if csv_files:
            return load_clients_from_csv(csv_files[0].read_text())
        return []
    data = json.loads(client_file.read_text())
    return [ClientData(**d) for d in data]


def get_client(client_id: str) -> Optional[ClientData]:
    return next((c for c in load_clients() if c.client_id == client_id), None)


def upsert_client(client: ClientData) -> None:
    clients = load_clients()
    clients = [c for c in clients if c.client_id != client.client_id]
    clients.append(client)
    save_clients(clients)


# ── Valuations ────────────────────────────────────────────────────────────────

def save_valuation(result: ValuationResult) -> str:
    _ensure_dirs()
    path = VALUATIONS_DIR / f"{result.valuation_id}.json"
    path.write_text(result.model_dump_json(indent=2))
    return str(path)


def load_valuation(valuation_id: str) -> Optional[ValuationResult]:
    _ensure_dirs()
    path = VALUATIONS_DIR / f"{valuation_id}.json"
    if not path.exists():
        return None
    return ValuationResult(**json.loads(path.read_text()))


def list_valuations(client_id: Optional[str] = None) -> list[dict]:
    _ensure_dirs()
    summaries = []
    for p in sorted(VALUATIONS_DIR.glob("*.json"), key=os.path.getmtime, reverse=True):
        try:
            data = json.loads(p.read_text())
            if client_id and data.get("client_id") != client_id:
                continue
            summaries.append({
                "valuation_id": data["valuation_id"],
                "client_id": data["client_id"],
                "client_name": data["client_name"],
                "valuation_date": data["valuation_date"],
                "gpv": data["gpv"],
                "loss_ratio": data["loss_ratio"],
                "projection_months": data["projection_months"],
            })
        except Exception:
            continue
    return summaries


def get_previous_valuation(client_id: str, exclude_id: str) -> Optional[ValuationResult]:
    """Return the most recent valuation for this client, excluding the given ID."""
    for s in list_valuations(client_id):
        if s["valuation_id"] != exclude_id:
            return load_valuation(s["valuation_id"])
    return None


# ── Reports ───────────────────────────────────────────────────────────────────

def save_report(opinion: ActuarialOpinion) -> str:
    _ensure_dirs()
    path = REPORTS_DIR / f"{opinion.opinion_id}.json"
    path.write_text(opinion.model_dump_json(indent=2))
    txt_path = REPORTS_DIR / f"{opinion.opinion_id}.txt"
    txt_path.write_text(opinion.full_opinion)
    return str(txt_path)


def load_report(opinion_id: str) -> Optional[ActuarialOpinion]:
    _ensure_dirs()
    path = REPORTS_DIR / f"{opinion_id}.json"
    if not path.exists():
        return None
    return ActuarialOpinion(**json.loads(path.read_text()))


def list_reports(client_name: Optional[str] = None) -> list[dict]:
    _ensure_dirs()
    summaries = []
    for p in sorted(REPORTS_DIR.glob("*.json"), key=os.path.getmtime, reverse=True):
        try:
            data = json.loads(p.read_text())
            if client_name and data.get("client_name") != client_name:
                continue
            summaries.append({
                "opinion_id": data["opinion_id"],
                "client_name": data["client_name"],
                "valuation_id": data["valuation_id"],
                "created_date": data["created_date"],
            })
        except Exception:
            continue
    return summaries
