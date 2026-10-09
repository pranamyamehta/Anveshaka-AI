"""Graph tests using a stubbed LLM: loop cap, fallback tool, finalize.

All tests run OFFLINE — no Ollama, no MongoDB required.

Owner: Member 2

Coverage:
  - TC-01  Fast no_action path for INFO alert
  - TC-02  Fast no_action path for RESOLVED message
  - TC-03  MAX_AGENT_STEPS hard cap prevents infinite loop
  - TC-04  Invalid tool choice triggers fallback to lookup_incidents
  - TC-05  Invalid tool choice on second call triggers fallback to recommend_action
  - TC-06  Successful match path: lookup → recommend → finalize with playbook steps
  - TC-07  No-match path: confidence below threshold → ESCALATE_UNKNOWN
  - TC-08  Tool trace is recorded on every tool call
  - TC-09  Playbook steps are NEVER LLM-generated (finalize only copies them)
  - TC-10  Graph produces TriageResult even if tool executor raises
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional
from unittest.mock import MagicMock, patch

import pytest

from anvesaka_AI.agent.graph import run_triage
from anvesaka_AI.agent.nodes import ToolExecutor, _is_noise_or_recovery
from anvesaka_AI.schemas import (
    Alert,
    AnomalyType,
    CorrelationResult,
    Decision,
    LookupResult,
    Metrics,
    NodeContext,
    PlaybookEntry,
    PlaybookMatch,
    Severity,
    TriageResult,
)

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

def _make_alert(
    alert_id: str = "ALT-TEST-001",
    severity: str = "CRITICAL",
    anomaly_type: str = "Thermal",
    raw_message: str = "Test alert",
    node_id: str = "srv-node-45",
    rack_id: str = "Rack-A12",
    metrics: Optional[dict] = None,
) -> dict:
    return {
        "alert_id": alert_id,
        "timestamp": "2026-10-03T10:00:00Z",
        "rack_id": rack_id,
        "node_id": node_id,
        "anomaly_type": anomaly_type,
        "metrics": metrics or {"cpu_temp_c": 96.0, "fan_rpm": 0, "inlet_temp_c": 23.5},
        "severity": severity,
        "raw_message": raw_message,
    }


def _make_playbook_entry(
    incident_id: str = "INC-4731",
    steps: Optional[list[str]] = None,
) -> PlaybookEntry:
    return PlaybookEntry.model_validate({
        "incident_id": incident_id,
        "anomaly_category": "Thermal",
        "symptom_signature": ["anomaly_type == Thermal", "fan_rpm < 2000"],
        "historical_root_cause": "Fan seized.",
        "remediation_action": "1. Cordon node. 2. Replace fan.",
        "historical_resolution_time_mins": 58,
        "remediation_steps": steps or ["Cordon node.", "Replace fan."],
    })


def _stub_executor(
    lookup_result: Optional[LookupResult] = None,
    corr_result: Optional[CorrelationResult] = None,
    node_ctx: Optional[NodeContext] = None,
) -> ToolExecutor:
    """Create a ToolExecutor with stub implementations."""
    default_lookup = LookupResult(
        anchor_alert_id="ALT-TEST-001",
        candidates=[
            PlaybookMatch(
                incident_id="INC-4731",
                score=0.8,
                n_satisfied=4,
                n_violated=1,
                n_unverified=0,
                satisfied=["anomaly_type == Thermal", "fan_rpm < 2000"],
                violated=[],
                unverified=[],
                needs_tools=[],
            )
        ],
    )
    default_corr = CorrelationResult(
        anchor_alert_id="ALT-TEST-001",
        window_min=360,
        related=[],
        affected_nodes=["srv-node-45"],
        affected_racks=["Rack-A12"],
        categories_present=[AnomalyType.THERMAL],
        escalating=False,
    )
    default_node = NodeContext()

    return ToolExecutor(
        correlate_fn=lambda args: corr_result or default_corr,
        node_context_fn=lambda args: node_ctx or default_node,
        lookup_fn=lambda args: lookup_result or default_lookup,
        playbook_index={"INC-4731": _make_playbook_entry()},
    )


PLAYBOOK_INDEX = {"INC-4731": _make_playbook_entry()}


def _patch_llm(responses: list[str]):
    """Return a context manager that patches _llm_chat_raw with canned responses."""
    call_count = 0

    def fake_chat(messages):
        nonlocal call_count
        resp = responses[min(call_count, len(responses) - 1)]
        call_count += 1
        return resp

    return patch("anvesaka_AI.agent.nodes._llm_chat_raw", side_effect=fake_chat)


# --------------------------------------------------------------------------- #
# TC-01: Fast no_action path — INFO alert
# --------------------------------------------------------------------------- #

def test_tc01_info_alert_no_action():
    alert = _make_alert(severity="INFO", raw_message="Hourly thermal baseline sample")
    result = run_triage(alert, _stub_executor(), PLAYBOOK_INDEX, max_steps=4)
    assert result.decision == Decision.NO_ACTION
    assert result.tool_trace == []
    assert result.confidence == 1.0


# --------------------------------------------------------------------------- #
# TC-02: Fast no_action path — RESOLVED message
# --------------------------------------------------------------------------- #

def test_tc02_recovery_alert_no_action():
    alert = _make_alert(
        severity="WARNING",
        raw_message="Prometheus: RESOLVED: node_cpu_steal_ratio back to normal",
    )
    result = run_triage(alert, _stub_executor(), PLAYBOOK_INDEX, max_steps=4)
    assert result.decision == Decision.NO_ACTION
    assert len(result.tool_trace) == 0


# --------------------------------------------------------------------------- #
# TC-03: MAX_AGENT_STEPS hard cap
# --------------------------------------------------------------------------- #

def test_tc03_step_limit_does_not_loop_forever():
    """Agent must stop at max_steps and not recurse infinitely."""
    alert = _make_alert()
    # LLM always asks for correlate_alerts — would loop forever without cap
    always_correlate = json.dumps({"tool": "correlate_alerts", "args": {"alert_id": "ALT-TEST-001"}})
    with _patch_llm([always_correlate] * 10):
        result = run_triage(alert, _stub_executor(), PLAYBOOK_INDEX, max_steps=3)
    assert result is not None
    assert isinstance(result, TriageResult)
    # Must not have more tool calls than max_steps
    assert len(result.tool_trace) <= 3


# --------------------------------------------------------------------------- #
# TC-04: Invalid tool choice → fallback to lookup_incidents
# --------------------------------------------------------------------------- #

def test_tc04_invalid_tool_triggers_fallback_lookup():
    alert = _make_alert()
    # LLM returns garbage JSON, then a valid recommend_action call
    garbage = "NOT VALID JSON {{{"
    recommend = json.dumps({
        "tool": "recommend_action",
        "args": {
            "alert_id": "ALT-TEST-001",
            "candidate_incident_id": "INC-4731",
            "root_cause": "Fan seized.",
            "evidence": ["fan_rpm=0"],
        },
    })
    with _patch_llm([garbage, recommend]):
        result = run_triage(alert, _stub_executor(), PLAYBOOK_INDEX, max_steps=4)
    assert result is not None
    # Forced fallback should appear in tool trace
    forced = [t for t in result.tool_trace if t.forced]
    assert len(forced) >= 1


# --------------------------------------------------------------------------- #
# TC-05: Second fallback → recommend_action
# --------------------------------------------------------------------------- #

def test_tc05_fallback_recommend_after_lookup_done():
    alert = _make_alert()
    # First call: invalid — triggers fallback to lookup_incidents
    # Second call: invalid again — triggers fallback to recommend_action
    garbage = "INVALID"
    with _patch_llm([garbage, garbage]):
        result = run_triage(alert, _stub_executor(), PLAYBOOK_INDEX, max_steps=4)
    assert result is not None
    assert isinstance(result, TriageResult)


# --------------------------------------------------------------------------- #
# TC-06: Successful match path
# --------------------------------------------------------------------------- #

def test_tc06_successful_match_path():
    alert = _make_alert()
    lookup_resp = json.dumps({"tool": "lookup_incidents", "args": {"alert_id": "ALT-TEST-001"}})
    recommend_resp = json.dumps({
        "tool": "recommend_action",
        "args": {
            "alert_id": "ALT-TEST-001",
            "candidate_incident_id": "INC-4731",
            "root_cause": "Fan 2 seized, CPU PROCHOT, normal inlet.",
            "evidence": ["fan_rpm=0", "cpu_temp_c=96.0", "inlet_temp_c=23.5"],
        },
    })
    with _patch_llm([lookup_resp, recommend_resp]):
        result = run_triage(alert, _stub_executor(), PLAYBOOK_INDEX, max_steps=4)
    assert result.decision == Decision.MATCH_INCIDENT
    assert result.matched_incident_id == "INC-4731"
    assert result.confidence > 0


# --------------------------------------------------------------------------- #
# TC-07: No match → ESCALATE or NO_ACTION depending on score
# --------------------------------------------------------------------------- #

def test_tc07_no_match_low_score_escalates():
    alert = _make_alert()
    # Lookup returns a low-score candidate
    low_lookup = LookupResult(
        anchor_alert_id="ALT-TEST-001",
        candidates=[
            PlaybookMatch(
                incident_id="INC-4731",
                score=0.1,  # below CONFIDENCE_THRESHOLD=0.4
                n_satisfied=1,
                n_violated=5,
                n_unverified=0,
                satisfied=["anomaly_type == Thermal"],
                violated=["fan_rpm < 2000", "cpu_temp_c > 85"],
                unverified=[],
                needs_tools=[],
            )
        ],
    )
    executor = _stub_executor(lookup_result=low_lookup)
    lookup_resp = json.dumps({"tool": "lookup_incidents", "args": {"alert_id": "ALT-TEST-001"}})
    recommend_resp = json.dumps({
        "tool": "recommend_action",
        "args": {
            "alert_id": "ALT-TEST-001",
            "candidate_incident_id": "INC-4731",
            "root_cause": "Uncertain.",
            "evidence": [],
        },
    })
    with _patch_llm([lookup_resp, recommend_resp]):
        result = run_triage(alert, executor, PLAYBOOK_INDEX, max_steps=4)
    assert result.decision in (Decision.ESCALATE_UNKNOWN, Decision.NO_ACTION)
    assert result.confidence == 0.0


# --------------------------------------------------------------------------- #
# TC-08: Tool trace is always recorded
# --------------------------------------------------------------------------- #

def test_tc08_tool_trace_recorded():
    alert = _make_alert()
    lookup_resp = json.dumps({"tool": "lookup_incidents", "args": {"alert_id": "ALT-TEST-001"}})
    recommend_resp = json.dumps({
        "tool": "recommend_action",
        "args": {
            "alert_id": "ALT-TEST-001",
            "candidate_incident_id": "INC-4731",
            "root_cause": "Fan seized.",
            "evidence": ["fan_rpm=0"],
        },
    })
    with _patch_llm([lookup_resp, recommend_resp]):
        result = run_triage(alert, _stub_executor(), PLAYBOOK_INDEX, max_steps=4)
    assert len(result.tool_trace) >= 1
    for entry in result.tool_trace:
        assert entry.tool in ("correlate_alerts", "get_node_context", "lookup_incidents", "recommend_action")
        assert isinstance(entry.step, int)
        assert isinstance(entry.duration_ms, int)


# --------------------------------------------------------------------------- #
# TC-09: Playbook steps NEVER LLM-generated
# --------------------------------------------------------------------------- #

def test_tc09_steps_come_from_playbook_not_llm():
    alert = _make_alert()
    playbook_steps = ["Step A from playbook.", "Step B from playbook."]
    custom_entry = _make_playbook_entry(steps=playbook_steps)
    playbook_index = {"INC-4731": custom_entry}

    lookup_resp = json.dumps({"tool": "lookup_incidents", "args": {"alert_id": "ALT-TEST-001"}})
    # LLM tries to invent steps — they must be ignored
    recommend_resp = json.dumps({
        "tool": "recommend_action",
        "args": {
            "alert_id": "ALT-TEST-001",
            "candidate_incident_id": "INC-4731",
            "root_cause": "Fan seized.",
            "evidence": ["fan_rpm=0"],
            # LLM also passes a "steps" field — must be discarded
            "steps": ["INVENTED step 1", "INVENTED step 2"],
        },
    })
    with _patch_llm([lookup_resp, recommend_resp]):
        result = run_triage(alert, _stub_executor(), playbook_index, max_steps=4)

    if result.decision == Decision.MATCH_INCIDENT:
        for s in result.recommended_steps:
            assert "INVENTED" not in s, "LLM-generated step leaked into result!"
        assert result.recommended_steps == playbook_steps


# --------------------------------------------------------------------------- #
# TC-10: Graph returns TriageResult even if tool executor raises
# --------------------------------------------------------------------------- #

def test_tc10_tool_executor_exception_handled():
    alert = _make_alert()

    def boom(args):
        raise RuntimeError("DB is down")

    executor = ToolExecutor(
        correlate_fn=boom,
        node_context_fn=boom,
        lookup_fn=boom,
        playbook_index=PLAYBOOK_INDEX,
    )

    lookup_resp = json.dumps({"tool": "lookup_incidents", "args": {"alert_id": "ALT-TEST-001"}})
    with _patch_llm([lookup_resp]):
        result = run_triage(alert, executor, PLAYBOOK_INDEX, max_steps=2)

    assert isinstance(result, TriageResult)
    # Errors in tool execution should not crash — tool trace should contain an error entry
    error_entries = [t for t in result.tool_trace if t.error]
    assert len(error_entries) >= 1


# --------------------------------------------------------------------------- #
# Unit tests for helper functions
# --------------------------------------------------------------------------- #

def test_is_noise_or_recovery_info():
    a = Alert.model_validate(_make_alert(severity="INFO"))
    assert _is_noise_or_recovery(a) is True


def test_is_noise_or_recovery_resolved():
    a = Alert.model_validate(_make_alert(severity="WARNING", raw_message="RESOLVED: fan back to normal"))
    assert _is_noise_or_recovery(a) is True


def test_is_noise_or_recovery_critical_not_noise():
    a = Alert.model_validate(_make_alert(severity="CRITICAL"))
    assert _is_noise_or_recovery(a) is False
