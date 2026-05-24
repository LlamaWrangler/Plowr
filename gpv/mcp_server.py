"""
MCP Server for Gross Premium Valuation.

Exposes tools and resources so an AI assistant can:
  • Load and manage client data
  • Run GPV calculations and scenarios
  • Update actuarial assumptions
  • Generate and retrieve actuarial opinions
  • Compare valuations over time

Run with:  python -m gpv.mcp_server
or via stdio transport for Claude Desktop / Claude Code integration.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Resource, ResourceTemplate, Tool,
    TextContent, EmbeddedResource,
    CallToolResult, ListResourcesResult,
    ListToolsResult, ReadResourceResult,
)

# Make gpv importable when run as a module
sys.path.insert(0, str(Path(__file__).parent.parent))

from gpv import calculations, storage, report_generator
from gpv.models import ClientData, AssumptionUpdate

server = Server("gpv-valuation-server")


# ═══════════════════════════════════════════════════════════
# TOOLS
# ═══════════════════════════════════════════════════════════

@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="get_assumptions",
            description="Return the current actuarial assumptions used for GPV calculations.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="update_assumption",
            description=(
                "Update a single actuarial assumption field. "
                "Use dot-path notation, e.g. 'medical_trend.annual_rate'."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "field_path": {"type": "string", "description": "Dot-path to the assumption field"},
                    "new_value": {"description": "New value (number or string)"},
                    "updated_by": {"type": "string", "description": "Name of who is making the change"},
                    "rationale": {"type": "string", "description": "Justification for the change"},
                },
                "required": ["field_path", "new_value", "updated_by", "rationale"],
            },
        ),
        Tool(
            name="list_clients",
            description="List all loaded clients with their key data.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="get_client",
            description="Get detailed data for a specific client by client_id.",
            inputSchema={
                "type": "object",
                "properties": {"client_id": {"type": "string"}},
                "required": ["client_id"],
            },
        ),
        Tool(
            name="add_client",
            description="Add or update a client record.",
            inputSchema={
                "type": "object",
                "properties": {
                    "client_id": {"type": "string"},
                    "client_name": {"type": "string"},
                    "num_members": {"type": "integer"},
                    "monthly_premium_pmpm": {"type": "number", "description": "Per-member per-month premium"},
                    "annual_expected_claims": {"type": "number"},
                    "contract_end_date": {"type": "string", "description": "ISO format YYYY-MM-DD"},
                    "plan_type": {"type": "string"},
                    "industry": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": ["client_id", "client_name", "num_members", "monthly_premium_pmpm",
                             "annual_expected_claims", "contract_end_date"],
            },
        ),
        Tool(
            name="load_clients_csv",
            description=(
                "Load clients from a CSV string. "
                "Required columns: client_id, client_name, num_members, monthly_premium_pmpm, "
                "annual_expected_claims, contract_end_date."
            ),
            inputSchema={
                "type": "object",
                "properties": {"csv_content": {"type": "string", "description": "Full CSV text"}},
                "required": ["csv_content"],
            },
        ),
        Tool(
            name="run_valuation",
            description=(
                "Run a Gross Premium Valuation for a client. "
                "Returns GPV, loss ratio, PMPM metrics, and monthly projection detail."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "client_id": {"type": "string"},
                    "valuation_date": {"type": "string", "description": "ISO YYYY-MM-DD, defaults to today"},
                },
                "required": ["client_id"],
            },
        ),
        Tool(
            name="run_scenarios",
            description=(
                "Run base case plus standard sensitivity scenarios "
                "(Favorable, Adverse, High Rx Trend, No Cash Card) for a client."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "client_id": {"type": "string"},
                    "valuation_date": {"type": "string", "description": "ISO YYYY-MM-DD, defaults to today"},
                },
                "required": ["client_id"],
            },
        ),
        Tool(
            name="run_custom_scenario",
            description=(
                "Run a valuation with a custom set of assumption overrides. "
                "Pass any subset of the assumptions as overrides."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "client_id": {"type": "string"},
                    "scenario_name": {"type": "string"},
                    "scenario_description": {"type": "string"},
                    "assumptions_override": {
                        "type": "object",
                        "description": "Partial assumptions dict to override, e.g. {\"medical_trend\": {\"annual_rate\": 0.10}}",
                    },
                    "valuation_date": {"type": "string"},
                },
                "required": ["client_id", "scenario_name", "assumptions_override"],
            },
        ),
        Tool(
            name="run_portfolio_valuation",
            description="Run GPV for all clients and return a portfolio-level summary.",
            inputSchema={
                "type": "object",
                "properties": {
                    "valuation_date": {"type": "string", "description": "ISO YYYY-MM-DD, defaults to today"},
                },
                "required": [],
            },
        ),
        Tool(
            name="list_valuations",
            description="List saved valuation results, optionally filtered by client_id.",
            inputSchema={
                "type": "object",
                "properties": {"client_id": {"type": "string", "description": "Optional filter"}},
                "required": [],
            },
        ),
        Tool(
            name="get_valuation",
            description="Retrieve a saved valuation result by valuation_id.",
            inputSchema={
                "type": "object",
                "properties": {"valuation_id": {"type": "string"}},
                "required": ["valuation_id"],
            },
        ),
        Tool(
            name="compare_valuations",
            description="Compare two saved valuations side-by-side and return a difference summary.",
            inputSchema={
                "type": "object",
                "properties": {
                    "valuation_id_1": {"type": "string", "description": "Current / newer valuation"},
                    "valuation_id_2": {"type": "string", "description": "Prior / older valuation"},
                },
                "required": ["valuation_id_1", "valuation_id_2"],
            },
        ),
        Tool(
            name="generate_actuarial_opinion",
            description=(
                "Generate a draft actuarial opinion document for a valuation. "
                "Optionally include scenario analysis and comparison to a prior valuation."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "valuation_id": {"type": "string"},
                    "include_scenarios": {"type": "boolean", "default": True},
                    "actuary_note": {"type": "string", "description": "Optional qualitative commentary to include"},
                },
                "required": ["valuation_id"],
            },
        ),
        Tool(
            name="list_reports",
            description="List generated actuarial opinion reports.",
            inputSchema={
                "type": "object",
                "properties": {"client_name": {"type": "string", "description": "Optional filter"}},
                "required": [],
            },
        ),
        Tool(
            name="get_report",
            description="Retrieve a generated actuarial opinion by opinion_id.",
            inputSchema={
                "type": "object",
                "properties": {"opinion_id": {"type": "string"}},
                "required": ["opinion_id"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    try:
        result = await _dispatch(name, arguments)
        return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e), "tool": name}))]


async def _dispatch(name: str, args: dict) -> Any:
    if name == "get_assumptions":
        return storage.load_assumptions().model_dump()

    elif name == "update_assumption":
        updated = storage.update_assumption_field(
            args["field_path"], args["new_value"], args["updated_by"]
        )
        return {"status": "updated", "field": args["field_path"], "new_value": args["new_value"]}

    elif name == "list_clients":
        clients = storage.load_clients()
        return [
            {
                "client_id": c.client_id,
                "client_name": c.client_name,
                "num_members": c.num_members,
                "monthly_premium_pmpm": c.monthly_premium_pmpm,
                "annual_expected_claims": c.annual_expected_claims,
                "contract_end_date": str(c.contract_end_date),
                "plan_type": c.plan_type,
                "industry": c.industry,
            }
            for c in clients
        ]

    elif name == "get_client":
        client = storage.get_client(args["client_id"])
        if not client:
            return {"error": f"Client {args['client_id']} not found"}
        return client.model_dump()

    elif name == "add_client":
        client = ClientData(
            client_id=args["client_id"],
            client_name=args["client_name"],
            num_members=args["num_members"],
            monthly_premium_pmpm=args["monthly_premium_pmpm"],
            annual_expected_claims=args["annual_expected_claims"],
            contract_end_date=date.fromisoformat(args["contract_end_date"]),
            plan_type=args.get("plan_type"),
            industry=args.get("industry"),
            notes=args.get("notes"),
        )
        storage.upsert_client(client)
        return {"status": "saved", "client_id": client.client_id}

    elif name == "load_clients_csv":
        clients = storage.load_clients_from_csv(args["csv_content"])
        storage.save_clients(clients)
        return {"status": "loaded", "count": len(clients), "client_ids": [c.client_id for c in clients]}

    elif name == "run_valuation":
        client = storage.get_client(args["client_id"])
        if not client:
            return {"error": f"Client {args['client_id']} not found"}
        asm = storage.load_assumptions()
        val_date = date.fromisoformat(args["valuation_date"]) if args.get("valuation_date") else None
        result = calculations.run_valuation(client, asm, val_date)
        storage.save_valuation(result)
        # Return summary (omit large monthly_projections list from default response)
        summary = result.model_dump()
        summary["monthly_projections"] = f"[{len(result.monthly_projections)} months — use get_valuation for detail]"
        return summary

    elif name == "run_scenarios":
        client = storage.get_client(args["client_id"])
        if not client:
            return {"error": f"Client {args['client_id']} not found"}
        asm = storage.load_assumptions()
        val_date = date.fromisoformat(args["valuation_date"]) if args.get("valuation_date") else None
        scenarios = calculations.run_scenarios(client, asm, val_date)
        # Save each scenario result
        for sc in scenarios:
            storage.save_valuation(sc.result)
        return [
            {
                "scenario_name": sc.scenario_name,
                "scenario_description": sc.scenario_description,
                "assumptions_override": sc.assumptions_override,
                "valuation_id": sc.result.valuation_id,
                "gpv": sc.result.gpv,
                "loss_ratio": sc.result.loss_ratio,
                "projected_claims_pmpm": sc.result.projected_claims_pmpm,
            }
            for sc in scenarios
        ]

    elif name == "run_custom_scenario":
        client = storage.get_client(args["client_id"])
        if not client:
            return {"error": f"Client {args['client_id']} not found"}
        asm = storage.load_assumptions()
        val_date = date.fromisoformat(args["valuation_date"]) if args.get("valuation_date") else None
        result = calculations.run_valuation(
            client, asm, val_date,
            scenario_name=args["scenario_name"],
            scenario_assumptions=args["assumptions_override"],
        )
        storage.save_valuation(result)
        return {
            "valuation_id": result.valuation_id,
            "gpv": result.gpv,
            "loss_ratio": result.loss_ratio,
            "projected_claims_pmpm": result.projected_claims_pmpm,
        }

    elif name == "run_portfolio_valuation":
        clients = storage.load_clients()
        if not clients:
            return {"error": "No clients loaded"}
        asm = storage.load_assumptions()
        val_date = date.fromisoformat(args["valuation_date"]) if args.get("valuation_date") else None
        portfolio = calculations.run_portfolio_valuation(clients, asm, val_date)
        return {
            "portfolio_id": portfolio.portfolio_id,
            "valuation_date": portfolio.valuation_date,
            "portfolio_gpv": portfolio.portfolio_gpv,
            "total_members": portfolio.total_members,
            "total_annual_premium": portfolio.total_annual_premium,
            "total_annual_claims": portfolio.total_annual_claims,
            "portfolio_loss_ratio": portfolio.portfolio_loss_ratio,
            "clients": [
                {
                    "client_id": r.client_id,
                    "client_name": r.client_name,
                    "gpv": r.gpv,
                    "loss_ratio": r.loss_ratio,
                }
                for r in portfolio.client_results
            ],
        }

    elif name == "list_valuations":
        return storage.list_valuations(args.get("client_id"))

    elif name == "get_valuation":
        result = storage.load_valuation(args["valuation_id"])
        if not result:
            return {"error": f"Valuation {args['valuation_id']} not found"}
        return result.model_dump()

    elif name == "compare_valuations":
        r1 = storage.load_valuation(args["valuation_id_1"])
        r2 = storage.load_valuation(args["valuation_id_2"])
        if not r1:
            return {"error": f"Valuation {args['valuation_id_1']} not found"}
        if not r2:
            return {"error": f"Valuation {args['valuation_id_2']} not found"}
        return {
            "comparison": {
                "metric": ["GPV", "Loss Ratio", "Claims PMPM", "Premium PMPM", "Projection Months"],
                "current": [r1.gpv, r1.loss_ratio, r1.projected_claims_pmpm, r1.current_premium_pmpm, r1.projection_months],
                "prior": [r2.gpv, r2.loss_ratio, r2.projected_claims_pmpm, r2.current_premium_pmpm, r2.projection_months],
                "change": [
                    round(r1.gpv - r2.gpv, 2),
                    round(r1.loss_ratio - r2.loss_ratio, 4),
                    round(r1.projected_claims_pmpm - r2.projected_claims_pmpm, 2),
                    round(r1.current_premium_pmpm - r2.current_premium_pmpm, 2),
                    r1.projection_months - r2.projection_months,
                ],
            },
            "current_valuation_id": r1.valuation_id,
            "prior_valuation_id": r2.valuation_id,
        }

    elif name == "generate_actuarial_opinion":
        result = storage.load_valuation(args["valuation_id"])
        if not result:
            return {"error": f"Valuation {args['valuation_id']} not found"}

        scenarios = None
        if args.get("include_scenarios", True):
            client = storage.get_client(result.client_id)
            if client:
                asm = storage.load_assumptions()
                val_date = date.fromisoformat(result.valuation_date)
                sc_results = calculations.run_scenarios(client, asm, val_date)
                scenarios = sc_results

        prior = storage.get_previous_valuation(result.client_id, result.valuation_id)
        opinion = report_generator.generate_actuarial_opinion(
            result,
            scenarios=scenarios,
            previous_result=prior,
            actuary_note=args.get("actuary_note", ""),
        )
        path = storage.save_report(opinion)
        return {
            "opinion_id": opinion.opinion_id,
            "saved_to": path,
            "full_opinion": opinion.full_opinion,
        }

    elif name == "list_reports":
        return storage.list_reports(args.get("client_name"))

    elif name == "get_report":
        opinion = storage.load_report(args["opinion_id"])
        if not opinion:
            return {"error": f"Report {args['opinion_id']} not found"}
        return opinion.model_dump()

    else:
        return {"error": f"Unknown tool: {name}"}


# ═══════════════════════════════════════════════════════════
# RESOURCES
# ═══════════════════════════════════════════════════════════

@server.list_resources()
async def list_resources() -> list[Resource]:
    resources = [
        Resource(
            uri="gpv://assumptions/current",
            name="Current Actuarial Assumptions",
            description="The active assumption set used for all GPV calculations",
            mimeType="application/json",
        ),
        Resource(
            uri="gpv://clients/all",
            name="All Clients",
            description="All loaded client data",
            mimeType="application/json",
        ),
    ]
    # Add individual valuation resources
    for v in storage.list_valuations()[:10]:
        resources.append(Resource(
            uri=f"gpv://valuations/{v['valuation_id']}",
            name=f"Valuation: {v['client_name']} ({v['valuation_date']})",
            description=f"GPV={v['gpv']:,.0f} | LR={v['loss_ratio']:.1%}",
            mimeType="application/json",
        ))
    return resources


@server.read_resource()
async def read_resource(uri: str) -> str:
    if uri == "gpv://assumptions/current":
        return storage.load_assumptions().model_dump_json(indent=2)
    elif uri == "gpv://clients/all":
        clients = storage.load_clients()
        return json.dumps([c.model_dump() for c in clients], indent=2, default=str)
    elif uri.startswith("gpv://valuations/"):
        val_id = uri.split("/")[-1]
        result = storage.load_valuation(val_id)
        if result:
            return result.model_dump_json(indent=2)
        return json.dumps({"error": "not found"})
    elif uri.startswith("gpv://reports/"):
        op_id = uri.split("/")[-1]
        report = storage.load_report(op_id)
        if report:
            return report.full_opinion
        return "Report not found"
    return json.dumps({"error": f"Unknown resource: {uri}"})


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
