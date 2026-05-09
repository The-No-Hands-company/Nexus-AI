from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def _render_chat(messages: list[dict]) -> str:
    chunks: list[str] = []
    for message in messages:
        role = str(message.get("role", "")).strip().lower()
        content = str(message.get("content", "")).strip()
        if role and content:
            chunks.append(f"{role}: {content}")
    return "\n".join(chunks)


def _load_jsonl_rows(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            messages = obj.get("messages")
            if not isinstance(messages, list):
                continue
            text = _render_chat(messages)
            if text:
                rows.append({"text": text})
    return rows


def _default_version() -> str:
    return datetime.now(timezone.utc).strftime("v%Y%m%d%H%M%S")


def train_lora_sft(
    base_model: str,
    train_file: str,
    val_file: str | None,
    output_dir: str,
    epochs: int = 1,
    batch_size: int = 2,
    grad_accum: int = 8,
    lr: float = 2e-4,
    max_length: int = 1024,
    lora_r: int = 16,
    lora_alpha: int = 32,
    lora_dropout: float = 0.05,
    use_4bit: bool = False,
    register_adapter: bool = False,
    adapter_id: str = "",
    adapter_version: str = "",
    hot_swap: bool = False,
    run_eval: bool = True,
    eval_provider: str = "offline",
    eval_suites: list[str] | None = None,
    eval_samples: int = 20,
) -> dict:
    train_path = Path(train_file)
    if not train_path.is_file():
        raise FileNotFoundError(f"Train file not found: {train_path}")

    val_path = Path(val_file) if val_file else None
    if val_path and not val_path.is_file():
        raise FileNotFoundError(f"Validation file not found: {val_path}")

    try:
        import torch
        from datasets import Dataset
        from peft import LoraConfig, get_peft_model
        from transformers import (
            AutoModelForCausalLM,
            AutoTokenizer,
            BitsAndBytesConfig,
            DataCollatorForLanguageModeling,
            Trainer,
            TrainingArguments,
        )
    except ImportError as exc:
        raise ImportError(
            "Training dependencies are missing. Install with: pip install transformers datasets peft accelerate trl bitsandbytes"
        ) from exc

    tokenizer = AutoTokenizer.from_pretrained(base_model, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    quantization_config = None
    if use_4bit:
        try:
            import bitsandbytes  # noqa: F401

            quantization_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_use_double_quant=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=torch.float16,
            )
        except Exception:
            quantization_config = None

    model = AutoModelForCausalLM.from_pretrained(
        base_model,
        trust_remote_code=True,
        quantization_config=quantization_config,
        torch_dtype=torch.float16 if quantization_config is None else None,
    )

    lora_cfg = LoraConfig(
        r=lora_r,
        lora_alpha=lora_alpha,
        lora_dropout=lora_dropout,
        bias="none",
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, lora_cfg)

    train_rows = _load_jsonl_rows(train_path)
    if not train_rows:
        raise ValueError("No train samples could be parsed from JSONL")

    val_rows = _load_jsonl_rows(val_path) if val_path else []

    train_dataset = Dataset.from_list(train_rows)
    eval_dataset = Dataset.from_list(val_rows) if val_rows else None

    def _tokenize(batch: dict) -> dict:
        encoded = tokenizer(
            batch["text"],
            truncation=True,
            max_length=max_length,
            padding="max_length",
        )
        encoded["labels"] = encoded["input_ids"].copy()
        return encoded

    train_dataset = train_dataset.map(_tokenize, batched=True, remove_columns=["text"])
    if eval_dataset is not None and len(eval_dataset) > 0:
        eval_dataset = eval_dataset.map(_tokenize, batched=True, remove_columns=["text"])
    else:
        eval_dataset = None

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    training_args = TrainingArguments(
        output_dir=str(output_path),
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        gradient_accumulation_steps=grad_accum,
        learning_rate=lr,
        logging_steps=10,
        save_strategy="epoch",
        eval_strategy="epoch" if eval_dataset is not None else "no",
        report_to="none",
        fp16=True,
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        data_collator=DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False),
    )

    train_result = trainer.train()
    model.save_pretrained(str(output_path))
    tokenizer.save_pretrained(str(output_path))

    metrics = dict(train_result.metrics)
    metrics["train_samples"] = len(train_rows)
    metrics["eval_samples"] = len(val_rows)
    metrics_path = output_path / "metrics.json"
    metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    resolved_adapter_id = adapter_id.strip() or f"{base_model.split('/')[-1]}-lora"
    resolved_adapter_version = adapter_version.strip() or _default_version()

    result: dict = {
        "output_dir": str(output_path),
        "metrics_file": str(metrics_path),
        "metrics": metrics,
        "adapter_id": resolved_adapter_id,
        "adapter_version": resolved_adapter_version,
    }

    if register_adapter:
        from src.db import save_lora_adapter_version, set_active_lora_adapter

        adapter_record = save_lora_adapter_version(
            adapter_id=resolved_adapter_id,
            version=resolved_adapter_version,
            base_model=base_model,
            checkpoint_uri=str(output_path),
            metrics=metrics,
            provenance={
                "source": "src.training.train_lora_sft",
                "train_file": str(train_path),
                "val_file": str(val_path) if val_path else "",
            },
            tags=["sft", "lora"],
            status="ready",
        )
        result["adapter_registry"] = adapter_record

        if hot_swap:
            active = set_active_lora_adapter(
                adapter_id=resolved_adapter_id,
                version=resolved_adapter_version,
                target_model=base_model,
            )
            result["hot_swap"] = {"enabled": True, "active_adapter": active}
        else:
            result["hot_swap"] = {"enabled": False}

    if run_eval:
        from src.eval_pipeline import run_baseline_vs_adapter_eval

        suites = eval_suites or ["code", "reasoning", "safety"]
        proof_report = run_baseline_vs_adapter_eval(
            base_model=base_model,
            adapter_id=resolved_adapter_id,
            adapter_version=resolved_adapter_version,
            provider=eval_provider,
            suites=suites,
            n_samples=max(1, int(eval_samples)),
        )
        eval_path = output_path / "baseline_vs_adapter_eval.json"
        eval_path.write_text(json.dumps(proof_report, indent=2), encoding="utf-8")
        result["evaluation"] = {
            "report_file": str(eval_path),
            "report": proof_report,
        }

    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run LoRA SFT on JSONL chat data.")
    parser.add_argument("--base-model", required=True, help="Base model id, e.g. Qwen/Qwen2.5-7B-Instruct")
    parser.add_argument("--train-file", required=True, help="Path to train JSONL with messages rows")
    parser.add_argument("--val-file", help="Optional validation JSONL")
    parser.add_argument("--output-dir", required=True, help="Directory to save LoRA adapter")
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--grad-accum", type=int, default=8)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--max-length", type=int, default=1024)
    parser.add_argument("--lora-r", type=int, default=16)
    parser.add_argument("--lora-alpha", type=int, default=32)
    parser.add_argument("--lora-dropout", type=float, default=0.05)
    parser.add_argument("--use-4bit", action="store_true", help="Enable 4-bit loading when bitsandbytes is available")
    parser.add_argument("--register-adapter", action="store_true", help="Register trained adapter into finetune adapter registry")
    parser.add_argument("--adapter-id", default="", help="Adapter ID for registry/evaluation")
    parser.add_argument("--adapter-version", default="", help="Adapter version for registry/evaluation")
    parser.add_argument("--hot-swap", action="store_true", help="Mark trained adapter as active in hot-swap state")
    parser.add_argument("--skip-eval", action="store_true", help="Skip baseline-vs-adapter evaluation")
    parser.add_argument("--eval-provider", default="offline", help="Provider label for evaluation records")
    parser.add_argument("--eval-suites", default="code,reasoning,safety", help="Comma-separated eval suites")
    parser.add_argument("--eval-samples", type=int, default=20, help="Number of samples per suite")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    suites = [s.strip() for s in str(args.eval_suites or "").split(",") if s.strip()]
    result = train_lora_sft(
        base_model=args.base_model,
        train_file=args.train_file,
        val_file=args.val_file,
        output_dir=args.output_dir,
        epochs=args.epochs,
        batch_size=args.batch_size,
        grad_accum=args.grad_accum,
        lr=args.lr,
        max_length=args.max_length,
        lora_r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
        use_4bit=bool(args.use_4bit),
        register_adapter=bool(args.register_adapter),
        adapter_id=args.adapter_id,
        adapter_version=args.adapter_version,
        hot_swap=bool(args.hot_swap),
        run_eval=not bool(args.skip_eval),
        eval_provider=args.eval_provider,
        eval_suites=suites,
        eval_samples=args.eval_samples,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
