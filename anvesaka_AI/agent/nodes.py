"""Graph nodes: ingest, llm_decide, tool_node, finalize, notify.

Includes the default-tool fallback when the LLM produces an invalid tool call.

Owner: Member 2

Node flow:
  ingest_node
      ↓
  llm_decide_node  ←────────────────────────────────┐
      ↓                                              │
  tool_node  (correlate / node_ctx / lookup / rec)  │
      ↓ (if step < max_steps and not final)          │
      └──────────────────────────────────────────────┘
      ↓ (when recommend_action called OR step limit)
  finalize_node
      ↓
  notify_node   (optional Slack — Member 4 wires this)

Each node receives the full AgentState and returns a dict of updates.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

from anvesaka_AI.agent.llm import OllamaError, chat_structured
from anvesaka_AI.agent.prompts import SYSTEM_PROMPT, TOOL_SELECTION_PROMPT
from anvesaka_AI.config import settings
from anvesaka_AI.schemas import (
    AgentState,
    Alert,
    CorrelateArgs,
    Decision,
    LookupArgs,
    NodeContextArgs,
    PlaybookEntry,
    Priority,
    Recommendation,
    Severity,
    ToolCall,
    TriageResult,
    priority_for,
)
from anvesaka_AI.tools.recommend_action import build_recommendation, format_tool_summary
from anvesaka_AI.tools.registry import CONFIDENCE_THRESHOLD, TOOL_NAMES

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

_RECOVERY_WORDS = frozenset(["resolved", "recovered", "ok", "recovery", "clear"])


def _is_noise_or_recovery(alert: Alert) -> bool:
    """Return True for INFO alerts and RESOLVED/Recovered messages."""
    if alert.severity == Severity.INFO:
        return True
    msg = alert.raw_message.lower()
    return any(w in msg for w in _RECOVERY_WORDS)


def _alert_summary(alert: Alert) -> str:
    return (
        f"{alert.alert_id} | {alert.node_id} | {alert.rack_id} | "
        f"{alert.anomaly_type.value} | {alert.severity.value} | "
        f"{alert.raw_message[:200]}"
    )


def _corr_summary(state: AgentState) -> str:
    c = state.get("correlation")
    if not c:
        return "not yet fetched"
    n = len(c.get("related", []))
    return f"{n} related alert(s), racks={c.get('affected_racks', [])}"


def _node_summary(state: AgentState) -> str:
    ctx = state.get("node_context")
    if not ctx:
        return "not yet fetched"
    n = ctx.get("node")
    if not n:
        return "node unknown in CMDB"
    return f"rack={n.get('rack_id')} u_pos={n.get('u_position')} prior_alerts={len(ctx.get('prior_alert_ids', []))}"


def _lookup_summary(state: AgentState) -> str:
    lu = state.get("lookup")
    if not lu:
        return "not yet fetched"
    cands = lu.get("candidates", [])
    if not cands:
        return "no candidates"
    top = cands[0]
    return f"top={top['incident_id']} score={top['score']:.2f} needs_tools={top.get('needs_tools', [])}"


def _make_tool_call_record(
    step: int,
    tool: str,
    args: dict,
    summary: str,
    duration_ms: int,
    forced: bool = False,
    error: Optional[str] = None,
) -> dict:
    return ToolCall(
        step=step,
        tool=tool,
        args=args,
        summary=summary,
        duration_ms=duration_ms,
        forced=forced,
        error=error,
    ).model_dump()


# --------------------------------------------------------------------------- #
# Node: ingest
# --------------------------------------------------------------------------- #

def ingest_node(state: AgentState, *, alert_data: dict) -> dict:
    """Validate and store the raw alert dict, set step=0.

    Args:
        state: Current graph state (may be empty at start).
        alert_data: dict representation of the Alert model.

    Returns:
        State update dict.
    """
    alert = Alert.model_validate(alert_data)
    max_steps = settings.max_agent_steps
    logger.info("ingest_node: %s severity=%s", alert.alert_id, alert.severity.value)
    return {
        "alert": alert.model_dump(mode="json"),
        "step": 0,
        "max_steps": max_steps,
        "tool_trace": [],
        "forced_tools": [],
        "messages": [
            {
                "role": "system",
                "content": SYSTEM_PROMPT.format(max_steps=max_steps),
            },
            {
                "role": "user",
                "content": (
                    f"Investigate this alert:\n\n{_alert_summary(alert)}\n\n"
                    "Metrics: " + json.dumps(alert.metrics.present())
                ),
            },
        ],
    }


# --------------------------------------------------------------------------- #
# Node: llm_decide
# --------------------------------------------------------------------------- #

class _ToolChoice:
    """Minimal model for parsing the LLM's tool choice."""

    def __init__(self, tool: str, args: dict):
        self.tool = tool
        self.args = args

    @classmethod
    def from_dict(cls, d: dict) -> "_ToolChoice":
        return cls(tool=str(d.get("tool", "")), args=d.get("args", {}))


