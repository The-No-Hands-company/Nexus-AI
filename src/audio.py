"""
src/audio.py — Audio processing (STT, TTS, audio analysis)

Provider delegation:
  STT: Groq Whisper → OpenAI Whisper (in priority order)
  TTS: OpenAI TTS-1 → (future: Kokoro local, ElevenLabs)

Set GROQ_API_KEY and/or OPENAI_API_KEY environment variables to enable live
provider calls.  When no provider key is present, AudioProviderError is raised
and the route converts it to a structured 503 with retry guidance.
"""

from __future__ import annotations

import io
import os
from typing import Optional


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class AudioProviderError(Exception):
    """Raised when no audio provider is configured or all providers fail."""


# ---------------------------------------------------------------------------
# Speech-to-text (STT)
# ---------------------------------------------------------------------------

STT_BACKENDS = ["groq_whisper", "openai_whisper"]


def transcribe_audio(
    audio_bytes: bytes,
    mime_type: str = "audio/wav",
    language: str | None = None,
    backend: str = "auto",
) -> dict:
    """
    Transcribe audio bytes to text.

    Returns::

        {
            "text": str,
            "language": str,
            "duration_seconds": float,
            "segments": [{"start": float, "end": float, "text": str}]
        }

    Provider priority (``backend="auto"``):
      1. Groq Whisper API   (GROQ_API_KEY)
      2. OpenAI Whisper API (OPENAI_API_KEY)

    Raises ``AudioProviderError`` when no provider is available.
    """
    if not audio_bytes:
        raise ValueError("audio_bytes must not be empty")

    errors: list[str] = []

    if backend in ("auto", "groq_whisper"):
        result = _transcribe_groq(audio_bytes, mime_type, language)
        if result is not None:
            return result
        errors.append("groq_whisper: GROQ_API_KEY not set or request failed")

    if backend in ("auto", "openai_whisper"):
        result = _transcribe_openai(audio_bytes, mime_type, language)
        if result is not None:
            return result
        errors.append("openai_whisper: OPENAI_API_KEY not set or request failed")

    raise AudioProviderError(
        "No STT provider available. "
        "Set GROQ_API_KEY or OPENAI_API_KEY to enable audio transcription. "
        f"Attempted: {'; '.join(errors)}"
    )


def _transcribe_groq(audio_bytes: bytes, mime_type: str, language: str | None) -> dict | None:
    """Try Groq Whisper API. Returns dict on success, None if unavailable."""
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
        }
    except Exception:
        return None


def _transcribe_openai(audio_bytes: bytes, mime_type: str, language: str | None) -> dict | None:
    """Try OpenAI Whisper API. Returns dict on success, None if unavailable."""
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
        }
    except Exception:
        return None


def transcribe_audio_path(path: str, language: str | None = None) -> dict:
    """Transcribe audio file at *path*."""
    with open(path, "rb") as f:
        data = f.read()
    return transcribe_audio(data, language=language)


# ---------------------------------------------------------------------------
# Text-to-speech (TTS)
# ---------------------------------------------------------------------------

TTS_BACKENDS = ["openai_tts", "kokoro_local", "coqui_local", "elevenlabs"]

_OPENAI_TTS_VOICES = {"alloy", "echo", "fable", "onyx", "nova", "shimmer"}
_DEFAULT_VOICE = "alloy"


def synthesize_speech(
    text: str,
    voice: str = "alloy",
    speed: float = 1.0,
    format: str = "mp3",
    backend: str = "auto",
) -> bytes:
    """
    Convert *text* to audio bytes.

    Returns raw audio bytes in the requested *format* (``"mp3"`` by default).

    Provider priority (``backend="auto"``):
      1. OpenAI TTS-1  (OPENAI_API_KEY)

    Raises ``AudioProviderError`` when no provider is available.
    """
    if not text or not text.strip():
        raise ValueError("text must not be empty")

    safe_voice = voice if voice in _OPENAI_TTS_VOICES else _DEFAULT_VOICE

    if backend in ("auto", "openai_tts"):
        result = _synthesize_openai(text, safe_voice, speed, format)
        if result is not None:
            return result

    raise AudioProviderError(
        "No TTS provider available. "
        "Set OPENAI_API_KEY to enable speech synthesis."
    )


