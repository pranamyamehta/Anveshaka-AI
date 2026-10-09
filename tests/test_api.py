"""Comprehensive FastAPI TestClient integration tests for Anvesaka API.

Validates all routes, status codes, payload structures, and error responses.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from anvesaka_AI.api.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def test_root_endpoint(client: TestClient) -> None:
    """Test GET / returns health and docs link."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "message" in data
    assert data["docs"] == "/docs"


def test_health_endpoint(client: TestClient) -> None:
    """Test GET /health returns service readiness without leaking credentials."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("ok", "degraded")
    assert "services" in data
    assert data["services"]["api"] == "healthy"
    assert "mongodb" in data["services"]
    assert "ollama" in data["services"]
    assert "ollama_model" in data


def test_list_alerts(client: TestClient) -> None:
    """Test GET /alerts returns priority-sorted alerts with queue positions."""
    response = client.get("/alerts")
    assert response.status_code == 200
    alerts = response.json()
    assert len(alerts) > 0

    first = alerts[0]
    assert "alert_id" in first
    assert "severity" in first
    assert "queue_status" in first
    assert first["queue_position"] == 1


def test_list_alerts_filtered(client: TestClient) -> None:
    """Test GET /alerts with severity query filter."""
    response = client.get("/alerts?severity=CRITICAL")
    assert response.status_code == 200
    alerts = response.json()
    for alert in alerts:
        assert alert["severity"] == "CRITICAL"


def test_get_alert_by_id(client: TestClient) -> None:
    """Test GET /alerts/{alert_id} for valid and invalid IDs."""
    # Valid alert
    valid_res = client.get("/alerts/ALT-1001")
    assert valid_res.status_code == 200
    alert = valid_res.json()
    assert alert["alert_id"] == "ALT-1001"
    assert alert["node_id"] == "srv-node-45"

    # Invalid alert -> 404
    invalid_res = client.get("/alerts/ALT-NONEXISTENT")
    assert invalid_res.status_code == 404
    err = invalid_res.json()
    assert err["error"]["code"] == "ALERT_NOT_FOUND"


def test_analyze_alert(client: TestClient) -> None:
    """Test POST /alerts/{alert_id}/analyze returns 202 Accepted."""
    response = client.post("/alerts/ALT-1001/analyze")
    assert response.status_code == 202
    data = response.json()
    assert data["alert_id"] == "ALT-1001"
    assert data["status"] == "queued"


def test_triage_result_info_alert(client: TestClient) -> None:
    """Test GET /triage/{id} on an informational baseline alert concludes no_action."""
    response = client.get("/triage/ALT-1001")
    assert response.status_code == 200
    triage = response.json()
    assert triage["alert_id"] == "ALT-1001"
    assert triage["decision"] == "no_action"
    assert triage["matched_incident_id"] is None
    assert len(triage["tool_trace"]) >= 1


def test_triage_result_critical_incident(client: TestClient) -> None:
    """Test GET /triage/{id} on a critical incident provides grounded match and tool trace."""
    response = client.get("/triage/ALT-1034")
    assert response.status_code == 200
    triage = response.json()
    assert triage["alert_id"] == "ALT-1034"
    assert triage["decision"] == "match_incident"
    assert triage["matched_incident_id"] is not None
    assert len(triage["recommended_steps"]) > 0
    assert len(triage["tool_trace"]) == 4

    # Validate tool trace structure
    first_step = triage["tool_trace"][0]
    assert first_step["step"] == 1
    assert first_step["tool"] == "correlate_alerts"
    assert "summary" in first_step
    assert "duration_ms" in first_step


def test_submit_human_review(client: TestClient) -> None:
    """Test POST /triage/{id}/review captures reviewer decision."""
    payload = {
        "decision": "accepted",
        "reviewer": "Atulya",
        "notes": "Verified fan speed telemetry.",
    }
    response = client.post("/triage/ALT-1034/review", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["alert_id"] == "ALT-1034"
    assert data["review"]["decision"] == "accepted"
    assert data["review"]["reviewer"] == "Atulya"
    assert "reviewed_at" in data["review"]


def test_demo_controls(client: TestClient) -> None:
    """Test POST /demo/start and POST /demo/pause simulator toggles."""
    start_res = client.post("/demo/start", json={"interval_seconds": 2.0})
    assert start_res.status_code == 200
    assert start_res.json()["status"] == "running"

    pause_res = client.post("/demo/pause")
    assert pause_res.status_code == 200
    assert pause_res.json()["status"] == "paused"
