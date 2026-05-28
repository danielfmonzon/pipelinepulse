"""Tests for the deterministic scoring engine."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from pipelinepulse.config import AppConfig
from pipelinepulse.salesforce_client import Opportunity
from pipelinepulse.scoring import (
    AT_RISK,
    HEALTHY,
    SLIPPING,
    score_opportunity,
    score_pipeline,
    summarize,
)

REF = date(2025, 6, 16)


@pytest.fixture
def scoring_config():
    return AppConfig().scoring


def make_opp(
    *,
    stage="Negotiation/Review",
    amount=50_000.0,
    days_to_close=20,
    days_since_activity=2,
    age_days=30,
    owner="Test Owner",
    name="Test Deal",
) -> Opportunity:
    return Opportunity(
        name=name,
        stage=stage,
        amount=amount,
        close_date=REF + timedelta(days=days_to_close),
        last_activity_date=REF - timedelta(days=days_since_activity),
        created_date=REF - timedelta(days=age_days),
        owner=owner,
    )


def test_healthy_classification(scoring_config):
    opp = make_opp(days_since_activity=3, days_to_close=21, stage="Negotiation/Review")
    deal = score_opportunity(opp, scoring_config, REF)
    assert deal.status == HEALTHY
    assert deal.health_score >= scoring_config.health_thresholds.healthy
    assert deal.risk_reasons == ["On track — no material risk signals."]


def test_slipping_classification(scoring_config):
    # Warn-level idle + near-close in a non-advanced stage -> middling score.
    opp = make_opp(
        stage="Value Proposition",
        days_since_activity=18,  # warn (>=14)
        days_to_close=4,         # near close (<=7) and not advanced
        amount=60_000.0,
    )
    deal = score_opportunity(opp, scoring_config, REF)
    assert deal.status == SLIPPING
    t = scoring_config.health_thresholds
    assert t.at_risk <= deal.health_score < t.healthy


def test_at_risk_classification(scoring_config):
    # Overdue + critically idle + stuck early-stage -> very low score.
    opp = make_opp(
        stage="Qualification",
        days_since_activity=49,  # critical
        days_to_close=-10,       # overdue
        age_days=116,            # stuck early-stage
        amount=400_000.0,
    )
    deal = score_opportunity(opp, scoring_config, REF)
    assert deal.status == AT_RISK
    assert deal.health_score < scoring_config.health_thresholds.at_risk


def test_risk_reasons_are_generated(scoring_config):
    opp = make_opp(days_since_activity=40, days_to_close=-5, stage="Prospecting", age_days=90)
    deal = score_opportunity(opp, scoring_config, REF)
    joined = " ".join(deal.risk_reasons).lower()
    assert "overdue" in joined
    assert "activity" in joined
    assert len(deal.risk_reasons) >= 2


def test_no_activity_date_is_penalized(scoring_config):
    opp = make_opp()
    opp.last_activity_date = None
    deal = score_opportunity(opp, scoring_config, REF)
    assert any("activity" in r.lower() for r in deal.risk_reasons)
    assert deal.health_score < 100


def test_amount_weighting_changes_priority(scoring_config):
    """Identical risk profile, different deal size -> different priority/score."""
    base = dict(
        stage="Qualification",
        days_since_activity=49,
        days_to_close=-10,
        age_days=116,
    )
    enterprise = score_opportunity(make_opp(**base, amount=400_000.0), scoring_config, REF)
    smb = score_opportunity(make_opp(**base, amount=5_000.0), scoring_config, REF)

    assert enterprise.amount_tier == "enterprise"
    assert smb.amount_tier == "smb"
    # Both at-risk, but the enterprise deal is escalated higher.
    assert enterprise.recommended_priority == "P1"
    assert smb.recommended_priority == "P2"
    # Large deals carry an extra risk-emphasis penalty when already flagged.
    assert enterprise.health_score <= smb.health_score
    assert any("high-value" in r.lower() for r in enterprise.risk_reasons)


def test_missing_amount_is_handled(scoring_config):
    opp = make_opp(amount=None)
    deal = score_opportunity(opp, scoring_config, REF)
    assert deal.amount_tier == "smb"
    assert any("amount not set" in r.lower() for r in deal.risk_reasons)


def test_pipeline_sorted_worst_first_and_summary(scoring_config):
    opps = [
        make_opp(name="Good", days_since_activity=2, days_to_close=20),
        make_opp(
            name="Bad",
            stage="Qualification",
            days_since_activity=49,
            days_to_close=-10,
            age_days=116,
            amount=400_000.0,
        ),
    ]
    scored = score_pipeline(opps, scoring_config, REF)
    assert scored[0].opportunity.name == "Bad"  # at-risk sorts first
    summary = summarize(scored)
    assert summary["total_deals"] == 2
    assert summary["counts"][AT_RISK] == 1
    assert summary["counts"][HEALTHY] == 1
