"""Runs the agent on data/eval/ground_truth.json (held-out split) and writes results to eval/results/.

Owner: Member 2
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from datetime import datetime

from anvesaka_AI.agent.graph import run_triage
from anvesaka_AI.agent.nodes import ToolExecutor
from anvesaka_AI.config import settings
from anvesaka_AI.schemas import Alert, PlaybookEntry, Scenario, NodeInfo
from anvesaka_AI.signature_engine import correlate, node_context, rank_candidates, Ctx, parse_playbook
from eval.metrics import evaluate_result

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).parent.parent
DATA_DIR = ROOT_DIR / "data"
EVAL_RESULTS_DIR = ROOT_DIR / "eval" / "results"

def main() -> None:
    EVAL_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    
    # 1. Load Data
    logger.info("Loading data...")
    with open(DATA_DIR / "raw" / "alerts.json", "r", encoding="utf-8") as f:
        alerts_data = json.load(f)
        alerts_list = [Alert.model_validate(a) for a in alerts_data]
        alerts_by_id = {a.alert_id: a for a in alerts_list}
        alerts_raw_by_id = {a["alert_id"]: a for a in alerts_data}
        
    with open(DATA_DIR / "raw" / "playbook.json", "r", encoding="utf-8") as f:
        playbook_data = json.load(f)
        playbook_list = [parse_playbook(PlaybookEntry.model_validate(p)) for p in playbook_data]
        playbook_index = {p.incident_id: p for p in playbook_list}
        
    with open(DATA_DIR / "raw" / "cmdb_nodes.json", "r", encoding="utf-8") as f:
        nodes_data = json.load(f)
        nodes_index = {n["node_id"]: NodeInfo.model_validate(n) for n in nodes_data}
        
    with open(DATA_DIR / "eval" / "ground_truth.json", "r", encoding="utf-8") as f:
        scenarios_data = json.load(f)
        scenarios = [Scenario.model_validate(s) for s in scenarios_data]

    # Filter for test split
    test_scenarios = [s for s in scenarios if s.split == "test"]
    logger.info(f"Found {len(test_scenarios)} test scenarios.")

    # 2. Build ToolExecutor with real signature engine functions
    def correlate_fn(args):
        anchor = alerts_by_id[args.alert_id]
        return correlate(anchor, alerts_list, window_min=args.window_min)

    def node_context_fn(args):
        # We need the anchor alert. In practice, node_context tool requires node_id.
        # But wait, signature_engine's node_context signature:
        # def node_context(anchor: Alert, alerts: list[Alert], nodes: dict[str, NodeInfo]) -> NodeContext:
        # And the tool schema only takes "node_id". We have a slight mismatch.
        # Let's find an alert for that node_id to act as anchor, or just look up the node.
        # In this eval context, we can just use the trigger alert as anchor.
        # Since args only has node_id, we just pick the latest alert for that node or assume the trigger alert.
        # The schema doesn't pass alert_id to node_context. We'll find an alert for the node.
        node_alerts = [a for a in alerts_list if a.node_id == args.node_id]
        anchor = node_alerts[-1] if node_alerts else None
        if not anchor:
            raise ValueError(f"No alerts found for node_id {args.node_id}")
        return node_context(anchor, alerts_list, nodes_index)
        
    def lookup_fn(args):
        anchor = alerts_by_id[args.alert_id]
        # ctx requires corr and node to be populated if we want exact evaluation.
        # In a real environment, lookup_incidents might just evaluate what it can (returning None for missing context).
        # We'll just provide empty context, which matches the behavior of evaluating what we have.
        ctx = Ctx(anchor=anchor, corr=None, node=None)
        return rank_candidates(ctx, playbook_list, top_k=args.top_k)

    executor = ToolExecutor(
        correlate_fn=correlate_fn,
        node_context_fn=node_context_fn,
        lookup_fn=lookup_fn,
        playbook_index=playbook_index,
    )

    # 3. Run Evaluation
    records = []
    logger.info("Starting evaluation run...")
    for s in test_scenarios:
        if s.trigger_alert_id not in alerts_raw_by_id:
            logger.warning(f"Trigger alert {s.trigger_alert_id} not found for scenario {s.scenario_id}. Skipping.")
            continue
            
        alert_data = alerts_raw_by_id[s.trigger_alert_id]
        logger.info(f"Running scenario {s.scenario_id}: {s.title}")
        
        result = run_triage(alert_data, executor, playbook_index)
        record = evaluate_result(s, result, playbook_index, mode="agent", run_idx=0)
        records.append(record)
        
        logger.info(f"  Decision: {result.decision.value} (Expected: {s.outcome.value})")
        logger.info(f"  Correct: {record.correct}, Tools Correct: {record.tools_correct}, Faithful: {record.steps_faithful}")
        
    # 4. Save results
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = EVAL_RESULTS_DIR / f"eval_run_{timestamp}.json"
    
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump([r.model_dump(mode="json") for r in records], f, indent=2)
        
    logger.info(f"Evaluation complete. Results saved to {out_file}")
    
    # Print summary
    total = len(records)
    if total > 0:
        correct = sum(1 for r in records if r.correct)
        faithful = sum(1 for r in records if r.steps_faithful)
        tools = sum(1 for r in records if r.tools_correct)
        
        print("\n=== Evaluation Summary ===")
        print(f"Total Scenarios : {total}")
        print(f"Accuracy        : {correct}/{total} ({correct/total*100:.1f}%)")
        print(f"Steps Faithful  : {faithful}/{total} ({faithful/total*100:.1f}%)")
        print(f"Tools Correct   : {tools}/{total} ({tools/total*100:.1f}%)")
        print("==========================\n")

if __name__ == "__main__":
    main()
