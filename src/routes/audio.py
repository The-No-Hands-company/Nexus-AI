from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
import base64

router = APIRouter()


def _api_error(message: str, code: str = "invalid_request", status_code: int = 400):
    return JSONResponse({"error": message, "type": code}, status_code=status_code)


# ── Audio HTTP Endpoints ────────────────────────────────────────────────

@router.post("/audio/ingest-transcript")
async def audio_ingest_transcript(request: Request):
    data        = await request.json()
    source      = data.get("source", "").strip()
    source_type = data.get("source_type", "audio_file")
    metadata    = data.get("metadata", {})
    if not source:
        return _api_error("source is required", "validation_error", 422)
    if source_type not in ("youtube", "audio_file", "meeting_url"):
        return _api_error("source_type must be youtube, audio_file, or meeting_url", "validation_error", 422)
    try:
        from ..audio import ingest_transcript
        result = ingest_transcript(source, source_type, metadata=metadata)
        return result if isinstance(result, dict) else {"result": result}
    except Exception as exc:
        return _api_error(str(exc), "ingest_error", 500)


@router.post("/audio/analyse")
async def api_audio_analyse(request: Request):
    from ..audio import AudioProviderError, analyse_audio
    body = await request.json()
    audio_b64 = str(body.get("audio_base64", ""))
    analyses = body.get("analyses")
    profile_b64 = body.get("voice_profile_base64")
    if not audio_b64:
        return _api_error("audio_base64 required", status_code=422)
    try:
        audio_bytes = base64.b64decode(audio_b64)
        profile_bytes = base64.b64decode(profile_b64) if profile_b64 else None
    except Exception:
        return _api_error("Invalid base64 audio", status_code=422)
    try:
        return analyse_audio(audio_bytes, analyses=analyses, voice_profile_bytes=profile_bytes)
    except AudioProviderError as exc:
        return _api_error(str(exc), status_code=503)
    except ValueError as exc:
        return _api_error(str(exc), status_code=422)


@router.post("/audio/diarize")
async def api_audio_diarize(request: Request):
    from ..audio import diarize_audio
    body = await request.json()
    audio_b64 = str(body.get("audio_base64", ""))
    num_speakers = body.get("num_speakers")
    if not audio_b64:
        return _api_error("audio_base64 required", status_code=422)
    try:
        audio_bytes = base64.b64decode(audio_b64)
    except Exception:
        return _api_error("Invalid base64 audio", status_code=422)
    return diarize_audio(audio_bytes, num_speakers=num_speakers)


@router.post("/audio/identify-speaker")
async def api_audio_identify_speaker(request: Request):
    from ..audio import identify_speaker
    body = await request.json()
    audio_b64 = str(body.get("audio_base64", ""))
    profile_b64 = body.get("voice_profile_base64")
    known_profiles = body.get("known_profiles") if isinstance(body.get("known_profiles"), list) else None
    if not audio_b64:
        return _api_error("audio_base64 required", status_code=422)
    try:
        audio_bytes = base64.b64decode(audio_b64)
        profile_bytes = base64.b64decode(profile_b64) if profile_b64 else None
    except Exception:
        return _api_error("Invalid base64 audio", status_code=422)
    return identify_speaker(audio_bytes, voice_profile_bytes=profile_bytes, known_profiles=known_profiles)


