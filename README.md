# Anvesaka: Agentic AI Assistant for Data Center Incident Triage

> **Read this file first.** It tells you what this project is, how it is laid out, what is already decided, and the rules to follow when writing code here.

Anvesaka (Sanskrit अन्वेषक, "investigator") is a mini project for the Dept. of CSE, BMSIT&M (2026). It is a **lightweight agent that receives a data center alert and investigates it the way an on-call engineer would**: it correlates related alerts, checks node context, matches the evidence against a playbook of past incidents, and recommends a remediation. It is exposed through a FastAPI REST endpoint.

The system features a **FastAPI backend** paired with an interactive **Next.js operations console frontend** (`frontend/`) and real-time Server-Sent Events (SSE). Swagger UI (`/docs`), CLI demo scripts, and the operations dashboard serve as the demo surfaces.

---

## 1. Goals and Architecture

**Goals**
- A LangGraph agent that chooses among at least 3 tools (we have 4) and loops until it has enough evidence.
- A local open-source LLM via Ollama does the reasoning step.
- MongoDB Atlas stores alerts, the playbook, and CMDB node metadata.
- Priority Queue service enforcing FATAL > CRITICAL > ERROR > WARNING > INFO intake.
- Interactive Next.js triage console with real-time SSE event updates.
- `POST /triage` returns root cause, recommended action, confidence and the **tool trace**.
- An evaluation comparing the agent against a manual baseline and a rule-only baseline (accuracy, time, consistency).

**Non-goals (Safety Boundaries)**
- No automatic execution of remediation commands changing physical infrastructure.
- No cloud LLM APIs. The LLM must run locally through Ollama.
- No real monitoring integration. All alerts are simulated from realistic telemetry.

---

## 2. Tech stack

| Layer | Choice |
|---|---|
| Language | Python 3.11+ |
| Agent orchestration | LangGraph (custom `StateGraph`, not the prebuilt ReAct agent) |
| LLM | Ollama, default `qwen2.5:7b` (use `qwen2.5:3b` or `llama3.2:3b` on low-RAM laptops) |
| Database | MongoDB 7 (Docker Compose) |
| API | FastAPI + Uvicorn |
| Models and validation | Pydantic v2 |
| Notifications | Slack incoming webhook (email is optional) |
| Tests | pytest |

---

## 3. How the agent works

```
POST /triage {alert_id}
        |
        v
   [ingest]  load the alert, build initial AgentState
        |
        v
 +-->[decide_tool]  LLM picks the next tool, or "finish"
 |      |
 |      v
 |   [run_tool]     executes correlate_alerts / get_node_context / lookup_similar_incidents
 |      |           and appends the result to state.evidence and state.tool_trace
 +------+  (loop, max MAX_AGENT_STEPS = 4)
        |
        v
  [finalize]  recommend_action: LLM picks the playbook incident and explains why
        |
        v
  [notify]    optional Slack message, then return TriageResponse
```

### The four tools

| Tool | Purpose | Owner |
|---|---|---|
| `correlate_alerts` | Find alerts related to the trigger alert (same rack, host or neighbours, within a time window) | B |
| `get_node_context` | CMDB baselines, rack position, neighbour nodes. Needed because some playbook clauses cannot be checked from the alert alone | B |
| `lookup_similar_incidents` | Match the evidence against the playbook signatures and return ranked candidates | B |
| `recommend_action` | The LLM chooses the incident and explains why; steps come from the playbook | C |

Tool functions are plain, deterministic Python functions with typed inputs and outputs from `schemas.py`. They have **no LLM calls inside them**, except `recommend_action`, which is the designated reasoning step.

---

## 4. Data (already built)

All data was designed around two files the team supplied (`alerts.json`, `playbook.json`). The rest was derived from them.

| File | Contents |
|---|---|
| `data/raw/alerts.json` | 40 simulated alerts (temperature, CPU, disk, performance, etc.) |
| `data/raw/playbook.json` | 15 incidents. **This is the historical incident log**: symptoms, signature clauses, root cause, fix steps, resolution time |
| `data/raw/cmdb_nodes.json` | 22 nodes with rack position, role, memory and link baselines, power cap, PSU rating. Fields not stated in the alert text are listed in each node's `inferred_fields` |
| `data/eval/ground_truth.json` | 23 labelled scenarios: 15 matching a playbook incident, 1 novel case (humidity alert, no playbook entry), 7 noise or recovery alerts that must **not** be escalated. Split: 7 for prompt tuning, 16 held out for evaluation |
| `data/generated/` | Output of `scripts/generate_variants.py` (about 60 noisy variants). Empty until generated |
| `docs/SCHEMAS.md` | Human-readable explanation of every schema. **Read before changing data structures** |

### Key design decisions (do not undo these without asking)

