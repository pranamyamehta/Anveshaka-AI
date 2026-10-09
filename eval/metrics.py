"""Root-cause accuracy, action accuracy, correct-tool-called rate, latency.

Owner: Member 2
"""
from __future__ import annotations

from typing import Literal

from anvesaka_AI.schemas import Decision, EvalRecord, PlaybookEntry, Scenario, TriageResult


def evaluate_result(
    scenario: Scenario,
    result: TriageResult,
    playbook_index: dict[str, PlaybookEntry],
    mode: Literal["agent", "rule_based", "manual"] = "agent",
    run_idx: int = 0,
) -> EvalRecord:
    """Compare a TriageResult against the ground truth Scenario.
    
    Metrics calculated:
      - correct: True if decision matches and incident_id matches expected (or acceptable).
      - tools_correct: True if all expected_tools were called.
      - mention_hits: fraction of must_mention strings found in the root cause text.
      - steps_faithful: True if all recommended steps are present in the chosen playbook entry.
    """
    # 1. Decision & Incident ID correctness
    correct = False
    if result.decision == scenario.outcome:
        if scenario.outcome == Decision.MATCH_INCIDENT:
            acceptable = {scenario.expected_incident_id} | set(scenario.acceptable_incident_ids)
            if result.matched_incident_id in acceptable:
                correct = True
        else:
            correct = True

    # 2. Tool correctness
    tools_called = {t.tool for t in result.tool_trace}
    expected_tools = set(scenario.expected_tools)
    tools_correct = expected_tools.issubset(tools_called) if expected_tools else True

    # 3. Mention hits
    mention_hits = 1.0
    if scenario.must_mention:
        root_cause_lower = result.root_cause.lower()
        hits = sum(1 for m in scenario.must_mention if m.lower() in root_cause_lower)
        mention_hits = hits / len(scenario.must_mention)

    # 4. Steps faithful
    steps_faithful = True
    if result.matched_incident_id and result.matched_incident_id in playbook_index:
        pb_steps = playbook_index[result.matched_incident_id].remediation_steps or []
        for step in result.recommended_steps:
            if step not in pb_steps:
                steps_faithful = False
                break
    elif result.recommended_steps:
        # If no playbook entry matched but steps were recommended, it's not faithful
        steps_faithful = False

    return EvalRecord(
        mode=mode,
        scenario_id=scenario.scenario_id,
        run_idx=run_idx,
        model=result.model if mode == "agent" else None,
        decision=result.decision,
        predicted_incident_id=result.matched_incident_id,
        correct=correct,
        tools_called=list(tools_called),
        tools_correct=tools_correct,
        mention_hits=mention_hits,
        steps_faithful=steps_faithful,
        time_seconds=result.latency_s,
    )
