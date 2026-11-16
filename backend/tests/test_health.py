"""Tests for /health endpoint asserting service status and database checks."""
from fastapi.testclient import TestClient
from unittest.mock import patch


def test_health_check_healthy(client: TestClient):
    """Verify /health returns 200 OK and database healthy when DB query succeeds."""
    response = client.get("/health")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "ok"
    assert data["database"] == "healthy"
    assert "timestamp" in data
    assert data["service"] == "EDC Ingestion Server"
    assert data["version"] == "0.1.0"


def test_health_check_degraded_when_db_fails(client: TestClient):
    """Verify /health returns 503 Service Unavailable when DB check fails."""
    with patch("edc_server.api.health.check_db_health", return_value=False):
        response = client.get("/health")
        assert response.status_code == 503

        data = response.json()
        assert data["status"] == "degraded"
        assert data["database"] == "unhealthy"