1. **The playbook is the incident history.** There is no separate incident collection.
2. **The LLM never writes remediation steps.** It selects an incident and gives a rationale. The fix steps are copied verbatim from the playbook entry, so they cannot be hallucinated.
3. **91 signature clauses exist across the playbook; 9 cannot be verified from the alert alone** (for example "Storage CRITICAL alert in the same rack within the previous 120 min"). Verifying these is exactly what the tool calls are for.
4. **The rule-based engine is a baseline, not the product.** `signature_engine.py` scores 23/23 on the clean data, because the alerts were written to satisfy the signatures. With about ±10% noise on sensor values it drops to roughly 74%. The agent must be evaluated on the **noisy variants**, otherwise it can only tie the rules.
5. **Novel and noise cases must be handled.** The agent should say "no matching playbook incident" or "no action needed" rather than force a match.

---

## 5. Repository structure

```
anvesaka/
├── README.md                    <- you are here
├── requirements.txt
├── docker-compose.yml           MongoDB service
├── .env.example                 copy to .env
├── .gitignore
│
├── docs/
│   └── SCHEMAS.md               schema documentation (provided)
│
├── data/
│   ├── raw/
│   │   ├── alerts.json          40 alerts (provided)
│   │   ├── playbook.json        15 incidents (provided)
│   │   └── cmdb_nodes.json      22 nodes (provided)
│   ├── eval/
│   │   └── ground_truth.json    23 labelled scenarios (provided)
│   └── generated/               noisy variants (created by script)
│
├── anvesaka/                    <- the Python package (run everything from repo root)
│   ├── config.py                settings from .env                         [D]
│   ├── schemas.py               ALL Pydantic models. Source of truth       [shared, provided]
│   ├── signature_engine.py      signature clauses and rule-based baseline  [B, provided]
│   ├── db/
│   │   ├── mongo.py             client and collection accessors            [B]
│   │   └── seed.py              load JSON into Mongo, create indexes       [B]
│   ├── tools/
│   │   ├── correlate_alerts.py                                             [B]
│   │   ├── node_context.py      get_node_context                           [B]
│   │   ├── lookup_incidents.py  lookup_similar_incidents                   [B]
│   │   ├── recommend_action.py                                             [C]
│   │   └── registry.py          tool descriptions and schemas for Ollama   [A]
│   ├── agent/
│   │   ├── state.py             AgentState                                 [A]
│   │   ├── nodes.py             ingest, decide_tool, run_tool, finalize    [A]
│   │   ├── graph.py             StateGraph build and compile               [A]
│   │   ├── llm.py               Ollama wrapper                             [C]
│   │   └── prompts.py           versioned prompts                          [C]
│   └── api/
│       ├── main.py              FastAPI app (/triage, /health)             [D]
│       └── notifier.py          Slack and optional email                   [D]
│
├── scripts/
│   ├── validate_dataset.py      integrity checks (provided)                [B]
│   ├── seed_db.py               CLI for db/seed.py                         [B]
│   ├── generate_variants.py     noisy test variants                        [B]
│   ├── run_eval.py              runs the agent on the held-out set         [C]
│   └── demo.py                  prints tool traces for the live demo       [D]
│
├── eval/
│   ├── metrics.py               accuracy, tool-call correctness, latency   [C]
│   ├── baseline/
│   │   └── manual_timings.csv   manual triage timings (humans fill this)   [D]
│   └── results/                 generated outputs (gitignored)
│
├── tests/
│   ├── test_tools.py            [B]
│   ├── test_graph.py            [A]
│   └── test_api.py              [D]
│
└── report/                      final report and PPT                       [D]
```

The `[A]` to `[D]` tags are the owning team member (see section 8). Files marked "provided" already exist and should be copied in, not rewritten.

---

## 6. Contracts

`anvesaka/schemas.py` is the **single source of truth**. If this README and `schemas.py` disagree, `schemas.py` wins. It defines the Alert, PlaybookEntry, Node, tool inputs and outputs, `TriageRequest`, `TriageResponse`, `AgentState`, and the Mongo collections and indexes.

Indicative shape of the API response (check `schemas.py` for exact fields):

```json
{
  "alert_id": "...",
  "root_cause": "...",
  "matched_incident_id": "...",
  "recommended_action": ["step 1 from playbook", "step 2 from playbook"],
  "confidence": 0.0,
  "tool_trace": [{"step": 1, "tool": "correlate_alerts", "input": {}, "output_summary": "..."}],
  "latency_s": 0.0
}
```

---

## 7. Rules for any AI agent or developer editing this repo

