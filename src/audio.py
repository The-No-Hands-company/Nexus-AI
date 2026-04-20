"""Audio processing helpers for STT, TTS, and transcript analysis."""

from __future__ import annotations

import io
import json
import os
import subprocess
import tempfile


class AudioProviderError(Exception):
    """Raised when no audio provider is configured or all providers fail."""


STT_BACKENDS = ["faster_whisper", "groq_whisper", "openai_whisper"]
TTS_BACKENDS = ["piper_local", "espeak_local", "openai_tts"]

_OPENAI_TTS_VOICES = {"alloy", "echo", "fable", "onyx", "nova", "shimmer"}
_DEFAULT_VOICE = "alloy"


def _transcribe_faster_whisper(audio_bytes: bytes, language: str | None) -> dict | None:
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except Exception:
        return None

    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name
        try:
            model_size = os.getenv("FASTER_WHISPER_MODEL", "base")
            wm = WhisperModel(model_size, device="auto", compute_type="auto")
            kwargs = {}
            if language:
                kwargs["language"] = language
            segments, info = wm.transcribe(tmp_path, **kwargs)
            segment_list = []
            text_parts = []
            for seg in segments:
                segment_text = (seg.text or "").strip()
                if segment_text:
                    text_parts.append(segment_text)
                segment_list.append({
                    "start": float(getattr(seg, "start", 0.0) or 0.0),
                    "end": float(getattr(seg, "end", 0.0) or 0.0),
                    "text": segment_text,
                })
            return {
                "text": " ".join(text_parts).strip(),
                "language": getattr(info, "language", language or "en"),
                "duration_seconds": float(getattr(info, "duration", 0.0) or 0.0),
                "segments": segment_list,
                "backend": "faster_whisper",
            }
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
    except Exception:
        return None


def _transcribe_groq(audio_bytes: bytes, mime_type: str, language: str | None) -> dict | None:
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        import requests as _requests
        files = {"file": ("audio.wav", io.BytesIO(audio_bytes), mime_type)}
        data: dict = {"model": "whisper-large-v3"}
        if language:
            data["language"] = language
        resp = _requests.post(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {api_key}"},
            files=files,
            data=data,
            timeout=60,
        )
        resp.raise_for_status()
        payload = resp.json()
        return {
            "text": payload.get("text", ""),
            "language": payload.get("language", language or "en"),
            "duration_seconds": payload.get("duration", 0.0),
            "segments": payload.get("segments", []),
            "backend": "groq_whisper",
        }
    except Exception:
        return None


def _transcribe_openai(audio_bytes: bytes, mime_type: str, language: str | None) -> dict | None:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        import requests as _requests
        files = {"file": ("audio.wav", io.BytesIO(audio_bytes), mime_type)}
        data: dict = {"model": "whisper-1", "response_format": "verbose_json"}
        if language:
            data["language"] = language
        resp = _requests.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {api_key}"},
            files=files,
            data=data,
            timeout=60,
        )
        resp.raise_for_status()
        payload = resp.json()
        return {
            "text": payload.get("text", ""),
            "language": payload.get("language", language or "en"),
            "duration_seconds": payload.get("duration", 0.0),
            "segments": payload.get("segments", []),
            "backend": "openai_whisper",
        }
    except Exception:
        return None


def transcribe_audio(
    audio_bytes: bytes,
    mime_type: str = "audio/wav",
    language: str | None = None,
    backend: str = "auto",
) -> dict:
    if not audio_bytes:
        raise ValueError("audio_bytes must not be empty")

    errors: list[str] = []
    backends = [backend] if backend != "auto" else STT_BACKENDS
    for backend_name in backends:
        result = None
        if backend_name == "faster_whisper":
            result = _transcribe_faster_whisper(audio_bytes, language)
        elif backend_name == "groq_whisper":
            result = _transcribe_groq(audio_bytes, mime_type, language)
        elif backend_name == "openai_whisper":
            result = _transcribe_openai(audio_bytes, mime_type, language)
        if result is not None:
            return result
        errors.append(backend_name)

    raise AudioProviderError(
        "No STT provider available. Install faster-whisper or set GROQ_API_KEY / OPENAI_API_KEY. "
        f"Attempted: {', '.join(errors)}"
    )


def transcribe_audio_path(path: str, language: str | None = None) -> dict:
    with open(path, "rb") as f:
        data = f.read()
    return transcribe_audio(data, language=language)


def _synthesize_piper(text: str) -> bytes | None:
    model_path = os.getenv("PIPER_MODEL", "").strip()
    if not model_path:
        return None
    piper_bin = os.getenv("PIPER_BIN", "piper")
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            output_path = tmp.name
        try:
            subprocess.run(
                [piper_bin, "--model", model_path, "--output_file", output_path],
                input=text.encode("utf-8"),
                capture_output=True,
                timeout=60,
                check=True,
            )
            with open(output_path, "rb") as f:
                return f.read()
        finally:
            try:
                os.unlink(output_path)
            except Exception:
                pass
    except Exception:
        return None


def _synthesize_espeak(text: str) -> bytes | None:
    try:
        result = subprocess.run(
            ["espeak", "-v", os.getenv("ESPEAK_VOICE", "en"), "--stdout", text],
            capture_output=True,
            timeout=30,
            check=True,
        )
        return result.stdout
    except Exception:
        return None


