"""Audio processing helpers for STT, TTS, transcript analysis, diarization, and live voice sessions."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import math
import os
import subprocess
import tempfile
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)


class AudioProviderError(Exception):
    """Raised when no audio provider is configured or all providers fail."""


STT_BACKENDS = ["faster_whisper", "groq_whisper", "openai_whisper"]
TTS_BACKENDS = ["piper_local", "espeak_local", "openai_tts"]
_STREAM_SESSION_TTL_SECONDS = int(os.getenv("AUDIO_STREAM_SESSION_TTL_SECONDS", "1800"))
_MAX_STREAM_BUFFER_BYTES = int(os.getenv("AUDIO_STREAM_MAX_BUFFER_BYTES", str(4 * 1024 * 1024)))
_MAX_STREAM_CHUNKS = int(os.getenv("AUDIO_STREAM_MAX_CHUNKS", "128"))

_OPENAI_TTS_VOICES = {"alloy", "echo", "fable", "onyx", "nova", "shimmer"}
_DEFAULT_VOICE = "alloy"
_STREAM_SESSIONS: dict[str, dict[str, Any]] = {}

_POSITIVE_WORDS = {"great", "good", "happy", "excellent", "love", "success", "calm", "fine", "thanks", "awesome"}
_NEGATIVE_WORDS = {"bad", "sad", "angry", "upset", "issue", "error", "problem", "worried", "stress", "frustrated"}
_EXCITED_WORDS = {"wow", "amazing", "excited", "lets", "can't", "go", "great"}
_CONCERNED_WORDS = {"risk", "incident", "problem", "urgent", "worried", "alert", "blocked", "failed"}
_CALM_WORDS = {"steady", "normal", "okay", "calm", "routine", "stable", "clear"}


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
        data: dict[str, Any] = {"model": "whisper-large-v3"}
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
        data: dict[str, Any] = {"model": "whisper-1", "response_format": "verbose_json"}
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


def _normalize_segments(segments: list[dict] | None) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for segment in segments or []:
        normalized.append({
            "start": float(segment.get("start", 0.0) or 0.0),
            "end": float(segment.get("end", 0.0) or 0.0),
            "text": str(segment.get("text", "") or "").strip(),
        })
    return normalized


def _speaker_diagnostics(segments: list[dict]) -> dict:
    normalized = _normalize_segments(segments)
    if not normalized:
        return {"speaker_count_estimate": 1, "segment_count": 0, "long_pause_count": 0, "average_gap_seconds": 0.0}
    long_pauses = 0
    gap_total = 0.0
    for idx in range(1, len(normalized)):
        prev_end = normalized[idx - 1]["end"]
        cur_start = normalized[idx]["start"]
        gap = max(0.0, cur_start - prev_end)
        gap_total += gap
        if gap > 1.5:
            long_pauses += 1
    speaker_estimate = 1 + min(3, max(0, long_pauses // 2))
    return {
        "speaker_count_estimate": speaker_estimate,
        "segment_count": len(normalized),
        "long_pause_count": long_pauses,
        "average_gap_seconds": round(gap_total / max(1, len(normalized) - 1), 3),
    }


def _word_hits(text: str, lexicon: set[str]) -> int:
    tokens = [token.strip(".,!?;:\"'()[]{}") for token in text.lower().split()]
    return sum(1 for token in tokens if token in lexicon)


def _infer_sentiment(text: str) -> dict[str, Any]:
    pos = _word_hits(text, _POSITIVE_WORDS)
    neg = _word_hits(text, _NEGATIVE_WORDS)
    score = 0.0
    if pos or neg:
        score = (pos - neg) / max(1, pos + neg)
    label = "neutral"
    if score >= 0.2:
        label = "positive"
    elif score <= -0.2:
        label = "negative"
    return {"label": label, "score": round(score, 3), "positive_hits": pos, "negative_hits": neg}


def _infer_emotion(text: str) -> dict[str, Any]:
    excited = _word_hits(text, _EXCITED_WORDS)
    concerned = _word_hits(text, _CONCERNED_WORDS)
    calm = _word_hits(text, _CALM_WORDS)
    exclamations = text.count("!")
    energy = min(1.0, round((excited + exclamations + max(0, len(text.split()) - 20) / 20) / 6, 3))
    candidates = {
        "excited": excited + exclamations,
        "concerned": concerned,
        "calm": calm,
    }
    primary = max(candidates, key=candidates.get)
    if candidates[primary] == 0:
        primary = "neutral"
    return {
        "primary": primary,
        "energy": energy,
        "candidates": {k: int(v) for k, v in candidates.items()},
    }


def _infer_tone(text: str) -> dict[str, Any]:
    sentiment = _infer_sentiment(text)
    emotion = _infer_emotion(text)
    tone = "neutral"
    if emotion["primary"] == "excited":
        tone = "energetic"
    elif emotion["primary"] == "concerned":
        tone = "concerned"
    elif emotion["primary"] == "calm":
        tone = "steady"
    elif sentiment["label"] == "positive":
        tone = "supportive"
    elif sentiment["label"] == "negative":
        tone = "tense"
    return {"label": tone, "sentiment": sentiment["label"], "energy": emotion["energy"]}


def _build_turn_taking_summary(segments: list[dict[str, Any]]) -> str:
    if not segments:
        return "No speech segments detected."
    if len(segments) == 1:
        return "Single continuous speaking turn detected."
    speakers = [str(segment.get("speaker") or "SPEAKER_01") for segment in segments]
    changes = 0
    for idx in range(1, len(speakers)):
        if speakers[idx] != speakers[idx - 1]:
            changes += 1
    return f"Detected {len(segments)} spoken turns with {changes} speaker transitions."


def _label_transcript_with_speakers(segments: list[dict[str, Any]]) -> str:
    lines = []
    for segment in segments:
        text = str(segment.get("text", "") or "").strip()
        if not text:
            continue
        speaker = str(segment.get("speaker") or "SPEAKER_01")
        lines.append(f"{speaker}: {text}")
    return "\n".join(lines).strip()


def _heuristic_audio_analysis(transcript_text: str, segments: list[dict[str, Any]], diarization: dict[str, Any], speaker_identification: dict[str, Any] | None = None) -> dict[str, Any]:
    sentiment = _infer_sentiment(transcript_text)
    emotion = _infer_emotion(transcript_text)
    tone = _infer_tone(transcript_text)
    speaker_patterns = {
        "turn_taking_summary": _build_turn_taking_summary(diarization.get("segments", [])),
        "segment_count": len(segments),
        "speaker_count_estimate": diarization.get("speaker_count", diarization.get("speaker_count_estimate", 1)),
    }
    payload = {
        "sentiment": sentiment,
        "tone": tone,
        "emotion": emotion,
        "speaker_patterns": speaker_patterns,
        "diarization": {
            "speaker_count_estimate": diarization.get("speaker_count", diarization.get("speaker_count_estimate", 1)),
            "turn_taking_summary": speaker_patterns["turn_taking_summary"],
            "caveats": diarization.get("caveat") or "Heuristic speaker segmentation; install pyannote.audio for higher diarization accuracy.",
        },
    }
    if speaker_identification is not None:
        payload["speaker_identification"] = speaker_identification
    return payload


def _extract_voice_features(audio_bytes: bytes) -> tuple[list[float], str]:
    try:
        import librosa  # type: ignore
        import numpy as np  # type: ignore
        y, sr = librosa.load(io.BytesIO(audio_bytes), sr=16000)
        mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
        vector = mfcc.mean(axis=1).astype(float).tolist()
        return vector, "librosa_mfcc"
    except Exception:
        if not audio_bytes:
            return [], "byte_fingerprint"
        sample = audio_bytes[: min(len(audio_bytes), 65536)]
        buckets = [0.0] * 16
        for idx, value in enumerate(sample):
            buckets[idx % 16] += value / 255.0
        total = sum(buckets)
        if total > 0:
            buckets = [bucket / total for bucket in buckets]
        return buckets, "byte_fingerprint"


def _cosine_similarity(vector_a: list[float], vector_b: list[float]) -> float:
    if not vector_a or not vector_b:
        return 0.0
    length = min(len(vector_a), len(vector_b))
    a = vector_a[:length]
    b = vector_b[:length]
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def diarize_audio(audio_bytes: bytes, num_speakers: int | None = None) -> dict:
    """Perform speaker diarization on audio bytes."""
    hf_token = os.environ.get("HF_TOKEN", "")

    if hf_token:
        try:
            from pyannote.audio import Pipeline  # type: ignore
            pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1",
                use_auth_token=hf_token,
            )
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name
            try:
                params: dict[str, Any] = {}
                if num_speakers:
                    params["num_speakers"] = num_speakers
                diarization = pipeline(tmp_path, **params)
                segments = []
                speakers: set[str] = set()
                for turn, _, speaker in diarization.itertracks(yield_label=True):
                    segments.append({
                        "start": round(turn.start, 3),
                        "end": round(turn.end, 3),
                        "speaker": speaker,
                    })
                    speakers.add(speaker)
                return {
                    "ok": True,
                    "segments": segments,
                    "speakers": sorted(speakers),
                    "speaker_count": len(speakers),
                    "backend": "pyannote",
                    "turn_taking_summary": _build_turn_taking_summary(segments),
                    "confidence": 0.95,
                }
            finally:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
        except ImportError:
            pass
        except Exception as exc:
            logger.warning("pyannote diarization failed: %s", exc)

    try:
        transcript_result = transcribe_audio(audio_bytes)
        segments_raw = _normalize_segments(transcript_result.get("segments", []))
        speaker_segments = []
        current_speaker = 1
        prev_end = 0.0
        speakers_used: set[int] = {1}

        for segment in segments_raw:
            start = float(segment.get("start", 0.0))
            end_t = float(segment.get("end", 0.0))
            gap = start - prev_end
            if gap > 1.5 and current_speaker < (num_speakers or 6):
                current_speaker += 1
                speakers_used.add(current_speaker)
            speaker_segments.append({
                "start": round(start, 3),
                "end": round(end_t, 3),
                "speaker": f"SPEAKER_{current_speaker:02d}",
                "text": segment.get("text", ""),
            })
            prev_end = end_t

        speaker_labels = [f"SPEAKER_{idx:02d}" for idx in sorted(speakers_used)]
        return {
            "ok": True,
            "segments": speaker_segments,
            "speakers": speaker_labels,
            "speaker_count": len(speaker_labels),
            "backend": "heuristic",
            "caveat": "Heuristic diarization; install pyannote.audio for production-grade diarization accuracy.",
            "turn_taking_summary": _build_turn_taking_summary(speaker_segments),
            "confidence": 0.55,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "segments": [], "speakers": [], "backend": "failed"}


def identify_speaker(
    audio_bytes: bytes,
    voice_profile_bytes: bytes | None = None,
    known_profiles: list[dict[str, Any]] | None = None,
) -> dict:
    """Attempt speaker identification by matching against one or more voice profiles."""
    input_features, backend = _extract_voice_features(audio_bytes)
    if not input_features:
        return {"ok": False, "error": "Could not extract audio features", "backend": backend}

    candidates: list[dict[str, Any]] = []

    if voice_profile_bytes:
        profile_features, profile_backend = _extract_voice_features(voice_profile_bytes)
        if profile_features:
            candidates.append({
                "profile_id": "provided_profile",
                "features": profile_features,
                "backend": profile_backend,
                "label": "provided_profile",
            })

    for profile in known_profiles or []:
        raw_bytes = profile.get("voice_profile_bytes")
        raw_features = profile.get("features")
        features: list[float] = []
        candidate_backend = profile.get("backend") or backend
        if isinstance(raw_features, list) and raw_features:
            features = [float(item) for item in raw_features]
        elif isinstance(raw_bytes, (bytes, bytearray)):
            features, candidate_backend = _extract_voice_features(bytes(raw_bytes))
        if features:
            candidates.append({
                "profile_id": str(profile.get("profile_id") or profile.get("speaker_name") or f"profile_{len(candidates)+1}"),
                "features": features,
                "backend": candidate_backend,
                "label": str(profile.get("speaker_name") or profile.get("profile_id") or "known_speaker"),
            })

    scored_candidates = []
    for candidate in candidates:
        similarity = round(_cosine_similarity(input_features, candidate["features"]), 4)
        scored_candidates.append({
            "profile_id": candidate["profile_id"],
            "label": candidate["label"],
            "similarity": similarity,
            "backend": candidate["backend"],
        })

    scored_candidates.sort(key=lambda item: item["similarity"], reverse=True)
    best = scored_candidates[0] if scored_candidates else None
    threshold = 0.85 if backend == "librosa_mfcc" else 0.98
    return {
        "ok": True,
        "backend": backend,
        "match": bool(best and best["similarity"] >= threshold),
        "best_match": best,
        "threshold": threshold,
        "features": input_features,
        "candidates": scored_candidates,
        "note": "Provide or register voice profiles to enable stable speaker matching." if not scored_candidates else "Compared against supplied speaker profiles.",
    }


def analyse_audio(
    audio_bytes: bytes,
    analyses: list[str] | None = None,
    voice_profile_bytes: bytes | None = None,
) -> dict:
    if analyses is None:
        analyses = ["sentiment", "tone", "emotion", "speaker_patterns", "diarization", "speaker_identification"]

    try:
        transcript_result = transcribe_audio(audio_bytes)
    except AudioProviderError:
        raise
    except Exception as exc:
        raise AudioProviderError(f"Transcription failed: {exc}") from exc

    transcript_text = str(transcript_result.get("text", "") or "").strip()
    if not transcript_text:
        raise ValueError("Audio transcription returned empty text")

    segments = _normalize_segments(transcript_result.get("segments", []))
    diarization = diarize_audio(audio_bytes)
    speaker_identification = None
    if voice_profile_bytes is not None:
        speaker_identification = identify_speaker(audio_bytes, voice_profile_bytes=voice_profile_bytes)

    heuristic_payload = _heuristic_audio_analysis(
        transcript_text,
        segments,
        diarization,
        speaker_identification=speaker_identification,
    )

    provider = "heuristic"
    try:
        from .agent import call_llm_with_fallback
        analysis_prompt = f"""Analyze the following audio transcript for {', '.join(analyses)}.

