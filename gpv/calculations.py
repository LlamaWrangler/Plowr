"""
Gross Premium Valuation (GPV) calculation engine.

GPV = PV(Future Premiums) - PV(Future Benefits)
A positive GPV means premiums exceed projected claims (surplus).
A negative GPV means claims exceed premiums (deficiency / liability).
"""
from __future__ import annotations
import math
import uuid
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
from typing import Optional

from .models import (
    Assumptions, ClientData, MonthlyProjection,
    ValuationResult, ScenarioResult, PortfolioValuation
)


def _months_between(start: date, end: date) -> int:
    delta = relativedelta(end, start)
    return delta.years * 12 + delta.months + (1 if delta.days > 0 else 0)


def _trend_factor(annual_rate: float, months: float, compounding: str = "continuous") -> float:
    """Return growth factor for a given trend rate over months."""
    years = months / 12.0
    if compounding == "continuous":
        return math.exp(math.log(1 + annual_rate) * years)
    return (1 + annual_rate) ** years


def run_valuation(
    client: ClientData,
    assumptions: Assumptions,
    valuation_date: Optional[date] = None,
    scenario_name: Optional[str] = None,
    scenario_assumptions: Optional[dict] = None,
) -> ValuationResult:
    """
    Project monthly claims and premiums from valuation_date to contract_end_date,
    apply trend adjustments, discount to present value, and return the GPV.
    """
    if valuation_date is None:
        valuation_date = date.today()

    # Allow scenario overrides by merging into a copy
    asm = assumptions
    if scenario_assumptions:
        asm_dict = assumptions.model_dump()
        _deep_merge(asm_dict, scenario_assumptions)
        asm = Assumptions(**asm_dict)

    projection_months = max(1, _months_between(valuation_date, client.contract_end_date))

    monthly_premium = client.monthly_premium_pmpm * client.num_members
    monthly_expected_claims = client.annual_expected_claims / 12.0

    medical_portion = asm.claims_split.medical_portion
    rx_portion = asm.claims_split.rx_portion
    compounding = asm.projection_basis.trend_compounding

    medical_trend = asm.medical_trend.annual_rate
    rx_trend = asm.rx_trend.annual_rate
    adj_trend = asm.claims_adjustment.annual_rate
    cash_card_pmpm = asm.cash_card_claims.per_member_per_month
    discount_rate = asm.discount_rate.annual_rate

    projections: list[MonthlyProjection] = []
    total_claims = 0.0
    total_premium = 0.0
    total_pv_net = 0.0
    total_medical_trend_impact = 0.0
    total_rx_trend_impact = 0.0
    total_adj_impact = 0.0
    total_cash_impact = 0.0

    for m in range(1, projection_months + 1):
        # Midpoint of projection period for trend application
        midpoint_months = m - 0.5
        proj_date = valuation_date + relativedelta(months=m)

        # Base split
        base_medical = monthly_expected_claims * medical_portion
        base_rx = monthly_expected_claims * rx_portion

        # Apply trends
        trended_medical = base_medical * _trend_factor(medical_trend, midpoint_months, compounding)
        trended_rx = base_rx * _trend_factor(rx_trend, midpoint_months, compounding)

        # Combined trended claims before adjustment
        trended_claims = trended_medical + trended_rx

        # Claims adjustment trend on top
        adj_factor = _trend_factor(adj_trend, midpoint_months, compounding)
        gross_claims = trended_claims * adj_factor

        # Cash card deduction (flat PMPM, not trended)
        cash_deduction = cash_card_pmpm * client.num_members
        net_claims = gross_claims - cash_deduction

        # Net cash flow from plan perspective: premium received minus claims paid
        net_cf = monthly_premium - net_claims

        # Discount factor to present value
        disc = _trend_factor(-discount_rate, midpoint_months, compounding)
        pv_net = net_cf * disc

        # Track trend impacts vs. baseline (no trend)
        total_medical_trend_impact += (trended_medical - base_medical)
        total_rx_trend_impact += (trended_rx - base_rx)
        total_adj_impact += (trended_claims * adj_factor - trended_claims)
        total_cash_impact += cash_deduction

        total_claims += net_claims
        total_premium += monthly_premium
        total_pv_net += pv_net

        projections.append(MonthlyProjection(
            period=m,
            projection_date=proj_date.isoformat(),
            members=client.num_members,
            gross_claims=round(gross_claims, 2),
            medical_claims=round(trended_medical, 2),
            rx_claims=round(trended_rx, 2),
            claims_adjustment=round(trended_claims * adj_factor - trended_claims, 2),
            cash_card_deduction=round(cash_deduction, 2),
            net_claims=round(net_claims, 2),
            monthly_premium=round(monthly_premium, 2),
            net_cash_flow=round(net_cf, 2),
            discount_factor=round(disc, 6),
            pv_net_cash_flow=round(pv_net, 2),
        ))

    loss_ratio = total_claims / total_premium if total_premium > 0 else 0.0
    projected_claims_pmpm = total_claims / (client.num_members * projection_months)
    gpv = total_pv_net  # positive = surplus, negative = deficiency

    val_id = scenario_name or f"VAL-{uuid.uuid4().hex[:8].upper()}"

    return ValuationResult(
        valuation_id=val_id,
        valuation_date=valuation_date.isoformat(),
        client_id=client.client_id,
        client_name=client.client_name,
        contract_end_date=client.contract_end_date.isoformat(),
        projection_months=projection_months,
        assumptions_version=asm.version,
        total_projected_claims=round(total_claims, 2),
        total_projected_premium=round(total_premium, 2),
        total_net_cash_flow=round(total_premium - total_claims, 2),
        gpv=round(gpv, 2),
        projected_claims_pmpm=round(projected_claims_pmpm, 2),
        current_premium_pmpm=round(client.monthly_premium_pmpm, 2),
        loss_ratio=round(loss_ratio, 4),
        medical_trend_impact=round(total_medical_trend_impact, 2),
        rx_trend_impact=round(total_rx_trend_impact, 2),
        claims_adj_impact=round(total_adj_impact, 2),
        cash_card_impact=round(total_cash_impact, 2),
        monthly_projections=projections,
        assumptions_snapshot=asm.model_dump(),
    )