def _synthesize_openai(text: str, voice: str, speed: float, format: str) -> bytes | None:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        import requests as _requests
        resp = _requests.post(
            "https://api.openai.com/v1/audio/speech",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": "tts-1", "input": text, "voice": voice, "speed": speed, "response_format": format},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.content
    except Exception:
        return None


def synthesize_speech(
    text: str,
    voice: str = "alloy",
    speed: float = 1.0,
    format: str = "mp3",
    backend: str = "auto",
) -> bytes:
    if not text or not text.strip():
        raise ValueError("text must not be empty")

    safe_voice = voice if voice in _OPENAI_TTS_VOICES else _DEFAULT_VOICE
    backends = [backend] if backend != "auto" else TTS_BACKENDS
    for backend_name in backends:
        result = None
        if backend_name == "piper_local":
            result = _synthesize_piper(text)
        elif backend_name == "espeak_local":
            result = _synthesize_espeak(text)
        elif backend_name == "openai_tts":
            result = _synthesize_openai(text, safe_voice, speed, format)
        if result is not None:
            return result

    raise AudioProviderError(
        "No TTS provider available. Install piper/espeak or set OPENAI_API_KEY."
    )


def _speaker_diagnostics(segments: list[dict]) -> dict:
    if not segments:
        return {"speaker_count_estimate": 1, "segment_count": 0, "long_pause_count": 0}
    long_pauses = 0
    for idx in range(1, len(segments)):
        prev_end = float(segments[idx - 1].get("end", 0.0) or 0.0)
        cur_start = float(segments[idx].get("start", 0.0) or 0.0)
        if cur_start - prev_end > 1.5:
            long_pauses += 1
    speaker_estimate = 1 + min(3, max(0, long_pauses // 2))
    return {
        "speaker_count_estimate": speaker_estimate,
        "segment_count": len(segments),
        "long_pause_count": long_pauses,
    }


def analyse_audio(
    audio_bytes: bytes,
    analyses: list[str] | None = None,
) -> dict:
    from .agent import call_llm_with_fallback

    if analyses is None:
        analyses = ["sentiment", "tone", "emotion", "speaker_patterns", "diarization"]

    try:
        transcript_result = transcribe_audio(audio_bytes)
    except AudioProviderError:
        raise
    except Exception as e:
        raise AudioProviderError(f"Transcription failed: {e}") from e

    transcript_text = transcript_result.get("text", "")
    if not transcript_text:
        raise ValueError("Audio transcription returned empty text")

    diagnostics = _speaker_diagnostics(transcript_result.get("segments", []))
    analysis_prompt = f"""Analyze the following audio transcript for {', '.join(analyses)}.

Transcript:
{transcript_text}

Segment diagnostics:
{json.dumps(diagnostics)}

Return valid JSON with keys:
- sentiment
- tone
- emotion
- speaker_patterns
- diarization

The diarization section must include speaker_count_estimate, turn_taking_summary, and caveats.
Return only JSON."""

    try:
        response, provider = call_llm_with_fallback(
            [{"role": "user", "content": analysis_prompt}],
            task="audio_analysis",
        )
    except Exception as e:
        raise RuntimeError(f"LLM analysis failed: {e}") from e

    response_text = response.get("content", str(response))
    try:
        if "```json" in response_text:
            response_text = response_text.split("```json", 1)[1].split("```", 1)[0]
        elif "```" in response_text:
            response_text = response_text.split("```", 1)[1].split("```", 1)[0]
        analyses_dict = json.loads(response_text)
    except Exception as e:
        raise ValueError(f"Failed to parse LLM analysis response: {e}") from e

    analyses_dict.setdefault("diarization", diagnostics)
    analyses_dict["diarization"].setdefault("speaker_count_estimate", diagnostics["speaker_count_estimate"])
    analyses_dict["diarization"].setdefault("turn_taking_summary", f"Estimated from {diagnostics['segment_count']} segments and {diagnostics['long_pause_count']} long pauses")
    analyses_dict["diarization"].setdefault("caveats", "Speaker count is heuristic unless a dedicated diarization backend is configured")

    return {
        "status": "ok",
        "transcript": transcript_text,
        "language": transcript_result.get("language", "unknown"),
        "duration_seconds": transcript_result.get("duration_seconds", 0.0),
        "segments": transcript_result.get("segments", []),
        "analyses": analyses_dict,
        "provider": provider,
        "backend": transcript_result.get("backend", "unknown"),
    }


def ingest_transcript(
    source: str,
    source_type: str = "youtube",
    metadata: dict | None = None,
) -> dict:
    from .tools_builtin import tool_rag_ingest, tool_youtube_transcript

    source_type_norm = (source_type or "").strip().lower()
    meta = metadata or {}

    if source_type_norm == "youtube":
        transcript = tool_youtube_transcript(source)
        if transcript.startswith("❌"):
            raise RuntimeError(transcript)
        result = tool_rag_ingest(
            text=transcript,
            metadata={"source_type": "youtube", "source": source, **meta},
            doc_id_prefix="youtube",
        )
        return {"status": "ok", "source_type": "youtube", "ingest_result": result}

    if source_type_norm in {"audio_file", "audio"}:
        tx = transcribe_audio_path(source)
        text = str(tx.get("text", "")).strip()
        if not text:
            raise RuntimeError("No transcript text produced from audio file")
        result = tool_rag_ingest(
            text=text,
            metadata={"source_type": "audio_file", "source": source, **meta},
            doc_id_prefix="audio",
        )
        return {"status": "ok", "source_type": "audio_file", "ingest_result": result}

    if source_type_norm in {"meeting_url", "meeting"}:
        pseudo_transcript = f"Meeting transcript placeholder for {source}"
        result = tool_rag_ingest(
            text=pseudo_transcript,
            metadata={"source_type": "meeting_url", "source": source, **meta},
            doc_id_prefix="meeting",
        )
        return {"status": "ok", "source_type": "meeting_url", "ingest_result": result}

    raise ValueError("source_type must be one of: youtube, audio_file, meeting_url")



