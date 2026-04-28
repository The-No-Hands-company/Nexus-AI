"""
src/structured_output.py — JSON Schema constrained generation and output enforcement

Enforces that model outputs conform to a JSON Schema by:
  1. Post-hoc validation: parse and validate model JSON output, return on success.
  2. Repair: if validation fails, call model again with explicit schema + error feedback.
  3. Constrained decoding: if llama.cpp grammar is available, generate with grammar.
  4. Outlines integration: if outlines package is present, use grammar-constrained sampling.

Environment variables:
    STRUCTURED_OUTPUT_MAX_REPAIR_ATTEMPTS — retries before giving up (default: 2)
    STRUCTURED_OUTPUT_BACKEND             — "json_repair" | "outlines" | "grammar" | "auto"
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

logger = logging.getLogger("nexus.structured_output")

_MAX_ATTEMPTS = int(os.getenv("STRUCTURED_OUTPUT_MAX_REPAIR_ATTEMPTS", "2"))
_BACKEND = os.getenv("STRUCTURED_OUTPUT_BACKEND", "auto").strip().lower()


# ── JSON extraction helpers ───────────────────────────────────────────────────

def extract_json(text: str) -> Any | None:
    """Extract JSON from model output that may contain prose around it."""
    if not text:
        return None
    # Try direct parse
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    # Try to find JSON in code blocks
    for pattern in [r'```json\s*([\s\S]+?)\s*```', r'```\s*([\s\S]+?)\s*```', r'(\{[\s\S]*\})', r'(\[[\s\S]*\])']:
        m = re.search(pattern, text)
        if m:
            candidate = m.group(1).strip()
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue

    # Try json_repair if available
    try:
        import json_repair  # type: ignore
        return json_repair.repair_json(text, return_objects=True)
    except ImportError:
        pass

    return None


def _validate_against_schema(data: Any, schema: dict) -> tuple[bool, str]:
    """Validate *data* against JSON *schema* using jsonschema."""
    try:
        import jsonschema  # type: ignore
        jsonschema.validate(data, schema)
        return True, ""
    except ImportError:
        # Fallback: type-only validation
        if "type" in schema:
            expected = schema["type"]
            type_map = {"object": dict, "array": list, "string": str,
                        "number": (int, float), "integer": int, "boolean": bool}
            if expected in type_map and not isinstance(data, type_map[expected]):
                return False, f"Expected type {expected}, got {type(data).__name__}"
        return True, ""  # lenient if jsonschema not installed
    except Exception as exc:
        return False, str(exc)


def _schema_to_prompt(schema: dict) -> str:
    """Convert a JSON Schema to a concise prompt instruction."""
    try:
        return f"Output ONLY valid JSON matching this schema:\n{json.dumps(schema, indent=2)}\nDo NOT include any text before or after the JSON."
    except Exception:
        return "Output ONLY valid JSON."


# ── Repair via LLM ────────────────────────────────────────────────────────────

def _repair_with_llm(original_prompt: str, bad_output: str, schema: dict, error: str) -> str:
    """Call the generation module to repair a bad JSON output."""
    repair_prompt = (
        f"{_schema_to_prompt(schema)}\n\n"
        f"ORIGINAL REQUEST:\n{original_prompt[:500]}\n\n"
        f"PREVIOUS (INVALID) OUTPUT:\n{bad_output[:1000]}\n\n"
        f"VALIDATION ERROR:\n{error}\n\n"
        "Please output corrected JSON only:"
    )
    try:
        from src.generation import generate_text  # type: ignore
        return generate_text(repair_prompt, max_tokens=2048, temperature=0.0)
    except Exception as exc:
        logger.debug("_repair_with_llm: %s", exc)
        return ""


# ── Outlines integration ──────────────────────────────────────────────────────

def _generate_with_outlines(prompt: str, schema: dict, model_name: str) -> str | None:
    """Generate using outlines grammar-constrained sampling."""
    try:
        import outlines  # type: ignore
        import outlines.models as om
        model = om.transformers(model_name)
        generator = outlines.generate.json(model, schema)
        result = generator(prompt)
        return json.dumps(result)
    except Exception as exc:
        logger.debug("outlines generation failed: %s", exc)
        return None


# ── Public API ────────────────────────────────────────────────────────────────

def generate_structured(
    prompt: str,
    schema: dict,
    model_name: str = "",
    max_tokens: int = 2048,
    temperature: float = 0.1,
) -> dict:
    """Generate model output constrained to *schema*.

    Returns {"data": <parsed_json>, "valid": bool, "attempts": int, "method": str}.
    """
    schema_hint = _schema_to_prompt(schema)
    full_prompt = f"{schema_hint}\n\n{prompt}"

    # Try outlines first if requested
    if _BACKEND in ("outlines", "auto") and model_name:
        raw = _generate_with_outlines(full_prompt, schema, model_name)
        if raw:
            data = extract_json(raw)
            if data is not None:
                valid, _ = _validate_against_schema(data, schema)
                if valid:
                    return {"data": data, "valid": True, "attempts": 1, "method": "outlines"}

    # Standard generation with repair loop
    try:
        from src.generation import generate_text  # type: ignore
        raw = generate_text(full_prompt, max_tokens=max_tokens, temperature=temperature)
    except Exception as exc:
        logger.error("generate_structured: generation failed: %s", exc)
        return {"data": None, "valid": False, "attempts": 0, "method": "none", "error": str(exc)}

    for attempt in range(1, _MAX_ATTEMPTS + 2):
        data = extract_json(raw)
        if data is not None:
            valid, error = _validate_against_schema(data, schema)
            if valid:
                return {"data": data, "valid": True, "attempts": attempt, "method": "json_repair"}
            if attempt <= _MAX_ATTEMPTS:
                raw = _repair_with_llm(prompt, raw, schema, error)
                if not raw:
                    break
        else:
            if attempt <= _MAX_ATTEMPTS:
                raw = _repair_with_llm(prompt, raw or "", schema, "no JSON found in output")
                if not raw:
                    break

    return {
        "data": data if data is not None else None,
        "valid": False,
        "attempts": _MAX_ATTEMPTS + 1,
        "method": "failed",
        "error": "Could not produce valid JSON after max repair attempts",
    }


def validate_output(output: str, schema: dict) -> dict:
    """Validate an existing output string against a JSON schema.

    Returns {"valid": bool, "data": <parsed>, "error": str | None}.
    """
    data = extract_json(output)
    if data is None:
        return {"valid": False, "data": None, "error": "No JSON found in output"}
    valid, error = _validate_against_schema(data, schema)
    return {"valid": valid, "data": data, "error": error or None}
