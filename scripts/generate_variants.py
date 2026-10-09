"""Generates ~60 noisy variants (+/-10% sensor noise) for evaluation.

Owner: Member 1 (Data & MongoDB)
Produces realistic sensor variance to evaluate agent reasoning under uncertainty.
"""
from __future__ import annotations

import argparse
import copy
import json
import random
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from anvesaka_AI.db.mongo import get_alerts_collection, get_collection, ping_db
from anvesaka_AI.schemas import Alert, Decision, Metrics, Scenario

ROOT = Path(__file__).resolve().parents[1]
GENERATED_DIR = ROOT / "data" / "generated"


def _add_noise(val: float | None, pct: float = 0.10, is_int: bool = False, min_val: float = 0.0) -> float | None:
    """Apply uniform noise within [-pct, +pct] to a numerical metric."""
    if val is None:
        return None
    # Don't perturb 0 values (e.g. stalled fan RPM = 0)
    if val == 0:
        return 0 if is_int else 0.0
    factor = 1.0 + random.uniform(-pct, pct)
    new_val = max(min_val, val * factor)
    return int(round(new_val)) if is_int else round(new_val, 1)


def generate_variants(
    variants_per_incident: int = 4,
    seed: int = 42,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Generate noisy variants from the 15 historical incident scenarios."""
    random.seed(seed)
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Fetch alerts and scenarios from MongoDB Atlas or local files
    raw_alerts: dict[str, dict[str, Any]] = {}
    raw_scenarios: list[dict[str, Any]] = []

    if ping_db():
        alerts_coll = get_alerts_collection()
        scenarios_coll = get_collection("eval_scenarios")
        for doc in alerts_coll.find({}):
            doc.pop("_id", None)
            raw_alerts[doc["alert_id"]] = doc
        for doc in scenarios_coll.find({}):
            doc.pop("_id", None)
            raw_scenarios.append(doc)
    else:
        raw_file = ROOT / "data" / "raw" / "alerts.json"
        eval_file = ROOT / "data" / "eval" / "ground_truth.json"
        if raw_file.exists():
            with open(raw_file, "r", encoding="utf-8-sig") as f:
                for item in json.load(f):
                    raw_alerts[item["alert_id"]] = item
        if eval_file.exists():
            with open(eval_file, "r", encoding="utf-8-sig") as f:
                raw_scenarios = json.load(f)

    # Filter to only the 15 match_incident scenarios
    incident_scenarios = [s for s in raw_scenarios if s.get("outcome") == "match_incident"]

    generated_alerts: list[dict[str, Any]] = []
    generated_scenarios: list[dict[str, Any]] = []

    for sc in incident_scenarios:
        trig_id = sc["trigger_alert_id"]
        base_alert = raw_alerts.get(trig_id)
        if not base_alert:
            continue

        base_metrics = base_alert.get("metrics", {})
        base_ts = datetime.fromisoformat(str(base_alert["timestamp"]).replace("Z", "+00:00"))

        for v_idx in range(1, variants_per_incident + 1):
            var_alert_id = f"{trig_id}-v{v_idx}"
            var_scenario_id = f"{sc['scenario_id']}-v{v_idx}"

            # Perturb metrics by ±5% to ±12%
            noise_rate = random.uniform(0.05, 0.12)
            noisy_metrics = {
                "cpu_temp_c": _add_noise(base_metrics.get("cpu_temp_c"), noise_rate),
                "inlet_temp_c": _add_noise(base_metrics.get("inlet_temp_c"), noise_rate),
                "fan_rpm": _add_noise(base_metrics.get("fan_rpm"), noise_rate, is_int=True),
                "power_draw_w": _add_noise(base_metrics.get("power_draw_w"), noise_rate, is_int=True),
                "humidity_pct": _add_noise(base_metrics.get("humidity_pct"), noise_rate),
                "cpu_load_pct": _add_noise(base_metrics.get("cpu_load_pct"), noise_rate),
                "system_load_1m": _add_noise(base_metrics.get("system_load_1m"), noise_rate),
                "memory_usage_pct": _add_noise(base_metrics.get("memory_usage_pct"), noise_rate),
                "storage_capacity_pct": _add_noise(base_metrics.get("storage_capacity_pct"), noise_rate),
                "disk_iops": _add_noise(base_metrics.get("disk_iops"), noise_rate, is_int=True),
                "disk_read_errors": base_metrics.get("disk_read_errors"),
                "latency_ms": _add_noise(base_metrics.get("latency_ms"), noise_rate),
                "packet_drop_rate_pct": _add_noise(base_metrics.get("packet_drop_rate_pct"), noise_rate),
                "network_tx_mbps": _add_noise(base_metrics.get("network_tx_mbps"), noise_rate),
            }
            # Remove None keys
            noisy_metrics = {k: v for k, v in noisy_metrics.items() if v is not None}

            # Shift timestamp by a few minutes
            var_ts = base_ts + timedelta(minutes=random.randint(1, 15))

            var_alert = copy.deepcopy(base_alert)
            var_alert["alert_id"] = var_alert_id
            var_alert["timestamp"] = var_ts.isoformat()
            var_alert["metrics"] = noisy_metrics

            # Update raw message numbers to match perturbed telemetry
            msg = var_alert["raw_message"]
            if "cpu_temp_c" in noisy_metrics and "Temp=" in msg:
                msg = re.sub(r"Temp=\d+(\.\d+)?C", f"Temp={noisy_metrics['cpu_temp_c']}C", msg)
            if "fan_rpm" in noisy_metrics and "RPM=" in msg:
                msg = re.sub(r"RPM=\d+", f"RPM={noisy_metrics['fan_rpm']}", msg)
            var_alert["raw_message"] = msg

            generated_alerts.append(var_alert)

            # Build variant Scenario record
            var_sc = copy.deepcopy(sc)
            var_sc["scenario_id"] = var_scenario_id
            var_sc["trigger_alert_id"] = var_alert_id
            var_sc["title"] = f"{sc['title']} (Variant {v_idx})"
            var_sc["difficulty"] = "medium" if v_idx <= 2 else "hard"
            var_sc["split"] = "test"  # Always held-out test split
            var_sc["variant_of"] = sc["scenario_id"]
            generated_scenarios.append(var_sc)

    return generated_alerts, generated_scenarios


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate noisy variants for benchmark evaluation.")
    parser.add_argument("--count-per-incident", type=int, default=4, help="Variants per incident (default 4 -> 60 total)")
    parser.add_argument("--save-mongo", action="store_true", help="Also upsert generated variants to MongoDB Atlas")
    args = parser.parse_args()

    print(f"Generating {args.count_per_incident} noisy variants per incident scenario...")
    alerts, scenarios = generate_variants(variants_per_incident=args.count_per_incident)
    print(f"Generated {len(alerts)} noisy alerts and {len(scenarios)} evaluation scenarios.")

    # Save to data/generated/
    alerts_file = GENERATED_DIR / "noisy_alerts.json"
    scenarios_file = GENERATED_DIR / "noisy_scenarios.json"

    with open(alerts_file, "w", encoding="utf-8") as f:
        json.dump(alerts, f, indent=2)
    with open(scenarios_file, "w", encoding="utf-8") as f:
        json.dump(scenarios, f, indent=2)

    print(f"Saved to disk:")
    print(f"  - {alerts_file} ({len(alerts)} items)")
    print(f"  - {scenarios_file} ({len(scenarios)} items)")

    # Save to MongoDB Atlas if requested or if available
    if args.save_mongo and ping_db():
        print("Upserting variants into MongoDB Atlas...")
        alerts_coll = get_alerts_collection()
        scenarios_coll = get_collection("eval_scenarios")
        for a in alerts:
            doc = dict(a)
            doc["_id"] = a["alert_id"]
            alerts_coll.replace_one({"_id": doc["_id"]}, doc, upsert=True)
        for s in scenarios:
            doc = dict(s)
            doc["_id"] = s["scenario_id"]
            scenarios_coll.replace_one({"_id": doc["_id"]}, doc, upsert=True)
        print("Successfully uploaded all variants to MongoDB Atlas!")


if __name__ == "__main__":
    main()
