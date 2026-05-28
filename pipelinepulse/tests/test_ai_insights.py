"""Tests for the AI insight layer (Claude). No live credentials required."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from pipelinepulse.ai_insights import PIPELINE_PROMPT, build_prompt, generate_insights
from pipelinepulse.config import AppConfig
from pipelinepulse.salesforce_client import Opportunity
from pipelinepulse.scoring import score_opportunity

REF = date(2025, 6, 16)


@pytest.fixture
def scored_deals():
    config = AppConfig().scoring
    opps = [
        Opportunity(
            name="Vertex Holdings - Enterprise Rollout",
            stage="Qualification",
            amount=400_000.0,
            close_date=date(2025, 6, 6),
            last_activity_date=date(2025, 4, 28),
            created_date=date(2025, 2, 20),
            owner="Dana Whitfield",
        ),
        Opportunity(
            name="Acme Corp - Platform Expansion",
            stage="Negotiation/Review",
            amount=250_000.0,
            close_date=date(2025, 6, 28),
            last_activity_date=date(2025, 6, 13),
            created_date=date(2025, 4, 15),
            owner="Dana Whitfield",
        ),
    ]
    return [score_opportunity(o, config, REF) for o in opps]


@pytest.fixture
def summary(scored_deals):
    from pipelinepulse.scoring import summarize

    return summarize(scored_deals)


class FakeClient:
    """Records the kwargs it was called with and returns a canned response."""

    def __init__(self, text="## Summary\nPipeline looks tense today."):
        self.text = text
        self.calls = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        # Mimic a multi-block Claude response.
        return SimpleNamespace(
            content=[
                SimpleNamespace(type="text", text=self.text),
                SimpleNamespace(type="text", text="\n## Next Steps\nFollow up."),
            ]
        )


class ErrorClient:
    def __init__(self):
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        raise RuntimeError("simulated API outage")


def test_prompt_contains_rules_and_data(scored_deals, summary):
    prompt = build_prompt(scored_deals, summary, REF)
    # The deterministic guardrail must be present.
    assert "Do NOT recalculate" in prompt
    # Reporting date and a deal name flow through.
    assert REF.isoformat() in prompt
    assert "Vertex Holdings - Enterprise Rollout" in prompt
    # The deterministic scores/statuses are passed through verbatim.
    assert '"health_score"' in prompt
    assert '"status"' in prompt
    assert "at-risk" in prompt


def test_prompt_template_has_all_sections():
    for marker in ("Summary", "Key Risks", "Forecasting Concerns", "Recommended Next Steps"):
        assert marker in PIPELINE_PROMPT


def test_generate_insights_normal_response(scored_deals, summary):
    client = FakeClient()
    config = AppConfig().ai
    result = generate_insights(scored_deals, summary, config, REF, client=client)

    assert "Pipeline looks tense today." in result
    assert "Follow up." in result  # multi-block concatenation
    # Verify the model/config were used and the prompt was passed.
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["model"] == config.model
    assert call["max_tokens"] == config.max_tokens
    assert "Do NOT recalculate" in call["messages"][0]["content"]


def test_generate_insights_handles_api_error(scored_deals, summary):
    config = AppConfig().ai
    result = generate_insights(scored_deals, summary, config, REF, client=ErrorClient())
    # No exception is raised; a deterministic fallback digest is returned.
    assert isinstance(result, str)
    assert "## Summary" in result
    assert "Vertex Holdings - Enterprise Rollout" in result


def test_generate_insights_empty_response_falls_back(scored_deals, summary):
    config = AppConfig().ai
    empty_client = FakeClient(text="")
    # Both blocks empty -> treated as failure -> fallback.
    empty_client.messages.create = lambda **k: SimpleNamespace(content=[])
    result = generate_insights(scored_deals, summary, config, REF, client=empty_client)
    assert "## Summary" in result