def run_scenarios(client: ClientData, assumptions: Assumptions, valuation_date: Optional[date] = None) -> list[ScenarioResult]:
    """Run base case plus standard high/low sensitivity scenarios."""
    scenarios = [
        ("Base Case", "Central assumption set", {}),
        ("Favorable", "Low trend, high discount rate",
         {"medical_trend": {"annual_rate": assumptions.medical_trend.sensitivity_low},
          "rx_trend": {"annual_rate": assumptions.rx_trend.sensitivity_low},
          "discount_rate": {"annual_rate": assumptions.discount_rate.sensitivity_high}}),
        ("Adverse", "High trend, low discount rate",
         {"medical_trend": {"annual_rate": assumptions.medical_trend.sensitivity_high},
          "rx_trend": {"annual_rate": assumptions.rx_trend.sensitivity_high},
          "discount_rate": {"annual_rate": assumptions.discount_rate.sensitivity_low}}),
        ("High Rx Trend", "GLP-1 / specialty drug acceleration",
         {"rx_trend": {"annual_rate": assumptions.rx_trend.sensitivity_high}}),
        ("No Cash Card", "Cash card benefit discontinued",
         {"cash_card_claims": {"per_member_per_month": 0.0}}),
    ]

    results = []
    for name, desc, overrides in scenarios:
        result = run_valuation(client, assumptions, valuation_date, scenario_name=name, scenario_assumptions=overrides)
        results.append(ScenarioResult(
            scenario_name=name,
            scenario_description=desc,
            assumptions_override=overrides,
            result=result,
        ))
    return results


def run_portfolio_valuation(clients: list[ClientData], assumptions: Assumptions, valuation_date: Optional[date] = None) -> PortfolioValuation:
    """Valuate all clients and aggregate into a portfolio GPV."""
    if valuation_date is None:
        valuation_date = date.today()

    results = []
    for client in clients:
        results.append(run_valuation(client, assumptions, valuation_date))

    portfolio_gpv = sum(r.gpv for r in results)
    total_members = sum(c.num_members for c in clients)
    total_annual_premium = sum(c.monthly_premium_pmpm * c.num_members * 12 for c in clients)
    total_annual_claims = sum(c.annual_expected_claims for c in clients)
    portfolio_loss_ratio = total_annual_claims / total_annual_premium if total_annual_premium > 0 else 0.0

    return PortfolioValuation(
        portfolio_id=f"PORT-{uuid.uuid4().hex[:8].upper()}",
        valuation_date=valuation_date.isoformat(),
        client_results=results,
        portfolio_gpv=round(portfolio_gpv, 2),
        total_members=total_members,
        total_annual_premium=round(total_annual_premium, 2),
        total_annual_claims=round(total_annual_claims, 2),
        portfolio_loss_ratio=round(portfolio_loss_ratio, 4),
    )


def _deep_merge(base: dict, override: dict) -> None:
    """In-place deep merge of override into base."""
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