def llm_decide_node(
    state: AgentState,
    *,
    tool_executor: "ToolExecutor",  # injected by graph builder
) -> dict:
    """Ask the LLM which tool to call next, fall back on invalid choice.

    Returns:
        State update with incremented step, updated messages, and the
        result of the chosen tool already merged in.
    """
    alert = Alert.model_validate(state["alert"])
    step: int = state.get("step", 0)
    max_steps: int = state.get("max_steps", settings.max_agent_steps)
    tools_used = [tc["tool"] for tc in state.get("tool_trace", [])]

    # Build the prompt turn describing current state
    selection_msg = TOOL_SELECTION_PROMPT.format(
        alert_summary=_alert_summary(alert),
        step=step,
        max_steps=max_steps,
        tools_used=", ".join(tools_used) or "none",
        correlation_summary=_corr_summary(state),
        node_context_summary=_node_summary(state),
        lookup_summary=_lookup_summary(state),
    )

    messages = list(state.get("messages", []))
    messages.append({"role": "user", "content": selection_msg})

    # Convert LangGraph messages (which could be LangChain message objects) to plain dicts
    ollama_messages = []
    for msg in messages:
        if isinstance(msg, dict):
            ollama_messages.append(msg)
        else:
            role = "user"
            if msg.type == "system":
                role = "system"
            elif msg.type == "ai":
                role = "assistant"
            elif msg.type == "tool":
                role = "tool"
            
            ollama_messages.append({
                "role": role,
                "content": str(msg.content) if not isinstance(msg.content, str) else msg.content
            })

    # ---- LLM call with fallback ----
    forced = False
    chosen_tool: str
    args: dict

    try:
        raw = _llm_chat_raw(ollama_messages)
        choice = json.loads(raw)
        chosen_tool = str(choice.get("tool", "")).strip()
        args = choice.get("args", {})
        if chosen_tool not in TOOL_NAMES:
            raise ValueError(f"Unknown tool: {chosen_tool!r}")
    except (json.JSONDecodeError, ValueError, OllamaError) as exc:
        # Fallback: run lookup_incidents if not done yet, else finalize
        forced = True
        if "lookup_incidents" not in tools_used:
            chosen_tool = "lookup_incidents"
            args = {"alert_id": alert.alert_id}
            logger.warning("llm_decide_node fallback → %s (reason: %s)", chosen_tool, exc)
        else:
            chosen_tool = "recommend_action"
            args = {
                "alert_id": alert.alert_id,
                "root_cause": "Agent exceeded step budget or produced invalid output; escalating.",
                "evidence": [],
            }
            logger.warning("llm_decide_node fallback → recommend_action (reason: %s)", exc)

    messages.append({"role": "assistant", "content": json.dumps({"tool": chosen_tool, "args": args})})

    # ---- Execute tool ----
    t0 = time.monotonic()
    tool_result, tool_error = tool_executor.run(chosen_tool, args, state)
    duration_ms = int((time.monotonic() - t0) * 1000)

    result_summary = _result_summary(chosen_tool, tool_result, tool_error)
    messages.append({
        "role": "tool", 
        "name": chosen_tool,
        "content": result_summary,
        "tool_call_id": f"call_{step}"
    })

    trace_entry = _make_tool_call_record(
        step=step + 1,
        tool=chosen_tool,
        args=_safe_args(args),
        summary=result_summary,
        duration_ms=duration_ms,
        forced=forced,
        error=tool_error,
    )

    state_update: dict[str, Any] = {
        "step": step + 1,
        "messages": messages,
        "tool_trace": [trace_entry],
    }
    if forced:
        state_update["forced_tools"] = list(state.get("forced_tools", [])) + [chosen_tool]

    # Merge tool-specific result keys
    if tool_result:
        state_update.update(_merge_tool_result(chosen_tool, tool_result))

    return state_update


