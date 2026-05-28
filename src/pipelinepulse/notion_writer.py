"""Notion writer.

Posts the daily pipeline digest as a new page in a Notion database. Uses the
official ``notion-client`` SDK (imported lazily). Secrets come from the
environment: NOTION_API_KEY and NOTION_DATABASE_ID.

In dry-run mode no network call is made — the caller renders the digest to the
console instead.
"""

from __future__ import annotations

import logging
import os
from datetime import date

from .config import NotionConfig
from .scoring import ScoredDeal

logger = logging.getLogger(__name__)

_STATUS_EMOJI = {"at-risk": "🔴", "slipping": "🟠", "healthy": "🟢"}


def write_digest(
    narrative: str,
    scored: list[ScoredDeal],
    summary: dict[str, object],
    config: NotionConfig,
    reference_date: date,
    dry_run: bool = False,
) -> dict[str, object] | None:
    """Write the digest to Notion. Returns the created page, or None on dry-run.

    On dry-run the Notion API is never contacted.
    """
    if dry_run:
        logger.info("Dry-run: skipping Notion write.")
        return None

    try:
        from notion_client import Client  # lazy import
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "notion-client is not installed. Run `pip install -r requirements.txt`."
        ) from exc

    token = _require_env("NOTION_API_KEY")
    database_id = _require_env("NOTION_DATABASE_ID")

    client = Client(auth=token)
    title = f"{config.digest_title} — {reference_date.isoformat()}"
    children = _build_blocks(narrative, scored, summary, config)

    try:
        page = client.pages.create(
            parent={"database_id": database_id},
            properties={"Name": {"title": [{"text": {"content": title}}]}},
            children=children,
        )
        logger.info("Posted digest to Notion: %s", page.get("id"))
        return page
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to write digest to Notion: %s", exc)
        raise RuntimeError(f"Notion write failed: {exc}") from exc


def _build_blocks(
    narrative: str,
    scored: list[ScoredDeal],
    summary: dict[str, object],
    config: NotionConfig,
) -> list[dict]:
    """Build Notion block children: heading, callout summary, per-deal blocks."""
    counts = summary.get("counts", {})  # type: ignore[assignment]
    callout = (
        f"{summary.get('total_deals', 0)} open deals · "
        f"{counts.get('at-risk', 0)} at-risk · "
        f"{counts.get('slipping', 0)} slipping · "
        f"{counts.get('healthy', 0)} healthy. "
        f"At-risk pipeline: ${summary.get('at_risk_amount', 0):,.0f}."
    )

    blocks: list[dict] = [
        _heading(config.digest_title, level=2),
        {
            "object": "block",
            "type": "callout",
            "callout": {
                "icon": {"emoji": "📊"},
                "rich_text": _rich_text(callout),
            },
        },
        _heading("Pipeline Narrative", level=3),
    ]
    blocks += _narrative_blocks(narrative)
    blocks.append(_heading("Flagged Deals", level=3))

    flagged = [
        d
        for d in scored
        if d.is_flagged or config.include_healthy_in_table
    ][: config.max_flagged_deals]

    if not flagged:
        blocks.append(_paragraph("No flagged deals today. 🎉"))
        return blocks

    for deal in flagged:
        blocks += _deal_blocks(deal)
    return blocks


def _deal_blocks(deal: ScoredDeal) -> list[dict]:
    opp = deal.opportunity
    emoji = _STATUS_EMOJI.get(deal.status, "•")
    amount = f"${opp.amount:,.0f}" if opp.amount is not None else "N/A"
    close = opp.close_date.isoformat() if opp.close_date else "N/A"
    header = f"{emoji} {opp.name} — {deal.recommended_priority} ({deal.status})"
    details = [
        f"Owner: {opp.owner}",
        f"Amount: {amount}  ·  Stage: {opp.stage}  ·  Close: {close}",
        f"Health score: {deal.health_score}",
        f"Risk: {'; '.join(deal.risk_reasons)}",
        f"Next action: {deal.suggested_action}",
    ]
    blocks: list[dict] = [_heading(header, level=3)]
    blocks += [_bullet(line) for line in details]
    return blocks


def _narrative_blocks(narrative: str) -> list[dict]:
    """Convert the Claude markdown narrative into simple paragraph blocks."""
    blocks: list[dict] = []
    for line in narrative.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            blocks.append(_paragraph(line.lstrip("# ").strip()))
        elif line.startswith(("-", "*")):
            blocks.append(_bullet(line.lstrip("-* ").strip()))
        else:
            blocks.append(_paragraph(line))
    return blocks or [_paragraph(narrative)]


def _heading(text: str, level: int = 2) -> dict:
    key = f"heading_{level}"
    return {"object": "block", "type": key, key: {"rich_text": _rich_text(text)}}


def _paragraph(text: str) -> dict:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": _rich_text(text)},
    }


def _bullet(text: str) -> dict:
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": _rich_text(text)},
    }


def _rich_text(text: str) -> list[dict]:
    # Notion caps rich-text content at 2000 chars per block.
    return [{"type": "text", "text": {"content": text[:2000]}}]


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value
