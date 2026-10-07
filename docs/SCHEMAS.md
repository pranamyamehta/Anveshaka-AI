# Anvesaka – Data Schemas & Contracts

Single source of truth is `schemas.py`. This file explains the *why*. Everything here was checked against the real `alerts.json` (40 alerts) and `playbook.json` (15 incidents): `python validate_dataset.py` must pass before anyone merges a data change.

## 1. What you gave vs. what was added

| File | Origin | Contents |
|---|---|---|
| `alerts.json` | **yours** | 40 alerts, 20 nodes, 14 racks, 2026-10-03 → 10-04 |
| `playbook.json` | **yours** | 15 incidents with signature, root cause, remediation, resolution time |
| `cmdb_nodes.json` | added | 22 nodes: rack row/pos, role, U-position, PDU, baselines (memory, link speed, power cap, PSU) |
| `ground_truth.json` | added | 23 labelled scenarios for evaluation (agent must never read this) |
| `schemas.py` | added | Pydantic models, enums, LangGraph state, Mongo indexes |
| `signature_engine.py` | added | Reference code: signature parser, clause evaluator, `correlate`, `node_context`, ranking |
| `validate_dataset.py` | added | Integrity checks + deterministic rule-based baseline |

## 2. Things the data told us (and shaped the design)

1. **The playbook *is* the historical-incident store.** The synopsis mentions a separate "past incident log". Your playbook already contains symptom signature + root cause + fix + resolution time, so there is **no separate incidents collection**. `lookup_incidents` queries `playbook`.
2. **Signatures are mostly machine-checkable; 9 of 91 clauses are not.** Clauses like `fan_rpm < 2000` parse directly. But 9 need other evidence, for example *"Storage CRITICAL alert in same rack within the previous 120 min"* or *"MemTotal lower than CMDB baseline"*. They fall into 6 types (see `ClauseContext`): 5 are mapped to a tool, and `rack_wide` is read straight from `raw_message`. **This is the reason for tool-calling in this project:** the agent has to go and fetch evidence to verify them.
3. **Severity is normalised.** `severity` is one of INFO < WARNING < ERROR < CRITICAL < FATAL, but raw messages use source words. Zabbix: Information=INFO, Warning=WARNING, **Average=ERROR, High=CRITICAL, Disaster=FATAL**.
4. **Alerts include noise on purpose** (7 INFO alerts, 2 of them recovery messages, plus 1 humidity warning that has no playbook entry). Good: alert fatigue is the project's thesis, so the agent must be tested on *not* escalating.
5. **Playbook entries reference each other** (INC-5261 → INC-5156, INC-5014 → INC-4968). Captured as `related_incident_ids`.
6. **The alerts were clearly written to satisfy the signatures**, so a plain rule engine scores 23/23 on them (`validate_dataset.py`). With ±5% sensor noise it falls to ~85%, with ±10% to ~74%. See §7: you need noisy variants or the agent can't demonstrate value.

## 3. Mongo collections (`db = anvesaka`)

| Collection | `_id` | Source | Notes |
|---|---|---|---|
| `alerts` | `alert_id` | alerts.json | + derived `source`, `is_recovery`. Indexes: (rack_id, timestamp↓), (node_id, timestamp↓), (anomaly_type, severity) |
| `playbook` | `incident_id` | playbook.json | + derived `remediation_steps[]`, `signature_clauses[]`, `related_incident_ids[]`. Text index on root cause + remediation |
| `nodes` | `node_id` | cmdb_nodes.json | `inferred_fields` lists values that were **assumed**, not stated in alert text |
| `triage_runs` | `run_id` | API | Audit log of every `/triage` response |
| `eval_runs` | `eval_id` | evaluation | Agent, rule-based and **manual** rows share one shape |

`ground_truth.json` stays a file. Do not load it where the agent has a tool that can read it.

## 4. Tool contracts

Four tools. The synopsis needs ≥3; the 4th exists because of finding #2.

