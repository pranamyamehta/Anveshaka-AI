"""Tool 3: get_node_context.

CMDB baseline, rack position, 7-day median metrics and neighbor inlet temp lookups for a node.

Owner: B (Member 1)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from anvesaka_AI.db.mongo import get_alerts_collection, get_nodes_collection, ping_db
from anvesaka_AI.schemas import Alert, NodeContext, NodeInfo
from anvesaka_AI.signature_engine import node_context

ROOT = Path(__file__).resolve().parents[2]


def _load_offline_nodes() -> dict[str, NodeInfo]:
    """Fallback: load nodes from data/raw/cmdb_nodes.json."""
    nodes: dict[str, NodeInfo] = {}
    path = ROOT / "data" / "raw" / "cmdb_nodes.json"
    if path.exists():
        with open(path, "r", encoding="utf-8-sig") as f:
            for item in json.load(f):
                node = NodeInfo.model_validate(item)
                nodes[node.node_id] = node
    return nodes


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


def get_node_context(
    node_id: str,
    alert_id: Optional[str] = None,
    alerts_source: Optional[list[Alert]] = None,
    nodes_source: Optional[dict[str, NodeInfo]] = None,
) -> NodeContext:
    """Get CMDB details, historical median metrics, and neighbor temperatures for a node.

    Parameters:
        node_id: The ID of the node (e.g. 'srv-node-101').
        alert_id: Optional anchor alert ID. If provided, prior alerts are evaluated before
                  this anchor, and neighbor inlet temps are parsed from its raw_message.
        alerts_source: Optional explicit alerts list (for tests).
        nodes_source: Optional explicit nodes dict (for tests).

    Returns:
        NodeContext model.
    """
    nodes: dict[str, NodeInfo] = {}
    all_alerts: list[Alert] = []

    if nodes_source is not None:
        nodes = nodes_source
    elif ping_db():
        coll = get_nodes_collection()
        nodes = {d["node_id"]: NodeInfo.model_validate(d) for d in coll.find({})}
    else:
        nodes = _load_offline_nodes()

    if alerts_source is not None:
        all_alerts = alerts_source
    elif ping_db():
        coll = get_alerts_collection()
        all_alerts = [Alert.model_validate(d) for d in coll.find({})]
    else:
        all_alerts = _load_offline_alerts()

    anchor: Optional[Alert] = None
    if alert_id:
        for a in all_alerts:
            if a.alert_id == alert_id:
                anchor = a
                break
    else:
        node_alerts = [a for a in all_alerts if a.node_id == node_id]
        if node_alerts:
            node_alerts.sort(key=lambda a: a.timestamp, reverse=True)
            anchor = node_alerts[0]

    node_info = nodes.get(node_id)
    if anchor:
        return node_context(anchor=anchor, alerts=all_alerts, nodes=nodes)

    return NodeContext(
        node=node_info,
        prior_alert_ids=[],
        median_metrics={},
        neighbor_inlet_temps={},
    )


def get_node_context_tool(node_id: str, alert_id: Optional[str] = None) -> dict[str, Any]:
    """JSON-serializable wrapper for LangGraph / tool agent."""
    result = get_node_context(node_id=node_id, alert_id=alert_id)
    return result.model_dump()