@router.post("/audio/stream-chunk")
async def api_audio_stream_chunk(request: Request):
    from ..audio import stream_transcribe_chunk
    body = await request.json()
    chunk_b64 = str(body.get("audio_chunk_base64", ""))
    session_state = body.get("session_state")
    session_id = str(body.get("session_id", ""))
    language = str(body.get("language", "")) or None
    finalize = bool(body.get("finalize", False))
    diarize = bool(body.get("diarize", False))
    identify_speaker_enabled = bool(body.get("identify_speaker", False))
    profile_b64 = body.get("voice_profile_base64")
    speaker_name = str(body.get("speaker_name", ""))
    if not chunk_b64:
        return _api_error("audio_chunk_base64 required", status_code=422)
    try:
        chunk_bytes = base64.b64decode(chunk_b64)
        profile_bytes = base64.b64decode(profile_b64) if profile_b64 else None
    except Exception:
        return _api_error("Invalid base64 audio", status_code=422)
    return stream_transcribe_chunk(
        chunk_bytes,
        session_state=session_state,
        session_id=session_id,
        language=language,
        finalize=finalize,
        diarize=diarize,
        identify_speaker_enabled=identify_speaker_enabled,
        voice_profile_bytes=profile_bytes,
        speaker_name=speaker_name,
    )


# ── WebSocket Real-time Voice ───────────────────────────────────────────

@router.websocket("/audio/live/ws")
async def api_audio_live_ws(websocket):
    """Realtime voice-agent socket.

    Client messages (JSON):
    - {"type":"chunk","audio_chunk_base64":"...","session_id":"..."}
    - {"type":"finalize","audio_chunk_base64":"...optional...","prompt":"...optional..."}
    """
    from ..audio import stream_transcribe_chunk
    await websocket.accept()
    session_id = ""
    session_state = {}
    last_chunk_bytes = b""

    try:
        while True:
            try:
                payload = await websocket.receive_json()
            except Exception:
                # Client disconnected
                break
                
            msg_type = str(payload.get("type") or "chunk").strip().lower()
            session_id = str(payload.get("session_id") or session_id or "")
            language = str(payload.get("language") or "") or None
            diarize = bool(payload.get("diarize", False))
            identify_speaker = bool(payload.get("identify_speaker", False))
            prompt = str(payload.get("prompt") or "").strip()

            chunk_b64 = str(payload.get("audio_chunk_base64") or "")
            chunk_bytes = b""
            if chunk_b64:
                try:
                    chunk_bytes = base64.b64decode(chunk_b64)
                    last_chunk_bytes = chunk_bytes
                except Exception:
                    await websocket.send_json({"type": "error", "error": "invalid base64 chunk"})
                    continue

            if msg_type == "chunk":
                if not chunk_bytes:
                    await websocket.send_json({"type": "error", "error": "audio_chunk_base64 required"})
                    continue
                result = stream_transcribe_chunk(
                    chunk_bytes,
                    session_state=session_state,
                    session_id=session_id,
                    language=language,
                    finalize=False,
                    diarize=diarize,
                    identify_speaker_enabled=identify_speaker,
                )
                session_state = dict(result.get("session_state") or session_state)
                session_id = str(result.get("session_id") or session_id)
                await websocket.send_json({"type": "partial", **result})
                continue

            if msg_type == "finalize":
                final_chunk = chunk_bytes or last_chunk_bytes
                if not final_chunk:
                    await websocket.send_json({"type": "error", "error": "no audio available to finalize"})
                    continue
                result = stream_transcribe_chunk(
                    final_chunk,
                    session_state=session_state,
                    session_id=session_id,
                    language=language,
                    finalize=True,
                    diarize=diarize,
                    identify_speaker_enabled=identify_speaker,
                )
                session_state = dict(result.get("session_state") or session_state)
                session_id = str(result.get("session_id") or session_id)
                await websocket.send_json({"type": "final", **result})

                final_text = str(result.get("final_transcript") or result.get("partial") or "").strip()
                if final_text:
                    agent_task = prompt or final_text
                    from ..agent import run_agent_task
                    agent_out = run_agent_task(agent_task, history=[], files=[], sid=session_id)
                    await websocket.send_json({
                        "type": "agent_response",
                        "session_id": session_id,
                        "task": agent_task,
                        "agent": agent_out,
                    })
                continue

            await websocket.send_json({"type": "error", "error": f"unsupported message type: {msg_type}"})
    except Exception:  # Includes WebSocketDisconnect
        return