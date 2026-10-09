"""
Reference implementation of the deterministic parts of Anvesaka.

Pure Python over lists of models (no DB calls) so it is trivially testable.
Member B wraps these with Mongo queries; Member A calls them from the LangGraph tool nodes.

  parse_clause()      symptom_signature line  -> SignatureClause
  evaluate_clause()   clause + alert (+context) -> True / False / None (None = unverified)
  rank_candidates()   alert -> ranked PlaybookMatch list      (tool: lookup_incidents)
  correlate()         alert -> CorrelationResult              (tool: correlate_alerts)
  node_context()      alert -> NodeContext                    (tool: get_node_context)
"""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from typing import Optional

try:
    from anvesaka_AI.schemas import (
        Alert, AnomalyType, ClauseContext, ClauseKind, CorrelationResult, LookupResult,
        NodeContext, NodeInfo, PlaybookEntry, PlaybookMatch, RelatedAlert, Severity,
        SignatureClause, racks_adjacent,
    )
except ImportError:
    from schemas import (
        Alert, AnomalyType, ClauseContext, ClauseKind, CorrelationResult, LookupResult,
        NodeContext, NodeInfo, PlaybookEntry, PlaybookMatch, RelatedAlert, Severity,
        SignatureClause, racks_adjacent,
    )


TOP_OF_RACK_U = 36           # U36+ counts as "top-of-rack" in a 42U rack
_NUM = r"(-?\d+(?:\.\d+)?)"


# --------------------------------------------------------------------------- #
# parsing
# --------------------------------------------------------------------------- #
def parse_clause(raw: str) -> SignatureClause:
    s = raw.strip()
    C = lambda **kw: SignatureClause(raw=raw, **kw)  # noqa: E731

    if m := re.fullmatch(r"anomaly_type == (\w+)", s):
        return C(kind=ClauseKind.CATEGORY, field="anomaly_type", op="==", value=m.group(1))
    if m := re.fullmatch(r"severity == (\w+)", s):
        return C(kind=ClauseKind.SEVERITY, field="severity", op="IN", value=[m.group(1)])
    if m := re.fullmatch(r"severity IN \[(.+)\]", s):
        return C(kind=ClauseKind.SEVERITY, field="severity", op="IN",
                 value=[v.strip() for v in m.group(1).split(",")])
    if m := re.fullmatch(rf"(\w+) between {_NUM} and {_NUM}", s):
        return C(kind=ClauseKind.RANGE, field=m.group(1), op="between",
                 value=[float(m.group(2)), float(m.group(3))])
    if m := re.fullmatch(rf"(\w+) (==|!=|<=|>=|<|>) {_NUM}", s):
        return C(kind=ClauseKind.NUMERIC, field=m.group(1), op=m.group(2), value=float(m.group(3)))
    if m := re.fullmatch(r"raw_message contains (.+)", s):
        return C(kind=ClauseKind.TEXT, field="raw_message", op="contains_any",
                 value=[v.strip() for v in m.group(1).split(" OR ")])

    # ---- context clauses: need another tool ----
    if m := re.fullmatch(rf"(\w+) dropped > {_NUM}% vs 7-day median", s):
        return C(kind=ClauseKind.CONTEXT, context=ClauseContext.NODE_HISTORY,
                 field=m.group(1), op="drop_pct_gt", value=float(m.group(2)))
    if m := re.fullmatch(rf"(\w+) < {_NUM}% of link capacity", s):
        return C(kind=ClauseKind.CONTEXT, context=ClauseContext.CMDB,
                 field=m.group(1), op="pct_of_link_lt", value=float(m.group(2)))
    if s == "MemTotal lower than CMDB baseline":
        return C(kind=ClauseKind.CONTEXT, context=ClauseContext.CMDB, op="memtotal_lt_baseline")
    if s == "only top-of-rack U-positions affected":
        return C(kind=ClauseKind.CONTEXT, context=ClauseContext.CMDB, op="top_of_rack")
    if m := re.fullmatch(rf"adjacent node (\w+) < {_NUM}", s):
        return C(kind=ClauseKind.CONTEXT, context=ClauseContext.NEIGHBORS,
                 field=m.group(1), op="<", value=float(m.group(2)))
    if m := re.fullmatch(r"multiple nodes in same or adjacent racks alerting within (\d+) min", s):
        return C(kind=ClauseKind.CONTEXT, context=ClauseContext.CORRELATION,
                 op="multi_node_adjacent_min", value=int(m.group(1)))
    if m := re.fullmatch(r"multiple nodes in same rack lost within (\d+) seconds", s):
        return C(kind=ClauseKind.CONTEXT, context=ClauseContext.CORRELATION,
                 op="multi_node_rack_sec", value=int(m.group(1)))
    if m := re.fullmatch(r"(\w+) (\w+) alert in same rack within the previous (\d+) min", s):
        return C(kind=ClauseKind.CONTEXT, context=ClauseContext.CROSS_DOMAIN,
                 op="cross_domain", value={"category": m.group(1), "severity": m.group(2).upper(),
                                           "minutes": int(m.group(3))})
    if s == "all nodes in rack lose uplink simultaneously":
        return C(kind=ClauseKind.CONTEXT, context=ClauseContext.RACK_WIDE, op="rack_wide")

    raise ValueError(f"Unparseable signature clause: {raw!r}")   # fail loudly at ingest, not at 2am


