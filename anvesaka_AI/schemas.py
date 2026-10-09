"""
Anvesaka - shared data contracts (single source of truth).

Everyone imports from here. Nobody redefines these shapes locally.
Requires: pydantic>=2.  (pymongo only needed for create_indexes()).

Sections
  1. Enums
  2. Mongo document models   (alerts, playbook, nodes)
  3. Evaluation models       (scenarios = ground truth, eval_runs)
  4. Tool I/O models         (correlate_alerts, lookup_incidents, get_node_context, recommend_action)
  5. API models              (POST /triage)
  6. LangGraph agent state
  7. Mongo collections + indexes
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Literal, Optional, TypedDict

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# --------------------------------------------------------------------------- #
# 1. ENUMS
# --------------------------------------------------------------------------- #
class Severity(str, Enum):
    """Normalised severity. Ordered: INFO < WARNING < ERROR < CRITICAL < FATAL."""
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"
    FATAL = "FATAL"

    @property
    def rank(self) -> int:
        return ["INFO", "WARNING", "ERROR", "CRITICAL", "FATAL"].index(self.value)


class AnomalyType(str, Enum):
    THERMAL = "Thermal"
    STORAGE = "Storage"
    NETWORK = "Network"
    POWER = "Power"
    COMPUTE = "Compute"


class AlertSource(str, Enum):
    ZABBIX = "Zabbix"
    DATADOG = "Datadog"
    PROMETHEUS = "Prometheus"
    UNKNOWN = "Unknown"


class Decision(str, Enum):
    """What the agent concluded. This is the main label we evaluate."""
    MATCH_INCIDENT = "match_incident"      # confident match to a playbook entry
    NO_ACTION = "no_action"                # INFO / recovery / noise -> do not page anyone
    ESCALATE_UNKNOWN = "escalate_unknown"  # real problem, no playbook entry fits -> human


class Priority(str, Enum):
    P1 = "P1"  # FATAL, or blast radius >= 2 racks
    P2 = "P2"  # CRITICAL
    P3 = "P3"  # ERROR / WARNING
    P4 = "P4"  # INFO


# Zabbix/Datadog/Prometheus each use their own words in raw_message. Ingest maps
# them to the normalised Severity above (the `severity` field in alerts.json is
# already normalised; this table documents WHY e.g. "Average" == ERROR).
ZABBIX_SEVERITY_MAP = {
    "Information": "INFO", "Warning": "WARNING", "Average": "ERROR",
    "High": "CRITICAL", "Disaster": "FATAL",
}

RACK_ID_RE = re.compile(r"^Rack-([A-Z])(\d{2})$")


def parse_rack(rack_id: str) -> tuple[str, int]:
    """'Rack-C04' -> ('C', 4). Used for 'adjacent rack' logic (same row, |pos diff| <= 1)."""
    m = RACK_ID_RE.match(rack_id)
    if not m:
        raise ValueError(f"bad rack_id: {rack_id}")
    return m.group(1), int(m.group(2))


def racks_adjacent(a: str, b: str) -> bool:
    ra, pa = parse_rack(a)
    rb, pb = parse_rack(b)
    return ra == rb and abs(pa - pb) <= 1


# --------------------------------------------------------------------------- #
# 2. MONGO DOCUMENT MODELS
# --------------------------------------------------------------------------- #
class Metrics(BaseModel):
    """Closed set of the 14 metric keys that appear in alerts.json. All optional:
    each anomaly_type only populates the subset that makes sense for it."""
    model_config = ConfigDict(extra="forbid")

    # Thermal / Power / Compute
    cpu_temp_c: Optional[float] = None
    inlet_temp_c: Optional[float] = None
    fan_rpm: Optional[float] = None
    power_draw_w: Optional[float] = None
    humidity_pct: Optional[float] = None
    cpu_load_pct: Optional[float] = None
    system_load_1m: Optional[float] = None
    memory_usage_pct: Optional[float] = None
    # Storage
    storage_capacity_pct: Optional[float] = None
    disk_iops: Optional[float] = None
    disk_read_errors: Optional[float] = None
    # Storage + Network
    latency_ms: Optional[float] = None
    # Network
    packet_drop_rate_pct: Optional[float] = None
    network_tx_mbps: Optional[float] = None

    def present(self) -> dict[str, float]:
        return {k: v for k, v in self.model_dump().items() if v is not None}


class Alert(BaseModel):
    """Collection `alerts`.  First 8 fields = your alerts.json exactly.
    `source` and `is_recovery` are DERIVED at ingest from raw_message."""
    alert_id: str = Field(pattern=r"^ALT-[\w-]+$")   # ALT-1001, or ALT-1007-v3 for generated variants
    timestamp: datetime
    rack_id: str
    node_id: str = Field(pattern=r"^srv-node-\d+$")
    anomaly_type: AnomalyType
    metrics: Metrics
    severity: Severity
    raw_message: str
    # derived at ingest
    source: AlertSource = AlertSource.UNKNOWN
    is_recovery: bool = False   # True for "RESOLVED" / "Recovered" messages

    @field_validator("rack_id")
    @classmethod
    def _rack(cls, v: str) -> str:
        parse_rack(v)
        return v

    @field_validator("timestamp")
    @classmethod
    def _tz(cls, v: datetime) -> datetime:
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)

    @model_validator(mode="after")
    def _derive(self) -> "Alert":
        m = self.raw_message
        if self.source == AlertSource.UNKNOWN:
            for s in AlertSource:
                if s != AlertSource.UNKNOWN and s.value.lower() in m.lower():
                    self.source = s
                    break
        if re.search(r"\b(RESOLVED|Recovered)\b", m):
            self.is_recovery = True
        return self


class ClauseKind(str, Enum):
    NUMERIC = "numeric"            # fan_rpm < 2000
    RANGE = "range"                # fan_rpm between 12000 and 15000
    CATEGORY = "category"          # anomaly_type == Thermal
    SEVERITY = "severity"          # severity IN [ERROR, CRITICAL]
    TEXT = "text"                  # raw_message contains X OR Y
    CONTEXT = "context"            # needs another tool; see `context`


class ClauseContext(str, Enum):
    """Which tool can verify a CONTEXT clause. This drives `expected_tools`."""
    CORRELATION = "correlation"          # multiple nodes within N min / N s        -> correlate_alerts
    CROSS_DOMAIN = "cross_domain"        # Storage CRITICAL in same rack earlier    -> correlate_alerts
    NODE_HISTORY = "node_history"        # iops dropped >60% vs median              -> get_node_context
    CMDB = "cmdb"                        # % of link capacity, MemTotal baseline,
                                         # top-of-rack U-position                   -> get_node_context
    NEIGHBORS = "neighbors"              # adjacent node inlet_temp_c < 26          -> get_node_context
    RACK_WIDE = "rack_wide"              # all nodes in rack lose uplink            -> read from raw_message (no tool)


class SignatureClause(BaseModel):
    """One parsed line of `symptom_signature`. Built at ingest by signature_engine.parse_clause()."""
    raw: str
    kind: ClauseKind
    field: Optional[str] = None
    op: Optional[str] = None
    value: Any = None
    context: Optional[ClauseContext] = None


class PlaybookEntry(BaseModel):
    """Collection `playbook`.  First 6 fields = your playbook.json exactly.
    `remediation_steps`, `signature_clauses`, `related_incident_ids` are DERIVED at ingest.
    The agent is the 'historical incident lookup' knowledge base - there is no separate incident log."""
    incident_id: str = Field(pattern=r"^INC-\d+$")
    anomaly_category: AnomalyType
    symptom_signature: list[str]
    historical_root_cause: str
    remediation_action: str
    historical_resolution_time_mins: int
    # derived at ingest
    remediation_steps: list[str] = []
    signature_clauses: list[SignatureClause] = []
    related_incident_ids: list[str] = []   # e.g. INC-5261 -> [INC-5156]

    @model_validator(mode="after")
    def _derive(self) -> "PlaybookEntry":
        if not self.remediation_steps:
            parts = re.split(r"(?:^|\s)\d{1,2}\.\s+(?=[A-Z<])", self.remediation_action)
            self.remediation_steps = [p.strip() for p in parts if p.strip()]
        if not self.related_incident_ids:
            ids = set(re.findall(r"INC-\d{4}", self.historical_root_cause + " " + self.remediation_action))
            ids.discard(self.incident_id)
            self.related_incident_ids = sorted(ids)
        return self


class NodeRole(str, Enum):
    COMPUTE = "compute"
    STORAGE = "storage"


class NodeBaseline(BaseModel):
    """CMDB facts the playbook signatures refer to ('CMDB baseline', '% of link capacity')."""
    mem_total_gib: Optional[float] = None
    link_gbps: Optional[float] = None
    power_cap_w: Optional[float] = None
    psu_rating_w: Optional[float] = None


class NodeInfo(BaseModel):
    """Collection `nodes` (a mini-CMDB). Seeded from cmdb_nodes.json."""
    node_id: str
    rack_id: str
    rack_row: str
    rack_pos: int
    role: NodeRole = NodeRole.COMPUTE
    u_position: Optional[int] = None       # rack unit; 42U rack assumed, U36+ = 'top of rack'
    pdu: Optional[str] = None
    baseline: NodeBaseline = NodeBaseline()
    inferred_fields: list[str] = []        # fields NOT stated in alert text (defaults/assumptions)


# --------------------------------------------------------------------------- #
# 3. EVALUATION MODELS
# --------------------------------------------------------------------------- #
class Scenario(BaseModel):
    """Ground truth. File `ground_truth.json`. The agent must NEVER read this
    (keep it out of Mongo, or in a collection the agent has no tool for)."""
    scenario_id: str
    title: str
    outcome: Decision                       # expected decision
    trigger_alert_id: str                   # the alert you POST to /triage
    expected_incident_id: Optional[str] = None
    acceptable_incident_ids: list[str] = []  # extra IDs that also count as correct
    expected_related_alert_ids: list[str] = []   # what correlate_alerts SHOULD surface
    expected_tools: list[str] = []          # tools a correct investigation must call
    must_mention: list[str] = []            # case-insensitive substrings the root_cause text must contain
    difficulty: Literal["easy", "medium", "hard"]
    tags: list[str] = []
    split: Literal["dev", "test"]           # dev = used for prompt tuning, test = held out
    variant_of: Optional[str] = None        # scenario_id this noisy variant was generated from
    notes: str = ""


class EvalRecord(BaseModel):
    """Collection `eval_runs`. One row per (mode, scenario, run). Agent, rule-based
    baseline and manual humans all write the same shape so one query compares them."""
    eval_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    mode: Literal["agent", "rule_based", "manual"]
    scenario_id: str
    run_idx: int = 0                        # 0..2 for agent repeats
    rater: Optional[str] = None             # manual mode only
    model: Optional[str] = None             # agent mode only
    decision: Optional[Decision] = None
    predicted_incident_id: Optional[str] = None
    correct: Optional[bool] = None
    tools_called: list[str] = []
    tools_correct: Optional[bool] = None    # expected_tools subset of tools_called
    mention_hits: Optional[float] = None    # fraction of must_mention found
    steps_faithful: Optional[bool] = None   # every recommended step appears in the playbook entry
    time_seconds: float                     # latency (agent) or stopwatch (manual)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# --------------------------------------------------------------------------- #
# 4. TOOL I/O MODELS
# --------------------------------------------------------------------------- #
TOOL_NAMES = ["correlate_alerts", "lookup_incidents", "get_node_context", "recommend_action"]
# Synopsis Objective 2 asks for >= 3 tools: correlation, historical lookup, root-cause
# recommendation. get_node_context is the 4th and exists because 8 of the 15 playbook
# signatures contain clauses that cannot be checked from the alert alone.


class RelatedAlert(BaseModel):
    alert_id: str
    node_id: str
    rack_id: str
    anomaly_type: AnomalyType
    severity: Severity
    minutes_before: float                   # relative to anchor; never negative (no look-ahead)
    relation: Literal["same_node", "same_rack", "adjacent_rack"]


class CorrelateArgs(BaseModel):
    alert_id: str
    window_min: int = Field(default=360, ge=5, le=1440)
    # 360 not 120: the fan-failure story spans ~220 min; cross-domain clauses need
    # only 120 but each RelatedAlert carries minutes_before so clauses can filter.


class CorrelationResult(BaseModel):
    """RULES: only alerts with timestamp <= anchor (no look-ahead); skip INFO and
    recovery alerts; scope = same node, same rack, or adjacent rack (same row, |pos diff| <= 1)."""
    anchor_alert_id: str
    window_min: int
    related: list[RelatedAlert]
    affected_nodes: list[str]
    affected_racks: list[str]
    categories_present: list[AnomalyType]
    escalating: bool                        # same-node severity strictly rising over time


class LookupArgs(BaseModel):
    alert_id: str
    top_k: int = Field(default=3, ge=1, le=5)


class PlaybookMatch(BaseModel):
    incident_id: str
    score: float = Field(ge=0, le=1)        # satisfied / total clauses (unverified counts as 0)
    n_satisfied: int
    n_violated: int
    n_unverified: int
    satisfied: list[str]
    violated: list[str]
    unverified: list[str]                   # the agent should call a tool to verify these
    needs_tools: list[str]                  # tools implied by `unverified`


class LookupResult(BaseModel):
    anchor_alert_id: str
    candidates: list[PlaybookMatch]         # ranked: fewest violations, then most satisfied


class NodeContextArgs(BaseModel):
    node_id: str


class NodeContext(BaseModel):
    node: Optional[NodeInfo] = None
    prior_alert_ids: list[str] = []         # same node, before anchor, non-INFO
    median_metrics: dict[str, float] = {}   # median of the node's prior alerts (proxy for '7-day median')
    neighbor_inlet_temps: dict[str, float] = {}   # parsed from raw_message "Adjacent srv-node-26 (U22) Inlet=24.0C"


class Recommendation(BaseModel):
    """STRUCTURED OUTPUT of the final LLM call (recommend_action). The LLM chooses and
    explains; it does NOT write remediation steps. Steps are copied from the playbook
    by code, so they cannot be hallucinated."""
    decision: Decision
    incident_id: Optional[str] = None
    root_cause: str = Field(max_length=600)    # 1-3 sentences, grounded in evidence
    evidence: list[str] = Field(max_length=8)  # short facts, e.g. "fan_rpm=0 on srv-node-45"

    @model_validator(mode="after")
    def _consistent(self) -> "Recommendation":
        if self.decision == Decision.MATCH_INCIDENT and not self.incident_id:
            raise ValueError("match_incident requires incident_id")
        if self.decision != Decision.MATCH_INCIDENT:
            self.incident_id = None
        return self


# --------------------------------------------------------------------------- #
# 5. API MODELS  (POST /triage)
# --------------------------------------------------------------------------- #
class TriageRequest(BaseModel):
    alert_id: Optional[str] = None          # alert already in Mongo
    alert: Optional[Alert] = None           # or an inline alert (ingested first)
    max_steps: int = Field(default=6, ge=1, le=10)
    notify: bool = False                    # Slack/email

    @model_validator(mode="after")
    def _one(self) -> "TriageRequest":
        if bool(self.alert_id) == bool(self.alert):
            raise ValueError("provide exactly one of alert_id or alert")
        return self


class ToolCall(BaseModel):
    step: int
    tool: str
    args: dict[str, Any]
    summary: str                            # one line a human can read in the trace
    duration_ms: int
    forced: bool = False                    # True if the fallback ran it, not the LLM
    error: Optional[str] = None


class TriageResult(BaseModel):
    run_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    alert_id: str
    status: Literal["ok", "fallback_used", "step_limit", "error"]
    decision: Decision
    matched_incident_id: Optional[str] = None
    root_cause: str
    recommended_steps: list[str] = []       # verbatim playbook steps, <node> placeholders filled
    estimated_resolution_mins: Optional[int] = None   # historical_resolution_time_mins
    priority: Priority
    escalate: bool                          # True for ESCALATE_UNKNOWN, FATAL, or priority P1
    confidence: float = Field(ge=0, le=1)
    # confidence = top matcher score (0-1) x 1.0 if LLM incident == matcher #1 else x 0.6; 0 if no match.
    # NOT the LLM's self-reported confidence - small models are badly calibrated.
    correlated_alert_ids: list[str] = []
    evidence: list[str] = []
    tool_trace: list[ToolCall] = []
    model: str
    latency_s: float
    notifications_sent: list[str] = []      # e.g. ["slack"]


def priority_for(severity: Severity, racks_affected: int) -> Priority:
    """Deterministic priority rule (documented so it is the same everywhere)."""
    if severity == Severity.FATAL or racks_affected >= 2:
        return Priority.P1
    if severity == Severity.CRITICAL:
        return Priority.P2
    if severity in (Severity.ERROR, Severity.WARNING):
        return Priority.P3
    return Priority.P4


# --------------------------------------------------------------------------- #
# 6. LANGGRAPH AGENT STATE
# --------------------------------------------------------------------------- #
def _merge_trace(old: list, new: list) -> list:
    return (old or []) + (new or [])


try:  # langgraph is optional at import time so this file works for data tasks too
    from langgraph.graph.message import add_messages  # type: ignore
except Exception:                                     # pragma: no cover
    def add_messages(left: list, right: list) -> list:  # type: ignore
        return (left or []) + (right or [])

_Msgs = Annotated[list, add_messages]


class AgentState(TypedDict, total=False):
    """Graph:  ingest -> llm_decide -> tool_node -> (loop <= max_steps) -> finalize -> notify
    Each tool node writes its result into the matching key AND appends to tool_trace."""
    alert: dict                      # Alert.model_dump()
    messages: Annotated[list, add_messages]  # LLM conversation incl. tool calls/results
    correlation: Optional[dict]      # CorrelationResult
    node_context: Optional[dict]     # NodeContext
    lookup: Optional[dict]           # LookupResult
    recommendation: Optional[dict]   # Recommendation
    tool_trace: Annotated[list, _merge_trace]
    step: int
    max_steps: int
    forced_tools: list[str]          # tools the fallback had to run itself
    result: Optional[dict]           # TriageResult


# --------------------------------------------------------------------------- #
# 7. MONGO COLLECTIONS + INDEXES
# --------------------------------------------------------------------------- #
DB_NAME = "anvesaka"

# collection -> (model, _id source field)
COLLECTIONS = {
    "alerts":      (Alert, "alert_id"),
    "playbook":    (PlaybookEntry, "incident_id"),
    "nodes":       (NodeInfo, "node_id"),
    "triage_runs": (TriageResult, "run_id"),   # audit log: every /triage response
    "eval_runs":   (EvalRecord, "eval_id"),    # agent + rule_based + manual rows
}

# (keys, options). Reasons: correlate_alerts filters by rack/node + time; the
# lookup filters playbook by category; the text index is a fallback if the
# signature matcher returns nothing.
INDEXES: dict[str, list[tuple[list[tuple[str, Any]], dict]]] = {
    "alerts": [
        ([("rack_id", 1), ("timestamp", -1)], {}),
        ([("node_id", 1), ("timestamp", -1)], {}),
        ([("anomaly_type", 1), ("severity", 1)], {}),
        ([("timestamp", -1)], {}),
    ],
    "playbook": [
        ([("anomaly_category", 1)], {}),
        ([("historical_root_cause", "text"), ("remediation_action", "text")], {"name": "playbook_text"}),
    ],
    "nodes": [([("rack_id", 1)], {})],
    "triage_runs": [([("alert_id", 1), ("created_at", -1)], {})],
    "eval_runs": [([("mode", 1), ("scenario_id", 1), ("run_idx", 1)], {})],
}


def create_indexes(db) -> None:  # pragma: no cover - needs a live Mongo
    for coll, specs in INDEXES.items():
        for keys, opts in specs:
            db[coll].create_index(keys, **opts)
