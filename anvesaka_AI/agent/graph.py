"""Builds and compiles the LangGraph StateGraph.

Loop is capped at MAX_AGENT_STEPS (from config.settings, default 4).

Owner: Member 2

Public API
----------
build_graph(tool_executor, playbook_index) -> CompiledGraph
run_triage(alert_data, tool_executor, playbook_index) -> TriageResult

The graph intentionally does NOT import FastAPI or Member 4 code.
Member 4 calls run_triage() from the API route.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable, cast

from anvesaka_AI.agent.nodes import (
    ToolExecutor,
    finalize_node,
    ingest_node,
    llm_decide_node,
    _is_noise_or_recovery,
)
from anvesaka_AI.config import settings
from anvesaka_AI.schemas import AgentState, Alert, PlaybookEntry, Severity, TriageResult

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Routing helpers
# --------------------------------------------------------------------------- #

def _should_continue(state: AgentState) -> str:
    """Edge function: decide whether to loop back to llm_decide or go to finalize."""
    step = state.get("step", 0)
    max_steps = state.get("max_steps", settings.max_agent_steps)

    # If recommend_action was called, we're done
    if state.get("recommendation"):
        return "finalize"

    # Hard cap
    if step >= max_steps:
        logger.warning(
            "Graph reached step limit (%d/%d) without recommendation — finalizing",
            step,
            max_steps,
        )
        return "finalize"

    return "llm_decide"


# --------------------------------------------------------------------------- #
# Graph builder
# --------------------------------------------------------------------------- #

def build_graph(
    tool_executor: ToolExecutor,
    playbook_index: dict[str, PlaybookEntry],
):
    """Construct and compile the StateGraph.

    Returns a CompiledGraph with a `.invoke(state)` method.
    Falls back gracefully if langgraph is not installed (returns a
    FallbackGraph that runs the same logic sequentially).
    """
    try:
        from langgraph.graph import StateGraph, END  # type: ignore
    except ImportError:
        logger.warning("langgraph not installed — using sequential fallback graph")
        return _FallbackGraph(tool_executor=tool_executor, playbook_index=playbook_index)

    builder = StateGraph(AgentState)

    # Partial helpers that close over injected dependencies
    def _llm_decide(state: AgentState) -> dict:
        return llm_decide_node(state, tool_executor=tool_executor)

    def _finalize(state: AgentState) -> dict:
        return finalize_node(state, playbook_index=playbook_index)

    builder.add_node("llm_decide", _llm_decide)
    builder.add_node("finalize", _finalize)

    builder.set_entry_point("llm_decide")

    builder.add_conditional_edges(
        "llm_decide",
        _should_continue,
        {"llm_decide": "llm_decide", "finalize": "finalize"},
    )
    builder.add_edge("finalize", END)

    return builder.compile()


# --------------------------------------------------------------------------- #
# Fallback graph (sequential, no langgraph required)
# --------------------------------------------------------------------------- #

class _FallbackGraph:
    """Sequential implementation used when langgraph is unavailable.

    Runs the same node functions in the same order so behavior is
    identical modulo the graph middleware.
    """

    def __init__(self, tool_executor: ToolExecutor, playbook_index: dict[str, PlaybookEntry]):
        self._executor = tool_executor
        self._playbook_index = playbook_index

    def invoke(self, state: AgentState) -> AgentState:
        step = state.get("step", 0)
        max_steps = state.get("max_steps", settings.max_agent_steps)

        while step < max_steps:
            update = llm_decide_node(state, tool_executor=self._executor)
            existing_trace = list(state.get("tool_trace", []))
            new_trace = list(update.get("tool_trace", []))
            merged = {**state, **update}
            merged["tool_trace"] = existing_trace + new_trace
            state = cast(AgentState, merged)
            step = state.get("step", 0)
            if state.get("recommendation"):
                break

        final_update = finalize_node(state, playbook_index=self._playbook_index)
        state = cast(AgentState, {**state, **final_update})
        return state


# --------------------------------------------------------------------------- #
# High-level entry point
# --------------------------------------------------------------------------- #

def run_triage(
    alert_data: dict,
    tool_executor: ToolExecutor,
    playbook_index: dict[str, PlaybookEntry],
    *,
    max_steps: int | None = None,
) -> TriageResult:
    """Run the full triage pipeline and return a validated TriageResult.

    Args:
        alert_data: dict representation of an Alert.
        tool_executor: ToolExecutor with real or stub tool functions.
        playbook_index: dict mapping incident_id → PlaybookEntry.
        max_steps: Override for MAX_AGENT_STEPS (tests use small values).

    Returns:
        TriageResult — always, even on failures (status="error" in that case).
    """
    t_start = time.monotonic()

    # Quick path: noise / recovery → no_action without touching the LLM
    alert = Alert.model_validate(alert_data)
    if _is_noise_or_recovery(alert):
        logger.info("run_triage: fast no_action path for %s (INFO/recovery)", alert.alert_id)
        from anvesaka_AI.schemas import Decision, Priority, priority_for
        return TriageResult(
            alert_id=alert.alert_id,
            status="ok",
            decision=Decision.NO_ACTION,
            root_cause="Alert is informational or a recovery notification; no action required.",
            recommended_steps=[],
            priority=priority_for(alert.severity, 1),
            escalate=False,
            confidence=1.0,
            tool_trace=[],
            model=settings.ollama_model,
            latency_s=round(time.monotonic() - t_start, 3),
        )

    # Build initial state
    effective_max = max_steps if max_steps is not None else settings.max_agent_steps
    init_state: AgentState = ingest_node({}, alert_data=alert_data)  # type: ignore[arg-type]
    init_state["max_steps"] = effective_max

    try:
        graph = build_graph(tool_executor, playbook_index)
        final_state = graph.invoke(init_state)
    except Exception as exc:
        logger.exception("run_triage: graph execution failed for %s", alert.alert_id)
        from anvesaka_AI.schemas import Decision, priority_for
        return TriageResult(
            alert_id=alert.alert_id,
            status="error",
            decision=Decision.ESCALATE_UNKNOWN,
            root_cause=f"Internal agent error: {exc}",
            recommended_steps=[],
            priority=priority_for(alert.severity, 1),
            escalate=True,
            confidence=0.0,
            tool_trace=[],
            model=settings.ollama_model,
            latency_s=round(time.monotonic() - t_start, 3),
        )

    result_dict = final_state.get("result")
    if not result_dict:
        # finalize_node didn't run — build a minimal error result
        logger.error("run_triage: no result produced for %s", alert.alert_id)
        from anvesaka_AI.schemas import Decision, priority_for
        return TriageResult(
            alert_id=alert.alert_id,
            status="error",
            decision=Decision.ESCALATE_UNKNOWN,
            root_cause="Agent produced no result.",
            recommended_steps=[],
            priority=priority_for(alert.severity, 1),
            escalate=True,
            confidence=0.0,
            tool_trace=final_state.get("tool_trace", []),
            model=settings.ollama_model,
            latency_s=round(time.monotonic() - t_start, 3),
        )

    result = TriageResult.model_validate(result_dict)
    result.latency_s = round(time.monotonic() - t_start, 3)
    return result