| Tool | Input | Output | Verifies clause type |
|---|---|---|---|
| `correlate_alerts` | `alert_id, window_min=360` | `CorrelationResult`: related alerts (oldest first, with `minutes_before` and `relation`), affected nodes/racks, categories, `escalating` | correlation, cross_domain |
| `get_node_context` | `node_id` | `NodeContext`: CMDB record, prior alerts, median metrics, neighbour inlet temps | node_history, cmdb, neighbors |
| `lookup_incidents` | `alert_id, top_k=3` | `PlaybookMatch[]` ranked by fewest violated then most satisfied; each lists **satisfied / violated / unverified** clauses and `needs_tools` | – |
| `recommend_action` | (final LLM call) | `Recommendation`: `decision`, `incident_id`, `root_cause`, `evidence[]` | – |

Rules baked into `correlate_alerts`:
- **No look-ahead.** Only alerts with `timestamp ≤ anchor`. Otherwise the agent "sees" the RESOLVED alert from the future and the evaluation is invalid.
- Skips INFO and recovery alerts. Scope = same node, same rack, or **adjacent rack** (same row, |position diff| ≤ 1, e.g. C03↔C04).
- Window default is 360 min because the fan-failure story spans ~220 min.

**The `unverified` list is what drives the agent loop.** Example, `ALT-1023` (network saturation on Rack-D09):

| Step | Top candidate | Score | Violated | Unverified |
|---|---|---|---|---|
| after `lookup_incidents` only | INC-5261 | 0.833 | 0 | 1 → needs `correlate_alerts` |
| after `correlate_alerts` | INC-5261 | **1.000** | 0 | 0 |

`correlate_alerts` returned ALT-1020 (Storage CRITICAL, same rack, 88 min earlier), which satisfies the cross-domain clause. The alert *looks* like a network fault (a competing candidate is INC-5232, bad optic), but the root cause is Ceph backfill after an NVMe failure.

**Design rule: the LLM never writes remediation steps.** It picks `incident_id` and writes a short grounded `root_cause`. Code copies `remediation_steps` from the playbook and fills `<node>` placeholders. Result: steps cannot be hallucinated, and we can measure `steps_faithful`.

## 5. API: `POST /triage`

Request: `{ "alert_id": "ALT-1023" }` (or an inline `alert`), optional `max_steps` (default 6), `notify`.

```json
{
  "run_id": "9f3c1a77d2e0",
  "alert_id": "ALT-1023",
  "status": "ok",
  "decision": "match_incident",
  "matched_incident_id": "INC-5261",
  "root_cause": "Network saturation on srv-node-204 is Ceph backfill traffic following the NVMe/OSD failure on srv-node-203 in the same rack, not a network fault.",
  "recommended_steps": ["<step 1 of INC-5261, node filled in>", "..."],
  "estimated_resolution_mins": 44,
  "priority": "P2",
  "escalate": false,
  "confidence": 1.0,
  "correlated_alert_ids": ["ALT-1019", "ALT-1020", "ALT-1022"],
  "evidence": ["ALT-1020 Storage CRITICAL on Rack-D09 88 min earlier", "tx 24630 Mbps = 98.5% of 25G link", "message: ceph backfill traffic detected"],
  "tool_trace": [
    {"step": 1, "tool": "lookup_incidents",  "summary": "top=INC-5261 score=0.83, 1 unverified", "duration_ms": 12},
    {"step": 2, "tool": "correlate_alerts",  "summary": "3 related, Storage+Network, escalating", "duration_ms": 9},
    {"step": 3, "tool": "recommend_action",  "summary": "match INC-5261", "duration_ms": 4100}
  ],
  "model": "qwen2.5:7b", "latency_s": 4.6, "notifications_sent": []
}
```

