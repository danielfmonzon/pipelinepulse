"""Deterministic deal-health scoring engine.

No LLM is involved here. Every score is explainable and reproducible: we start
each deal at 100 points and subtract rule-based penalties for activity
staleness, slipping close dates, and deals stuck in early stages too long
("stage age"). Amount weighting drives the recommended priority and adds a small
risk emphasis for high-value deals.

Thresholds and penalties come from config so the logic stays business-readable
and tunable without code changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .config import ScoringConfig
from .salesforce_client import Opportunity

HEALTHY = "healthy"
SLIPPING = "slipping"
AT_RISK = "at-risk"

# Priority order used for sorting (worst-first) and reporting.
_STATUS_RANK = {AT_RISK: 0, SLIPPING: 1, HEALTHY: 2}
_PRIORITY_RANK = {"P1": 0, "P2": 1, "P3": 2}


@dataclass(slots=True)
class ScoredDeal:
    """An opportunity plus its deterministic health assessment."""

    opportunity: Opportunity
    health_score: int
    status: str
    risk_reasons: list[str] = field(default_factory=list)
    recommended_priority: str = "P3"
    amount_tier: str = "smb"
    suggested_action: str = ""

    @property
    def is_flagged(self) -> bool:
        return self.status in (SLIPPING, AT_RISK)


def amount_tier(amount: float | None, rules) -> str:
    """Classify a deal size as enterprise / midmarket / smb."""
    value = amount or 0.0
    if value >= rules.enterprise_threshold:
        return "enterprise"
    if value >= rules.midmarket_threshold:
        return "midmarket"
    return "smb"


def score_opportunity(
    opp: Opportunity,
    config: ScoringConfig,
    reference_date: date,
) -> ScoredDeal:
    """Score a single opportunity. Pure and deterministic."""
    penalty = 0
    reasons: list[str] = []

    # --- Rule 1: activity staleness -------------------------------------
    if opp.last_activity_date is None:
        penalty += config.activity.penalty_warn
        reasons.append("No recorded sales activity.")
    else:
        idle = (reference_date - opp.last_activity_date).days
        if idle >= config.activity.stale_days_critical:
            penalty += config.activity.penalty_critical
            reasons.append(f"No activity in {idle} days (critical).")
        elif idle >= config.activity.stale_days_warn:
            penalty += config.activity.penalty_warn
            reasons.append(f"No activity in {idle} days.")

    # --- Rule 2: close-date slip risk -----------------------------------
    max_order = max(config.stage.order.values(), default=1)
    stage_order = config.stage.order.get(opp.stage, 1)
    is_advanced = stage_order >= max_order  # only the final stage counts as "advanced"

    if opp.close_date is not None:
        days_to_close = (opp.close_date - reference_date).days
        if days_to_close < 0:
            penalty += config.close_date.overdue_penalty
            reasons.append(f"Close date is {abs(days_to_close)} days overdue.")
        elif days_to_close <= config.close_date.near_close_days and not is_advanced:
            penalty += config.close_date.near_close_penalty
            reasons.append(
                f"Close date in {days_to_close} days but still in '{opp.stage}'."
            )

    # --- Rule 3: stage age (stuck in an early stage) --------------------
    if opp.created_date is not None:
        deal_age = (reference_date - opp.created_date).days
        if (
            deal_age >= config.stage.stale_deal_age_days
            and stage_order <= config.stage.early_stage_max_order
        ):
            penalty += config.stage.stuck_penalty
            reasons.append(
                f"Open {deal_age} days but still early-stage ('{opp.stage}')."
            )

    # --- Rule 4: amount weighting ---------------------------------------
    tier = amount_tier(opp.amount, config.amount)
    if tier == "enterprise" and penalty > 0:
        penalty += config.amount.large_deal_risk_penalty
        reasons.append("High-value deal with open risks — prioritize.")
    if opp.amount is None:
        reasons.append("Amount not set on opportunity.")

    health_score = max(0, min(100, 100 - penalty))
    status = _classify(health_score, config.health_thresholds)
    if not reasons:
        reasons = ["On track — no material risk signals."]

    priority = _priority(status, tier)
    action = _suggested_action(status, opp, reference_date, config)

    return ScoredDeal(
        opportunity=opp,
        health_score=health_score,
        status=status,
        risk_reasons=reasons,
        recommended_priority=priority,
        amount_tier=tier,
        suggested_action=action,
    )


def score_pipeline(
    opportunities: list[Opportunity],
    config: ScoringConfig,
    reference_date: date,
) -> list[ScoredDeal]:
    """Score every opportunity and sort worst-first for reporting."""
    scored = [score_opportunity(o, config, reference_date) for o in opportunities]
    scored.sort(
        key=lambda d: (
            _STATUS_RANK.get(d.status, 3),
            _PRIORITY_RANK.get(d.recommended_priority, 3),
            -(d.opportunity.amount or 0.0),
        )
    )
    return scored


def summarize(scored: list[ScoredDeal]) -> dict[str, object]:
    """Aggregate pipeline-level stats used by the digest and the AI prompt."""
    flagged = [d for d in scored if d.is_flagged]
    by_status = {HEALTHY: 0, SLIPPING: 0, AT_RISK: 0}
    for deal in scored:
        by_status[deal.status] = by_status.get(deal.status, 0) + 1
    return {
        "total_deals": len(scored),
        "counts": by_status,
        "flagged_count": len(flagged),
        "total_pipeline_amount": sum(d.opportunity.amount or 0.0 for d in scored),
        "at_risk_amount": sum(
            d.opportunity.amount or 0.0 for d in scored if d.status == AT_RISK
        ),
    }


def _classify(score: int, thresholds) -> str:
    if score >= thresholds.healthy:
        return HEALTHY
    if score >= thresholds.at_risk:
        return SLIPPING
    return AT_RISK


def _priority(status: str, tier: str) -> str:
    """Combine risk severity and deal size into P1/P2/P3."""
    matrix = {
        (AT_RISK, "enterprise"): "P1",
        (AT_RISK, "midmarket"): "P1",
        (AT_RISK, "smb"): "P2",
        (SLIPPING, "enterprise"): "P1",
        (SLIPPING, "midmarket"): "P2",
        (SLIPPING, "smb"): "P3",
        (HEALTHY, "enterprise"): "P2",
        (HEALTHY, "midmarket"): "P3",
        (HEALTHY, "smb"): "P3",
    }
    return matrix.get((status, tier), "P3")


def _suggested_action(
    status: str,
    opp: Opportunity,
    reference_date: date,
    config: ScoringConfig,
) -> str:
    """Deterministic, reliable next-step recommendation per deal.

    This is the rule-based fallback action shown per deal. The Claude layer adds
    a narrative summary on top — but per-deal actions never depend on the LLM.
    """
    if status == HEALTHY:
        return "Maintain cadence; confirm next milestone."

    # Most severe driver first.
    if opp.close_date is not None and (opp.close_date - reference_date).days < 0:
        return f"Re-baseline close date with {opp.owner}; confirm the deal is still live."
    if opp.last_activity_date is None:
        return f"{opp.owner} to log a touchpoint and re-engage the buyer this week."
    idle = (reference_date - opp.last_activity_date).days
    if idle >= config.activity.stale_days_warn:
        return f"{opp.owner} to re-engage — no contact in {idle} days."
    return f"{opp.owner} to validate stage and next step with the buyer."
