"""Tool 2: lookup_incidents.

Matches evidence against playbook incidents and returns ranked candidates
with clauses that were satisfied, violated, or remain unverified.

Owner: B (Member 1)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from anvesaka_AI.db.mongo import get_alerts_collection, get_playbook_collection, ping_db
from anvesaka_AI.schemas import (
    Alert,
    CorrelationResult,
    LookupResult,
    NodeContext,
    PlaybookEntry,
)
from anvesaka_AI.signature_engine import Ctx, parse_playbook, rank_candidates

ROOT = Path(__file__).resolve().parents[2]


def _load_offline_playbook() -> list[PlaybookEntry]:
    """Fallback: load playbook from data/raw/playbook.json."""
    entries: list[PlaybookEntry] = []
    path = ROOT / "data" / "raw" / "playbook.json"
    if path.exists():
        with open(path, "r", encoding="utf-8-sig") as f:
            for item in json.load(f):
                entries.append(parse_playbook(PlaybookEntry.model_validate(item)))
    return entries


def _load_offline_alerts() -> list[Alert]:
    """Fallback: load alerts from data/raw/alerts.json."""
    alerts: list[Alert] = []
    seen: set[str] = set()
    raw_path = ROOT / "data" / "raw" / "alerts.json"
    if raw_path.exists():
        with open(raw_path, "r", encoding="utf-8-sig") as f:
            for item in json.load(f):
                if item["alert_id"] not in seen:
                    alerts.append(Alert.model_validate(item))
                    seen.add(item["alert_id"])
    return alerts


def lookup_incidents(
    alert_id: str,
    top_k: int = 3,
    corr: Optional[CorrelationResult] = None,
    node_ctx: Optional[NodeContext] = None,
    alerts_source: Optional[list[Alert]] = None,
    playbook_source: Optional[list[PlaybookEntry]] = None,
) -> LookupResult:
    """Match alert and gathered context against playbook incidents.

    Parameters:
        alert_id: ID of the anchor alert to match.
        top_k: Number of ranked candidates to return (default 3).
        corr: Optional CorrelationResult if correlate_alerts has already run.
        node_ctx: Optional NodeContext if get_node_context has already run.
        alerts_source: Optional explicit alerts list (for tests).
        playbook_source: Optional explicit playbook list (for tests).

    Returns:
        LookupResult containing top-k candidates with satisfied/violated/unverified clauses.
    """
    anchor: Optional[Alert] = None
    playbook: list[PlaybookEntry] = []

    if alerts_source is not None:
        for a in alerts_source:
            if a.alert_id == alert_id:
                anchor = a
                break
    elif ping_db():
        coll = get_alerts_collection()
        doc = coll.find_one({"alert_id": alert_id})
        if doc:
            anchor = Alert.model_validate(doc)
    else:
        for a in _load_offline_alerts():
            if a.alert_id == alert_id:
                anchor = a
                break

    if anchor is None:
        raise KeyError(f"Alert not found: {alert_id}")

    if playbook_source is not None:
        playbook = [parse_playbook(e) if not e.signature_clauses else e for e in playbook_source]
    elif ping_db():
        coll = get_playbook_collection()
        playbook = [parse_playbook(PlaybookEntry.model_validate(d)) for d in coll.find({})]
    else:
        playbook = _load_offline_playbook()

    ctx = Ctx(anchor=anchor, corr=corr, node=node_ctx)
    return rank_candidates(ctx=ctx, playbook=playbook, top_k=top_k)


def lookup_incidents_tool(
    alert_id: str,
    top_k: int = 3,
) -> dict[str, Any]:
    """JSON-serializable wrapper for LangGraph / tool agent."""
    result = lookup_incidents(alert_id=alert_id, top_k=top_k)
    return result.model_dump()
