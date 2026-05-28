"""AI insight layer.

Turns the deterministic scoring output into a plain-English pipeline digest
using the Anthropic Claude API. The LLM never recomputes scores — it receives
the already-scored deals and only summarizes, explains risk, flags forecasting
concerns, and recommends next steps in language a revenue team can act on.

Design notes:
  * The prompt lives in one reusable template constant (``PIPELINE_PROMPT``).
  * ``generate_insights`` accepts an injectable ``client`` so tests can mock the
    API without credentials.
  * Multi-block responses are concatenated.
  * Any API failure degrades gracefully to a deterministic local summary so the
    pipeline still produces a usable digest.
"""

from __future__ import annotations

import json
import logging
from datetime import date

from .config import AIConfig
from .scoring import ScoredDeal

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Reusable prompt framework. Sections: ROLE -> CONTEXT -> RULES -> DATA -> TASK
# Keeping this as a single template makes the prompt versionable and testable.
# --------------------------------------------------------------------------- #
PIPELINE_PROMPT = """You are a sales-operations analyst writing a concise daily \
pipeline digest for a revenue team. Your audience is account executives and \
their sales manager. Be direct, specific, and action-oriented.

CONTEXT
- Reporting date: {reference_date}
- Pipeline totals: {summary}

GROUND RULES
- The deal statuses and health scores below were computed by a deterministic \
rules engine. Treat them as fixed facts. Do NOT recalculate, second-guess, or \
invent new scores.
- Only discuss the deals provided. Do not fabricate deals, names, or numbers.
- Write for busy sales leaders: short sentences, no fluff, no preamble.

SCORED DEALS (JSON)
{deals_json}

TASK
Produce a digest with these sections, using markdown headers:
1. **Summary** — 2-3 sentences on overall pipeline health for the day.
2. **Key Risks** — bullet the most important at-risk and slipping deals and why.
3. **Forecasting Concerns** — call out exposure to the forecast (e.g. large \
deals slipping, overdue close dates).
4. **Recommended Next Steps** — one specific next action per flagged deal, \
addressed to the deal owner.
Keep the whole digest under 350 words."""


def build_prompt(
    scored: list[ScoredDeal],
    summary: dict[str, object],
    reference_date: date,
) -> str:
    """Render the reusable prompt template with the scored pipeline data."""
    deals_payload = [_deal_to_dict(d) for d in scored]
    return PIPELINE_PROMPT.format(
        reference_date=reference_date.isoformat(),
        summary=json.dumps(summary, default=str),
        deals_json=json.dumps(deals_payload, indent=2, default=str),
    )


def generate_insights(
    scored: list[ScoredDeal],
    summary: dict[str, object],
    config: AIConfig,
    reference_date: date,
    client: object | None = None,
) -> str:
    """Generate the narrative digest via Claude, falling back locally on error.

    ``client`` may be injected (for tests/mocks). When omitted, a real
    ``anthropic.Anthropic`` client is constructed from the ANTHROPIC_API_KEY
    environment variable.
    """
    prompt = build_prompt(scored, summary, reference_date)

    try:
        if client is None:
            client = _default_client()
        response = client.messages.create(
            model=config.model,
            max_tokens=config.max_tokens,
            temperature=config.temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        text = _extract_text(response)
        if not text.strip():
            raise ValueError("Empty response from Claude")
        return text
    except Exception as exc:  # noqa: BLE001 - we deliberately degrade gracefully
        logger.warning("Claude insight generation failed (%s); using local fallback.", exc)
        return _fallback_summary(scored, summary, reference_date)


def _default_client():
    try:
        from anthropic import Anthropic  # lazy import
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "anthropic is not installed. Run `pip install -r requirements.txt`."
        ) from exc
    return Anthropic()


def _extract_text(response: object) -> str:
    """Concatenate text from a (possibly multi-block) Claude response."""
    content = getattr(response, "content", None)
    if content is None and isinstance(response, dict):
        content = response.get("content")
    if not content:
        return ""
    parts: list[str] = []
    for block in content:
        text = getattr(block, "text", None)
        if text is None and isinstance(block, dict):
            text = block.get("text")
        if text:
            parts.append(text)
    return "\n".join(parts)


def _deal_to_dict(deal: ScoredDeal) -> dict[str, object]:
    opp = deal.opportunity
    return {
        "name": opp.name,
        "owner": opp.owner,
        "amount": opp.amount,
        "stage": opp.stage,
        "close_date": opp.close_date.isoformat() if opp.close_date else None,
        "status": deal.status,
        "health_score": deal.health_score,
        "priority": deal.recommended_priority,
        "risk_reasons": deal.risk_reasons,
    }


def _fallback_summary(
    scored: list[ScoredDeal],
    summary: dict[str, object],
    reference_date: date,
) -> str:
    """Deterministic digest used when the Claude API is unavailable."""
    counts = summary.get("counts", {})  # type: ignore[assignment]
    flagged = [d for d in scored if d.is_flagged]
    lines = [
        f"## Summary",
        f"Pipeline digest for {reference_date.isoformat()} (offline fallback — "
        f"AI narrative unavailable). {summary.get('total_deals', 0)} open deals: "
        f"{counts.get('at-risk', 0)} at-risk, {counts.get('slipping', 0)} slipping, "
        f"{counts.get('healthy', 0)} healthy.",
        "",
        "## Key Risks",
    ]
    if flagged:
        for d in flagged:
            reason = d.risk_reasons[0] if d.risk_reasons else "Flagged for review."
            lines.append(
                f"- [{d.recommended_priority}] {d.opportunity.name} "
                f"({d.status}, score {d.health_score}): {reason}"
            )
    else:
        lines.append("- No flagged deals today.")
    lines += ["", "## Recommended Next Steps"]
    for d in flagged:
        lines.append(f"- {d.opportunity.name}: {d.suggested_action}")
    return "\n".join(lines)
