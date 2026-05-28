"""Salesforce connector.

Pulls open opportunities from a Salesforce org using ``simple-salesforce`` and
returns them as typed :class:`Opportunity` objects the rest of the app can use.

The ``simple_salesforce`` dependency is imported lazily inside
:meth:`SalesforceClient.connect` so that the scoring engine, prompt builder, and
the offline mock-data demo can run without the SDK installed.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Opportunity:
    """A single open Salesforce opportunity, normalized for scoring."""

    name: str
    stage: str
    amount: float | None
    close_date: date | None
    last_activity_date: date | None
    created_date: date | None
    owner: str

    @classmethod
    def from_record(cls, record: dict[str, Any], fields: "Any") -> "Opportunity":
        """Build an Opportunity from a raw Salesforce/SOQL record dict.

        ``fields`` is the SalesforceFieldMap from config so field API names stay
        configurable rather than hardcoded throughout the codebase.
        """
        owner = record.get("Owner") or {}
        owner_name = owner.get("Name") if isinstance(owner, dict) else record.get("OwnerName")
        return cls(
            name=record.get(fields.name) or "(unnamed)",
            stage=record.get(fields.stage) or "Unknown",
            amount=_to_float(record.get(fields.amount)),
            close_date=_to_date(record.get(fields.close_date)),
            last_activity_date=_to_date(record.get(fields.last_activity_date)),
            created_date=_to_date(record.get(fields.created_date)),
            owner=owner_name or "Unassigned",
        )


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = str(value)
    # Salesforce returns dates as YYYY-MM-DD and datetimes as ISO 8601.
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


class SalesforceClient:
    """Thin wrapper over ``simple-salesforce`` for pulling open opportunities."""

    def __init__(self, fields: "Any") -> None:
        self._fields = fields
        self._sf: Any = None

    def connect(self) -> None:
        """Authenticate against Salesforce using environment variables.

        Required env vars:
          SF_USERNAME, SF_PASSWORD, SF_SECURITY_TOKEN
        Optional:
          SF_DOMAIN (e.g. "login" or "test"; defaults to "login")
        """
        try:
            from simple_salesforce import Salesforce  # lazy import
        except ImportError as exc:  # pragma: no cover - surfaced only on real runs
            raise RuntimeError(
                "simple-salesforce is not installed. Run `pip install -r requirements.txt`."
            ) from exc

        username = _require_env("SF_USERNAME")
        password = _require_env("SF_PASSWORD")
        token = _require_env("SF_SECURITY_TOKEN")
        domain = os.environ.get("SF_DOMAIN", "login")

        logger.info("Connecting to Salesforce as %s (domain=%s)", username, domain)
        self._sf = Salesforce(
            username=username,
            password=password,
            security_token=token,
            domain=domain,
        )

    def fetch_open_opportunities(self) -> list[Opportunity]:
        """Query open opportunities (IsClosed = false) via SOQL."""
        if self._sf is None:
            self.connect()

        soql = (
            "SELECT Name, StageName, Amount, CloseDate, LastActivityDate, "
            "CreatedDate, Owner.Name "
            "FROM Opportunity "
            "WHERE IsClosed = false "
            "ORDER BY Amount DESC NULLS LAST"
        )
        logger.info("Running SOQL: %s", soql)
        result = self._sf.query_all(soql)
        records = result.get("records", [])
        logger.info("Fetched %d open opportunities", len(records))
        return [Opportunity.from_record(r, self._fields) for r in records]


def load_mock_opportunities(path: str | Path, fields: "Any") -> list[Opportunity]:
    """Load opportunities from a JSON fixture for offline demos and tests."""
    path = Path(path)
    with path.open("r", encoding="utf-8") as fh:
        records = json.load(fh)
    return [Opportunity.from_record(r, fields) for r in records]


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value