def parse_playbook(entry: PlaybookEntry) -> PlaybookEntry:
    entry.signature_clauses = [parse_clause(c) for c in entry.symptom_signature]
    return entry


# --------------------------------------------------------------------------- #
# correlation  (tool: correlate_alerts)
# --------------------------------------------------------------------------- #
def correlate(anchor: Alert, alerts: list[Alert], window_min: int = 360) -> CorrelationResult:
    related: list[RelatedAlert] = []
    for a in alerts:
        if a.alert_id == anchor.alert_id or a.severity == Severity.INFO or a.is_recovery:
            continue
        delta = (anchor.timestamp - a.timestamp).total_seconds() / 60.0
        if delta < 0 or delta > window_min:               # no look-ahead, inside window
            continue
        if a.node_id == anchor.node_id:
            rel = "same_node"
        elif a.rack_id == anchor.rack_id:
            rel = "same_rack"
        elif racks_adjacent(a.rack_id, anchor.rack_id):
            rel = "adjacent_rack"
        else:
            continue
        related.append(RelatedAlert(
            alert_id=a.alert_id, node_id=a.node_id, rack_id=a.rack_id,
            anomaly_type=a.anomaly_type, severity=a.severity,
            minutes_before=round(delta, 2), relation=rel))
    related.sort(key=lambda r: r.minutes_before, reverse=True)       # oldest first

    same_node = [r for r in related if r.relation == "same_node"]
    sev_seq = [r.severity.rank for r in same_node] + [anchor.severity.rank]
    escalating = len(sev_seq) >= 2 and all(b >= a for a, b in zip(sev_seq, sev_seq[1:])) and sev_seq[-1] > sev_seq[0]
    return CorrelationResult(
        anchor_alert_id=anchor.alert_id, window_min=window_min, related=related,
        affected_nodes=sorted({anchor.node_id, *[r.node_id for r in related]}),
        affected_racks=sorted({anchor.rack_id, *[r.rack_id for r in related]}),
        categories_present=sorted({anchor.anomaly_type, *[r.anomaly_type for r in related]}, key=lambda c: c.value),
        escalating=escalating)


# --------------------------------------------------------------------------- #
# node context  (tool: get_node_context)
# --------------------------------------------------------------------------- #
def node_context(anchor: Alert, alerts: list[Alert], nodes: dict[str, NodeInfo]) -> NodeContext:
    prior = [a for a in alerts if a.node_id == anchor.node_id and a.timestamp < anchor.timestamp
             and a.severity != Severity.INFO and not a.is_recovery]
    medians: dict[str, float] = {}
    keys = {k for a in prior for k in a.metrics.present()}
    for k in keys:
        vals = [a.metrics.present()[k] for a in prior if k in a.metrics.present()]
        medians[k] = statistics.median(vals)
    neighbors = {n: float(t) for n, t in re.findall(r"(srv-node-\d+) \(U\d+\) Inlet=(\d+(?:\.\d+)?)C", anchor.raw_message)}
    return NodeContext(node=nodes.get(anchor.node_id), prior_alert_ids=[a.alert_id for a in prior],
                       median_metrics=medians, neighbor_inlet_temps=neighbors)


# --------------------------------------------------------------------------- #
# clause evaluation + ranking  (tool: lookup_incidents)
# --------------------------------------------------------------------------- #
_OPS = {"<": lambda a, b: a < b, ">": lambda a, b: a > b, "<=": lambda a, b: a <= b,
        ">=": lambda a, b: a >= b, "==": lambda a, b: a == b, "!=": lambda a, b: a != b}


@dataclass
class Ctx:
    anchor: Alert
    corr: Optional[CorrelationResult] = None
    node: Optional[NodeContext] = None


