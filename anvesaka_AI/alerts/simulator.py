"""Alert simulator service for replaying alerts into the queue or API stream.

Supports:
- Chronological alert replay
- Scenario burst injections
- Live event streaming callbacks

Owner: B (Member 1)
"""
from __future__ import annotations

import json
from pathlib import Path
import threading
import time
from typing import Any, Callable, Optional

from anvesaka_AI.alerts.queue import AlertQueue
from anvesaka_AI.db.mongo import get_alerts_collection, get_collection, ping_db
from anvesaka_AI.schemas import Alert

ROOT = Path(__file__).resolve().parents[2]


class AlertSimulator:
    """Simulates real-time incoming alerts from data center infrastructure."""

    def __init__(
        self,
        queue: Optional[AlertQueue] = None,
        on_alert_callback: Optional[Callable[[Alert], None]] = None,
    ) -> None:
        self.queue = queue or AlertQueue()
        self.on_alert_callback = on_alert_callback
        self._is_running = False
        self._is_paused = False
        self._thread: Optional[threading.Thread] = None
        self._emitted_count = 0
        self._alerts_cache: list[Alert] = []

    def load_alerts(self) -> list[Alert]:
        """Load alerts from MongoDB Atlas or local JSON."""
        if self._alerts_cache:
            return self._alerts_cache

        alerts: list[Alert] = []
        if ping_db():
            coll = get_alerts_collection()
            alerts = [Alert.model_validate(d) for d in coll.find({})]
        else:
            raw_path = ROOT / "data" / "raw" / "alerts.json"
            if raw_path.exists():
                with open(raw_path, "r", encoding="utf-8-sig") as f:
                    alerts = [Alert.model_validate(d) for d in json.load(f)]

        # Chronological order by timestamp
        alerts.sort(key=lambda a: a.timestamp)
        self._alerts_cache = alerts
        return alerts

    def emit_alert(self, alert: Alert) -> None:
        """Emit a single alert to the queue and optional callback."""
        self.queue.push(alert)
        self._emitted_count += 1
        if self.on_alert_callback:
            self.on_alert_callback(alert)

    def emit_scenario(self, scenario_id: str) -> list[Alert]:
        """Emit all alerts associated with a specific incident scenario."""
        all_alerts = {a.alert_id: a for a in self.load_alerts()}
        emitted: list[Alert] = []

        scenarios: list[dict[str, Any]] = []
        if ping_db():
            scenarios = list(get_collection("eval_scenarios").find({"scenario_id": scenario_id}))
        if not scenarios:
            eval_path = ROOT / "data" / "eval" / "ground_truth.json"
            if eval_path.exists():
                with open(eval_path, "r", encoding="utf-8-sig") as f:
                    scenarios = [s for s in json.load(f) if s.get("scenario_id") == scenario_id]

        if not scenarios:
            raise KeyError(f"Scenario '{scenario_id}' not found")

        sc = scenarios[0]
        target_ids = [sc["trigger_alert_id"]] + sc.get("expected_related_alert_ids", [])
        for aid in target_ids:
            if aid in all_alerts:
                alert = all_alerts[aid]
                self.emit_alert(alert)
                emitted.append(alert)

        return emitted

    def start(self, interval_sec: float = 1.0, limit: Optional[int] = None) -> None:
        """Start streaming alerts in a background thread."""
        if self._is_running:
            return

        self._is_running = True
        self._is_paused = False

        def _worker() -> None:
            alerts = self.load_alerts()
            count = 0
            for alert in alerts:
                if not self._is_running:
                    break
                while self._is_paused and self._is_running:
                    time.sleep(0.1)

                self.emit_alert(alert)
                count += 1
                if limit and count >= limit:
                    break
                time.sleep(interval_sec)

            self._is_running = False

        self._thread = threading.Thread(target=_worker, daemon=True)
        self._thread.start()

    def pause(self) -> None:
        """Pause playback."""
        self._is_paused = True

    def resume(self) -> None:
        """Resume playback."""
        self._is_paused = False

    def stop(self) -> None:
        """Stop playback."""
        self._is_running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def is_paused(self) -> bool:
        return self._is_paused

    @property
    def emitted_count(self) -> int:
        return self._emitted_count
