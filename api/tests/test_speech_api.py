import base64
from unittest.mock import Mock

from fastapi.testclient import TestClient

from habitat_api.main import app
from habitat_api.settings import DEVELOPMENT_DEMO_INSPECTION_ID
from habitat_api.speech import SpeechTranscript


def test_inspection_transcription_returns_editable_human_review_text(monkeypatch) -> None:
    speech = Mock()
    speech.configured = True
    speech.transcribe_short_audio.return_value = SpeechTranscript(
        text="Visible staining below the window.", model_id="qwen-audio-test",
    )
    headers = {
        "X-Dev-Tenant-Id": "demo-tenant",
        "X-Dev-User-Id": "demo-admin",
        "X-Dev-Roles": "admin",
    }
    with TestClient(app) as client:
        monkeypatch.setattr(app.state, "speech_client", speech)
        response = client.post(
            f"/v1/inspections/{DEVELOPMENT_DEMO_INSPECTION_ID}/transcriptions",
            headers=headers,
            json={
                "audio_base64": base64.b64encode(b"mock audio").decode("ascii"),
                "audio_format": "m4a",
                "sample_rate": 44100,
                "duration_seconds": 4.2,
            },
        )
    assert response.status_code == 200
    assert response.json()["text"] == "Visible staining below the window."
    assert response.json()["requires_human_review"] is True
    speech.transcribe_short_audio.assert_called_once_with(
        b"mock audio", audio_format="m4a", sample_rate=44100, duration_seconds=4.2,
    )


def test_inspection_transcription_stays_disabled_without_provider(monkeypatch) -> None:
    speech = Mock()
    speech.configured = False
    speech.unavailable_reason = "Remote speech transcription is disabled."
    with TestClient(app) as client:
        monkeypatch.setattr(app.state, "speech_client", speech)
        response = client.post(
            f"/v1/inspections/{DEVELOPMENT_DEMO_INSPECTION_ID}/transcriptions",
            headers={
                "X-Dev-Tenant-Id": "demo-tenant",
                "X-Dev-User-Id": "demo-inspector",
                "X-Dev-Roles": "inspector",
            },
            json={
                "audio_base64": base64.b64encode(b"mock audio").decode("ascii"),
                "audio_format": "m4a",
                "sample_rate": 44100,
                "duration_seconds": 4.2,
            },
        )
    assert response.status_code == 503
    assert response.json()["detail"] == "Remote speech transcription is disabled."
    speech.transcribe_short_audio.assert_not_called()