from __future__ import annotations

import json
import uuid


def format_claude_request(payload: dict) -> dict:
    system_parts = []
    messages = []
    role_map = {"user": "user", "assistant": "assistant", "system": "user"}

    for msg in payload.get("messages", []):
        role = msg.get("role", "user")

        if role == "system":
            content = msg.get("content", "")
            if isinstance(content, list):
                for block in content:
                    if block.get("type") == "text":
                        system_parts.append(block["text"])
            elif isinstance(content, str):
                system_parts.append(content)
            continue

        content_blocks = []
        raw_content = msg.get("content", "")

        if isinstance(raw_content, str):
            content_blocks.append({"type": "text", "text": raw_content})
        elif isinstance(raw_content, list):
            for block in raw_content:
                if block.get("type") == "text":
                    content_blocks.append({"type": "text", "text": block["text"]})
                elif block.get("type") == "image_url":
                    image_url = block.get("image_url", {})
                    url = image_url.get("url", "")
                    if url.startswith("data:"):
                        media_type = url.split(";")[0].split(":")[1]
                        data = url.split(",")[1]
                        content_blocks.append({
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": data,
                            },
                        })
                    else:
                        content_blocks.append({
                            "type": "image",
                            "source": {
                                "type": "url",
                                "url": url,
                            },
                        })

        tool_calls = msg.get("tool_calls") or msg.get("tool_use", [])
        if tool_calls:
            for tc in tool_calls:
                func = tc.get("function", {})
                content_blocks.append({
                    "type": "tool_use",
                    "id": tc.get("id", tc.get("tool_use_id", f"tu_{uuid.uuid4().hex[:8]}")),
                    "name": func.get("name", tc.get("name", "")),
                    "input": json.loads(func.get("arguments", tc.get("input", "{}"))) if isinstance(func.get("arguments"), str) else func.get("arguments", tc.get("input", {})),
                })

        if role == "tool":
            content_blocks = [{
                "type": "tool_result",
                "tool_use_id": msg.get("tool_call_id", ""),
                "content": raw_content if isinstance(raw_content, str) else json.dumps(raw_content),
            }]

        if role == "assistant" and any(b.get("type") == "tool_use" for b in content_blocks):
            pass

        mapped_role = role_map.get(role, "user")
        if mapped_role == "user" and not content_blocks:
            continue

        if mapped_role == "user" and content_blocks:
            content_blocks = [b for b in content_blocks if b.get("type") != "tool_result" and b.get("type") != "tool_use"]

        if messages and messages[-1]["role"] == mapped_role:
            existing = messages[-1]["content"]
            if isinstance(existing, list):
                existing.extend(content_blocks)
            else:
                messages[-1]["content"] = [{"type": "text", "text": existing}] + content_blocks
        else:
            messages.append({
                "role": mapped_role,
                "content": content_blocks if len(content_blocks) != 1 or content_blocks[0].get("type") != "text" else content_blocks[0]["text"],
            })

    body: dict = {
        "model": payload.get("model", "claude-sonnet-4-20250514"),
        "max_tokens": payload.get("max_tokens", 4096),
        "messages": messages,
    }

    if system_parts:
        body["system"] = "\n\n".join(system_parts)

    if payload.get("temperature") is not None:
        body["temperature"] = payload["temperature"]
    if payload.get("top_p") is not None:
        body["top_p"] = payload["top_p"]
    if payload.get("stop"):
        stop = payload["stop"]
        body["stop_sequences"] = stop if isinstance(stop, list) else [stop]
    if payload.get("stream"):
        body["stream"] = True

    thinking = payload.get("thinking")
    if thinking:
        body["thinking"] = thinking

    tools = payload.get("tools")
    if tools:
        claude_tools = []
        for tool in tools:
            func = tool.get("function", tool)
            claude_tools.append({
                "name": func.get("name", ""),
                "description": func.get("description", ""),
                "input_schema": func.get("parameters", {}),
            })
        body["tools"] = claude_tools

    return body


def normalise_claude_response(raw: dict) -> dict:
    content = raw.get("content", [])
    choices = []

    text_parts = []
    tool_calls = []
    thinking_text = None

    for block in content:
        if isinstance(block, dict):
            btype = block.get("type", "")
            if btype == "text":
                text_parts.append(block.get("text", ""))
            elif btype == "tool_use":
                tool_calls.append({
                    "id": block.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": block.get("name", ""),
                        "arguments": json.dumps(block.get("input", {})),
                    },
                })
            elif btype == "thinking":
                thinking_text = block.get("thinking", "")

    message: dict = {"role": "assistant", "content": "\n".join(text_parts)}
    if tool_calls:
        message["tool_calls"] = tool_calls
    if thinking_text:
        message["thinking"] = thinking_text

    stop_reason = raw.get("stop_reason", "end_turn")
    finish_reason_map = {
        "end_turn": "stop",
        "max_tokens": "length",
        "stop_sequence": "stop",
        "tool_use": "tool_calls",
    }

    choices.append({
        "index": 0,
        "message": message,
        "finish_reason": finish_reason_map.get(stop_reason, stop_reason),
    })

    usage = raw.get("usage", {})
    return {
        "id": raw.get("id", ""),
        "object": "chat.completion",
        "model": raw.get("model", ""),
        "choices": choices,
        "usage": {
            "prompt_tokens": usage.get("input_tokens", 0),
            "completion_tokens": usage.get("output_tokens", 0),
            "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
        },
    }


def extract_thinking(raw: dict) -> str | None:
    content = raw.get("content", [])
    for block in content:
        if isinstance(block, dict) and block.get("type") == "thinking":
            return block.get("thinking", "")
    return None


def format_tool_result(tool_use_id: str, content: str, is_error: bool = False) -> dict:
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": content,
        "is_error": is_error,
    }
