# Anvesaka Implementation Plan

## Purpose

This document divides the project among four people for a five-day build. Each person can use an AI coding assistant, but should work only in their assigned area and follow the shared interfaces in this plan. The goal is a judge-ready demo in which simulated alerts arrive live, are prioritized, investigated by the agent, and shown in a polished frontend with an explanation of the evidence.

## What we are building

Anvesaka is an incident-triage assistant for simulated data-center alerts. It receives an alert, checks related alerts and node information, compares the evidence with a historical incident playbook, and presents a recommendation for a human to review. The LLM may choose investigation tools and explain a match. It must not invent remediation steps: recommended steps must come from the matching playbook entry.

The demo flow is:

1. A simulator sends an alert from the project's sample alert set.
2. The backend stores it and places it in a queue according to severity and arrival time.
3. The frontend shows a brief pop-up and adds the alert to the persistent queue.
4. The agent investigates the highest-priority waiting alert and emits progress updates.
5. The investigation page shows evidence, tool calls, the matching incident (if any), and the playbook recommendation.
6. A human reviewer records whether the result was accepted, rejected, or escalated. This is a demo record only; it does not make changes to real equipment.

### Scope and constraints

- “Live alerts” in this five-day demo means alerts emitted by a simulator. The existing README says there is no real monitoring integration. Connecting to real monitoring is a separate scope decision.
- Do not build automatic remediation or commands that change infrastructure.
- Do not force a playbook match for novel, noise, or recovery alerts. Return a clear no-match/no-action result when appropriate.
- Process one investigation at a time for predictable local-model behavior. Sort queued alerts Critical, High, Medium, Low; within a severity, process oldest first. A new urgent alert moves ahead of waiting work but does not cancel an investigation already running.
- Keep the agent loop bounded by `MAX_AGENT_STEPS` (default 4), use temperature 0, request structured output, validate it, and retry once on invalid output.
- Every completed triage response includes a tool trace.
- MongoDB remains the data store; Ollama remains the local LLM. No cloud LLM calls.
- This plan adds the frontend that the team now wants. The README's previous “no UI” non-goal is superseded for this project by that team decision; update the README when the scope is agreed and implementation begins.

## Important starting-state facts

Before asking an AI assistant to implement anything, have it inspect the current checkout. The checkout examined while writing this plan has these gaps:

- The package directory is `anvesaka_AI/` (the README examples refer to `anvesaka/`). Use the actual package name unless the team deliberately renames it.
- `anvesaka_AI/schemas.py`, `docs/SCHEMAS.md`, and the sample JSON files under `data/` are placeholders, not usable contracts or data.
- Many backend modules and tests are TODO stubs. The minimal settings module and FastAPI root/health routes have been started, but the actual triage API and graph are not complete.
- Python dependencies were installed in the ignored project `.venv`. Docker and Ollama were not available on PATH at inspection time.

**Do not let an AI fabricate replacement schemas, historical incidents, alerts, or ground truth.** First ask the team for the original supplied files. If they cannot be found, the team must explicitly agree to recreate them; record that decision, keep the shapes consistent across all modules, and label synthetic data as synthetic. Work that does not depend on those files can continue with clearly labelled mock objects.

## Team ownership and file boundaries

Use the names Member 1–4 below, then replace them with the actual names. Each member works on a separate branch and owns the listed paths. Do not edit another member's owned files without coordinating first. A shared interface change is proposed to Member 4, discussed by the affected owners, then merged as a small reviewed change.