1. **Do not change `schemas.py` or the data files** without being told to. Other people's code depends on them. If a change is needed, propose it and list every file affected.
2. **Keep tools pure and deterministic.** No LLM calls inside tools except `recommend_action`. Tools take and return the Pydantic models from `schemas.py`.
3. **Never let the LLM generate remediation steps.** Always copy them from the matched playbook entry.
4. **Cap the agent loop** at `MAX_AGENT_STEPS` (default 4). If the model picks no valid tool, fall back to running `correlate_alerts` first, then `lookup_similar_incidents`.
5. **Run the LLM at temperature 0** and request structured JSON. Validate model output with Pydantic and retry once on failure.
6. **Small local models are unreliable at tool calling.** Write clear tool descriptions, keep the tool list short, and add fallbacks rather than assuming the model will behave.
7. **Every triage response must include `tool_trace`.** Transparency is the main selling point of this project.
8. **No UI, no cloud LLMs, no new heavy dependencies.** Ask first.
9. **Type hints and docstrings on every function.** Short, readable code over clever code. This is a student project that will be explained in a viva.
10. **Write or update a test** for any logic you add. Use a stubbed LLM in tests so they run without Ollama.
11. **Configuration comes from `.env` via `anvesaka/config.py`.** Never hard-code the Mongo URI, model name or webhook URL.
12. **Run commands from the repo root** (`python -m scripts.run_eval`, `uvicorn anvesaka.api.main:app`).

---

## 8. Team roles and file ownership

| Member | Role | Owns |
|---|---|---|
| A | Agent lead | `agent/state.py`, `agent/nodes.py`, `agent/graph.py`, `tools/registry.py`, `tests/test_graph.py` |
| B | Data and MongoDB | `db/`, `tools/correlate_alerts.py`, `tools/node_context.py`, `tools/lookup_incidents.py`, `signature_engine.py`, `scripts/validate_dataset.py`, `seed_db.py`, `generate_variants.py`, `tests/test_tools.py` |
| C | LLM and evaluation | `agent/llm.py`, `agent/prompts.py`, `tools/recommend_action.py`, `eval/metrics.py`, `scripts/run_eval.py` |
| D | API, integration and docs | `config.py`, `api/`, `scripts/demo.py`, `tests/test_api.py`, `eval/baseline/`, `report/`, `docker-compose.yml` |

If you are an AI agent working for one member, **stay inside that member's files** unless asked otherwise.

---

## 9. Setup and run

```bash
# 1. Environment & Dependencies
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                  # Add your MONGO_URI in .env

# 2. Start Local LLM (Optional for agent reasoning)
ollama pull qwen2.5:7b                                # or qwen2.5:3b on low RAM

# 3. Data & Validation
python -m scripts.validate_dataset                    # 23/23 signature check
python -m scripts.generate_variants --save-mongo      # 60 noisy variants
python -m scripts.seed_db                             # upload/verify cloud Mongo

# 4. Run the FastAPI Backend (Port 8000)
PYTHONPATH=. uvicorn anvesaka_AI.api.main:app --reload --port 8000

# 5. Run the Next.js Frontend (Port 3000)
cd frontend
pnpm install && pnpm dev

# 6. Run the Streaming Alert Simulator
PYTHONPATH=. python -m scripts.simulate_alerts --count 10 --interval 0.5

# 7. Run the Automated Judge Demo Script
PYTHONPATH=. python -m scripts.demo

# 8. Run the Full Test Suite
PYTHONPATH=. pytest tests/ -v
```

---

## 10. Build order and status

Follow this order. Each step can be developed against mocks until the real piece exists.

- [ ] **Day 1** Repo and contracts in place; Mongo running; Ollama tool-calling tested on two models; graph skeleton with mock tools; FastAPI hello-world
- [ ] **Day 2** Variant generator and seed script; prompt v1 with JSON output; `/triage` endpoint with a mocked agent
- [ ] **Day 3** Real tools wired into the graph; API connected to the real agent (**integration day, work together**)
- [ ] **Day 4** Multi-alert handling, loop limits and fallbacks; indexes and query timing; Slack webhook; tool trace in the response
- [ ] **Day 5** Evaluation run; manual baseline timing study (2 people, 10 scenarios)
- [ ] **Day 6** Results tables and charts; README and dataset docs; report and PPT; demo script
- [ ] **Day 7** Buffer, demo rehearsal, final push

**Scope cuts if behind:** skip Kaggle data, use Slack only (no email), reduce the test set to 20 scenarios, no UI.

---

## 11. Assumptions to confirm as a team

These were assumed while building the CMDB and are listed in `docs/SCHEMAS.md` (section 9): racks are 42U, all links are 25 Gbps, and the `S*` racks plus `Rack-D09` are storage racks. Confirm or correct them before evaluation.

---

## 12. Evaluation metrics (objectives 3 and 6)

- **Root-cause accuracy** and **action accuracy** on the held-out scenarios, for the agent, the rule-only baseline, and the manual baseline
- **Correct tools called** per scenario
- **Latency**, averaged over 3 runs per scenario
- **Consistency:** agreement between the two human triagers versus agreement across repeated agent runs
- **Query response time** for the Mongo lookups (objective 4)
- **Novel and noise handling:** does the agent avoid forcing a wrong match?
