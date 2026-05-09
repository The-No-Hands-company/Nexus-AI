from __future__ import annotations

import argparse
import json
from pathlib import Path


def _build_chunks(token_ids: list[int], block_size: int) -> list[dict]:
    chunks: list[dict] = []
    step = max(8, block_size // 2)
    for i in range(0, max(0, len(token_ids) - block_size), step):
        seq = token_ids[i : i + block_size]
        if len(seq) < block_size:
            continue
        chunks.append({"input_ids": seq, "labels": seq[:]})
    return chunks


def pretrain_apex(
    corpus_file: Path,
    tokenizer_dir: Path,
    output_dir: Path,
    block_size: int = 512,
    train_ratio: float = 0.9,
    epochs: int = 1,
    batch_size: int = 2,
    grad_accum: int = 8,
    learning_rate: float = 3e-4,
    n_layer: int = 8,
    n_head: int = 8,
    n_embd: int = 512,
) -> dict:
    if not corpus_file.is_file():
        raise FileNotFoundError(f"Corpus not found: {corpus_file}")
    if not tokenizer_dir.is_dir():
        raise FileNotFoundError(f"Tokenizer dir not found: {tokenizer_dir}")

    try:
        from datasets import Dataset
        from transformers import (
            AutoTokenizer,
            DataCollatorForLanguageModeling,
            GPT2Config,
            GPT2LMHeadModel,
            Trainer,
            TrainingArguments,
        )
    except ImportError as exc:
        raise ImportError(
            "Pretraining dependencies missing. Install with: pip install transformers datasets"
        ) from exc

    output_dir.mkdir(parents=True, exist_ok=True)

    tokenizer = AutoTokenizer.from_pretrained(str(tokenizer_dir), use_fast=True)
    if tokenizer.pad_token is None:
        tokenizer.add_special_tokens({"pad_token": "[PAD]"})

    text = corpus_file.read_text(encoding="utf-8", errors="ignore")
    token_ids = tokenizer.encode(text, add_special_tokens=False)
    samples = _build_chunks(token_ids, block_size=max(64, int(block_size)))
    if len(samples) < 4:
        raise ValueError("Corpus too small for pretraining. Add more text or lower block size.")

    split_idx = max(1, int(len(samples) * max(0.6, min(train_ratio, 0.98))))
    train_samples = samples[:split_idx]
    eval_samples = samples[split_idx:] or samples[-1:]

    train_dataset = Dataset.from_list(train_samples)
    eval_dataset = Dataset.from_list(eval_samples)

    config = GPT2Config(
        vocab_size=int(tokenizer.vocab_size),
        n_positions=int(block_size),
        n_ctx=int(block_size),
        n_embd=int(n_embd),
        n_layer=int(n_layer),
        n_head=int(n_head),
        bos_token_id=tokenizer.bos_token_id,
        eos_token_id=tokenizer.eos_token_id,
        pad_token_id=tokenizer.pad_token_id,
    )
    model = GPT2LMHeadModel(config)
    model.resize_token_embeddings(len(tokenizer))

    args = TrainingArguments(
        output_dir=str(output_dir),
        num_train_epochs=max(1, int(epochs)),
        per_device_train_batch_size=max(1, int(batch_size)),
        per_device_eval_batch_size=max(1, int(batch_size)),
        gradient_accumulation_steps=max(1, int(grad_accum)),
        learning_rate=float(learning_rate),
        logging_steps=10,
        save_strategy="epoch",
        eval_strategy="epoch",
        report_to="none",
        fp16=False,
    )

    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        data_collator=DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False),
    )

    train_result = trainer.train()
    eval_metrics = trainer.evaluate()

    model.save_pretrained(str(output_dir))
    tokenizer.save_pretrained(str(output_dir))

    summary = {
        "model_name": "Apex",
        "output_dir": str(output_dir),
        "train_samples": len(train_samples),
        "eval_samples": len(eval_samples),
        "block_size": int(block_size),
        "config": {
            "vocab_size": int(tokenizer.vocab_size),
            "n_layer": int(n_layer),
            "n_head": int(n_head),
            "n_embd": int(n_embd),
        },
        "train_metrics": dict(train_result.metrics),
        "eval_metrics": dict(eval_metrics),
    }
    (output_dir / "apex_pretrain_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pretrain Apex from scratch (GPT architecture) on text corpus.")
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--tokenizer-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--block-size", type=int, default=512)
    parser.add_argument("--train-ratio", type=float, default=0.9)
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--grad-accum", type=int, default=8)
    parser.add_argument("--learning-rate", type=float, default=3e-4)
    parser.add_argument("--n-layer", type=int, default=8)
    parser.add_argument("--n-head", type=int, default=8)
    parser.add_argument("--n-embd", type=int, default=512)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = pretrain_apex(
        corpus_file=Path(args.corpus),
        tokenizer_dir=Path(args.tokenizer_dir),
        output_dir=Path(args.output_dir),
        block_size=args.block_size,
        train_ratio=args.train_ratio,
        epochs=args.epochs,
        batch_size=args.batch_size,
        grad_accum=args.grad_accum,
        learning_rate=args.learning_rate,
        n_layer=args.n_layer,
        n_head=args.n_head,
        n_embd=args.n_embd,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