| Member | Workstream | Owns |
|---|---|---|
| **1 — Data, MongoDB, alert intake and queue** | Data validation/seeding, deterministic evidence tools, simulated alert producer and priority queue | `anvesaka_AI/db/`; `anvesaka_AI/tools/correlate_alerts.py`; `anvesaka_AI/tools/node_context.py`; `anvesaka_AI/tools/lookup_incidents.py`; `anvesaka_AI/signature_engine.py`; `anvesaka_AI/alerts/` (new); `scripts/validate_dataset.py`; `scripts/seed_db.py`; `scripts/generate_variants.py`; `scripts/simulate_alerts.py` (new); `tests/test_tools.py`; new tests for the queue/simulator |
| **Member 2 — Agent, LLM and evaluation** | Tool selection, bounded LangGraph workflow, playbook-grounded recommendation, evaluation logic | `anvesaka_AI/agent/`; `anvesaka_AI/tools/registry.py`; `anvesaka_AI/tools/recommend_action.py`; `eval/metrics.py`; `scripts/run_eval.py`; `tests/test_graph.py`; evaluation-only tests |
| **Member 3 — Frontend** | Complete judge-facing interface, event handling, responsive styling, demo controls | `frontend/` (new; React + TypeScript + Vite is the recommended implementation); frontend-only documentation/configuration in that directory; frontend component tests if the team chooses to add them |
| **Member 4 — API, contracts and integration** | API contract, FastAPI endpoints and event stream, application configuration, cross-workstream integration, demo/report | `anvesaka_AI/config.py`; `anvesaka_AI/api/`; `scripts/demo.py`; `tests/test_api.py`; `docs/API_CONTRACT.md` (new); `README.md`; `report/`; integration wiring and integration notes |

### Shared files and ownership rules

- `anvesaka_AI/schemas.py` is the intended source of truth, but is currently a placeholder. Member 4 coordinates obtaining the original file. No one edits or replaces it until the team has the actual file or explicitly approves a replacement contract.
- `docs/SCHEMAS.md` and the JSON data are also placeholders. Member 1 verifies the original dataset files and tells the team exactly which inputs are missing.
- If a type/interface needs to change, its owner proposes the change in `docs/API_CONTRACT.md` or the relevant schema proposal; affected owners agree before code is changed.
- Never share one working file between members during parallel implementation. Members may review each other's work, but the owner applies changes to their own files.
- Keep secrets out of AI prompts, source control, logs, screenshots and demo recordings. Use `.env.example` for variable names and local `.env` for actual machine settings.

## Shared interface to agree on before parallel implementation

Member 4 writes the detailed contract in `docs/API_CONTRACT.md` on Day 1. Keep it concise and version it if it changes. At minimum, align on these operations:

| Operation | Purpose |
|---|---|
| `GET /health` | API and dependency readiness summary; do not expose secrets |
| `GET /alerts` | Return alerts and their queue/investigation status, with optional severity/status filters |
| `GET /alerts/{alert_id}` | Return one alert and its basic context |
| `GET /triage/{alert_id}` | Return the current or completed investigation for an alert |
| `POST /demo/start` | Start or resume the simulated alert feed; accept a speed/interval setting within safe bounds |
| `POST /demo/pause` | Pause the simulator without deleting existing alerts |
| `POST /alerts/{alert_id}/analyze` | Queue analysis when manual retry is needed; repeated requests should not create duplicate active jobs |
| `POST /triage/{alert_id}/review` | Record accepted/rejected/escalated and optional short reviewer note; never execute remediation |
| `GET /events` | Server-Sent Events stream for new alerts, queue changes, analysis progress and completion/failure |

The API contract must define request/response examples, error shapes, and these shared fields: stable alert ID; event timestamp; severity; source/host/rack when known; queue status; triage status; matched incident ID or explicit no-match; root-cause explanation; playbook-derived action steps; confidence; latency; and ordered tool trace. Use the real Pydantic schemas once supplied. Do not silently invent a different model in the frontend.

Suggested event types: `alert_received`, `queue_updated`, `analysis_started`, `tool_started`, `tool_completed`, `analysis_completed`, `analysis_failed`, and `review_recorded`. Each event includes an event ID/time, alert ID, and only the fields needed by the UI. SSE is a good fit because the browser mostly receives server updates; ordinary REST endpoints handle queries and user actions.

## Detailed tasks by member

### Member 1 — Data, MongoDB, alert intake and queue

**Goal:** Provide valid data and a deterministic alert stream/queue for the rest of the system.

**Tasks**

