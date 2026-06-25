from __future__ import annotations

import json
import uuid


def _openai_to_gemini_role(role: str) -> str:
    if role == "assistant":
        return "model"
    return "user"


def format_gemini_request(payload: dict) -> dict:
    contents = []
    system_instruction = None

    for msg in payload.get("messages", []):
        role = msg.get("role", "user")
        raw_content = msg.get("content", "")

        if role == "system":
            text = raw_content if isinstance(raw_content, str) else " ".join(
                b.get("text", "") for b in raw_content if isinstance(b, dict) and b.get("type") == "text"
            )
            if system_instruction is None:
                system_instruction = {"parts": [{"text": text}]}
            else:
                system_instruction["parts"][0]["text"] += "\n" + text
            continue

        parts = []

        if isinstance(raw_content, str):
            parts.append({"text": raw_content})
        elif isinstance(raw_content, list):
            for block in raw_content:
                if isinstance(block, dict):
                    btype = block.get("type", "")
                    if btype == "text":
                        parts.append({"text": block["text"]})
                    elif btype == "image_url":
                        image_url = block.get("image_url", {})
                        url = image_url.get("url", "")
                        if url.startswith("data:"):
                            media_type = url.split(";")[0].split(":")[1]
                            data = url.split(",")[1]
                            parts.append({
                                "inline_data": {
                                    "mime_type": media_type,
                                    "data": data,
                                },
                            })
                        else:
                            parts.append({"text": f"[Image: {url}]"})

        tool_calls = msg.get("tool_calls") or msg.get("tool_use", [])
        for tc in tool_calls:
            func = tc.get("function", {})
            name = func.get("name", tc.get("name", ""))
            args = func.get("arguments", tc.get("input", {}))
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {"raw": args}
            parts.append({
                "functionCall": {
                    "name": name,
                    "args": args,
                },
            })

        if role == "tool":
            tool_call_id = msg.get("tool_call_id", "")
            content = raw_content if isinstance(raw_content, str) else json.dumps(raw_content)
            parts.append({
                "functionResponse": {
                    "name": tool_call_id,
                    "response": {
                        "name": tool_call_id,
                        "content": content,
                    },
                },
            })

        if parts:
            gemini_role = _openai_to_gemini_role(role)
            if contents and contents[-1]["role"] == gemini_role:
                contents[-1]["parts"].extend(parts)
            else:
                contents.append({"role": gemini_role, "parts": parts})

    body: dict = {
        "contents": contents,
    }

    if system_instruction:
        body["systemInstruction"] = system_instruction

    generation_config = {}
    if payload.get("temperature") is not None:
        generation_config["temperature"] = payload["temperature"]
    if payload.get("top_p") is not None:
        generation_config["topP"] = payload["top_p"]
    if payload.get("top_k") is not None:
        generation_config["topK"] = payload["top_k"]
    if payload.get("max_tokens") is not None:
        generation_config["maxOutputTokens"] = payload["max_tokens"]
    if payload.get("stop"):
        stops = payload["stop"]
        generation_config["stopSequences"] = stops if isinstance(stops, list) else [stops]

    if generation_config:
        body["generationConfig"] = generation_config

    tools = payload.get("tools")
    if tools:
        function_declarations = []
        for tool in tools:
            func = tool.get("function", tool)
            function_declarations.append({
                "name": func.get("name", ""),
                "description": func.get("description", ""),
                "parameters": func.get("parameters", {}),
            })
        body["tools"] = [{"functionDeclarations": function_declarations}]

    return body


def normalise_gemini_response(raw: dict) -> dict:
    candidates = raw.get("candidates", [])
    choices = []

    for idx, candidate in enumerate(candidates):
        content = candidate.get("content", {})
        parts = content.get("parts", [])
        role = content.get("role", "model")

        text_parts = []
        tool_calls = []

        for part in parts:
            if "text" in part:
                text_parts.append(part["text"])
            if "functionCall" in part:
                fc = part["functionCall"]
                tool_calls.append({
                    "id": f"call_{uuid.uuid4().hex[:12]}",
                    "type": "function",
                    "function": {
                        "name": fc.get("name", ""),
                        "arguments": json.dumps(fc.get("args", {})),
                    },
                })

        message = {"role": "assistant", "content": "\n".join(text_parts)}
        if tool_calls:
            message["tool_calls"] = tool_calls

        finish_reason = candidate.get("finishReason", "STOP")
        finish_reason_map = {
            "STOP": "stop",
            "MAX_TOKENS": "length",
            "SAFETY": "safety",
            "RECITATION": "recitation",
            "OTHER": "stop",
        }

        choices.append({
            "index": idx,
            "message": message,
            "finish_reason": finish_reason_map.get(finish_reason, finish_reason.lower()),
        })

    usage = raw.get("usageMetadata", {})
    return {
        "id": raw.get("id", ""),
        "object": "chat.completion",
        "model": raw.get("model", ""),
        "choices": choices,
        "usage": {
            "prompt_tokens": usage.get("promptTokenCount", 0),
            "completion_tokens": usage.get("candidatesTokenCount", 0),
            "total_tokens": usage.get("totalTokenCount", 0),
        },
    }


def assign_tool_call_ids(response: dict) -> dict:
    for choice in response.get("choices", []):
        message = choice.get("message", {})
        tool_calls = message.get("tool_calls", [])
        for tc in tool_calls:
            if not tc.get("id"):
                tc["id"] = f"call_{uuid.uuid4().hex[:12]}"
    return response


def parse_safety_ratings(ratings: list[dict]) -> dict:
    result = {}
    for r in ratings:
        category = r.get("category", "UNKNOWN").replace("HARM_CATEGORY_", "").lower()
        result[category] = r.get("probability", "UNKNOWN")
    return result
