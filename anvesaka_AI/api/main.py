import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from anvesaka_AI.config import settings


app = FastAPI(
    title="Anvesaka",
    description="Agentic AI assistant for data center incident triage.",
    version="0.1.0",
)

# Allow the Next.js dev server (and production build) to call the API.
# Adjust origins as needed for production deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



@app.get("/", tags=["health"])
def root() -> dict[str, str]:
    """Return a short message confirming the API process is running."""
    return {"message": "Anvesaka API is running", "docs": "/docs"}


@app.get("/health", tags=["health"])
async def health() -> dict:
    """Report the API and external dependency readiness."""
    services: dict[str, str] = {
        "api": "healthy",
        "mongodb": "disconnected",
        "ollama": "unreachable",
    }

    # 1. Quick non-blocking MongoDB ping
    try:
        client = MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=500)
        client.admin.command("ping")
        services["mongodb"] = "connected"
    except (PyMongoError, Exception):
        services["mongodb"] = "disconnected"

    # 2. Quick non-blocking Ollama ping
    try:
        async with httpx.AsyncClient(timeout=0.5) as http_client:
            resp = await http_client.get(f"{settings.ollama_host}/api/tags")
            if resp.status_code == 200:
                services["ollama"] = "reachable"
    except Exception:
        services["ollama"] = "unreachable"

    overall_status = "ok" if services["mongodb"] == "connected" and services["ollama"] == "reachable" else "degraded"

    return {
        "status": overall_status,
        "version": "0.1.0",
        "services": services,
        "ollama_model": settings.ollama_model,
    }


# --------------------------------------------------------------------------- #
# ALERTS API
# --------------------------------------------------------------------------- #
from typing import Optional
from fastapi import Query, status
from fastapi.responses import JSONResponse
from anvesaka_AI.api.store import get_all_alerts, get_alert_by_id, queue_alert_for_analysis


@app.get("/alerts", tags=["alerts"])
def list_alerts(
    severity: Optional[str] = Query(None, description="Filter by severity (e.g. CRITICAL, WARNING)"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by queue status (queued, investigating, completed)"),
    limit: int = Query(50, ge=1, le=100, description="Max alerts to return"),
) -> list[dict]:
    """Retrieve alerts from datastore or queue with priority ordering."""
    return get_all_alerts(severity=severity, status=status_filter, limit=limit)


@app.get("/alerts/{alert_id}", tags=["alerts"])
def get_alert(alert_id: str):
    """Retrieve a single alert by ID."""
    alert = get_alert_by_id(alert_id)
    if not alert:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "error": {
                    "code": "ALERT_NOT_FOUND",
                    "message": f"Alert '{alert_id}' was not found in the datastore.",
                    "details": {},
                }
            },
        )
    return alert


@app.post("/alerts/{alert_id}/analyze", tags=["alerts"], status_code=status.HTTP_202_ACCEPTED)
def analyze_alert(alert_id: str):
    """Queue an alert for agent investigation."""
    result = queue_alert_for_analysis(alert_id)
    if not result:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "error": {
                    "code": "ALERT_NOT_FOUND",
                    "message": f"Alert '{alert_id}' was not found in the datastore.",
                    "details": {},
                }
            },
        )
    return result


# --------------------------------------------------------------------------- #
# TRIAGE & HUMAN REVIEW API
# --------------------------------------------------------------------------- #
from typing import Literal
from pydantic import BaseModel
from anvesaka_AI.api.store import get_triage_result, record_triage_review


class ReviewRequest(BaseModel):
    decision: Literal["accepted", "rejected", "escalated"]
    reviewer: Optional[str] = "On-Call Engineer"
    notes: Optional[str] = ""


@app.get("/triage/{alert_id}", tags=["triage"])
def get_triage(alert_id: str):
    """Retrieve completed triage findings, playbook remediation steps, and tool trace."""
    triage = get_triage_result(alert_id)
    if not triage:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "error": {
                    "code": "TRIAGE_NOT_FOUND",
                    "message": f"Triage result for '{alert_id}' not found.",
                    "details": {},
                }
            },
        )
    return triage


@app.post("/triage/{alert_id}/review", tags=["triage"])
def submit_review(alert_id: str, req: ReviewRequest):
    """Record human reviewer oversight verdict (Accept / Reject / Escalate)."""
    result = record_triage_review(
        alert_id=alert_id,
        decision=req.decision,
        reviewer=req.reviewer,
        notes=req.notes,
    )
    if not result:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "error": {
                    "code": "ALERT_NOT_FOUND",
                    "message": f"Alert '{alert_id}' was not found in the datastore.",
                    "details": {},
                }
            },
        )
    return result


# --------------------------------------------------------------------------- #
# SIMULATOR & REALTIME SSE API
# --------------------------------------------------------------------------- #
from fastapi.responses import StreamingResponse
from anvesaka_AI.api.events import event_bus, simulator, sse_event_generator


class StartDemoRequest(BaseModel):
    interval_seconds: float = 5.0
    scenario_mode: Optional[str] = "demo_sequence"


@app.post("/demo/start", tags=["simulator"])
async def start_demo(req: Optional[StartDemoRequest] = None):
    """Start or resume the simulated alert feed."""
    interval = req.interval_seconds if req else 5.0
    return simulator.start(interval_seconds=interval)


@app.post("/demo/pause", tags=["simulator"])
async def pause_demo():
    """Pause the simulated alert feed without resetting queue state."""
    return simulator.pause()



@app.get("/events", tags=["events"])
async def stream_events():
    """Server-Sent Events (SSE) push stream for live alerts, queue, and triage steps."""
    q = event_bus.subscribe()
    return StreamingResponse(
        sse_event_generator(q),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )




