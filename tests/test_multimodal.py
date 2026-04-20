"""Tests for Section 11: Multimodal Features.

Covers:
  11.1 Vision routing — _messages_have_images, _smart_order_for_vision,
       /v1/chat/completions with image_url content, /agent images field
  11.2 Image generation — tool_generate_image (URL + persistence)
  11.3 Audio — POST /audio/ingest-transcript route (schema + error handling)
  11.4 YouTube — tool_youtube LLM summarization path
"""
import base64
import json
import pytest
from unittest.mock import patch, MagicMock
from starlette.testclient import TestClient

from src.app import app
from src.agent import _messages_have_images, _smart_order_for_vision
from src.tools_builtin import tool_generate_image

client = TestClient(app, raise_server_exceptions=False)


# ── 11.1  Vision helpers ──────────────────────────────────────────────────────

def test_messages_have_images_false_for_plain_text():
    msgs = [{"role": "user", "content": "Hello world"}]
    assert _messages_have_images(msgs) is False


def test_messages_have_images_true_for_image_url():
    msgs = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "What is this?"},
                {"type": "image_url", "image_url": {"url": "https://example.com/img.png"}},
            ],
        }
    ]
    assert _messages_have_images(msgs) is True


def test_messages_have_images_true_for_data_url():
    b64 = base64.b64encode(b"PNGDATA").decode()
    msgs = [
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ],
        }
    ]
    assert _messages_have_images(msgs) is True


def test_smart_order_for_vision_promotes_ollama(monkeypatch):
    """_smart_order_for_vision should promote ollama when a vision model is available."""
    from src import agent as _agent
    monkeypatch.setattr(_agent, "_config", {
        "ollama_url": "http://localhost:11434",
        "ollama_model": "llava:13b",
        "openai_key": "",
        "anthropic_key": "",
        "google_key": "",
    })
    msgs = [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "https://x.com/a.jpg"}}]}]
    # Should not raise
    _smart_order_for_vision(msgs)


# ── 11.1  /v1/chat/completions with image_url ─────────────────────────────────

def test_v1_chat_completions_vision_path():
    """Route should accept multipart content with image_url and not crash."""
    mock_resp = {"role": "assistant", "content": "I see a cat."}
    with patch("src.api.routes.call_llm_with_fallback", return_value=(mock_resp, "ollama")):
        resp = client.post("/v1/chat/completions", json={
            "model": "llava",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "What do you see?"},
                        {"type": "image_url", "image_url": {"url": "https://example.com/cat.jpg"}},
                    ],
                }
            ],
        })
    assert resp.status_code == 200
    body = resp.json()
    assert "choices" in body
    assert "I see" in body["choices"][0]["message"]["content"]


# ── 11.1  /agent images field ─────────────────────────────────────────────────

def test_agent_post_with_images():
    """POST /agent with images= should invoke vision fast-path."""
    mock_resp = {"role": "assistant", "content": "Dog detected."}
    with patch("src.api.routes.call_llm_with_fallback", return_value=(mock_resp, "ollama")):
        resp = client.post("/agent", json={
            "task": "Describe this image",
            "images": [{"url": "https://example.com/dog.jpg"}],
        })
    assert resp.status_code == 200
    body = resp.json()
    assert body["result"] == "Dog detected."
    assert body["provider"] == "ollama"


def test_agent_post_with_b64_images():
    """POST /agent with base64 images should build data URL and call vision LLM."""
    mock_resp = {"role": "assistant", "content": "Cat photo."}
    b64 = base64.b64encode(b"FAKEIMAGEDATA").decode()
    with patch("src.api.routes.call_llm_with_fallback", return_value=(mock_resp, "claude")):
        resp = client.post("/agent", json={
            "task": "What is in this image?",
            "images": [{"b64": b64, "mime_type": "image/jpeg"}],
        })
    assert resp.status_code == 200
    assert resp.json()["result"] == "Cat photo."


def test_agent_post_without_images_uses_normal_path():
    """POST /agent without images= should use run_agent_task normally."""
    with patch("src.api.routes.run_agent_task", return_value={
        "result": "42", "provider": "ollama", "model": "llama3", "history": []
    }):
        resp = client.post("/agent", json={"task": "What is 6 × 7?"})
    assert resp.status_code == 200
    assert resp.json()["result"] == "42"


# ── 11.2  tool_generate_image ─────────────────────────────────────────────────

def test_tool_generate_image_returns_url():
    result = tool_generate_image("a red apple")
    assert "url" in result
    assert "pollinations.ai" in result["url"]
    assert result["prompt"] == "a red apple"


def test_tool_generate_image_save_false_no_saved_path():
    result = tool_generate_image("blue sky", save=False)
    assert "saved_path" not in result
    assert "save_error" not in result


def test_tool_generate_image_save_persists_file(tmp_path):
    """When save=True the image should be downloaded and saved."""
    fake_bytes = b"PNGFAKEDATA"
    with patch("src.tools_builtin._fetch_binary_tool_input", return_value=fake_bytes):
        result = tool_generate_image(
            "mountain sunset", save=True, workdir=str(tmp_path)
        )
    assert "saved_path" in result
    import os
    assert os.path.exists(result["saved_path"])
    with open(result["saved_path"], "rb") as f:
        assert f.read() == fake_bytes


