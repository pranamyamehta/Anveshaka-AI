"""Tool 1: correlate_alerts.

Finds alerts related to an anchor alert within a time window (same rack/node/adjacent rack).
Strictly adheres to no look-ahead: only alerts with timestamp <= anchor.timestamp.
Filters out INFO and recovery alerts.

Owner: B (Member 1)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from anvesaka_AI.db.mongo import get_alerts_collection, ping_db
from anvesaka_AI.schemas import Alert, CorrelationResult
from anvesaka_AI.signature_engine import correlate

ROOT = Path(__file__).resolve().parents[2]


def _load_offline_alerts() -> list[Alert]:
    """Fallback: load alerts from data/raw/alerts.json (and generated noisy if available)."""
    alerts: list[Alert] = []
    seen: set[str] = set()
    raw_path = ROOT / "data" / "raw" / "alerts.json"
    if raw_path.exists():
        with open(raw_path, "r", encoding="utf-8-sig") as f:
            for item in json.load(f):
                if item["alert_id"] not in seen:
                    alerts.append(Alert.model_validate(item))
                    seen.add(item["alert_id"])
    gen_path = ROOT / "data" / "generated" / "noisy_alerts.json"
    if gen_path.exists():
        with open(gen_path, "r", encoding="utf-8-sig") as f:
            for item in json.load(f):
                if item["alert_id"] not in seen:
                    alerts.append(Alert.model_validate(item))
                    seen.add(item["alert_id"])
    return alerts


def correlate_alerts(
    alert_id: str,
    window_min: int = 360,
    alerts_source: Optional[list[Alert]] = None,
) -> CorrelationResult:
    """Find related alerts within window_min minutes before the anchor alert.

    Parameters:
        alert_id: The ID of the trigger/anchor alert.
        window_min: Lookback window in minutes (default 360).
        alerts_source: Optional explicit alert list (bypasses DB for testing).

    Returns:
        CorrelationResult with related alerts, affected nodes/racks, and escalation status.
    """
    anchor: Optional[Alert] = None
    all_alerts: list[Alert] = []

    if alerts_source is not None:
        all_alerts = alerts_source
        for a in all_alerts:
            if a.alert_id == alert_id:
                anchor = a
                break
    elif ping_db():
        coll = get_alerts_collection()
        doc = coll.find_one({"alert_id": alert_id})
        if doc:
            anchor = Alert.model_validate(doc)
            all_alerts = [Alert.model_validate(d) for d in coll.find({})]
    else:
        all_alerts = _load_offline_alerts()
        for a in all_alerts:
            if a.alert_id == alert_id:
                anchor = a
                break

    if anchor is None:
        raise KeyError(f"Anchor alert not found: {alert_id}")

    return correlate(anchor=anchor, alerts=all_alerts, window_min=window_min)


def correlate_alerts_tool(alert_id: str, window_min: int = 360) -> dict[str, Any]:
    """JSON-serializable wrapper for LangGraph / tool agent."""
    result = correlate_alerts(alert_id=alert_id, window_min=window_min)
    return result.model_dump()