def _llm_chat_raw(messages: list[dict]) -> str:
    """Direct chat call — separated so tests can monkeypatch."""
    from anvesaka_AI.agent.llm import chat as _chat  # local import so tests can mock
    return _chat(messages)


def _safe_args(args: dict) -> dict:
    """Strip sensitive keys before storing in trace."""
    return {k: v for k, v in args.items() if k not in ("password", "token", "secret")}


def _result_summary(tool: str, result: Optional[dict], error: Optional[str]) -> str:
    if error:
        return f"{tool} error: {error}"
    if not result:
        return f"{tool}: no result"
    if tool == "correlate_alerts":
        n = len(result.get("related", []))
        return f"correlate_alerts: {n} related alert(s)"
    if tool == "get_node_context":
        node = result.get("node")
        return f"get_node_context: node={'found' if node else 'unknown'}"
    if tool == "lookup_incidents":
        cands = result.get("candidates", [])
        top = cands[0] if cands else None
        return f"lookup_incidents: {len(cands)} candidate(s), top={top['incident_id'] if top else 'none'} score={top['score'] if top else 0:.2f}"
    if tool == "recommend_action":
        return f"recommend_action: decision={result.get('decision')}"
    return f"{tool}: ok"


def _merge_tool_result(tool: str, result: dict) -> dict:
    key_map = {
        "correlate_alerts": "correlation",
        "get_node_context": "node_context",
        "lookup_incidents": "lookup",
        "recommend_action": "recommendation",
    }
    key = key_map.get(tool)
    return {key: result} if key else {}


# --------------------------------------------------------------------------- #
# Node: finalize
# --------------------------------------------------------------------------- #