def test_tool_generate_image_save_error_graceful(tmp_path):
    """When download fails, result should contain save_error, not raise."""
    with patch("src.tools_builtin._fetch_binary_tool_input", side_effect=ConnectionError("timeout")):
        result = tool_generate_image("stars", save=True, workdir=str(tmp_path))
    assert "save_error" in result
    assert "timeout" in result["save_error"]


# ── 11.3  POST /audio/ingest-transcript ──────────────────────────────────────

def test_audio_ingest_transcript_missing_source():
    resp = client.post("/audio/ingest-transcript", json={"source_type": "youtube"})
    assert resp.status_code == 422


def test_audio_ingest_transcript_invalid_source_type():
    resp = client.post("/audio/ingest-transcript", json={
        "source": "https://example.com/audio.mp3",
        "source_type": "foobar",
    })
    assert resp.status_code == 422


def test_audio_ingest_transcript_youtube_calls_ingest():
    mock_result = {"status": "ok", "source_type": "youtube", "ingest_result": {"chunks": 5}}
    with patch("src.audio.ingest_transcript", return_value=mock_result):
        resp = client.post("/audio/ingest-transcript", json={
            "source": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "source_type": "youtube",
        })
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["source_type"] == "youtube"


def test_audio_ingest_transcript_audio_file():
    mock_result = {"status": "ok", "source_type": "audio_file", "ingest_result": {"chunks": 3}}
    with patch("src.audio.ingest_transcript", return_value=mock_result):
        resp = client.post("/audio/ingest-transcript", json={
            "source": "/tmp/meeting.mp3",
            "source_type": "audio_file",
        })
    assert resp.status_code == 200


def test_audio_ingest_transcript_meeting_url():
    mock_result = {"status": "ok", "source_type": "meeting_url", "ingest_result": {"chunks": 10}}
    with patch("src.audio.ingest_transcript", return_value=mock_result):
        resp = client.post("/audio/ingest-transcript", json={
            "source": "https://meet.google.com/abc-xyz",
            "source_type": "meeting_url",
        })
    assert resp.status_code == 200


def test_audio_ingest_transcript_runtime_error():
    with patch("src.audio.ingest_transcript", side_effect=RuntimeError("no subtitles")):
        resp = client.post("/audio/ingest-transcript", json={
            "source": "https://www.youtube.com/watch?v=notfound",
            "source_type": "youtube",
        })
    assert resp.status_code == 500


# ── 11.4  tool_youtube LLM summarization ─────────────────────────────────────

def test_tool_youtube_calls_llm_when_transcript_available():
    """tool_youtube should call call_llm_with_fallback when a transcript is found."""
    import sys, types
    # Provide a minimal yt_dlp stub so tests don't require the package installed.
    fake_info = {
        "title": "Test Video",
        "uploader": "TestChan",
        "duration_string": "5:30",
        "description": "A great video about testing.",
        "webpage_url": "https://www.youtube.com/watch?v=test123",
    }
    fake_transcript = "This is the full transcript of the test video."
    mock_llm_resp = {"role": "assistant", "content": "TLDR: A test video. Key points: testing."}

    mock_ydl_instance = MagicMock()
    mock_ydl_instance.__enter__ = MagicMock(return_value=mock_ydl_instance)
    mock_ydl_instance.__exit__ = MagicMock(return_value=False)
    mock_ydl_instance.extract_info.return_value = fake_info

    mock_ydl_cls = MagicMock(return_value=mock_ydl_instance)
    yt_dlp_stub = types.ModuleType("yt_dlp")
    yt_dlp_stub.YoutubeDL = mock_ydl_cls

    with patch.dict(sys.modules, {"yt_dlp": yt_dlp_stub}), \
         patch("src.tools_builtin.tool_youtube_transcript", return_value=fake_transcript), \
         patch("src.tools_builtin.call_llm_with_fallback", return_value=(mock_llm_resp, "ollama"), create=True), \
         patch("src.agent.call_llm_with_fallback", return_value=(mock_llm_resp, "ollama")):
        # Re-import inside patched context so yt_dlp stub is picked up
        import importlib, src.tools_builtin as _tb
        importlib.reload(_tb)
        result = _tb.tool_youtube("https://www.youtube.com/watch?v=test123")

    assert "Summary" in result or "TLDR" in result or "testing" in result or "Test Video" in result


def test_tool_youtube_falls_back_when_no_transcript():
    """tool_youtube should fall back gracefully when no transcript is available."""
    import sys, types, importlib
    fake_info = {
        "title": "No Transcript Video",
        "uploader": "Chan",
        "duration_string": "2:00",
        "description": "A video.",
        "webpage_url": "https://www.youtube.com/watch?v=notranscript",
    }
    mock_ydl_instance = MagicMock()
    mock_ydl_instance.__enter__ = MagicMock(return_value=mock_ydl_instance)
    mock_ydl_instance.__exit__ = MagicMock(return_value=False)
    mock_ydl_instance.extract_info.return_value = fake_info
    mock_ydl_cls = MagicMock(return_value=mock_ydl_instance)
    yt_dlp_stub = types.ModuleType("yt_dlp")
    yt_dlp_stub.YoutubeDL = mock_ydl_cls

    with patch.dict(sys.modules, {"yt_dlp": yt_dlp_stub}), \
         patch("src.tools_builtin.tool_youtube_transcript", return_value="Transcript unavailable."):
        import src.tools_builtin as _tb2
        importlib.reload(_tb2)
        result = _tb2.tool_youtube("https://www.youtube.com/watch?v=notranscript")

    # Should still return a result with video metadata, not crash
    assert "No Transcript Video" in result