def evaluate_clause(c: SignatureClause, ctx: Ctx) -> Optional[bool]:
    """True / False, or None when the evidence needed has not been gathered yet."""
    a = ctx.anchor
    if c.kind == ClauseKind.CATEGORY:
        return a.anomaly_type.value == c.value
    if c.kind == ClauseKind.SEVERITY:
        return a.severity.value in c.value
    if c.kind == ClauseKind.TEXT:
        return any(t.lower() in a.raw_message.lower() for t in c.value)
    if c.kind in (ClauseKind.NUMERIC, ClauseKind.RANGE):
        v = a.metrics.present().get(c.field)
        if v is None:
            return False          # metric absent on this alert type -> clause cannot hold
        return _OPS[c.op](v, c.value) if c.kind == ClauseKind.NUMERIC else c.value[0] <= v <= c.value[1]

    # ---- context ----
    if c.context == ClauseContext.CORRELATION:
        if ctx.corr is None:
            return None
        if c.op == "multi_node_adjacent_min":
            near = {r.node_id for r in ctx.corr.related if r.minutes_before <= c.value}
            return len(near | {a.node_id}) >= 2
        if c.op == "multi_node_rack_sec":
            peers = {r.node_id for r in ctx.corr.related
                     if r.rack_id == a.rack_id and r.severity == a.severity
                     and r.minutes_before * 60 <= c.value}
            return len(peers | {a.node_id}) >= 2
    if c.context == ClauseContext.CROSS_DOMAIN:
        if ctx.corr is None:
            return None
        v = c.value
        return any(r.anomaly_type.value == v["category"] and r.severity.value == v["severity"]
                   and r.rack_id == a.rack_id and r.minutes_before <= v["minutes"] for r in ctx.corr.related)
    if c.context == ClauseContext.RACK_WIDE:
        return bool(re.search(r"on all \d+ (downlinks|nodes)", a.raw_message))   # message-derived
    if ctx.node is None:
        return None
    if c.context == ClauseContext.NODE_HISTORY:
        base = ctx.node.median_metrics.get(c.field)
        cur = a.metrics.present().get(c.field)
        if base is None or cur is None or base == 0:
            return None
        return (base - cur) / base * 100 > c.value
    if c.context == ClauseContext.NEIGHBORS:
        if not ctx.node.neighbor_inlet_temps:
            return None
        return all(t < c.value for t in ctx.node.neighbor_inlet_temps.values())
    if c.context == ClauseContext.CMDB:
        n = ctx.node.node
        if n is None:
            return None
        if c.op == "pct_of_link_lt":
            link = n.baseline.link_gbps
            tx = a.metrics.present().get(c.field)
            return None if link is None or tx is None else tx < link * 1000 * c.value / 100
        if c.op == "memtotal_lt_baseline":
            m = re.search(r"of (\d+(?:\.\d+)?)GiB", a.raw_message)
            return None if not m or n.baseline.mem_total_gib is None else float(m.group(1)) < n.baseline.mem_total_gib
        if c.op == "top_of_rack":
            return None if n.u_position is None else n.u_position >= TOP_OF_RACK_U
    return None


def score_entry(entry: PlaybookEntry, ctx: Ctx) -> PlaybookMatch:
    sat, vio, unv = [], [], []
    tools: set[str] = set()
    for c in entry.signature_clauses:
        r = evaluate_clause(c, ctx)
        (sat if r is True else vio if r is False else unv).append(c.raw)
        if r is None and c.context:
            tools.add("correlate_alerts" if c.context in (ClauseContext.CORRELATION, ClauseContext.CROSS_DOMAIN)
                      else "get_node_context")
    n = len(entry.signature_clauses)
    return PlaybookMatch(incident_id=entry.incident_id, score=round(len(sat) / n, 3), n_satisfied=len(sat),
                         n_violated=len(vio), n_unverified=len(unv), satisfied=sat, violated=vio,
                         unverified=unv, needs_tools=sorted(tools))


def rank_candidates(ctx: Ctx, playbook: list[PlaybookEntry], top_k: int = 3) -> LookupResult:
    """Rank: fewest violated clauses first, then most satisfied. Entries from a different
    anomaly_category are still scored (an alert's own category can mislead - see INC-5261)."""
    scored = [score_entry(e, ctx) for e in playbook]
    scored.sort(key=lambda m: (m.n_violated, -m.n_satisfied, m.incident_id))
    return LookupResult(anchor_alert_id=ctx.anchor.alert_id, candidates=scored[:top_k])


def required_tools(entry: PlaybookEntry) -> list[str]:
    """Tools a correct investigation of this incident MUST call (-> Scenario.expected_tools)."""
    t = {"lookup_incidents", "recommend_action"}
    for c in entry.signature_clauses:
        if c.context in (ClauseContext.CORRELATION, ClauseContext.CROSS_DOMAIN):
            t.add("correlate_alerts")
        elif c.context and c.context != ClauseContext.RACK_WIDE:   # rack_wide is read from raw_message
            t.add("get_node_context")
    return sorted(t)