1. Locate and validate the original alerts, playbook, CMDB node and ground-truth files. Compare their shape to the intended schema. Report missing files on Day 1; do not make replacement data without team approval.
2. Implement/finish Mongo client and collection accessors, seed scripts, and indexes using the agreed schemas. Make seeding repeatable and safe to rerun.
3. Implement the deterministic tools: correlate related alerts; retrieve node/rack context; rank similar playbook incidents and explain matched/failed clauses. Tool functions should not call the LLM.
4. Implement the alert simulator using existing sample alerts. It should support start, pause, configurable interval, and a repeatable scenario order for the demo. Do not call an external alert system.
5. Implement the queue service separately from FastAPI. Provide clear functions for adding/listing alerts, selecting the next alert, and updating status. Sort by severity then oldest timestamp; define behavior for unknown severity. Do not preempt an in-progress analysis.
6. Keep duplicate alert IDs idempotent. A retry/replayed event must not make duplicate queue entries.
7. Document the simulator-to-queue function signatures and any expected database state for Member 4 and Member 2.

**Definition of done**

- Dataset validator reports useful failures and passes against the real supplied data.
- A fresh local MongoDB can be seeded, and rerunning the seed does not duplicate records.
- Evidence tools have deterministic input/output behavior and handle missing node/playbook entries clearly.
- A short simulator run emits known sample alerts and demonstrates ordering (including a Critical arriving behind a waiting Low alert).
- Queue/simulator logic has isolated tests using a temporary or mocked database; tests do not require Ollama.
- Member 4 can call the queue service without importing UI or API code.

**AI-use instructions:** Ask AI to inspect `schemas.py`, `docs/SCHEMAS.md`, the real data and current database/tool modules before coding. Tell it to edit only Member 1 paths, preserve playbook fields exactly, keep tools deterministic, add type hints/docstrings, and report assumptions instead of inventing missing data.

### Member 2 — Agent, LLM and evaluation

**Goal:** Make the agent investigate safely, explain its evidence and ground actions in the playbook.

**Tasks**

1. Inspect the actual schemas and tools first. Define `AgentState` in agreement with the real contract; do not create a competing state model.
2. Build the custom LangGraph `StateGraph`: ingest alert → decide next tool → execute tool → loop or finish → finalize recommendation. Keep the loop bounded by `MAX_AGENT_STEPS`.
3. Register only the intended investigation tools and provide concise descriptions/typed argument schemas suitable for local Ollama models.
4. Implement the Ollama wrapper with configured host/model, temperature 0, structured JSON response, schema validation and one retry on invalid output. Add a safe fallback when the model selects an invalid tool or malformed arguments.
5. Implement recommendation selection so the model may select a candidate and explain the evidence, but action steps are copied from the selected playbook entry. If no candidate passes the agreed confidence/evidence rule, return a no-match/no-action result.
6. Record every tool call in an ordered, readable trace, including the tool, safe input summary, output summary, and step number. Avoid storing unnecessary sensitive content.
7. Use a stubbed LLM in graph tests so tests run offline. Cover tool loop, invalid choice fallback, maximum steps, no-match case, tool trace and playbook action copying.
8. Complete evaluation code against the held-out scenarios after data is available. Compare the agent, rule-only baseline and manual baseline; report root-cause/action accuracy, tool correctness, latency and novel/noise behavior. Do not tune prompts against the held-out set.

**Definition of done**

- Graph can run end-to-end with stub tools and stubbed LLM, then with real tools and local Ollama when available.
- No path lets the LLM produce arbitrary remediation steps.
- Invalid model output does not crash the API or create an unbounded loop.
- Every result has a tool trace and explicit no-match behavior.
- Evaluation output is reproducible and distinguishes tuning cases from held-out cases.

**AI-use instructions:** Give AI the schema, graph design, tool descriptions, prompt constraints and test expectations. Restrict edits to Member 2 paths. Explicitly forbid cloud model calls, unbounded loops, invented fixes and tests that depend on a live Ollama server. Ask it to show where output validation and fallback occur.

### Member 3 — Frontend

**Goal:** Make the investigation understandable and compelling to judges without hiding uncertainty or tool evidence.

**Recommended screens and behavior**

