"""
Generates draft actuarial opinion documents from valuation results.
"""
from __future__ import annotations
import uuid
from datetime import date
from typing import Optional

from .models import ActuarialOpinion, ValuationResult, ScenarioResult


def _fmt_dollars(v: float) -> str:
    return f"${v:,.0f}"


def _fmt_pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def _fmt_pmpm(v: float) -> str:
    return f"${v:,.2f} PMPM"


def _gpv_label(gpv: float) -> str:
    if gpv >= 0:
        return f"SURPLUS of {_fmt_dollars(gpv)}"
    return f"DEFICIENCY of {_fmt_dollars(abs(gpv))}"


def generate_actuarial_opinion(
    result: ValuationResult,
    scenarios: Optional[list[ScenarioResult]] = None,
    previous_result: Optional[ValuationResult] = None,
    actuary_note: str = "",
) -> ActuarialOpinion:
    opinion_id = f"OPN-{uuid.uuid4().hex[:8].upper()}"
    today = date.today().isoformat()
    asm = result.assumptions_snapshot

    # ── Executive Summary ─────────────────────────────────────────────────────
    surplus_label = _gpv_label(result.gpv)
    exec_summary = f"""EXECUTIVE SUMMARY
=================
Client:            {result.client_name}
Valuation Date:    {result.valuation_date}
Contract End:      {result.contract_end_date}
Projection Period: {result.projection_months} months

Gross Premium Valuation (GPV): {_fmt_dollars(result.gpv)}
Status: {"SURPLUS — premiums are expected to exceed trended claims." if result.gpv >= 0 else "DEFICIENCY — trended claims are expected to exceed premiums."}

The present value of future premiums less the present value of future trended claims
produces a {surplus_label} over the remaining contract period.

Key Metrics:
  • Projected Loss Ratio:          {_fmt_pct(result.loss_ratio)}
  • Projected Claims (PMPM):       {_fmt_pmpm(result.projected_claims_pmpm)}
  • Current Premium (PMPM):        {_fmt_pmpm(result.current_premium_pmpm)}
  • Total Projected Claims:        {_fmt_dollars(result.total_projected_claims)}
  • Total Projected Premium:       {_fmt_dollars(result.total_projected_premium)}
  • Enrolled Members:              {result.monthly_projections[0].members:,} if result.monthly_projections else "N/A"
"""

    # ── Assumptions Section ───────────────────────────────────────────────────
    mt = asm["medical_trend"]
    rt = asm["rx_trend"]
    ca = asm["claims_adjustment"]
    cc = asm["cash_card_claims"]
    cs = asm["claims_split"]
    dr = asm["discount_rate"]

    assumptions_section = f"""ACTUARIAL ASSUMPTIONS
=====================
Assumptions Version: {result.assumptions_version}
Effective Date:      {asm.get("effective_date", "N/A")}

1. MEDICAL TREND
   Annual Rate:  {_fmt_pct(mt["annual_rate"])}
   Rationale:    {mt["rationale"]}
   Source:       {mt["source"]}
   Sensitivity:  Low {_fmt_pct(mt["sensitivity_low"])} / High {_fmt_pct(mt["sensitivity_high"])}

2. Rx (PHARMACY) TREND
   Annual Rate:  {_fmt_pct(rt["annual_rate"])}
   Rationale:    {rt["rationale"]}
   Source:       {rt["source"]}
   Sensitivity:  Low {_fmt_pct(rt["sensitivity_low"])} / High {_fmt_pct(rt["sensitivity_high"])}

3. CLAIMS ADJUSTMENT (IBNR / POOLING)
   Annual Rate:  {_fmt_pct(ca["annual_rate"])}
   Rationale:    {ca["rationale"]}
   Source:       {ca["source"]}

4. CASH CARD / HEALTH BENEFIT CARD DEDUCTION
   Per Member Per Month: {_fmt_pmpm(cc["per_member_per_month"])}
   Rationale:    {cc["rationale"]}
   Source:       {cc["source"]}

5. CLAIMS SPLIT (Medical / Rx)
   Medical Portion: {_fmt_pct(cs["medical_portion"])}
   Rx Portion:      {_fmt_pct(cs["rx_portion"])}
   Rationale:       {cs["rationale"]}

6. DISCOUNT RATE
   Annual Rate:  {_fmt_pct(dr["annual_rate"])}
   Rationale:    {dr["rationale"]}
   Source:       {dr["source"]}
   Sensitivity:  Low {_fmt_pct(dr["sensitivity_low"])} / High {_fmt_pct(dr["sensitivity_high"])}

7. PROJECTION BASIS
   Frequency:    Monthly
   Compounding:  Continuous (trend applied to midpoint of each period)
"""

    # ── Results Section ───────────────────────────────────────────────────────
    results_section = f"""VALUATION RESULTS
=================
Valuation ID: {result.valuation_id}

FINANCIAL SUMMARY
  Total Projected Premium:        {_fmt_dollars(result.total_projected_premium)}
  Total Projected Claims (Net):   {_fmt_dollars(result.total_projected_claims)}
  Total Net Cash Flow:            {_fmt_dollars(result.total_net_cash_flow)}
  Gross Premium Valuation (GPV):  {_fmt_dollars(result.gpv)}

TREND IMPACT BREAKDOWN (Total over projection period)
  Medical Trend Incremental Cost: {_fmt_dollars(result.medical_trend_impact)}
  Rx Trend Incremental Cost:      {_fmt_dollars(result.rx_trend_impact)}
  Claims Adjustment:              {_fmt_dollars(result.claims_adj_impact)}
  Cash Card Benefit (Reduction):  ({_fmt_dollars(result.cash_card_impact)})

UNIT COST METRICS
  Current Premium PMPM:           {_fmt_pmpm(result.current_premium_pmpm)}
  Projected Claims PMPM:          {_fmt_pmpm(result.projected_claims_pmpm)}
  Projected Loss Ratio:           {_fmt_pct(result.loss_ratio)}

MONTHLY PROJECTION SCHEDULE (First 12 periods)
  {'Period':<8} {'Date':<12} {'Net Claims':>14} {'Premium':>14} {'Net CF':>14} {'PV Net CF':>14}
  {'-'*76}
"""
    for mp in result.monthly_projections[:12]:
        results_section += (
            f"  {mp.period:<8} {mp.projection_date:<12} "
            f"  {_fmt_dollars(mp.net_claims):>12} "
            f"  {_fmt_dollars(mp.monthly_premium):>12} "
            f"  {_fmt_dollars(mp.net_cash_flow):>12} "
            f"  {_fmt_dollars(mp.pv_net_cash_flow):>12}\n"
        )
    if len(result.monthly_projections) > 12:
        results_section += f"  ... ({len(result.monthly_projections) - 12} additional periods not shown)\n"

    # ── Scenarios Section ─────────────────────────────────────────────────────
    if scenarios:
        scenarios_section = "SCENARIO ANALYSIS\n" + "=" * 50 + "\n\n"
        scenarios_section += f"  {'Scenario':<22} {'GPV':>14} {'Loss Ratio':>12} {'Claims PMPM':>14}\n"
        scenarios_section += f"  {'-'*65}\n"
        for sc in scenarios:
            r = sc.result
            scenarios_section += (
                f"  {sc.scenario_name:<22} {_fmt_dollars(r.gpv):>14} "
                f"{_fmt_pct(r.loss_ratio):>12} {_fmt_pmpm(r.projected_claims_pmpm):>14}\n"
            )
        scenarios_section += "\nScenario Descriptions:\n"
        for sc in scenarios:
            scenarios_section += f"  • {sc.scenario_name}: {sc.scenario_description}\n"
    else:
        scenarios_section = "SCENARIO ANALYSIS\n" + "=" * 50 + "\nNo scenario analysis performed for this valuation.\n"

    # ── Comparison Section ────────────────────────────────────────────────────
    if previous_result:
        gpv_chg = result.gpv - previous_result.gpv
        lr_chg = result.loss_ratio - previous_result.loss_ratio
        comparison_section = f"""COMPARISON TO PRIOR VALUATION
==============================
Prior Valuation ID:   {previous_result.valuation_id}
Prior Valuation Date: {previous_result.valuation_date}

                        Current          Prior            Change
  GPV:              {_fmt_dollars(result.gpv):>14}   {_fmt_dollars(previous_result.gpv):>14}   {_fmt_dollars(gpv_chg):>14}
  Loss Ratio:       {_fmt_pct(result.loss_ratio):>14}   {_fmt_pct(previous_result.loss_ratio):>14}   {_fmt_pct(lr_chg):>14}
  Claims PMPM:      {_fmt_pmpm(result.projected_claims_pmpm):>14}   {_fmt_pmpm(previous_result.projected_claims_pmpm):>14}
  Proj Months:      {result.projection_months:>14}   {previous_result.projection_months:>14}

Analysis: The GPV {"improved" if gpv_chg >= 0 else "deteriorated"} by {_fmt_dollars(abs(gpv_chg))} versus
the prior valuation. {"This improvement reflects" if gpv_chg >= 0 else "Key drivers include"} changes in
projection period, assumptions, or plan experience since the prior valuation date.
"""
    else:
        comparison_section = "COMPARISON TO PRIOR VALUATION\n" + "=" * 50 + "\nNo prior valuation available for comparison.\n"

    # ── Conclusions Section ───────────────────────────────────────────────────
    if result.gpv < 0:
        action = (
            f"The plan shows a DEFICIENCY of {_fmt_dollars(abs(result.gpv))}. "
            "Management should consider rate action, benefit redesign, or reserve strengthening."
        )
    elif result.loss_ratio > 0.90:
        action = (
            f"While a technical surplus exists ({_fmt_dollars(result.gpv)}), the loss ratio of "
            f"{_fmt_pct(result.loss_ratio)} leaves limited margin. Rate monitoring is advised."
        )
    else:
        action = (
            f"The plan demonstrates adequate premium adequacy with a surplus of "
            f"{_fmt_dollars(result.gpv)} and a loss ratio of {_fmt_pct(result.loss_ratio)}."
        )

    conclusions_section = f"""CONCLUSIONS AND RECOMMENDATIONS
================================
{action}

This opinion is based on the assumptions and data described herein and is intended
for the internal use of management in evaluating premium adequacy for group health
contract {result.client_name}. The actuary is not responsible for actions taken
by others based on this analysis without full consideration of the limitations noted.

Prepared by: [Credentialed Actuary — MAAA, FSA/ASA]
Date:        {today}
"""
    if actuary_note:
        conclusions_section += f"\nActuary's Note: {actuary_note}\n"

    # ── Assemble Full Opinion ─────────────────────────────────────────────────
    header = f"""================================================================================
DRAFT ACTUARIAL OPINION
GROSS PREMIUM VALUATION — LARGE GROUP HEALTH INSURANCE
================================================================================
Client:         {result.client_name}
Prepared:       {today}
Opinion ID:     {opinion_id}
Valuation ID:   {result.valuation_id}
DRAFT — FOR REVIEW PURPOSES ONLY — NOT FOR DISTRIBUTION
================================================================================

"""

    full_opinion = header + exec_summary + "\n\n" + assumptions_section + "\n\n" + results_section + "\n\n" + scenarios_section + "\n\n" + comparison_section + "\n\n" + conclusions_section

    return ActuarialOpinion(
        opinion_id=opinion_id,
        created_date=today,
        valuation_id=result.valuation_id,
        client_name=result.client_name,
        actuary_note=actuary_note,
        executive_summary=exec_summary,
        assumptions_section=assumptions_section,
        results_section=results_section,
        scenarios_section=scenarios_section,
        comparison_section=comparison_section,
        conclusions_section=conclusions_section,
        full_opinion=full_opinion,
    )
