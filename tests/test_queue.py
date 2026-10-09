"""Unit tests for Member 1 Priority Queue and Simulator."""
from __future__ import annotations

import concurrent.futures
from datetime import datetime, timezone
import pytest

from anvesaka_AI.alerts.queue import AlertQueue
from anvesaka_AI.alerts.simulator import AlertSimulator
from anvesaka_AI.schemas import Alert, AnomalyType, Metrics, Severity


def _make_alert(alert_id: str, severity: Severity, minute: int) -> Alert:
    return Alert(
        alert_id=alert_id,
        timestamp=datetime(2026, 10, 4, 10, minute, tzinfo=timezone.utc),
        rack_id="Rack-A01",
        node_id="srv-node-101",
        anomaly_type=AnomalyType.COMPUTE,
        severity=severity,
        metrics=Metrics(),
        raw_message=f"Test alert {alert_id}",
    )


def test_priority_ordering() -> None:
    queue = AlertQueue()
    queue.push(_make_alert("ALT-INFO", Severity.INFO, 1))
    queue.push(_make_alert("ALT-WARN", Severity.WARNING, 2))
    queue.push(_make_alert("ALT-ERR", Severity.ERROR, 3))
    queue.push(_make_alert("ALT-CRIT", Severity.CRITICAL, 4))
    queue.push(_make_alert("ALT-FATAL", Severity.FATAL, 5))

    assert queue.size() == 5
    assert queue.pop().alert_id == "ALT-FATAL"
    assert queue.pop().alert_id == "ALT-CRIT"
    assert queue.pop().alert_id == "ALT-ERR"
    assert queue.pop().alert_id == "ALT-WARN"
    assert queue.pop().alert_id == "ALT-INFO"
    assert queue.is_empty()


def test_oldest_arrival_tie_breaker() -> None:
    queue = AlertQueue()
    queue.push(_make_alert("ALT-NEWER", Severity.CRITICAL, 30))
    queue.push(_make_alert("ALT-OLDER", Severity.CRITICAL, 10))

    first = queue.pop()
    assert first.alert_id == "ALT-OLDER"
    second = queue.pop()
    assert second.alert_id == "ALT-NEWER"


def test_idempotent_push_and_deduplication() -> None:
    queue = AlertQueue()
    alert = _make_alert("ALT-DUP", Severity.WARNING, 10)

    assert queue.push(alert) is True
    assert queue.size() == 1

    updated_alert = _make_alert("ALT-DUP", Severity.CRITICAL, 10)
    assert queue.push(updated_alert) is False
    assert queue.size() == 1

    peeked = queue.peek()
    assert peeked.severity == Severity.CRITICAL


def test_priority_boost() -> None:
    queue = AlertQueue()
    queue.push(_make_alert("ALT-NORMAL", Severity.CRITICAL, 10))
    queue.push(_make_alert("ALT-BOOSTED", Severity.ERROR, 10))

    assert queue.peek().alert_id == "ALT-NORMAL"

    queue.boost_priority("ALT-BOOSTED", boost=2)
    assert queue.peek().alert_id == "ALT-BOOSTED"


def test_status_transitions_and_list() -> None:
    queue = AlertQueue()
    queue.push(_make_alert("ALT-1", Severity.CRITICAL, 10))
    queue.push(_make_alert("ALT-2", Severity.ERROR, 11))

    queue.update_status("ALT-1", "analyzing")

    assert queue.size("queued") == 1
    assert queue.size("analyzing") == 1

    popped = queue.pop()
    assert popped.alert_id == "ALT-2"

    item = queue.get("ALT-1")
    assert item is not None
    assert item["queue_status"] == "analyzing"


def test_concurrent_push_pop_thread_safety() -> None:
    queue = AlertQueue()
    num_alerts = 100

    def _pusher(i: int) -> None:
        queue.push(_make_alert(f"ALT-C{i:03d}", Severity.WARNING, i % 60))

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        list(executor.map(_pusher, range(num_alerts)))

    assert queue.size() == num_alerts

    popped_count = 0
    while queue.pop() is not None:
        popped_count += 1

    assert popped_count == num_alerts
    assert queue.is_empty()


def test_simulator_basic() -> None:
    queue = AlertQueue()
    sim = AlertSimulator(queue=queue)
    alerts = sim.load_alerts()
    assert len(alerts) > 0

    sim.emit_alert(alerts[0])
    assert queue.size() == 1
    assert sim.emitted_count == 1
