from __future__ import annotations

import argparse
import json
import random
from pathlib import Path


def _normalize_messages(messages: list[dict]) -> list[dict]:
    normalized: list[dict] = []
    for item in messages:
        role = str(item.get("role", "")).strip().lower()
        content = str(item.get("content", "")).strip()
        if not role or not content:
            continue
        if role not in {"system", "user", "assistant"}:
            continue
        normalized.append({"role": role, "content": content})
    return normalized


def _row_to_messages(row: dict) -> list[dict] | None:
    if isinstance(row.get("messages"), list):
        messages = _normalize_messages(row["messages"])
        return messages if messages else None

    prompt = str(row.get("prompt", "")).strip()
    chosen = str(row.get("chosen", "")).strip()
    if prompt and chosen:
        return [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": chosen},
        ]

    instruction = str(row.get("instruction", "")).strip()
    row_input = str(row.get("input", "")).strip()
    output = str(row.get("output", "")).strip()
    if instruction and output:
        user_content = instruction if not row_input else f"{instruction}\n\nInput:\n{row_input}"
        return [
            {"role": "user", "content": user_content},
            {"role": "assistant", "content": output},
        ]

    return None


def _contains_assistant_reply(messages: list[dict]) -> bool:
    return any(msg.get("role") == "assistant" and str(msg.get("content", "")).strip() for msg in messages)


def _assistant_chars(messages: list[dict]) -> int:
    return sum(len(str(msg.get("content", ""))) for msg in messages if msg.get("role") == "assistant")


def build_dataset(
    input_path: Path,
    min_chars: int,
    seed: int,
    val_ratio: float,
) -> tuple[list[dict], list[dict], int]:
    rng = random.Random(seed)
    rows: list[dict] = []
    rejected = 0

    with input_path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            payload = line.strip()
            if not payload:
                continue
            try:
                obj = json.loads(payload)
            except json.JSONDecodeError:
                rejected += 1
                continue

            messages = _row_to_messages(obj)
            if not messages:
                rejected += 1
                continue
            if not _contains_assistant_reply(messages):
                rejected += 1
                continue
            if _assistant_chars(messages) < min_chars:
                rejected += 1
                continue

            rows.append({"messages": messages})

    rng.shuffle(rows)
    split_idx = int(len(rows) * (1.0 - val_ratio))
    split_idx = max(1, split_idx) if rows else 0
    train_rows = rows[:split_idx]
    val_rows = rows[split_idx:]
    return train_rows, val_rows, rejected


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_dataset_splits(
    input_path: Path,
    train_output: Path,
    val_output: Path,
    min_chars: int = 24,
    seed: int = 42,
    val_ratio: float = 0.1,
) -> dict:
    train_rows, val_rows, rejected = build_dataset(
        input_path=input_path,
        min_chars=min_chars,
        seed=seed,
        val_ratio=val_ratio,
    )
    if not train_rows:
        raise ValueError("No valid training samples after filtering")

    _write_jsonl(train_output, train_rows)
    _write_jsonl(val_output, val_rows)
    return {
        "input": str(input_path),
        "train_output": str(train_output),
        "val_output": str(val_output),
        "train_samples": len(train_rows),
        "val_samples": len(val_rows),
        "rejected_rows": rejected,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build SFT JSONL dataset from Nexus export rows.")
    parser.add_argument("--input", required=True, help="Input JSONL path.")
    parser.add_argument("--train-output", required=True, help="Output train JSONL path.")
    parser.add_argument("--val-output", required=True, help="Output validation JSONL path.")
    parser.add_argument("--val-ratio", type=float, default=0.1, help="Validation split ratio [0.0, 0.5].")
    parser.add_argument("--min-chars", type=int, default=24, help="Minimum assistant characters to keep sample.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducible split.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not (0.0 <= args.val_ratio <= 0.5):
        raise ValueError("--val-ratio must be between 0.0 and 0.5")

    input_path = Path(args.input)
    if not input_path.is_file():
        raise FileNotFoundError(f"Input JSONL not found: {input_path}")

    train_output = Path(args.train_output)
    val_output = Path(args.val_output)
    summary = write_dataset_splits(
        input_path=input_path,
        train_output=train_output,
        val_output=val_output,
        min_chars=args.min_chars,
        seed=args.seed,
        val_ratio=args.val_ratio,
    )

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
