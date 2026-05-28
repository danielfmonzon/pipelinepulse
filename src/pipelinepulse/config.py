"""Configuration models and loader.

All tunable behavior (field mappings, scoring thresholds, amount weighting,
Notion output, Claude model) lives in ``config.yaml`` and is validated here with
pydantic. Secrets never live in config — they come from environment variables.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

# Default Salesforce sales-process stage ordering (Prospecting -> Closed).
_DEFAULT_STAGE_ORDER = {
    "Prospecting": 1,
    "Qualification": 2,
    "Needs Analysis": 3,
    "Value Proposition": 4,
    "Proposal/Price Quote": 5,
    "Negotiation/Review": 6,
}


class SalesforceFieldMap(BaseModel):
    """Maps logical fields to Salesforce API field names (override per org)."""

    name: str = "Name"
    stage: str = "StageName"
    amount: str = "Amount"
    close_date: str = "CloseDate"
    last_activity_date: str = "LastActivityDate"
    created_date: str = "CreatedDate"


class HealthThresholds(BaseModel):
    """Score cutoffs. healthy >= ``healthy``; at-risk < ``at_risk``; else slipping."""

    healthy: int = 75
    at_risk: int = 40


class ActivityRules(BaseModel):
    """Penalties for stale opportunities based on days since last activity."""

    stale_days_warn: int = 14
    stale_days_critical: int = 30
    penalty_warn: int = 15
    penalty_critical: int = 30


class CloseDateRules(BaseModel):
    """Penalties for slipping / unrealistic close dates."""

    overdue_penalty: int = 35
    near_close_days: int = 7
    near_close_penalty: int = 15


class StageRules(BaseModel):
    """Penalties for deals stuck in early stages for too long ("stage age")."""

    order: dict[str, int] = Field(default_factory=lambda: dict(_DEFAULT_STAGE_ORDER))
    early_stage_max_order: int = 2
    stale_deal_age_days: int = 45
    stuck_penalty: int = 20


class AmountRules(BaseModel):
    """Amount weighting for priority tiers and large-deal risk emphasis."""

    enterprise_threshold: float = 100_000
    midmarket_threshold: float = 25_000
    large_deal_risk_penalty: int = 5


class ScoringConfig(BaseModel):
    health_thresholds: HealthThresholds = Field(default_factory=HealthThresholds)
    activity: ActivityRules = Field(default_factory=ActivityRules)
    close_date: CloseDateRules = Field(default_factory=CloseDateRules)
    stage: StageRules = Field(default_factory=StageRules)
    amount: AmountRules = Field(default_factory=AmountRules)


class NotionConfig(BaseModel):
    digest_title: str = "Daily Pipeline Digest"
    max_flagged_deals: int = 25
    include_healthy_in_table: bool = False


class AIConfig(BaseModel):
    model: str = "claude-sonnet-4-5-20250929"
    max_tokens: int = 1500
    temperature: float = 0.2


class DemoConfig(BaseModel):
    """Mock-mode behavior. A fixed reference date keeps the demo reproducible."""

    reference_date: str | None = "2025-06-16"


class AppConfig(BaseModel):
    salesforce_fields: SalesforceFieldMap = Field(default_factory=SalesforceFieldMap)
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)
    notion: NotionConfig = Field(default_factory=NotionConfig)
    ai: AIConfig = Field(default_factory=AIConfig)
    demo: DemoConfig = Field(default_factory=DemoConfig)


def load_config(path: str | Path = "config.yaml") -> AppConfig:
    """Load and validate configuration from a YAML file."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return AppConfig(**data)
