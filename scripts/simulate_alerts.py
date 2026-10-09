"""CLI runner for simulating alert streams.

Usage:
  # Stream alerts into memory queue:
  PYTHONPATH=. .venv/bin/python3 -m scripts.simulate_alerts --count 10 --interval 0.5

  # Emit a specific scenario:
  PYTHONPATH=. .venv/bin/python3 -m scripts.simulate_alerts --scenario SCN-001

  # Stream live alerts to running API server:
  PYTHONPATH=. .venv/bin/python3 -m scripts.simulate_alerts --target api --api-url http://localhost:8000
"""
from __future__ import annotations

import argparse
import sys
import time

try:
    import httpx
except ImportError:
    httpx = None

from anvesaka_AI.alerts.queue import AlertQueue
from anvesaka_AI.alerts.simulator import AlertSimulator
from anvesaka_AI.schemas import Alert


def _print_alert(alert: Alert, pos: int) -> None:
    sev_colors = {
        "FATAL": "\033[95m",
        "CRITICAL": "\033[91m",
        "ERROR": "\033[33m",
        "WARNING": "\033[93m",
        "INFO": "\033[94m",
    }
    color = sev_colors.get(alert.severity.value, "\033[0m")
    reset = "\033[0m"
    print(
        f"[{alert.timestamp.strftime('%H:%M:%S')}] "
        f"{color}[{alert.severity.value:8s}]{reset} "
        f"Alert: {alert.alert_id:<14s} "
        f"Node: {alert.node_id:<14s} "
        f"Rack: {alert.rack_id:<10s} "
        f"(Queue Depth: #{pos}) -> "
        f"{alert.raw_message[:45]}..."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulate alert streams for Project Anvesaka.")
    parser.add_argument("--count", type=int, default=15, help="Number of alerts to emit")
    parser.add_argument("--interval", type=float, default=0.5, help="Seconds between alerts")
    parser.add_argument("--scenario", type=str, default=None, help="Specific scenario ID (e.g. SCN-001)")
    parser.add_argument("--target", choices=["queue", "api"], default="queue", help="Simulation target")
    parser.add_argument("--api-url", type=str, default="http://localhost:8000", help="API URL for target=api")

    args = parser.parse_args()

    queue = AlertQueue()
    simulator = AlertSimulator(queue=queue)

    print("=" * 75)
    print("Anvesaka Alert Stream Simulator")
    print(f"Target: {args.target.upper()} | Interval: {args.interval}s | Max Alerts: {args.count}")
    print("=" * 75)

    if args.scenario:
        print(f"Injecting scenario cascade: {args.scenario}...\n")
        alerts = simulator.emit_scenario(args.scenario)
        for idx, a in enumerate(alerts, 1):
            _print_alert(a, idx)
        print(f"\nScenario '{args.scenario}' completed ({len(alerts)} alerts emitted).")
        return

    if args.target == "api":
        if httpx is None:
            print("ERROR: httpx is required for target=api. Run pip install httpx")
            sys.exit(1)
        alerts = simulator.load_alerts()[: args.count]
        print(f"Streaming {len(alerts)} alerts to {args.api_url}/alerts ...\n")
        with httpx.Client(base_url=args.api_url, timeout=5.0) as client:
            for idx, alert in enumerate(alerts, 1):
                try:
                    payload = alert.model_dump(mode="json")
                    client.post("/alerts", json=payload)
                    _print_alert(alert, idx)
                except Exception as exc:
                    print(f"Failed to post {alert.alert_id}: {exc}")
                time.sleep(args.interval)
        print("\nStreaming finished.")
        return

    # In-memory queue mode
    alerts = simulator.load_alerts()[: args.count]
    print(f"Enqueuing {len(alerts)} alerts chronologically into AlertQueue...\n")
    for alert in alerts:
        simulator.emit_alert(alert)
        _print_alert(alert, queue.size("queued"))
        time.sleep(args.interval)

    print("\n" + "=" * 75)
    print("Top 5 Highest Priority Alerts in Queue (after prioritization):")
    print("=" * 75)
    for a in queue.list_alerts(status="queued", limit=5):
        print(
            f"  Pos #{a['queue_position']}: [{a['severity']:8s}] {a['alert_id']:<14s} "
            f"({a['node_id']} / {a['rack_id']}) - {a['raw_message'][:40]}..."
        )
    print("=" * 75)


if __name__ == "__main__":
    main()