1. **Operations overview:** compact counts for Critical/High/Medium/Low, queued/analyzing/completed totals, API/DB/model health, simulator controls, and a recent-alert list.
2. **Alert queue:** severity-colored but accessible labels, timestamp, host/rack, alert text, status, search/filter, and clear queue order. Do not rely on color alone.
3. **Incoming alert pop-up:** concise toast with severity, host, and short alert text; clicking it opens the investigation. Toasts should stack/expire without blocking the queue or spamming the whole screen.
4. **Investigation detail:** original alert and timestamps; related alerts; node context; matched incident or explicit no match; confidence with an explanation; playbook steps; and an ordered tool-call timeline that shows what the agent checked and what it found.
5. **Review controls:** Accept, Reject, Escalate, and optional note. Show that this records a human decision only; it does not perform a fix.
6. **Demo states:** loading, no alerts, disconnected API, no matching playbook case, analysis failure, and empty tool trace. Make connection failures visible and provide retry guidance.

**Visual direction**

- Use a dark operations-console look with one restrained accent color, high contrast, readable type and generous spacing.
- Use severity labels/icons plus color. Reserve motion for new alerts and state changes; respect reduced-motion preferences.
- Make the main action obvious: select an alert and inspect its investigation. Avoid turning the page into a chat-only interface.
- Provide a responsive layout that still works on a projector/laptop and a narrow window. Ensure the demo remains legible at presentation distance.
- Keep charts optional and simple. A clear queue and evidence timeline matter more than decorative graphs.

**Tasks**

1. Read `docs/API_CONTRACT.md` and build typed frontend models from its examples. Use React + TypeScript + Vite unless the team chooses an existing frontend stack.
2. Build screens against local mock fixtures while backend endpoints are unfinished. Label mock mode so screenshots cannot be mistaken for live backend results.
3. Implement REST loading/actions and reconnecting `EventSource` handling for `/events`. Reflect event updates in the queue and investigation view without refreshing the page.
4. Handle duplicate/replayed events idempotently and show a connection indicator. Do not let a delayed event regress a completed triage status.
5. Keep all frontend code and dependencies inside `frontend/`; do not edit FastAPI or shared schemas. Send contract questions to Member 4.
6. Add a short `frontend/README.md` with setup/run commands, mock mode, environment variables and demo instructions.

**Definition of done**

- A judge can start the frontend, see a simulated alert arrive, open it, follow investigation progress and inspect a completed recommendation.
- Queue order/status changes appear without a full-page reload.
- The UI communicates no-match and failure cases honestly and always exposes the tool trace.
- Layout works at demo resolution, is keyboard navigable for primary controls, and has clear empty/loading/error states.
- Frontend can be developed against mocks independently and later switched to the agreed API without changing backend files.

**AI-use instructions:** Provide AI with the shared API contract, the screen list, visual direction and example states. Restrict edits to `frontend/`. Ask it to create realistic but clearly labelled fixtures, avoid inventing backend fields, preserve accessible severity indicators, and implement explicit loading/error/no-match states.

### Member 4 — API, contract and integration

**Goal:** Give all workstreams one stable interface and produce a reliable end-to-end demo.

**Tasks**

1. On Day 1, inspect the actual checkout and obtain/locate the real schemas/data. Record the blockers and tell the team; do not silently replace placeholders.
2. Write `docs/API_CONTRACT.md` with endpoint paths, payload examples, event names, status transitions, error behavior, and ownership of every response field. Get sign-off from Members 1–3 before they build to it.
3. Finish environment-backed settings for MongoDB, Ollama, simulator interval, and optional notification config. Keep secrets in `.env`, which is ignored by git.
4. Build FastAPI routes that call Member 1's queue/simulator and Member 2's agent through their agreed Python interfaces. Keep web concerns in `api/`; do not duplicate queue rules or agent logic in routes.
5. Add `/events` SSE stream with clean client disconnect handling and safe event payloads. Add `/health` dependency checks that clearly report unavailable Mongo/Ollama without leaking credentials.
6. Handle API validation errors, missing alert IDs, duplicate analyze requests, agent failures and graceful shutdown in a way the frontend can display.
7. Coordinate integration in small increments: mock contract → simulator/API → agent/API → frontend/API. Keep a simple mock response path while services are unavailable.
8. Update README run instructions and scope to include the frontend, simulated live feed, setup prerequisites and honest limitations. Prepare `scripts/demo.py`, report content and the judge walkthrough.
9. Own merge order and integration notes. Do not rewrite another member's feature to resolve a conflict; return the issue to its owner with a concrete reproduction.

