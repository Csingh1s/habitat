from __future__ import annotations

import base64
import json
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl, model_validator

from .settings import Settings


class SpeechSegment(BaseModel):
    begin_time: int = Field(ge=0)
    end_time: int = Field(ge=0)
    text: str
    speaker_id: int | None = Field(default=None, ge=0)
    channel_id: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_times(self) -> SpeechSegment:
        if self.end_time < self.begin_time:
            raise ValueError("Speech segment ends before it begins.")
        return self


class SpeechTranscript(BaseModel):
    text: str = Field(min_length=1)
    segments: list[SpeechSegment] = Field(default_factory=list)
    model_id: str
    requires_human_review: Literal[True] = True


class SpeechTask(BaseModel):
    task_id: UUID
    task_status: Literal["PENDING", "RUNNING", "SUCCEEDED", "FAILED", "CANCELED", "UNKNOWN"]
    transcription_url: HttpUrl | None = None


class AlibabaSpeechClient:
    def __init__(self, settings: Settings) -> None:
        self._allowed = settings.remote_inference_allowed
        self._host = (settings.alibaba_model_studio_host or "").rstrip("/")
        self._api_key = settings.qwen_cloud_api_key
        self.model_id = settings.alibaba_speech_model_id
        self.file_model_id = settings.alibaba_speech_file_model_id

    @property
    def configured(self) -> bool:
        return bool(self._allowed and self._host and self._api_key)

    @property
    def unavailable_reason(self) -> str:
        if not self._allowed:
            return "Remote speech transcription is disabled. Local development never calls Alibaba Cloud."
        return "Set ALIBABA_MODEL_STUDIO_HOST and DASHSCOPE_API_KEY in the deployed API service."

    def _request(self, path: str, body: dict | None = None, *, asynchronous: bool = False) -> dict:
        if not self.configured:
            raise RuntimeError(self.unavailable_reason)
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        if asynchronous:
            headers["X-DashScope-Async"] = "enable"
        else:
            headers["X-DashScope-SSE"] = "disable"
        request = Request(
            f"{self._host}/api/v1/{path}",
            data=json.dumps(body).encode() if body is not None else None,
            headers=headers,
            method="POST" if body is not None else "GET",
        )
        try:
            with urlopen(request, timeout=60) as response:
                raw = response.read(4 * 1024 * 1024 + 1)
            if len(raw) > 4 * 1024 * 1024:
                raise ValueError("Speech response exceeds the size limit.")
            payload = json.loads(raw)
            if not isinstance(payload, dict) or payload.get("code"):
                raise ValueError("Speech service returned an error or invalid response.")
            return payload
        except (HTTPError, URLError, TimeoutError, ValueError) as error:
            raise RuntimeError("Alibaba speech request failed; no transcript was approved.") from error

    @staticmethod
    def _validate_audio_url(audio_url: str) -> None:
        parsed = urlsplit(audio_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ValueError("Audio must use a server-generated HTTPS storage URL.")

    def transcribe_short(
        self, audio_url: str, *, audio_format: str, sample_rate: int, duration_seconds: float,
    ) -> SpeechTranscript:
        self._validate_audio_url(audio_url)
        if not 0 < duration_seconds <= 300:
            raise ValueError("Short recordings must be at most five minutes; use file transcription for longer audio.")
        if audio_format not in {"aac", "amr", "flac", "m4a", "mp3", "ogg", "opus", "wav"} or sample_rate <= 0:
            raise ValueError("Provide a supported audio format and its actual sample rate.")
        payload = self._request("services/aigc/multimodal-generation/generation", {
            "model": self.model_id,
            "input": {"messages": [{"role": "user", "content": [{
                "type": "input_audio", "input_audio": {"data": audio_url},
            }]}]},
            "parameters": {"format": audio_format, "sample_rate": str(sample_rate)},
        })
        return self._parse_short_transcript(payload)

    def transcribe_short_audio(
        self, audio: bytes, *, audio_format: str, sample_rate: int, duration_seconds: float,
    ) -> SpeechTranscript:
        if not 0 < duration_seconds <= 300:
            raise ValueError("Short recordings must be at most five minutes.")
        if not audio or len(audio) > 5_000_000:
            raise ValueError("Audio must be between 1 byte and 5 MB.")
        if audio_format not in {"aac", "amr", "flac", "m4a", "mp3", "ogg", "opus", "wav"} or not 8_000 <= sample_rate <= 48_000:
            raise ValueError("Provide a supported audio format and its actual sample rate.")
        media_type = "audio/mp4" if audio_format == "m4a" else f"audio/{audio_format}"
        audio_data = f"data:{media_type};base64,{base64.b64encode(audio).decode('ascii')}"
        payload = self._request("services/aigc/multimodal-generation/generation", {
            "model": self.model_id,
            "input": {"messages": [{"role": "user", "content": [{
                "type": "input_audio", "input_audio": {"data": audio_data},
            }]}]},
            "parameters": {"format": audio_format, "sample_rate": str(sample_rate)},
        })
        return self._parse_short_transcript(payload)

    def _parse_short_transcript(self, payload: dict) -> SpeechTranscript:
        try:
            output = payload["output"]
            segments = output.get("sentences", [])
            return SpeechTranscript(text=output["text"].strip(), segments=segments, model_id=self.model_id)
        except (KeyError, TypeError, AttributeError, ValueError) as error:
            raise RuntimeError("Alibaba returned an invalid speech transcript.") from error

    def submit_file(self, audio_url: str, *, diarization: bool = False) -> SpeechTask:
        self._validate_audio_url(audio_url)
        payload = self._request("services/audio/asr/transcription", {
            "model": self.file_model_id,
            "input": {"file_urls": [audio_url]},
            "parameters": {"diarization_enabled": diarization},
        }, asynchronous=True)
        return self._parse_task(payload)

    def get_task(self, task_id: UUID) -> SpeechTask:
        expected_id = UUID(str(task_id))
        task = self._parse_task(self._request(f"tasks/{expected_id}"))
        if task.task_id != expected_id:
            raise RuntimeError("Alibaba returned a different speech task.")
        return task

    @staticmethod
    def _parse_task(payload: dict) -> SpeechTask:
        try:
            output = payload["output"]
            values = {"task_id": output["task_id"], "task_status": output["task_status"]}
            if output["task_status"] == "SUCCEEDED":
                results = output["results"]
                if len(results) != 1 or results[0].get("subtask_status") != "SUCCEEDED":
                    raise ValueError("The recording transcription did not succeed.")
                values["transcription_url"] = results[0]["transcription_url"]
            return SpeechTask.model_validate(values)
        except (KeyError, TypeError, IndexError, ValueError) as error:
            raise RuntimeError("Alibaba returned an invalid speech task.") from error

    def parse_file_transcript(self, payload: dict) -> SpeechTranscript:
        try:
            transcripts = payload["transcripts"]
            text = "\n".join(channel["text"].strip() for channel in transcripts).strip()
            segments = [
                SpeechSegment.model_validate({**sentence, "channel_id": channel["channel_id"]})
                for channel in transcripts for sentence in channel.get("sentences", [])
            ]
            return SpeechTranscript(text=text, segments=segments, model_id=self.file_model_id)
        except (KeyError, TypeError, AttributeError, ValueError) as error:
            raise RuntimeError("Alibaba returned an invalid file transcript.") from error