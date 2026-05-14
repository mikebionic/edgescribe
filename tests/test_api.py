import io
from fastapi.testclient import TestClient
from api import app

client = TestClient(app)


def test_health():
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_get_unknown_job_returns_404():
    r = client.get("/v1/jobs/nonexistent-id")
    assert r.status_code == 404


def test_delete_unknown_job_returns_404():
    r = client.delete("/v1/jobs/nonexistent-id")
    assert r.status_code == 404


def test_transcribe_returns_job_id():
    # Background thread will fail on fake audio — endpoint still returns job_id immediately
    audio = io.BytesIO(b"fake audio data")
    r = client.post(
        "/v1/transcribe",
        files={"file": ("test.mp3", audio, "audio/mpeg")},
        data={"language": "auto", "model": "large-v3-turbo", "timestamps": "auto"},
    )
    assert r.status_code == 200
    assert "job_id" in r.json()
    assert r.json()["status"] == "queued"
