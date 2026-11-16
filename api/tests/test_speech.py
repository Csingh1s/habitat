import json
import base64
from unittest.mock import Mock
from uuid import uuid4

import pytest

from habitat_api.settings import Settings
from habitat_api.speech import AlibabaSpeechClient


def speech_client(**overrides) -> AlibabaSpeechClient:
    return AlibabaSpeechClient(Settings(_env_file=None, **{
        "app_env": "staging", "enable_remote_inference": True,
        "alibaba_model_studio_host": "https://test-workspace.ap-southeast-1.maas.aliyuncs.com",
        "qwen_cloud_api_key": "test-key", **overrides,
    }))


def mock_response(monkeypatch, payload):
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.read.return_value = json.dumps(payload).encode()
    sender = Mock(return_value=response)
    monkeypatch.setattr("habitat_api.speech.urlopen", sender)
    return sender


@pytest.mark.parametrize("settings", [
    {"app_env": "development"}, {"enable_remote_inference": False},
    {"alibaba_model_studio_host": None}, {"qwen_cloud_api_key": None},
])
def test_speech_fails_closed_without_network_calls(monkeypatch, settings) -> None:
    sender = mock_response(monkeypatch, {})
    client = speech_client(**settings)
    assert not client.configured
    with pytest.raises(RuntimeError):
        client.transcribe_short("https://storage.example/note.wav", audio_format="wav", sample_rate=16000, duration_seconds=30)
    sender.assert_not_called()


def test_short_recording_uses_native_asr_contract(monkeypatch) -> None:
    sender = mock_response(monkeypatch, {"output": {"text": " Inspect the window. "}})
    result = speech_client().transcribe_short("https://storage.example/note.wav", audio_format="wav", sample_rate=16000, duration_seconds=30)
    request = sender.call_args.args[0]
    assert request.full_url.endswith("/api/v1/services/aigc/multimodal-generation/generation")
    assert request.get_header("Authorization") == "Bearer test-key"
    body = json.loads(request.data)
    assert body["model"] == "qwen-audio-3.1-asr-flash"
    assert body["parameters"] == {"format": "wav", "sample_rate": "16000"}
    assert body["input"]["messages"][0]["content"][0]["input_audio"]["data"].endswith("note.wav")
    assert result.text == "Inspect the window."
    assert result.requires_human_review is True


def test_short_audio_bytes_are_sent_as_inline_data_uri(monkeypatch) -> None:
    sender = mock_response(monkeypatch, {"output": {"text": "Check the roof."}})
    result = speech_client().transcribe_short_audio(b"audio-bytes", audio_format="m4a", sample_rate=44100, duration_seconds=8)
    body = json.loads(sender.call_args.args[0].data)
    encoded = body["input"]["messages"][0]["content"][0]["input_audio"]["data"]
    assert encoded == "data:audio/mp4;base64," + base64.b64encode(b"audio-bytes").decode("ascii")
    assert body["parameters"] == {"format": "m4a", "sample_rate": "44100"}
    assert result.text == "Check the roof."


@pytest.mark.parametrize("output", [{}, {"text": " "}, {"text": 123}, {"text": "Text", "sentences": [{"begin_time": 2, "end_time": 1, "text": "Text"}]}])
def test_invalid_transcript_is_rejected(monkeypatch, output) -> None:
    mock_response(monkeypatch, {"output": output})
    with pytest.raises(RuntimeError, match="invalid speech transcript"):
        speech_client().transcribe_short("https://storage.example/note.wav", audio_format="wav", sample_rate=16000, duration_seconds=30)


def test_long_short_recording_is_rejected_before_network(monkeypatch) -> None:
    sender = mock_response(monkeypatch, {})
    with pytest.raises(ValueError, match="five minutes"):
        speech_client().transcribe_short("https://storage.example/note.wav", audio_format="wav", sample_rate=16000, duration_seconds=301)
    sender.assert_not_called()


def test_file_submission_and_task_polling(monkeypatch) -> None:
    task_id = uuid4()
    sender = mock_response(monkeypatch, {"output": {"task_id": str(task_id), "task_status": "PENDING"}})
    client = speech_client()
    task = client.submit_file("https://storage.example/conversation.m4a", diarization=True)
    request = sender.call_args.args[0]
    assert request.get_header("X-dashscope-async") == "enable"
    assert request.full_url.endswith("/api/v1/services/audio/asr/transcription")
    assert json.loads(request.data)["input"] == {"file_urls": ["https://storage.example/conversation.m4a"]}
    assert json.loads(request.data)["parameters"] == {"diarization_enabled": True}
    assert task.task_id == task_id
    sender = mock_response(monkeypatch, {"output": {"task_id": str(task_id), "task_status": "SUCCEEDED", "results": [{
        "subtask_status": "SUCCEEDED", "transcription_url": "https://results.example/transcript.json",
    }]}})
    task = client.get_task(task_id)
    assert task.task_status == "SUCCEEDED"
    assert sender.call_args.args[0].get_method() == "GET"
    assert sender.call_args.args[0].full_url.endswith(f"/tasks/{task_id}")


def test_failed_subtask_cannot_be_treated_as_success(monkeypatch) -> None:
    mock_response(monkeypatch, {"output": {"task_id": str(uuid4()), "task_status": "SUCCEEDED", "results": [{"subtask_status": "FAILED"}]}})
    with pytest.raises(RuntimeError, match="invalid speech task"):
        speech_client().get_task(uuid4())


def test_file_transcript_preserves_speaker_and_millisecond_offsets() -> None:
    transcript = speech_client().parse_file_transcript({"transcripts": [{
        "channel_id": 0, "text": "Check this window.",
        "sentences": [{"begin_time": 100, "end_time": 1800, "text": "Check this window.", "speaker_id": 1}],
    }]})
    assert transcript.segments[0].begin_time == 100
    assert transcript.segments[0].speaker_id == 1
    assert transcript.requires_human_review is True