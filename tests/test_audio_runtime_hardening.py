import base64
import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app import app
import src.audio as audio


client = TestClient(app)


def _fake_transcribe(audio_bytes: bytes, mime_type: str = "audio/wav", language: str | None = None, backend: str = "auto") -> dict:
    mapping = {
        b"analysis": {
            "text": "We are calm and happy.",
            "language": language or "en",
            "duration_seconds": 1.5,
            "segments": [{"start": 0.0, "end": 1.5, "text": "We are calm and happy."}],
            "backend": "stub_whisper",
        },
        b"chunk-1": {
            "text": "hello",
            "language": language or "en",
            "duration_seconds": 0.7,
            "segments": [{"start": 0.0, "end": 0.7, "text": "hello"}],
            "backend": "stub_whisper",
        },
        b"chunk-2": {
            "text": "world",
            "language": language or "en",
            "duration_seconds": 0.8,
            "segments": [{"start": 0.0, "end": 0.8, "text": "world"}],
            "backend": "stub_whisper",
        },
        b"chunk-1chunk-2": {
            "text": "hello world",
            "language": language or "en",
            "duration_seconds": 2.9,
            "segments": [
                {"start": 0.0, "end": 0.7, "text": "hello"},
                {"start": 2.2, "end": 2.9, "text": "world"},
            ],
            "backend": "stub_whisper",
        },
        b"full-audio": {
            "text": "speaker one checks in speaker two responds",
            "language": language or "en",
            "duration_seconds": 3.4,
            "segments": [
                {"start": 0.0, "end": 1.2, "text": "speaker one checks in"},
                {"start": 2.4, "end": 3.4, "text": "speaker two responds"},
            ],
            "backend": "stub_whisper",
        },
    }
    if audio_bytes not in mapping:
        raise AssertionError(f"unexpected audio bytes: {audio_bytes!r}")
    return mapping[audio_bytes]


def setup_function():
    audio._STREAM_SESSIONS.clear()


def test_audio_analyse_route_exposes_emotion_and_speaker_metadata(monkeypatch):
    monkeypatch.setattr(audio, "transcribe_audio", _fake_transcribe)

    encoded = base64.b64encode(b"analysis").decode("ascii")
    response = client.post(
        "/audio/analyse",
        json={
            "audio_base64": encoded,
            "voice_profile_base64": encoded,
            "analyses": ["emotion", "diarization", "speaker_identification"],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["analyses"]["emotion"]["primary"] in {"calm", "neutral", "excited"}
    assert payload["analyses"]["speaker_identification"]["match"] is True
    assert payload["transcript_with_speakers"].startswith("SPEAKER_01:")


def test_audio_stream_chunk_persists_session_and_finalizes(monkeypatch):
    monkeypatch.setattr(audio, "transcribe_audio", _fake_transcribe)

    first = client.post(
        "/audio/stream-chunk",
        json={"audio_chunk_base64": base64.b64encode(b"chunk-1").decode("ascii")},
    )
    assert first.status_code == 200
    first_payload = first.json()
    assert first_payload["ok"] is True
    assert first_payload["partial"] == "hello"
    assert first_payload["is_final"] is False

    second = client.post(
        "/audio/stream-chunk",
        json={
            "audio_chunk_base64": base64.b64encode(b"chunk-2").decode("ascii"),
            "session_id": first_payload["session_id"],
            "finalize": True,
            "diarize": True,
            "identify_speaker": True,
            "voice_profile_base64": base64.b64encode(b"chunk-1chunk-2").decode("ascii"),
            "speaker_name": "caller-a",
        },
    )
    assert second.status_code == 200
    payload = second.json()
    assert payload["ok"] is True
    assert payload["is_final"] is True
    assert payload["final_transcript"] == "hello world"
    assert payload["diarization"]["ok"] is True
    assert payload["speaker_identification"]["match"] is True
    assert "SPEAKER_01:" in payload["transcript_with_speakers"]
    assert payload["session_summary"]["chunk_count"] == 2


def test_v1_audio_transcriptions_can_return_speaker_labels(monkeypatch):
    monkeypatch.setattr(audio, "transcribe_audio", _fake_transcribe)

    response = client.post(
        "/v1/audio/transcriptions",
        files={"file": ("sample.wav", b"full-audio", "audio/wav")},
        data={
            "response_format": "verbose_json",
            "include_diarization": "true",
            "include_speaker_labels": "true",
            "voice_profile_base64": base64.b64encode(b"full-audio").decode("ascii"),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["text"] == "speaker one checks in speaker two responds"
    assert payload["diarization"]["ok"] is True
    assert payload["speaker_identification"]["match"] is True
    assert payload["transcript_with_speakers"].count("SPEAKER_") >= 2