def _synthesize_openai(text: str, voice: str, speed: float, format: str) -> bytes | None:
    """Try OpenAI TTS-1. Returns bytes on success, None if unavailable."""
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


# ---------------------------------------------------------------------------
# Audio analysis
# ---------------------------------------------------------------------------

def analyse_audio(
    audio_bytes: bytes,
    analyses: list[str] | None = None,
) -> dict:
    """
    Analyse audio for sentiment, diarization, speaker count, tone, etc.

    Transcribes the audio using Whisper, then sends the transcript to an LLM
    for analysis of sentiment, emotion, speaker characteristics, and tone.

    Args:
        audio_bytes: Raw audio bytes
        analyses: List of analysis types to perform (default: all)
                 ["sentiment", "tone", "emotion", "speaker_patterns"]

    Returns:
        {
            "status": "ok",
            "transcript": str,
            "language": str,
            "duration_seconds": float,
            "analyses": {
                "sentiment": {
                    "overall": "positive|neutral|negative",
                    "confidence": float,
                    "summary": str
                },
                "tone": {
                    "primary_tone": str,
                    "secondary_tones": [str],
                    "intensity": float,
                    "summary": str
                },
                "emotion": {
                    "primary": str,
                    "secondary": [str],
                    "confidence": float
                },
                "speaker_patterns": {
                    "speaking_style": str,
                    "pace": "slow|moderate|fast",
                    "clarity": float,
                    "formality": "casual|formal|professional"
                }
            }
        }
    """
    from .agent import call_llm_with_fallback
    import json as json_lib

    if analyses is None:
        analyses = ["sentiment", "tone", "emotion", "speaker_patterns"]

    # Step 1: Transcribe the audio
    try:
        transcript_result = transcribe_audio(audio_bytes)
    except AudioProviderError:
        raise
    except Exception as e:
        raise AudioProviderError(f"Transcription failed: {e}") from e

    transcript_text = transcript_result.get("text", "")
    if not transcript_text:
        raise ValueError("Audio transcription returned empty text")

    # Step 2: Build analysis prompt
    analyses_str = ", ".join(analyses)
    analysis_prompt = f"""Analyze the following audio transcript for: {analyses_str}

Transcript:
"{transcript_text}"

Provide a structured JSON analysis with the following schema:
{{
    "sentiment": {{
        "overall": "positive|neutral|negative",
        "confidence": <0.0-1.0>,
        "summary": "<brief explanation>"
    }},
    "tone": {{
        "primary_tone": "<main tone>",
        "secondary_tones": ["<tone1>", "<tone2>"],
        "intensity": <0.0-1.0>,
        "summary": "<brief explanation>"
    }},
    "emotion": {{
        "primary": "<main emotion>",
        "secondary": ["<emotion1>"],
        "confidence": <0.0-1.0>
    }},
    "speaker_patterns": {{
        "speaking_style": "<description>",
        "pace": "slow|moderate|fast",
        "clarity": <0.0-1.0>,
        "formality": "casual|formal|professional"
    }}
}}

Return ONLY valid JSON, no markdown code blocks."""

    # Step 3: Call LLM for analysis
    try:
        response, provider = call_llm_with_fallback(
            [{"role": "user", "content": analysis_prompt}],
            task="audio_analysis"
        )
    except Exception as e:
        raise RuntimeError(f"LLM analysis failed: {e}") from e

    # Extract JSON from response
    response_text = response.get("content", str(response))
    try:
        # Try to extract JSON from response (handle markdown code blocks)
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0]
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0]
        
        analyses_dict = json_lib.loads(response_text)
    except (json_lib.JSONDecodeError, IndexError) as e:
        raise ValueError(f"Failed to parse LLM analysis response: {e}") from e

    return {
        "status": "ok",
        "transcript": transcript_text,
        "language": transcript_result.get("language", "unknown"),
        "duration_seconds": transcript_result.get("duration_seconds", 0.0),
        "analyses": analyses_dict,
        "provider": provider,
    }


# ---------------------------------------------------------------------------
# Transcript ingestion pipeline
# ---------------------------------------------------------------------------

def ingest_transcript(
    source: str,
    source_type: str = "youtube",
    metadata: dict | None = None,
) -> dict:
    """Ingest transcript content into RAG using existing built-in tools."""
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



