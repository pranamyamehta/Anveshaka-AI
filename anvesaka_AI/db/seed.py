"""Load alerts, playbook, and CMDB nodes into MongoDB with idempotent upserts.

Owner: Member 1 (Data & MongoDB)
Safe to re-run multiple times without creating duplicate records.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from anvesaka_AI.db.mongo import get_db, ping_db
from anvesaka_AI.schemas import Alert, NodeInfo, PlaybookEntry, create_indexes
from anvesaka_AI.signature_engine import parse_playbook

ROOT = Path(__file__).resolve().parents[2]
RAW_DATA_DIR = ROOT / "data" / "raw"


def _read_json(file_path: Path) -> list[dict[str, Any]]:
    """Read and parse a JSON file."""
    with open(file_path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def seed_database(
    data_dir: Optional[Path] = None,
    drop_first: bool = False,
) -> dict[str, int]:
    """Seed MongoDB collections with data/raw documents idempotently."""
    source_dir = Path(data_dir) if data_dir else RAW_DATA_DIR
    alerts_path = source_dir / "alerts.json"
    playbook_path = source_dir / "playbook.json"
    nodes_path = source_dir / "cmdb_nodes.json"

    if not alerts_path.exists():
        raise FileNotFoundError(f"Alerts file missing: {alerts_path}")
    if not playbook_path.exists():
        raise FileNotFoundError(f"Playbook file missing: {playbook_path}")
    if not nodes_path.exists():
        raise FileNotFoundError(f"CMDB nodes file missing: {nodes_path}")

    db = get_db()

    if drop_first:
        db["alerts"].drop()
        db["playbook"].drop()
        db["nodes"].drop()

    # 1. Seed Alerts (upsert by alert_id)
    raw_alerts = _read_json(alerts_path)
    alerts_coll = db["alerts"]
    alert_count = 0
    for raw in raw_alerts:
        alert = Alert(**raw)
        doc = alert.model_dump()
        doc["_id"] = alert.alert_id
        alerts_coll.replace_one({"_id": alert.alert_id}, doc, upsert=True)
        alert_count += 1

    # 2. Seed Playbook (upsert by incident_id)
    raw_playbook = _read_json(playbook_path)
    playbook_coll = db["playbook"]
    playbook_count = 0
    for raw in raw_playbook:
        parsed_entry = parse_playbook(PlaybookEntry(**raw))
        doc = parsed_entry.model_dump()
        doc["_id"] = parsed_entry.incident_id
        playbook_coll.replace_one({"_id": parsed_entry.incident_id}, doc, upsert=True)
        playbook_count += 1

    # 3. Seed CMDB Nodes (upsert by node_id)
    raw_nodes = _read_json(nodes_path)
    nodes_coll = db["nodes"]
    node_count = 0
    for raw in raw_nodes:
        node = NodeInfo(**raw)
        doc = node.model_dump()
        doc["_id"] = node.node_id
        nodes_coll.replace_one({"_id": node.node_id}, doc, upsert=True)
        node_count += 1

    # 4. Seed Ground Truth Scenarios
    eval_path = ROOT / "data" / "eval" / "ground_truth.json"
    scenario_count = 0
    if eval_path.exists():
        raw_scenarios = _read_json(eval_path)
        scenarios_coll = db["eval_scenarios"]
        for raw in raw_scenarios:
            doc = dict(raw)
            doc["_id"] = raw.get("scenario_id")
            scenarios_coll.replace_one({"_id": doc["_id"]}, doc, upsert=True)
            scenario_count += 1

    # 5. Create compound & text indexes
    create_indexes(db)

    return {
        "alerts": alert_count,
        "playbook": playbook_count,
        "nodes": node_count,
        "scenarios": scenario_count,
    }

