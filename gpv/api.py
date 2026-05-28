"""
FastAPI web application for the GPV system.
Provides REST endpoints mirroring the MCP tools, plus a web UI.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import calculations, storage, report_generator
from .models import ClientData

app = FastAPI(
    title="Gross Premium Valuation System",
    description="Actuarial GPV tool for large group health insurance plans",
    version="1.0.0",
)

TEMPLATES_DIR = Path(__file__).parent / "templates"


# ── Request / Response models ─────────────────────────────────────────────────

class AssumptionUpdateRequest(BaseModel):
    field_path: str
    new_value: float
    updated_by: str
    rationale: str


class ClientRequest(BaseModel):
    client_id: str
    client_name: str
    num_members: int
    monthly_premium_pmpm: float
    annual_expected_claims: float
    contract_end_date: str
    plan_type: Optional[str] = None
    industry: Optional[str] = None
    notes: Optional[str] = None


class ValuationRequest(BaseModel):
    client_id: str
    valuation_date: Optional[str] = None


class ScenarioRequest(BaseModel):
    client_id: str
    scenario_name: str
    scenario_description: Optional[str] = ""
    assumptions_override: dict
    valuation_date: Optional[str] = None


class OpinionRequest(BaseModel):
    valuation_id: str
    include_scenarios: bool = True
    actuary_note: Optional[str] = ""


# ── Root / UI ─────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root():
    html_path = TEMPLATES_DIR / "index.html"
    return HTMLResponse(html_path.read_text())


# ── Assumptions ───────────────────────────────────────────────────────────────

@app.get("/api/assumptions")
async def get_assumptions():
    return storage.load_assumptions().model_dump()


@app.put("/api/assumptions")
async def update_assumption(req: AssumptionUpdateRequest):
    try:
        updated = storage.update_assumption_field(req.field_path, req.new_value, req.updated_by)
        return {"status": "updated", "field": req.field_path, "new_value": req.new_value}
    except (KeyError, ValueError) as e:
        raise HTTPException(400, str(e))


# ── Clients ───────────────────────────────────────────────────────────────────

@app.get("/api/clients")
async def list_clients():
    return [c.model_dump() for c in storage.load_clients()]


@app.get("/api/clients/{client_id}")
async def get_client(client_id: str):
    client = storage.get_client(client_id)
    if not client:
        raise HTTPException(404, f"Client {client_id} not found")
    return client.model_dump()


@app.post("/api/clients")
async def add_client(req: ClientRequest):
    client = ClientData(
        client_id=req.client_id,
        client_name=req.client_name,
        num_members=req.num_members,
        monthly_premium_pmpm=req.monthly_premium_pmpm,
        annual_expected_claims=req.annual_expected_claims,
        contract_end_date=date.fromisoformat(req.contract_end_date),
        plan_type=req.plan_type,
        industry=req.industry,
        notes=req.notes,
    )
    storage.upsert_client(client)
    return {"status": "saved", "client_id": client.client_id}


@app.post("/api/clients/upload-csv")
async def upload_csv(file: UploadFile = File(...)):
    content = (await file.read()).decode("utf-8")
    clients = storage.load_clients_from_csv(content)
    storage.save_clients(clients)
    return {"status": "loaded", "count": len(clients), "client_ids": [c.client_id for c in clients]}


# ── Valuations ────────────────────────────────────────────────────────────────

@app.post("/api/valuations/run")
async def run_valuation(req: ValuationRequest):
    client = storage.get_client(req.client_id)
    if not client:
        raise HTTPException(404, f"Client {req.client_id} not found")
    asm = storage.load_assumptions()
    val_date = date.fromisoformat(req.valuation_date) if req.valuation_date else None
    result = calculations.run_valuation(client, asm, val_date)
    storage.save_valuation(result)
    return result.model_dump()


@app.post("/api/valuations/run-scenarios")
async def run_scenarios(req: ValuationRequest):
    client = storage.get_client(req.client_id)
    if not client:
        raise HTTPException(404, f"Client {req.client_id} not found")
    asm = storage.load_assumptions()
    val_date = date.fromisoformat(req.valuation_date) if req.valuation_date else None
    scenarios = calculations.run_scenarios(client, asm, val_date)
    for sc in scenarios:
        storage.save_valuation(sc.result)
    return [sc.model_dump() for sc in scenarios]


@app.post("/api/valuations/run-custom-scenario")
async def run_custom_scenario(req: ScenarioRequest):
    client = storage.get_client(req.client_id)
    if not client:
        raise HTTPException(404, f"Client {req.client_id} not found")
    asm = storage.load_assumptions()
    val_date = date.fromisoformat(req.valuation_date) if req.valuation_date else None
    result = calculations.run_valuation(
        client, asm, val_date,
        scenario_name=req.scenario_name,
        scenario_assumptions=req.assumptions_override,
    )
    storage.save_valuation(result)
    return result.model_dump()


@app.post("/api/valuations/run-portfolio")
async def run_portfolio(valuation_date: Optional[str] = None):
    clients = storage.load_clients()
    if not clients:
        raise HTTPException(400, "No clients loaded")
    asm = storage.load_assumptions()
    val_date = date.fromisoformat(valuation_date) if valuation_date else None
    portfolio = calculations.run_portfolio_valuation(clients, asm, val_date)
    return portfolio.model_dump()


@app.get("/api/valuations")
async def list_valuations(client_id: Optional[str] = None):
    return storage.list_valuations(client_id)


@app.get("/api/valuations/{valuation_id}")
async def get_valuation(valuation_id: str):
    result = storage.load_valuation(valuation_id)
    if not result:
        raise HTTPException(404, f"Valuation {valuation_id} not found")
    return result.model_dump()


@app.get("/api/valuations/{id1}/compare/{id2}")
async def compare_valuations(id1: str, id2: str):
    r1 = storage.load_valuation(id1)
    r2 = storage.load_valuation(id2)
    if not r1:
        raise HTTPException(404, f"Valuation {id1} not found")
    if not r2:
        raise HTTPException(404, f"Valuation {id2} not found")
    return {
        "metrics": ["GPV", "Loss Ratio", "Claims PMPM", "Premium PMPM", "Projection Months"],
        "current": [r1.gpv, r1.loss_ratio, r1.projected_claims_pmpm, r1.current_premium_pmpm, r1.projection_months],
        "prior": [r2.gpv, r2.loss_ratio, r2.projected_claims_pmpm, r2.current_premium_pmpm, r2.projection_months],
        "change": [
            round(r1.gpv - r2.gpv, 2),
            round(r1.loss_ratio - r2.loss_ratio, 4),
            round(r1.projected_claims_pmpm - r2.projected_claims_pmpm, 2),
            round(r1.current_premium_pmpm - r2.current_premium_pmpm, 2),
            r1.projection_months - r2.projection_months,
        ],
    }


# ── Reports ───────────────────────────────────────────────────────────────────

@app.post("/api/reports/generate")
async def generate_report(req: OpinionRequest):
    result = storage.load_valuation(req.valuation_id)
    if not result:
        raise HTTPException(404, f"Valuation {req.valuation_id} not found")

    scenarios = None
    if req.include_scenarios:
        client = storage.get_client(result.client_id)
        if client:
            asm = storage.load_assumptions()
            val_date = date.fromisoformat(result.valuation_date)
            sc_results = calculations.run_scenarios(client, asm, val_date)
            scenarios = sc_results

    prior = storage.get_previous_valuation(result.client_id, result.valuation_id)
    opinion = report_generator.generate_actuarial_opinion(
        result, scenarios=scenarios, previous_result=prior,
        actuary_note=req.actuary_note or "",
    )
    storage.save_report(opinion)
    return opinion.model_dump()


@app.get("/api/reports")
async def list_reports(client_name: Optional[str] = None):
    return storage.list_reports(client_name)


@app.get("/api/reports/{opinion_id}")
async def get_report(opinion_id: str):
    opinion = storage.load_report(opinion_id)
    if not opinion:
        raise HTTPException(404, f"Report {opinion_id} not found")
    return opinion.model_dump()


@app.get("/api/reports/{opinion_id}/text")
async def get_report_text(opinion_id: str):
    opinion = storage.load_report(opinion_id)
    if not opinion:
        raise HTTPException(404, f"Report {opinion_id} not found")
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(opinion.full_opinion)
