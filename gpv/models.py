from __future__ import annotations
from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, Field


class ClientData(BaseModel):
    client_id: str
    client_name: str
    num_members: int = Field(gt=0)
    monthly_premium_pmpm: float = Field(gt=0, description="Per-member per-month premium")
    annual_expected_claims: float = Field(gt=0, description="Total annual expected claims")
    contract_end_date: date
    plan_type: Optional[str] = None
    industry: Optional[str] = None
    notes: Optional[str] = None


class TrendAssumption(BaseModel):
    annual_rate: float
    description: str
    source: str
    rationale: str
    sensitivity_low: float
    sensitivity_high: float


class CashCardAssumption(BaseModel):
    per_member_per_month: float
    description: str
    source: str
    rationale: str
    sensitivity_low: float
    sensitivity_high: float


class ClaimsSplitAssumption(BaseModel):
    medical_portion: float
    rx_portion: float
    description: str
    source: str
    rationale: str


class DiscountRateAssumption(BaseModel):
    annual_rate: float
    description: str
    source: str
    rationale: str
    sensitivity_low: float
    sensitivity_high: float


class ProjectionBasis(BaseModel):
    frequency: str
    trend_compounding: str
    description: str


class Assumptions(BaseModel):
    version: str
    effective_date: str
    description: str
    source: str
    last_updated: str
    updated_by: str
    medical_trend: TrendAssumption
    rx_trend: TrendAssumption
    claims_adjustment: TrendAssumption
    cash_card_claims: CashCardAssumption
    claims_split: ClaimsSplitAssumption
    discount_rate: DiscountRateAssumption
    projection_basis: ProjectionBasis


class MonthlyProjection(BaseModel):
    period: int  # months from valuation date
    projection_date: str
    members: int
    gross_claims: float
    medical_claims: float
    rx_claims: float
    claims_adjustment: float
    cash_card_deduction: float
    net_claims: float
    monthly_premium: float
    net_cash_flow: float  # premium - claims (positive = surplus)
    discount_factor: float
    pv_net_cash_flow: float


class ValuationResult(BaseModel):
    valuation_id: str
    valuation_date: str
    client_id: str
    client_name: str
    contract_end_date: str
    projection_months: int
    assumptions_version: str

    # Summary totals
    total_projected_claims: float
    total_projected_premium: float
    total_net_cash_flow: float
    gpv: float  # present value of (premium - claims); negative = liability

    # PMPM metrics
    projected_claims_pmpm: float
    current_premium_pmpm: float
    loss_ratio: float  # claims / premium

    # Trend impact breakdown
    medical_trend_impact: float
    rx_trend_impact: float
    claims_adj_impact: float
    cash_card_impact: float

    monthly_projections: list[MonthlyProjection]
    assumptions_snapshot: dict


class ScenarioResult(BaseModel):
    scenario_name: str
    scenario_description: str
    assumptions_override: dict
    result: ValuationResult


class PortfolioValuation(BaseModel):
    portfolio_id: str
    valuation_date: str
    client_results: list[ValuationResult]
    portfolio_gpv: float
    total_members: int
    total_annual_premium: float
    total_annual_claims: float
    portfolio_loss_ratio: float


class ActuarialOpinion(BaseModel):
    opinion_id: str
    created_date: str
    valuation_id: str
    client_name: str
    actuary_note: str
    executive_summary: str
    assumptions_section: str
    results_section: str
    scenarios_section: str
    comparison_section: str
    conclusions_section: str
    full_opinion: str


class AssumptionUpdate(BaseModel):
    field_path: str = Field(description="Dot-separated path e.g. 'medical_trend.annual_rate'")
    new_value: float | str
    updated_by: str
    rationale: str