**Definition of done**

- The API contract matches actual request/response models and frontend types.
- The full demo works from a documented clean start: MongoDB, Ollama/model, backend, frontend, simulator.
- Alert arrival, priority queue, agent progress and final result are visible in the UI.
- API health/errors are clear; a missing optional Slack webhook does not prevent triage.
- Demo script includes a known match, a novel/no-match alert, and a harmless/no-action alert.
- Documentation explains that the alert source is simulated and review controls do not remediate equipment.

**AI-use instructions:** Provide AI the repository map, real schemas, agreed API contract and integration sequence. Restrict ordinary edits to Member 4 paths. Ask it to preserve the API contract, avoid copying business logic into route handlers, avoid exposing environment variables, and list every endpoint/event touched. Coordinate any shared schema changes before asking AI to apply them.

## Five-day execution schedule

| Day | Member 1 | Member 2 | Member 3 | Member 4 | Shared checkpoint |
|---|---|---|---|---|---|
| **1 — Context and contract** | Locate original data/schema; inspect current DB/tools; specify simulator/queue interface and severity order. | Inspect schema and existing agent stubs; sketch state transitions and prompt/tool policy. | Create wireframe and typed mock fixtures from proposed fields; scaffold only inside `frontend/`. | Obtain missing inputs; draft API/event contract; document run prerequisites and ownership. | 30-minute contract review. Confirm actual schema/data source, field names, severity order, event list and no-real-remediation boundary. No parallel code against guessed fields. |
| **2 — Independent builds** | Implement data validation/seeding/tools plus isolated queue/simulator. | Implement graph and LLM wrapper with stubs; add offline graph coverage. | Build dashboard, alert queue, pop-up and investigation layout using labelled mocks. | Build API shell, settings and health routes using contract-shaped mocks; check local services availability. | Each member demonstrates their component locally. Raise interface gaps as written contract proposals. |
| **3 — First integration** | Connect simulator/queue to Mongo and expose callable service functions. | Connect deterministic tools to graph; verify trace/no-match behavior with stubbed LLM. | Connect list/details UI to API; render event stream progress. | Wire simulator and queue into API; wire agent call; connect frontend; record integration failures. | One alert completes end to end using real data if available, otherwise an explicitly labelled synthetic fixture. |
| **4 — Hardening** | Verify ordering, duplicate handling, missing-data behavior and query timings. | Verify max-step/fallback behavior and run held-out evaluation if data/model are ready. | Polish responsive layout, reconnect/errors, accessibility and judge-focused timeline. | Exercise API edge cases, SSE disconnects and full startup; finalize demo script and report draft. | Run the three scenario walkthroughs; fix blockers only through the owning member. |
| **5 — Freeze and presentation** | Confirm repeatable data seed and simulator reset/demo order. | Freeze prompts/settings; record evaluation results and limitations. | Freeze styling; rehearse queue-to-investigation flow and ensure pop-ups do not obscure evidence. | Run clean-start rehearsal, finalize README/report/slides, coordinate final merges. | Feature freeze. Rehearse from a fresh start and keep a recorded fallback walkthrough if a local model/service is unavailable. |

## Parallel AI workflow for every member

1. **Start with context.** Open the repository root, read `README.md`, this plan, `docs/SCHEMAS.md`, the actual schema file, relevant source modules, and any applicable `AGENTS.md`. Do not rely on a chat summary alone.
2. **Check the starting state.** Ask AI to report current file contents, TODOs, package name, available services and missing inputs before editing. Preserve existing user changes.
3. **Give one bounded task.** State the member's role, allowed paths, expected behavior, contract version, acceptance criteria and out-of-scope items. Avoid asking AI to “finish the whole project” in a single prompt.
4. **Keep AI inside the boundary.** If work requires another member's file or a contract change, have AI stop and describe the required interface change. The owner makes the coordinated change.
5. **Review generated work.** The human owner checks the diff, names/typing, error cases, secrets, playbook-grounding, and whether new dependencies were introduced. Do not merge code the owner cannot explain to judges.
6. **Use mocks responsibly.** Mocks must mirror the API contract and be labelled. Do not present mock output as evaluated agent output.
7. **Commit and communicate.** Commit a focused change on the member's branch. Send the team a short note with files changed, interface changes, startup steps and remaining blockers.
8. **Integrate deliberately.** Member 4 merges in dependency order after the owner confirms their acceptance criteria. Resolve conflicts with the relevant owner; do not overwrite their work.

