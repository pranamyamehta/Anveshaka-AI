# Anvesaka – Judge Demonstration Script & Walkthrough

**Project:** Anvesaka (Agentic AI Assistant for Data Center Incident Triage)  
**Institution:** Dept. of Computer Science & Engineering, BMSIT&M (2026)  
**Lead Integrator:** Member 4 (API, Contracts & Integration)

---

## 1. Executive Summary & Objective

In modern hyperscale data centers, hardware degradation (e.g., fan bearings, failing optics, thermal runaway) triggers **alert cascades** across monitoring tiers (Zabbix, Datadog, Prometheus). On-call SREs suffer from **alert fatigue** and delayed MTTR (Mean Time to Resolution).

**Anvesaka** automates the first 15 minutes of investigation:
1. **Intakes & Prioritizes:** Ingests telemetry into a strict priority queue ($\text{FATAL} > \text{CRITICAL} > \text{ERROR} > \text{WARNING} > \text{INFO}$).
2. **Gathers Deterministic Evidence:** Employs pure tools to correlate rack-level alerts, inspect CMDB baselines, and match symptom signatures against historical incident playbooks.
3. **Agentic Reasoning (Ollama / LangGraph):** Analyzes multi-modal telemetry and formulates a grounded diagnosis.
4. **Safety-Guaranteed Remediation:** Never hallucinates fixes; remediation steps are copied verbatim from the historical engineering playbook.
5. **Human-in-the-Loop Oversight:** Provides an operations console where engineers review and record audit decisions.

---

## 2. Quickstart Demo Setup (Under 2 Minutes)

To run the complete system from scratch on macOS / Linux:

### Step 1: Start the Backend API
```bash
PYTHONPATH=. .venv/bin/uvicorn anvesaka_AI.api.main:app --port 8000
```
* Swagger UI Docs: `http://localhost:8000/docs`
* API Health Check: `http://localhost:8000/health`

### Step 2: Start the Next.js Operations Console
```bash
cd frontend
pnpm dev
```
* Dashboard URL: `http://localhost:3000`

### Step 3: Run the Automated Judge Demo Script
In a new terminal window:
```bash
PYTHONPATH=. .venv/bin/python3 -m scripts.demo
```

---

## 3. The 3 Demo Walkthrough Scenarios

The demo highlights three distinct operational scenarios:

### Scenario 1: Known Incident Match (`ALT-1023`)
* **The Situation:** Node `srv-node-204` on `Rack-D09` fires a `CRITICAL` 24Gbps network saturation alert (`NetworkTxSaturationCritical`).
* **The Clue:** A naive engineer suspects a network card or cable failure.
* **Agent Investigation:**
  1. Calls `correlate_alerts`: Discovers `ALT-1020` (`Storage CRITICAL` Ceph OSD crash) occurred 88 minutes earlier on the same rack.
  2. Calls `node_context`: Discovers 25Gbps link baseline and adjacent storage roles.
  3. Calls `lookup_incidents`: Candidate score for `INC-5261` jumps from 83.3% to **100%**.
* **Outcome:** Matches `INC-5261` (Ceph backfill traffic following NVMe recovery). Correct playbook remediation steps displayed.

### Scenario 2: Novel Anomaly Escalation (`ALT-1033`)
* **The Situation:** An unprecedented environmental humidity spike with power loss on `Rack-E14`.
* **The Safety Feature:** The historical playbook contains no signature match.
* **Outcome:** Instead of guessing or hallucinating an incorrect repair, the agent outputs `ESCALATE_UNKNOWN` and alerts the on-call Lead SRE.

### Scenario 3: Telemetry Noise / Recovery Baseline (`ALT-1001`)
* **The Situation:** Routine hourly baseline log with normal thermal metrics.
* **Outcome:** Agent outputs `NO_ACTION` and suppresses alert fatigue.

---

## 4. Key Verification Metrics

* **Unit & Integration Tests:** 34 passing tests across API, Priority Queue, Evidence Tools, and Agent Graph (`pytest tests/`).
* **Referential Integrity:** 23/23 historical scenarios verified against MongoDB Atlas.
* **Deterministic Tools:** Zero hallucinated data, strict $t \le t_{\text{anchor}}$ look-ahead prevention.
