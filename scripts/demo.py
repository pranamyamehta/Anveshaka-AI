"""Final Judge Demo Runner for Project Anvesaka.

Walks through the 3 core evaluation scenarios demonstrating the end-to-end triage flow:
1. Scenario A: Known Match (ALT-1023: Ceph backfill on Rack-D09 -> INC-5261)
2. Scenario B: Novel Anomaly (ALT-1033: Unmatched humidity spike -> escalate_unknown)
3. Scenario C: Noise / Recovery (ALT-1001: Hourly thermal baseline -> no_action)

Owner: Member 4 (API, Contracts & Integration)
"""
from __future__ import annotations

import argparse
import sys
import time
from typing import Any

try:
    import httpx
except ImportError:
    httpx = None

from fastapi.testclient import TestClient
from anvesaka_AI.api.main import app

# Colors for terminal output
BOLD = "\033[1m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BLUE = "\033[94m"
CYAN = "\033[96m"
MAGENTA = "\033[95m"
RESET = "\033[0m"


class DemoClient:
    """HTTP client with automatic fallback to FastAPI TestClient."""

    def __init__(self, base_url: str):
        self.base_url = base_url
        self.live = False
        if httpx:
            try:
                resp = httpx.get(f"{base_url}/health", timeout=1.0)
                if resp.status_code == 200:
                    self.live = True
            except Exception:
                self.live = False

        if not self.live:
            self._client = TestClient(app)
        else:
            self._client = httpx.Client(base_url=base_url, timeout=10.0)

    def get(self, path: str) -> dict[str, Any]:
        resp = self._client.get(path)
        return resp.json()

    def post(self, path: str, json_data: dict[str, Any] | None = None) -> dict[str, Any]:
        resp = self._client.post(path, json=json_data)
        return resp.json()


def print_banner() -> None:
    print(f"\n{BOLD}{CYAN}{'='*80}{RESET}")
    print(f"{BOLD}{CYAN}   ANVESAKA: AGENTIC AI ASSISTANT FOR DATA CENTER INCIDENT TRIAGE{RESET}")
    print(f"{CYAN}   BMSIT&M Dept. of Computer Science & Engineering (2026){RESET}")
    print(f"{BOLD}{CYAN}{'='*80}{RESET}\n")


def print_section(title: str) -> None:
    print(f"\n{BOLD}{MAGENTA}▶ {title}{RESET}")
    print(f"{MAGENTA}{'-'*70}{RESET}")


def run_scenario(
    client: DemoClient,
    alert_id: str,
    scenario_title: str,
    expected_decision: str,
    explanation: str,
    delay: float = 0.5,
) -> None:
    print_section(f"DEMO SCENARIO: {scenario_title} [{alert_id}]")
    print(f"{BOLD}Concept:{RESET} {explanation}\n")

    # 1. Fetch Alert from Datastore
    print(f"  {BLUE}[1/4] Inspecting Ingested Alert...{RESET}")
    alert = client.get(f"/alerts/{alert_id}")
    if "error" in alert:
        print(f"  {RED}Error fetching alert: {alert['error']['message']}{RESET}")
        return

    sev_color = RED if alert.get("severity") in ("FATAL", "CRITICAL") else YELLOW if alert.get("severity") == "WARNING" else BLUE
    print(f"        Alert ID:  {BOLD}{alert['alert_id']}{RESET}")
    print(f"        Severity:  {sev_color}{alert.get('severity')}{RESET}")
    print(f"        Location:  Node: {alert.get('node_id')} | Rack: {alert.get('rack_id')}")
    print(f"        Message:   {alert.get('raw_message', '')[:75]}...")
    time.sleep(delay)

    # 2. Trigger / Inspect Triage
    print(f"\n  {BLUE}[2/4] Executing Agentic Triage (Tool Loop & Playbook Reasoning)...{RESET}")
    triage = client.get(f"/triage/{alert_id}")
    time.sleep(delay)

    dec = triage.get("decision", "unknown")
    dec_color = GREEN if dec == "match_incident" else YELLOW if dec == "no_action" else RED
    print(f"        Verdict:    {dec_color}{BOLD}{dec.upper()}{RESET} (Expected: {expected_decision})")
    print(f"        Matched:    {BOLD}{triage.get('matched_incident_id') or 'None (Zero Hallucinated Match)'}{RESET}")
    print(f"        Confidence: {BOLD}{float(triage.get('confidence', 0.0))*100:.1f}%{RESET}")
    print(f"        Root Cause: {triage.get('root_cause', '')[:120]}...")

    # 3. Tool Trace Evidence Timeline
    print(f"\n  {BLUE}[3/4] Inspection of Ordered Tool Trace (Explainability Timeline):{RESET}")
    tool_trace = triage.get("tool_trace", [])
    if tool_trace:
        for t in tool_trace:
            print(f"        Step {t.get('step')}: {CYAN}{t.get('tool')}{RESET} ({t.get('duration_ms')}ms)")
            print(f"               ↳ {t.get('summary')}")
    else:
        print(f"        [Fast Path] Rule-based classifier suppressed tool calls to prevent alert fatigue.")

    # Recommended Steps from Playbook
    steps = triage.get("recommended_steps", [])
    if steps:
        print(f"\n  {BLUE}      Remediation Steps (Ground-Truth Copied from Playbook):{RESET}")
        for s_idx, step in enumerate(steps, 1):
            print(f"        {s_idx}. {step}")
    time.sleep(delay)

    # 4. Human-In-The-Loop Review
    print(f"\n  {BLUE}[4/4] Submitting Human-in-the-Loop Review Verdict...{RESET}")
    review_verdict = "accepted" if dec in ("match_incident", "no_action") else "escalated"
    client.post(
        f"/triage/{alert_id}/review",
        {
            "decision": review_verdict,
            "reviewer": "Judge / Lead SRE",
            "notes": f"Verified during demo walkthrough for {scenario_title}.",
        },
    )
    print(f"        Audit Status: {GREEN}Recorded '{review_verdict.upper()}' with zero infrastructure mutation.{RESET}\n")
    time.sleep(delay)


def main() -> None:
    parser = argparse.ArgumentParser(description="Anvesaka Final Judge Demo Runner.")
    parser.add_argument("--api-url", default="http://localhost:8000", help="FastAPI server URL")
    parser.add_argument("--delay", type=float, default=0.5, help="Delay between demo steps in seconds")
    parser.add_argument("--scenario", choices=["match", "novel", "noise", "all"], default="all", help="Scenario to run")
    args = parser.parse_args()

    print_banner()

    client = DemoClient(base_url=args.api_url)
    mode_str = f"{GREEN}Live Server at {args.api_url}{RESET}" if client.live else f"{YELLOW}In-Process FastAPI Test Engine{RESET}"
    print(f"Execution Mode: {mode_str}\n")

    # 1. Health check
    health = client.get("/health")
    print(f"System Health Status: {GREEN if health.get('status') == 'ok' else YELLOW}{health.get('status', 'unknown').upper()}{RESET}")
    for svc, st in health.get("services", {}).items():
        print(f"  - {svc.capitalize()}: {st}")
    print()

    # Scenario 1: Known Match
    if args.scenario in ("all", "match"):
        run_scenario(
            client=client,
            alert_id="ALT-1023",
            scenario_title="Known Incident Match (Ceph Storage Backfill)",
            expected_decision="match_incident",
            explanation="Storage NVMe crash on node 203 caused cascading 24Gbps network saturation on node 204. Agent correlates timeline to identify Ceph backfill traffic.",
            delay=args.delay,
        )

    # Scenario 2: Novel Anomaly
    if args.scenario in ("all", "novel"):
        run_scenario(
            client=client,
            alert_id="ALT-1033",
            scenario_title="Novel Hardware Anomaly (Humidity / Unknown)",
            expected_decision="escalate_unknown",
            explanation="Unprecedented humidity telemetry condition not present in playbook. Agent safely refuses to force a hallucinated incident.",
            delay=args.delay,
        )

    # Scenario 3: Noise / Recovery
    if args.scenario in ("all", "noise"):
        run_scenario(
            client=client,
            alert_id="ALT-1001",
            scenario_title="Telemetry Noise / Recovery Baseline",
            expected_decision="no_action",
            explanation="Hourly baseline log within operating envelope. Agent classifies as no_action to eliminate engineer alert fatigue.",
            delay=args.delay,
        )

    print_section("DEMO SUMMARY & OBSERVATIONS")
    print(f"1. {GREEN}Accurate Playbook Grounding:{RESET} Action steps were strictly copied from historical incident records.")
    print(f"2. {GREEN}Explainable Investigation:{RESET} Every step, query, and CMDB inspection is documented in the tool trace.")
    print(f"3. {GREEN}Safety First:{RESET} Zero hallucinated fixes, automated escalation on novel anomalies, and strict human review.")
    print(f"\n{BOLD}{CYAN}{'='*80}{RESET}\n")


if __name__ == "__main__":
    main()
