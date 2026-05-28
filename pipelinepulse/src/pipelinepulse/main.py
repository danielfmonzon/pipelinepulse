"""PipelinePulse CLI entrypoint.

Orchestrates: load config -> fetch opportunities (Salesforce or mock) -> score
deterministically -> generate Claude narrative -> publish to Notion (or print a
console digest in dry-run).

Examples:
    python -m pipelinepulse.main --dry-run --use-mock-data
    python -m pipelinepulse.main --config config.yaml
"""

from __future__ import annotations

import argparse
import logging
from datetime import date
from pathlib import Path

from .ai_insights import generate_insights
from .config import AppConfig, load_config
from .salesforce_client import (
    Opportunity,
    SalesforceClient,
    load_mock_opportunities,
)
from .scoring import score_pipeline, summarize

logger = logging.getLogger("pipelinepulse")

# Repo-root-relative path to the demo fixture (src/pipelinepulse/main.py -> repo).
DEFAULT_MOCK_PATH = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "mock_opportunities.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pipelinepulse",
        description="AI sales-ops automation: Salesforce -> scoring -> Claude -> Notion.",
    )
    parser.add_argument(
        "--config", default="config.yaml", help="Path to config.yaml (default: config.yaml)."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the digest to the console instead of writing to Notion.",
    )
    parser.add_argument(
        "--use-mock-data",
        action="store_true",
        help="Use the bundled mock opportunities fixture (no Salesforce needed).",
    )
    parser.add_argument(
        "--mock-path",
        default=str(DEFAULT_MOCK_PATH),
        help="Override the mock fixture path.",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose logging."
    )
    return parser


def resolve_reference_date(config: AppConfig, use_mock_data: bool) -> date:
    """Mock runs use the fixed demo date for reproducibility; live runs use today."""
    if use_mock_data and config.demo.reference_date:
        return date.fromisoformat(config.demo.reference_date)
    return date.today()


def load_opportunities(config: AppConfig, args: argparse.Namespace) -> list[Opportunity]:
    if args.use_mock_data:
        logger.info("Loading mock opportunities from %s", args.mock_path)
        return load_mock_opportunities(args.mock_path, config.salesforce_fields)
    client = SalesforceClient(config.salesforce_fields)
    return client.fetch_open_opportunities()


def format_console_digest(scored, summary, narrative, reference_date) -> str:
    counts = summary["counts"]
    bar = "=" * 72
    lines = [
        bar,
        f"  PIPELINEPULSE — DAILY DIGEST ({reference_date.isoformat()})",
        bar,
        f"  {summary['total_deals']} open deals  |  "
        f"at-risk: {counts['at-risk']}  slipping: {counts['slipping']}  "
        f"healthy: {counts['healthy']}",
        f"  Total pipeline: ${summary['total_pipeline_amount']:,.0f}  |  "
        f"at-risk exposure: ${summary['at_risk_amount']:,.0f}",
        bar,
        "",
        "AI NARRATIVE",
        "-" * 72,
        narrative.strip(),
        "",
        "FLAGGED DEALS",
        "-" * 72,
    ]
    flagged = [d for d in scored if d.is_flagged]
    if not flagged:
        lines.append("  None — pipeline looks healthy today.")
    for d in flagged:
        opp = d.opportunity
        amount = f"${opp.amount:,.0f}" if opp.amount is not None else "N/A"
        close = opp.close_date.isoformat() if opp.close_date else "N/A"
        lines += [
            f"[{d.recommended_priority}] {opp.name}  ({d.status}, score {d.health_score})",
            f"     owner={opp.owner}  amount={amount}  stage={opp.stage}  close={close}",
            f"     risk: {'; '.join(d.risk_reasons)}",
            f"     next: {d.suggested_action}",
            "",
        ]
    lines.append(bar)
    return "\n".join(lines)


def run(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    reference_date = resolve_reference_date(config, args.use_mock_data)

    opportunities = load_opportunities(config, args)
    scored = score_pipeline(opportunities, config.scoring, reference_date)
    summary = summarize(scored)

    narrative = generate_insights(scored, summary, config.ai, reference_date)

    if args.dry_run:
        print(format_console_digest(scored, summary, narrative, reference_date))
        return 0

    from .notion_writer import write_digest  # lazy: only when actually publishing

    write_digest(narrative, scored, summary, config.notion, reference_date, dry_run=False)
    logger.info("Digest published to Notion.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
