from fastapi.testclient import TestClient

from app.main import app


def test_public_api_prefix_is_normalized_before_routing():
    with TestClient(app) as client:
        direct = client.get("/health")
        prefixed = client.get("/api/health")

    assert direct.status_code == 200
    assert prefixed.status_code == 200
    assert prefixed.json()["version"] == "0.4.0"
    assert prefixed.json()["database"] == "connected"