Transcript:
{transcript_text}

Segment diagnostics:
{json.dumps(_speaker_diagnostics(segments))}

Heuristic baseline:
{json.dumps(heuristic_payload)}

Return valid JSON with keys:
- sentiment
- tone
- emotion
- speaker_patterns
- diarization
- speaker_identification

Return only JSON."""
        response, provider = call_llm_with_fallback(
            [{"role": "user", "content": analysis_prompt}],
            task="audio_analysis",
        )
        response_text = response.get("content", str(response))
        if "```json" in response_text:
            response_text = response_text.split("```json", 1)[1].split("```", 1)[0]
        elif "```" in response_text:
            response_text = response_text.split("```", 1)[1].split("```", 1)[0]
        analyses_dict = json.loads(response_text)
    except Exception:
        analyses_dict = heuristic_payload
        provider = "heuristic"

    analyses_dict.setdefault("sentiment", heuristic_payload["sentiment"])
    analyses_dict.setdefault("tone", heuristic_payload["tone"])
    analyses_dict.setdefault("emotion", heuristic_payload["emotion"])
    analyses_dict.setdefault("speaker_patterns", heuristic_payload["speaker_patterns"])
    analyses_dict.setdefault("diarization", heuristic_payload["diarization"])
    if speaker_identification is not None:
        analyses_dict.setdefault("speaker_identification", speaker_identification)

    return {
        "status": "ok",
        "transcript": transcript_text,
        "language": transcript_result.get("language", "unknown"),
        "duration_seconds": transcript_result.get("duration_seconds", 0.0),
        "segments": segments,
        "analyses": analyses_dict,
        "provider": provider,
        "backend": transcript_result.get("backend", "unknown"),
        "transcript_with_speakers": _label_transcript_with_speakers(diarization.get("segments", [])),
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


def _prune_stream_sessions() -> None:
    cutoff = time.time() - _STREAM_SESSION_TTL_SECONDS
    stale = [session_id for session_id, session in _STREAM_SESSIONS.items() if float(session.get("updated_at", 0.0)) < cutoff]
    for session_id in stale:
        _STREAM_SESSIONS.pop(session_id, None)


def _get_or_create_stream_session(session_id: str | None = None) -> dict[str, Any]:
    _prune_stream_sessions()
    sid = (session_id or "").strip() or f"audio-{uuid.uuid4().hex[:12]}"
    session = _STREAM_SESSIONS.get(sid)
    if session is None:
        session = {
            "session_id": sid,
            "partial": "",
            "combined_audio": bytearray(),
            "chunk_count": 0,
            "created_at": time.time(),
            "updated_at": time.time(),
            "known_profiles": [],
            "history": [],
        }
        _STREAM_SESSIONS[sid] = session
    return session


def stream_transcribe_chunk(
    audio_chunk: bytes,
    session_state: dict | None = None,
    *,
    session_id: str = "",
    language: str | None = None,
    finalize: bool = False,
    diarize: bool = False,
    identify_speaker_enabled: bool = False,
    voice_profile_bytes: bytes | None = None,
    speaker_name: str = "",
) -> dict:
    """Transcribe streaming chunks with server-side session state and optional final labeling."""
    if not audio_chunk:
        return {"ok": False, "error": "audio_chunk must not be empty", "text": "", "is_final": False}

    incoming_state = dict(session_state or {})
    session = _get_or_create_stream_session(session_id or str(incoming_state.get("session_id") or ""))
    session["updated_at"] = time.time()
    session["chunk_count"] += 1
    session["combined_audio"].extend(audio_chunk)
    if len(session["combined_audio"]) > _MAX_STREAM_BUFFER_BYTES:
        del session["combined_audio"][:-_MAX_STREAM_BUFFER_BYTES]
    if session["chunk_count"] > _MAX_STREAM_CHUNKS:
        session["history"] = session["history"][-_MAX_STREAM_CHUNKS:]

    if voice_profile_bytes:
        profile_features, backend = _extract_voice_features(voice_profile_bytes)
        session["known_profiles"].append({
            "profile_id": hashlib.sha256(voice_profile_bytes).hexdigest()[:12],
            "speaker_name": speaker_name or "known_speaker",
            "features": profile_features,
            "backend": backend,
            "voice_profile_bytes": voice_profile_bytes,
        })

    try:
        chunk_result = transcribe_audio(audio_chunk, language=language)
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "text": "",
            "is_final": False,
            "session_state": {
                "session_id": session["session_id"],
                "partial": session["partial"],
                "chunk_count": session["chunk_count"],
            },
        }

    text = str(chunk_result.get("text", "") or "").strip()
    if text:
        session["partial"] = (session["partial"] + " " + text).strip()
        session["history"].append({"text": text, "segments": _normalize_segments(chunk_result.get("segments", []))})

    response: dict[str, Any] = {
        "ok": True,
        "text": text,
        "partial": session["partial"],
        "is_final": bool(finalize),
        "session_id": session["session_id"],
        "session_state": {
            "session_id": session["session_id"],
            "partial": session["partial"],
            "chunk_count": session["chunk_count"],
        },
        "chunk_backend": chunk_result.get("backend", "unknown"),
    }

    if not finalize:
        return response

    combined_audio = bytes(session["combined_audio"])
    try:
        final_result = transcribe_audio(combined_audio, language=language)
    except Exception:
        final_result = {
            "text": session["partial"],
            "language": language or "unknown",
            "duration_seconds": 0.0,
            "segments": [],
            "backend": "stream_fallback",
        }

    diarization = diarize_audio(combined_audio) if diarize else {"ok": False, "segments": [], "speaker_count": 1, "backend": "disabled"}
    speaker_identification = None
    if identify_speaker_enabled or voice_profile_bytes or session.get("known_profiles"):
        speaker_identification = identify_speaker(
            combined_audio,
            voice_profile_bytes=voice_profile_bytes,
            known_profiles=session.get("known_profiles"),
        )

    transcript_with_speakers = _label_transcript_with_speakers(diarization.get("segments", [])) if diarization.get("ok") else ""
    response.update({
        "final_transcript": str(final_result.get("text", "") or session["partial"]),
        "language": final_result.get("language", language or "unknown"),
        "duration_seconds": final_result.get("duration_seconds", 0.0),
        "segments": _normalize_segments(final_result.get("segments", [])),
        "diarization": diarization,
        "speaker_identification": speaker_identification,
        "transcript_with_speakers": transcript_with_speakers,
        "session_summary": {
            "chunk_count": session["chunk_count"],
            "profile_count": len(session.get("known_profiles", [])),
        },
        "backend": final_result.get("backend", chunk_result.get("backend", "unknown")),
    })
    return response
