# Anvesaka – System Integration & Architecture Notes

**Workstream:** Member 4 (API, Contracts, and Integration)  
**Date:** October 2026

---

## 1. System Topology

```
                  +--------------------------------+
                  |  Frontend (Next.js Dashboard)  |
                  |     (React 19, Tailwind CSS)   |
                  +---------------+----------------+
                                  |
                   REST (fetch)   |   SSE (/events)
                                  v
                  +--------------------------------+
                  |    FastAPI Gateway Engine      |
                  | (anvesaka_AI/api/main.py, SSE) |
                  +---------------+----------------+
                                  |
         +------------------------+------------------------+
         |                                                 |
         v                                                 v
+-----------------------+                         +-----------------------+
|  Alert Priority Queue |                         | LangGraph Agent Graph |
| (anvesaka_AI/alerts/) |                         |  (anvesaka_AI/agent/) |
+-----------+-----------+                         +-----------+-----------+
            |                                                 |
            |                                                 | Calls Tools
            v                                                 v
+-----------------------+                         +-----------------------+
|  MongoDB Atlas Cloud  |                         | Deterministic Tools   |
| (cluster0.uqzi2bu...) | <---------------------- | (anvesaka_AI/tools/)  |
+-----------------------+                         +-----------------------+
```

---

## 2. Shared Data Contracts & Endpoints

1. **`GET /health`**: Non-blocking dependency readiness check (`mongodb`, `ollama`, `api`).
2. **`GET /alerts`**: Retrieves alerts with 1-indexed `queue_position` and severity filtering.
3. **`GET /alerts/{id}`**: Returns individual alert with hardware context.
4. **`POST /alerts/{id}/analyze`**: Triggers agentic triage.
5. **`GET /triage/{id}`**: Returns completed root cause, playbook remediation, and tool trace.
6. **`POST /triage/{id}/review`**: Records human reviewer verdict (`accepted`, `rejected`, `escalated`).
7. **`GET /events`**: Server-Sent Events (SSE) broadcaster for streaming real-time alert arrivals.
8. **`POST /demo/start` & `POST /demo/pause`**: Remote controls for the streaming telemetry simulator.

---

## 3. Resilience Guarantees

* **Graceful Degradation:** The API and demo runner function smoothly whether MongoDB Atlas is online or offline (via in-memory and JSON fallbacks).
* **Zero Hallucination:** Remediation actions are immutable templates extracted from historical playbooks.
* **Bounded Reasoning:** Agent loops are capped by `MAX_AGENT_STEPS = 4` to prevent infinite LLM execution.