def finalize_node(state: AgentState, *, playbook_index: dict[str, PlaybookEntry]) -> dict:
    """Build the TriageResult from gathered evidence.

    Remediation steps are always copied from the playbook here.
    The LLM's recommendation (if any) provides the decision and explanation only.
    """
    alert = Alert.model_validate(state["alert"])
    rec_dict: Optional[dict] = state.get("recommendation")
    lookup_dict: Optional[dict] = state.get("lookup")
    tool_trace = state.get("tool_trace", [])

    # ---- Determine top playbook score ----
    top_score = 0.0
    if lookup_dict:
        cands = lookup_dict.get("candidates", [])
        if cands:
            top_score = cands[0].get("score", 0.0)

    # ---- Build Recommendation + steps ----
    if rec_dict:
        candidate_id = rec_dict.get("incident_id") or rec_dict.get("candidate_incident_id")
        root_cause = rec_dict.get("root_cause", "No explanation provided.")
        evidence = rec_dict.get("evidence", [])
    else:
        # Fallback: no recommend_action was ever called
        candidate_id = None
        root_cause = "Agent reached step limit without producing a recommendation."
        evidence = []

    recommendation, remediation_steps = build_recommendation(
        candidate_incident_id=candidate_id,
        root_cause=root_cause,
        evidence=evidence,
        top_score=top_score,
        playbook_index=playbook_index,
    )

    # ---- Confidence ----
    if recommendation.decision == Decision.MATCH_INCIDENT:
        llm_matches_top = (
            lookup_dict
            and lookup_dict.get("candidates")
            and lookup_dict["candidates"][0]["incident_id"] == recommendation.incident_id
        )
        confidence = round(top_score * (1.0 if llm_matches_top else 0.6), 3)
    else:
        confidence = 0.0

    # ---- Priority / escalate ----
    racks_affected = len(state.get("correlation", {}).get("affected_racks", [alert.rack_id]))
    priority = priority_for(alert.severity, racks_affected)
    escalate = recommendation.decision == Decision.ESCALATE_UNKNOWN or priority.value == "P1"

    result = TriageResult(
        alert_id=alert.alert_id,
        status="ok" if recommendation.decision != Decision.ESCALATE_UNKNOWN else "fallback_used"
        if state.get("forced_tools") else "ok",
        decision=recommendation.decision,
        matched_incident_id=recommendation.incident_id,
        root_cause=recommendation.root_cause,
        recommended_steps=remediation_steps,
        estimated_resolution_mins=(
            playbook_index[recommendation.incident_id].historical_resolution_time_mins
            if recommendation.incident_id and recommendation.incident_id in playbook_index
            else None
        ),
        priority=priority,
        escalate=escalate,
        confidence=confidence,
        correlated_alert_ids=[
            r["alert_id"] for r in (state.get("correlation") or {}).get("related", [])
        ],
        evidence=recommendation.evidence,
        tool_trace=[ToolCall.model_validate(t) for t in tool_trace],
        model=settings.ollama_model,
        latency_s=0.0,  # caller fills this in after timing the whole run
        notifications_sent=[],
    )

    logger.info(
        "finalize_node: %s → %s confidence=%.2f priority=%s",
        alert.alert_id,
        recommendation.decision.value,
        confidence,
        priority.value,
    )
    return {"result": result.model_dump(mode="json")}


# --------------------------------------------------------------------------- #
# ToolExecutor — dependency-injected; lets tests swap in stubs
# --------------------------------------------------------------------------- #

class ToolExecutor:
    """Dispatches tool name → callable.

    Wrap in tests by passing stub callables.  The graph builder injects
    a real instance that calls the Member 1 tool implementations.
    """

    def __init__(
        self,
        correlate_fn,
        node_context_fn,
        lookup_fn,
        playbook_index: dict[str, PlaybookEntry],
    ):
        self._correlate = correlate_fn
        self._node_context = node_context_fn
        self._lookup = lookup_fn
        self._playbook_index = playbook_index

    def run(
        self, tool: str, args: dict, state: AgentState
    ) -> tuple[Optional[dict], Optional[str]]:
        """Execute *tool* and return (result_dict, error_str).

        Always returns a tuple so callers don't need try/except.
        """
        try:
            if tool == "correlate_alerts":
                parsed = CorrelateArgs.model_validate({**args, "alert_id": args.get("alert_id", state["alert"]["alert_id"])})
                result = self._correlate(parsed)
                return result.model_dump(mode="json"), None

            if tool == "get_node_context":
                if "node" in args and "node_id" not in args:
                    args["node_id"] = args.pop("node")
                parsed = NodeContextArgs.model_validate(args)
                result = self._node_context(parsed)
                return result.model_dump(mode="json"), None

            if tool == "lookup_incidents":
                parsed = LookupArgs.model_validate({**args, "alert_id": args.get("alert_id", state["alert"]["alert_id"])})
                result = self._lookup(parsed)
                return result.model_dump(mode="json"), None

            if tool == "recommend_action":
                # recommend_action args are handled in finalize_node;
                # here we just return them as the "result" for the trace.
                return args, None

            return None, f"Unknown tool: {tool!r}"
        except Exception as exc:
            logger.exception("ToolExecutor.run(%s) failed", tool)
            return None, str(exc)