### Copyable shared context prompt for each AI assistant

Paste this at the beginning of each member's AI session, then append the member-specific task prompt below it:

```text
You are helping build Anvesaka, a local AI assistant that investigates simulated
data-center alerts. Read the repository README.md and implementationplan.md, then
inspect the real schemas, data, and files relevant to my task before editing.

Product flow: a simulator emits an alert; backend stores and prioritizes it;
frontend shows a pop-up and queue; a bounded LangGraph agent checks related alerts,
node context, and historical playbook incidents; the UI shows evidence, a tool
trace, a playbook-grounded recommendation, and human review status.

Architecture constraints: Python/FastAPI backend, MongoDB, LangGraph, Ollama local
LLM, and a separate frontend. There is no real monitoring integration in this
demo. Never call a cloud LLM. Never execute remediation. The LLM may select an
incident and explain why, but action steps must be copied from the playbook. Handle
novel/noise/recovery alerts without forcing a match. Include the tool trace.

Repository reality: use the actual package and paths found in the checkout, not
paths assumed from prose. Some starter files/data may be placeholders. Never
fabricate schemas, source data, playbook records, or ground truth. If a required
input is missing or differs from the contract, stop and report the exact file and
decision needed. Do not overwrite existing work or edit outside my assigned paths.
Use type hints and docstrings. Avoid new dependencies unless the team approved
them. Keep changes small and explain the resulting diff and how to run it.

Before editing, summarize the relevant current files, missing inputs, and your
proposed scoped change. After editing, summarize changed files, assumptions,
contract impact, and any checks performed. Do not claim tests or services ran if
they did not.
```

### Member-specific task prompt template

```text
My role is Member [1/2/3/4] — [workstream]. My allowed paths are:
[paste the paths from the ownership table].

Task for this change:
[one concrete task only]

Contract/API version:
[link or paste the agreed fields/endpoints/events]

Acceptance criteria:
- [observable result]
- [error/edge case]
- [required test or manual check]

Do not edit other members' paths. If you find a required cross-boundary change,
stop and propose the smallest contract/interface update instead of applying it.
```

## Judge demo checklist

- Start all services using documented commands from the repository root.
- Show system health and start the simulator.
- Let a Critical or High alert arrive and point out the pop-up and queue position.
- Open the alert and explain the tool timeline in plain language.
- Show a known playbook match and emphasize that the action steps came from history.
- Show a novel/noise case and explain why no fix was forced.
- Record a human review and state clearly that no infrastructure action was taken.
- Mention evaluation results only if they were run on the held-out set; distinguish mock/demo results from measured results.
- Have a fallback screen recording or prepared screenshots in case Docker, Ollama, or the local model is unavailable during judging.

## Decisions and blockers to resolve before implementation

1. Obtain the actual `schemas.py`, `docs/SCHEMAS.md`, alerts, playbook, CMDB and ground-truth files. If not available, ask the team whether to author a replacement contract/data set; do not make that decision silently.
2. Confirm whether the team accepts the frontend as an explicit change to the README's original no-UI scope (this plan assumes yes because the team requested it).
3. Confirm the demo machine can run Docker/MongoDB and Ollama with a chosen local model. Choose the smaller model if hardware is constrained and record the choice in `.env.example`/setup docs, not as a secret.
4. Confirm the exact severity labels present in the real data and map them to Critical/High/Medium/Low. Unknown severity must have a documented safe position in the queue.
5. Confirm whether reviewer decisions are stored in MongoDB for the demo and who can reset them between rehearsals.

