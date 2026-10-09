"""Unit tests for Member 1 deterministic evidence tools.

Tests both live MongoDB Atlas interaction and offline / mock fallbacks.
"""
from __future__ import annotations

from datetime import datetime, timezone
import pytest

from anvesaka_AI.schemas import (
    Alert,
    AnomalyType,
    Metrics,
    NodeBaseline,
    NodeInfo,
    NodeRole,
    PlaybookEntry,
    Severity,
)
from anvesaka_AI.tools import (
    correlate_alerts,
    correlate_alerts_tool,
    get_node_context,
    get_node_context_tool,
    lookup_incidents,
    lookup_incidents_tool,
)


def test_correlate_alerts_live() -> None:
    """Test correlation against live Atlas for ALT-1023."""
    res = correlate_alerts("ALT-1023", window_min=360)
    assert res.anchor_alert_id == "ALT-1023"
    assert len(res.related) > 0
    # Strict no look-ahead: minutes_before must be >= 0
    assert all(r.minutes_before >= 0 for r in res.related)
    # Ordered oldest first (highest minutes_before)
    mins = [r.minutes_before for r in res.related]
    assert mins == sorted(mins, reverse=True)
    # Same rack related alert ALT-1020 must be included
    rel_ids = [r.alert_id for r in res.related]
    assert "ALT-1020" in rel_ids


def test_get_node_context_live() -> None:
    """Test CMDB and baseline fetching for srv-node-204."""
    ctx = get_node_context("srv-node-204", alert_id="ALT-1023")
    assert ctx.node is not None
    assert ctx.node.node_id == "srv-node-204"
    assert ctx.node.rack_id == "Rack-D09"
    assert ctx.node.role == NodeRole.STORAGE


def test_lookup_incidents_progression() -> None:
    """Test candidate ranking progression before and after correlation."""
    # Step 1: without correlation context
    res1 = lookup_incidents("ALT-1023", top_k=3)
    assert len(res1.candidates) > 0
    top1 = res1.candidates[0]
    assert top1.incident_id == "INC-5261"
    assert top1.score == 0.833
    assert top1.n_unverified == 1
    assert "correlate_alerts" in top1.needs_tools

    # Step 2: with correlation context gathered
    corr = correlate_alerts("ALT-1023", window_min=360)
    res2 = lookup_incidents("ALT-1023", top_k=3, corr=corr)
    top2 = res2.candidates[0]
    assert top2.incident_id == "INC-5261"
    assert top2.score == 1.0
    assert top2.n_unverified == 0
    assert len(top2.needs_tools) == 0


def test_tools_offline_mock() -> None:
    """Test tools using completely in-memory mocked models (no DB call)."""
    t0 = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 10, 4, 12, 30, tzinfo=timezone.utc)

    mock_alerts = [
        Alert(
            alert_id="ALT-9001",
            timestamp=t0,
            rack_id="Rack-A01",
            node_id="srv-node-901",
            anomaly_type=AnomalyType.THERMAL,
            severity=Severity.WARNING,
            metrics=Metrics(cpu_temp_c=75.0),
            raw_message="Fan failure warning",
        ),
        Alert(
            alert_id="ALT-9002",
            timestamp=t1,
            rack_id="Rack-A01",
            node_id="srv-node-901",
            anomaly_type=AnomalyType.THERMAL,
            severity=Severity.CRITICAL,
            metrics=Metrics(cpu_temp_c=92.0),
            raw_message="Overheating critical",
        ),
    ]

    mock_nodes = {
        "srv-node-901": NodeInfo(
            node_id="srv-node-901",
            rack_id="Rack-A01",
            rack_row="A",
            rack_pos=1,
            role=NodeRole.COMPUTE,
            u_position=10,
            baseline=NodeBaseline(link_gbps=10.0),
        )
    }

    mock_playbook = [
        PlaybookEntry(
            incident_id="INC-9999",
            anomaly_category=AnomalyType.THERMAL,
            symptom_signature=[
                "anomaly_type == Thermal",
                "severity IN [CRITICAL, FATAL]",
            ],
            historical_root_cause="Fan failed",
            remediation_action="1. Replace fan module",
            historical_resolution_time_mins=30,
        )
    ]

    # Test correlation
    corr = correlate_alerts("ALT-9002", window_min=60, alerts_source=mock_alerts)
    assert len(corr.related) == 1
    assert corr.related[0].alert_id == "ALT-9001"
    assert corr.escalating is True

    # Test node context
    nc = get_node_context(
        "srv-node-901",
        alert_id="ALT-9002",
        alerts_source=mock_alerts,
        nodes_source=mock_nodes,
    )
    assert nc.node is not None
    assert nc.node.node_id == "srv-node-901"
    assert nc.prior_alert_ids == ["ALT-9001"]

    # Test lookup
    lookup = lookup_incidents(
        "ALT-9002",
        alerts_source=mock_alerts,
        playbook_source=mock_playbook,
    )
    assert len(lookup.candidates) == 1
    assert lookup.candidates[0].score == 1.0


def test_json_tool_wrappers() -> None:
    """Test dict output for LangGraph agent node execution."""
    corr_dict = correlate_alerts_tool("ALT-1023")
    assert isinstance(corr_dict, dict)
    assert "anchor_alert_id" in corr_dict

    nc_dict = get_node_context_tool("srv-node-204", alert_id="ALT-1023")
    assert isinstance(nc_dict, dict)
    assert "node" in nc_dict

    lookup_dict = lookup_incidents_tool("ALT-1023")
    assert isinstance(lookup_dict, dict)
    assert "candidates" in lookup_dict
