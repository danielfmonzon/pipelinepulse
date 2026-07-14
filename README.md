# PipelinePulse
> AI sales-ops automation: scores Salesforce pipeline health with deterministic
> rules and posts a Claude-generated daily digest to Notion.

Python · Docker · GitHub Actions · MIT

## What it is
PipelinePulse pulls open opportunities from Salesforce, scores each deal's health
using transparent, deterministic rules (no black-box guessing), and publishes a
concise daily pipeline digest to Notion — written by Claude, grounded in the scored data.

## Why it exists
Pipeline reviews are manual, inconsistent, and stale by the time anyone reads them.
PipelinePulse turns a recurring judgment call into a repeatable, auditable pipeline
that runs itself.

## Status
🟡 Active — runs on a schedule via GitHub Actions.

## How it works
1. **Extract** — pull open opportunities from the Salesforce API.
2. **Score** — deterministic rules assign a health signal per deal (auditable; no LLM in this step).
3. **Narrate** — Claude turns scored data into a readable digest (LLM for language, not judgment).
4. **Publish** — post to a Notion database. Scheduled via GitHub Actions (cron `0 13 * * 1-5` — 13:00 UTC, Mon–Fri; manual runs via `workflow_dispatch`).

Design decision: keep scoring deterministic and reserve the LLM for communication.
The numbers you can defend; the prose you can skim.

## Quickstart
Required environment variables: `SF_USERNAME`, `SF_PASSWORD`, `SF_SECURITY_TOKEN`, `SF_DOMAIN` (optional, defaults to `login`), `ANTHROPIC_API_KEY`, `NOTION_API_KEY`, `NOTION_DATABASE_ID`

```bash
# Local
python -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env            # fill in the variables above
pipelinepulse --dry-run --use-mock-data   # safe local run; drop the flags to run live

# Docker (entrypoint is `pipelinepulse`; default CMD is --dry-run --use-mock-data)
docker build -t pipelinepulse .
docker run --env-file .env pipelinepulse
```

## Roadmap
- Configurable scoring rules via YAML
- Slack digest target alongside Notion
- Per-rep and per-segment rollups

## Tech
Python · Salesforce API · Anthropic API · Notion API · Docker · GitHub Actions
