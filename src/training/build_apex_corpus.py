from __future__ import annotations

import argparse
import json
from pathlib import Path


def _row_to_text(row: dict) -> str:
    if isinstance(row.get("messages"), list):
        chunks = []
        for msg in row["messages"]:
            role = str(msg.get("role", "")).strip().lower()
            content = str(msg.get("content", "")).strip()
            if role and content:
                chunks.append(f"<{role}>\n{content}")
        if chunks:
            return "\n\n".join(chunks)

    prompt = str(row.get("prompt", "")).strip()
    chosen = str(row.get("chosen", "")).strip()
    if prompt and chosen:
        return f"<user>\n{prompt}\n\n<assistant>\n{chosen}"

    instruction = str(row.get("instruction", "")).strip()
    row_input = str(row.get("input", "")).strip()
    output = str(row.get("output", "")).strip()
    if instruction and output:
        user_text = instruction if not row_input else f"{instruction}\n\nInput:\n{row_input}"
        return f"<user>\n{user_text}\n\n<assistant>\n{output}"

    return ""


def build_apex_corpus(input_jsonl: Path, output_text: Path, min_chars: int = 16) -> dict:
    if not input_jsonl.is_file():
        raise FileNotFoundError(f"Input JSONL not found: {input_jsonl}")

    output_text.parent.mkdir(parents=True, exist_ok=True)
    kept = 0
    rejected = 0

    with input_jsonl.open("r", encoding="utf-8") as src, output_text.open("w", encoding="utf-8") as dst:
        for line in src:
            payload = line.strip()
            if not payload:
                continue
            try:
                obj = json.loads(payload)
            except json.JSONDecodeError:
                rejected += 1
                continue

            sample = _row_to_text(obj).strip()
            if len(sample) < min_chars:
                rejected += 1
                continue

            dst.write(sample)
            dst.write("\n\n")
            kept += 1

    if kept == 0:
        raise ValueError("No usable rows for Apex corpus")

    return {
        "input": str(input_jsonl),
        "output": str(output_text),
        "kept_rows": kept,
        "rejected_rows": rejected,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build plain-text Apex pretraining corpus from JSONL data.")
    parser.add_argument("--input", required=True, help="Input JSONL path")
    parser.add_argument("--output", required=True, help="Output text corpus path")
    parser.add_argument("--min-chars", type=int, default=16, help="Minimum chars required per sample")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = build_apex_corpus(
        input_jsonl=Path(args.input),
        output_text=Path(args.output),
        min_chars=args.min_chars,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