- `confidence` is **computed**, not self-reported by the LLM (small models are badly calibrated): top matcher score × (1.0 if the LLM agrees with matcher #1, else 0.6); 0 if no match.
- `priority`: P1 = FATAL or ≥2 racks affected; P2 = CRITICAL; P3 = ERROR/WARNING; P4 = INFO.
- `escalate` = true for `escalate_unknown`, FATAL, or P1.
- `status = "fallback_used"` when the model failed to call a needed tool and the graph forced it (`ToolCall.forced = true`).

## 6. LangGraph state

`ingest → llm_decide → tool_node → (loop ≤ max_steps) → finalize → notify`. See `AgentState` in `schemas.py`. Fallback rule: if the model picks no tool while the top candidate still has `unverified` clauses, force the tools in `needs_tools`. Inside the loop, the lookup result tells the model exactly what to verify, which makes small local models far more reliable than open-ended "which tool?" prompting.

## 7. Evaluation design

**23 scenarios** (`ground_truth.json`): 15 incident (one per playbook entry), 1 novel (humidity: correct answer is *escalate_unknown*), 7 noise (INFO / recovery: correct answer is *no_action*). Split: 7 dev (used for prompt tuning) / 16 test (held out). Every category has ≥1 dev example. Difficulty: 15 easy, 4 medium (need a context tool), 4 hard (cross-domain, progression, confusable).

Three arms, same `EvalRecord` shape:

| Arm | Who | Purpose |
|---|---|---|
| `manual` | 2 teammates, stopwatch | Synopsis Objective 6 baseline: time and agreement |
| `rule_based` | `validate_dataset.py` logic | Shows what the LLM adds beyond deterministic matching |
| `agent` | Anvesaka × 3 runs/scenario | Accuracy, tools-correct, latency, repeat-run consistency |

Metrics: decision accuracy, incident accuracy, `tools_correct` (expected tools ⊆ called), `mention_hits` (keywords in root cause), `steps_faithful`, latency, and consistency (agreement across the 3 runs vs. between the 2 humans).

> **The gap to close:** the rule engine already gets 23/23 on the clean data, so on this data alone the agent can at best tie it. To make the comparison meaningful, **generate noisy variants** of the 15 incident triggers: jitter metrics ±5–10 %, drop one metric, and reword `raw_message`. Give them IDs like `ALT-1007-v3`, `variant_of = "SC-04"`, and keep ground-truth labels (check the label is still defensible at ±10 %). Aim for ~60 variants in `test`. That is the revised Member B task.

## 8. Changes to the 7-day plan

- **B:** replace "generate 1,000 alerts" with *ingest script* (load JSON → models → derived fields → indexes) + *variant generator* (§7). The ingest must call `parse_playbook()` and fail loudly on an unparseable clause.
- **A:** the tool nodes are thin wrappers over `signature_engine.py`. Spend the time on the loop, the fallback, and the trace.
- **C:** the LLM prompt is now smaller: choose among ≤3 ranked candidates and explain. Prompt/model comparison is the interesting experiment (e.g. 3B vs 7B).
- **D:** manual-baseline sheet = `EvalRecord(mode="manual")` rows for the 16 test scenarios.
- Contract change from the earlier plan: `Incident` → `PlaybookEntry`; `Alert` now has `rack_id`, `node_id`, `anomaly_type`, `metrics{}`, `raw_message`; `lookup_similar_incidents` → `lookup_incidents`; added `get_node_context`.

## 9. Assumptions to confirm as a team

- 42U racks; U36+ counts as "top-of-rack" (used for INC-4911).
- All nodes have 25 Gbps links (stated in text for srv-node-204 and 540, assumed for the rest).
- `Rack-S*` and `Rack-D09` are storage racks, others compute.
- Neighbour nodes srv-node-26 and srv-node-28 were added to the CMDB because ALT-1018's text names them.
- "7-day median" is approximated by the median of the node's earlier alerts (the data spans only 2 days).
- The 17 alerts that are not scenario triggers (earlier stages of the same stories, e.g. ALT-1004 fan below 6000 RPM) are used as correlation context only. Triaging them standalone ("early warning") is a possible stretch test, but the correct answer is arguable, so no label was invented.
