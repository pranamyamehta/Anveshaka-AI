"""
Run:  python validate_dataset.py [--data-dir PATH] [--verbose]

1. Loads alerts.json / playbook.json / cmdb_nodes.json / ground_truth.json through the Pydantic models.
2. Checks referential integrity (IDs exist, keywords really appear in the playbook, etc.).
3. Runs a DETERMINISTIC rule-based triage (no LLM) on every scenario and reports accuracy.
   This doubles as the `rule_based` arm of the evaluation and as a sanity check on the labels:
   if the rules cannot find the right incident, either the label or the signature is wrong.
Exit code 1 if any integrity check fails.
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from schemas import Alert, Decision, NodeInfo, PlaybookEntry, Scenario, Severity
from signature_engine import Ctx, correlate, node_context, parse_playbook, rank_candidates, required_tools

ap = argparse.ArgumentParser()
ap.add_argument("--data-dir", default=".")
ap.add_argument("--alerts", default=None)
ap.add_argument("--playbook", default=None)
ap.add_argument("--verbose", action="store_true")
args = ap.parse_args()
D = Path(args.data_dir)


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8-sig"))


alerts = [Alert(**x) for x in load(args.alerts or D / "alerts.json")]
playbook = [parse_playbook(PlaybookEntry(**x)) for x in load(args.playbook or D / "playbook.json")]
nodes = {n["node_id"]: NodeInfo(**n) for n in load(D / "cmdb_nodes.json")}
scenarios = [Scenario(**x) for x in load(D / "ground_truth.json")]
A = {a.alert_id: a for a in alerts}
P = {e.incident_id: e for e in playbook}
errors: list[str] = []


def check(cond: bool, msg: str):
    if not cond:
        errors.append(msg)


# ---------------- integrity ----------------
check(len({a.alert_id for a in alerts}) == len(alerts), "duplicate alert_id")
check(len(P) == len(playbook), "duplicate incident_id")
for a in alerts:
    check(a.node_id in nodes, f"{a.alert_id}: node {a.node_id} missing from CMDB")
    if a.node_id in nodes:
        check(nodes[a.node_id].rack_id == a.rack_id, f"{a.alert_id}: rack mismatch with CMDB")
for e in playbook:
    check(1 <= len(e.remediation_steps) <= 12, f"{e.incident_id}: odd step count {len(e.remediation_steps)}")
    check(all(i in P for i in e.related_incident_ids), f"{e.incident_id}: dangling related incident")
for s in scenarios:
    check(s.trigger_alert_id in A, f"{s.scenario_id}: unknown trigger {s.trigger_alert_id}")
    if s.expected_incident_id:
        check(s.expected_incident_id in P, f"{s.scenario_id}: unknown incident")
        text = P[s.expected_incident_id].historical_root_cause.lower()
        for kw in s.must_mention:
            check(kw.lower() in text, f"{s.scenario_id}: must_mention '{kw}' not in {s.expected_incident_id} root cause")
    check(all(r in A for r in s.expected_related_alert_ids), f"{s.scenario_id}: unknown related alert")
covered = {s.expected_incident_id for s in scenarios if s.expected_incident_id}
check(covered == set(P), f"playbook entries with no scenario: {sorted(set(P) - covered)}")


# ---------------- rule-based triage (no LLM) ----------------
def rule_based(alert: Alert):
    if alert.severity == Severity.INFO or alert.is_recovery:
        return Decision.NO_ACTION, None, []
    corr = correlate(alert, alerts, 360)
    ctx = Ctx(anchor=alert, corr=corr, node=node_context(alert, alerts, nodes))
    top = rank_candidates(ctx, playbook, top_k=3).candidates
    best = top[0]
    # accept only if nothing contradicts it AND every clause could be verified
    if best.n_violated == 0 and best.n_unverified == 0:
        return Decision.MATCH_INCIDENT, best.incident_id, top
    return Decision.ESCALATE_UNKNOWN, None, top


rows, ok_decision, ok_incident, n_inc = [], 0, 0, 0
for s in scenarios:
    dec, inc, top = rule_based(A[s.trigger_alert_id])
    d_ok = dec == s.outcome
    i_ok = (inc == s.expected_incident_id) or (inc in s.acceptable_incident_ids)
    ok_decision += d_ok
    if s.outcome == Decision.MATCH_INCIDENT:
        n_inc += 1
        ok_incident += i_ok
    rows.append((s, dec, inc, d_ok and i_ok, top))

print(f"alerts={len(alerts)}  playbook={len(playbook)}  nodes={len(nodes)}  scenarios={len(scenarios)}")
print(f"severity mix: {dict(Counter(a.severity.value for a in alerts))}")
print(f"splits: {dict(Counter(s.split for s in scenarios))}   difficulty: {dict(Counter(s.difficulty for s in scenarios))}")
print(f"clauses: {sum(len(e.signature_clauses) for e in playbook)} total, "
      f"{sum(1 for e in playbook for c in e.signature_clauses if c.kind.value == 'context')} context-dependent")
print()
print(f"{'scenario':7} {'trigger':9} {'expected':10} {'rule-based':10} {'ok':3} tools-required")
for s, dec, inc, ok, top in rows:
    exp = s.expected_incident_id or s.outcome.value
    got = inc or dec.value
    print(f"{s.scenario_id:7} {s.trigger_alert_id:9} {exp:10} {got:10} {'Y' if ok else 'N':3} {','.join(t for t in s.expected_tools if t not in ('lookup_incidents','recommend_action')) or '-'}")
    if args.verbose or not ok:
        for m in top[:2]:
            print(f"        {m.incident_id} score={m.score} sat={m.n_satisfied} vio={m.n_violated} unv={m.n_unverified}"
                  + (f" violated={m.violated}" if m.violated else "") + (f" unverified={m.unverified}" if m.unverified else ""))
print()
print(f"rule-based decision accuracy : {ok_decision}/{len(scenarios)}")
print(f"rule-based incident accuracy : {ok_incident}/{n_inc}  (match_incident scenarios only)")
print()
if errors:
    print("INTEGRITY ERRORS:")
    for e in errors:
        print("  -", e)
    sys.exit(1)
print("integrity checks: all passed")
