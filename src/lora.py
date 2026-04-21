"""
src/lora.py — LoRA fine-tuning adapter management stub

This module is a STUB — all functions raise NotImplementedError until implemented.

Planned capabilities:
- LoRA fine-tuning job lifecycle (create / status / cancel)
- Adapter versioning and storage
- Hot-swap adapter onto a running Ollama base model
- RLHF / DPO pipeline integration
- Continual fine-tuning scheduler
- Eval-gated promotion (only promote adapter if benchmarks improve)
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class LoRAJob:
    job_id: str
    base_model: str
    dataset_path: str
    adapter_name: str
    status: str  # queued | running | completed | failed | cancelled
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: str | None = None
    error: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class LoRAAdapter:
    adapter_id: str
    adapter_name: str
    base_model: str
    version: int
    path: str                    # local filesystem path to adapter weights
    benchmark_score: float | None = None
    is_active: bool = False
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    notes: str = ""


# In-memory registries (will be persisted to DB once implemented)
_jobs: dict[str, LoRAJob] = {}
_adapters: dict[str, LoRAAdapter] = {}


# ---------------------------------------------------------------------------
# Fine-tuning job management
# ---------------------------------------------------------------------------

ADAPTER_STORE_DIR = os.getenv("ADAPTER_STORE_DIR", "/tmp/nexus_adapters")


def create_finetune_job(
    base_model: str,
    dataset_path: str,
    adapter_name: str,
    hyperparams: dict | None = None,
) -> LoRAJob:
    """Enqueue and launch a LoRA fine-tuning job via HuggingFace PEFT.

    Validates the dataset, allocates a job ID, persists the record, then
    dispatches a background subprocess that:
      1. Loads the base model with 4-bit quantisation (bitsandbytes)
      2. Wraps it in a LoraConfig (r=16, alpha=32, target_modules=auto)
      3. Trains on the JSONL dataset using HuggingFace Trainer
      4. Saves adapter weights to ADAPTER_STORE_DIR/<job_id>
      5. Updates the job record status to "completed" or "failed"

    Returns the LoRAJob immediately (status="queued") so the caller is not
    blocked on training.
    """
    import json as _json
    import threading

    # ── Validate dataset ──────────────────────────────────────────────────────
    if not base_model:
        raise ValueError("base_model is required")
    if not dataset_path:
        raise ValueError("dataset_path is required")
    if not os.path.isfile(dataset_path):
        raise FileNotFoundError(f"dataset_path not found: {dataset_path}")

    try:
        with open(dataset_path, encoding="utf-8") as f:
            samples = [_json.loads(line) for line in f if line.strip()]
        if not samples:
            raise ValueError("dataset is empty")
    except (_json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"Invalid JSONL dataset: {exc}") from exc

    # ── Create job record ─────────────────────────────────────────────────────
    hp = dict(hyperparams or {})
    job_id  = str(uuid.uuid4())
    job = LoRAJob(
        job_id=job_id,
        base_model=base_model,
        dataset_path=dataset_path,
        adapter_name=adapter_name,
        status="queued",
        metadata={
            "num_samples": len(samples),
            "hyperparams": hp,
        },
    )
    _jobs[job_id] = job

    output_dir = os.path.join(ADAPTER_STORE_DIR, job_id)
    os.makedirs(output_dir, exist_ok=True)

    # ── Launch background training thread ─────────────────────────────────────
    def _train():
        job.status = "running"
        try:
            _run_peft_training(
                base_model=base_model,
                dataset_path=dataset_path,
                output_dir=output_dir,
                hyperparams=hp,
            )
            job.status = "completed"
            job.completed_at = datetime.now(timezone.utc).isoformat()
            # Register adapter
            adapter_id = str(uuid.uuid4())[:8]
            _adapters[adapter_id] = LoRAAdapter(
                adapter_id=adapter_id,
                adapter_name=adapter_name,
                base_model=base_model,
                version=1,
                path=output_dir,
            )
        except Exception as exc:
            job.status = "failed"
            job.error = str(exc)[:500]
            job.completed_at = datetime.now(timezone.utc).isoformat()

    threading.Thread(target=_train, daemon=True, name=f"lora-{job_id[:8]}").start()
    return job


def _run_peft_training(base_model: str, dataset_path: str,
                        output_dir: str, hyperparams: dict) -> None:
    """Run HuggingFace PEFT LoRA training synchronously.

    Requires: transformers, peft, datasets, accelerate, bitsandbytes (optional)
    """
    from transformers import (  # type: ignore
        AutoModelForCausalLM, AutoTokenizer, TrainingArguments, Trainer,
        DataCollatorForLanguageModeling,
    )
    from peft import LoraConfig, get_peft_model, TaskType  # type: ignore
    from datasets import Dataset  # type: ignore
    import json as _json

    hp = hyperparams or {}
    lora_r           = int(hp.get("lora_r", 16))
    lora_alpha       = int(hp.get("lora_alpha", 32))
    lora_dropout     = float(hp.get("lora_dropout", 0.05))
    num_epochs       = int(hp.get("num_train_epochs", 1))
    per_device_batch = int(hp.get("per_device_train_batch_size", 4))
    max_length       = int(hp.get("max_length", 512))
    lr               = float(hp.get("learning_rate", 2e-4))

    tokenizer = AutoTokenizer.from_pretrained(base_model, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    # Load model (try 4-bit quantisation, fall back to float16)
    try:
        from transformers import BitsAndBytesConfig  # type: ignore
        import bitsandbytes  # type: ignore  # noqa: F401
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type="nf4",
        )
        model = AutoModelForCausalLM.from_pretrained(
            base_model, quantization_config=bnb_config, trust_remote_code=True
        )
    except Exception:
        model = AutoModelForCausalLM.from_pretrained(
            base_model, torch_dtype="auto", trust_remote_code=True
        )

    lora_config = LoraConfig(
        r=lora_r,
        lora_alpha=lora_alpha,
        lora_dropout=lora_dropout,
        bias="none",
        task_type=TaskType.CAUSAL_LM,
    )
    model = get_peft_model(model, lora_config)

    # Load JSONL dataset — expect {"instruction": ..., "output": ...} (Alpaca) or
    # {"messages": [...]} (ChatML) format.
    with open(dataset_path, encoding="utf-8") as f:
        raw_samples = [_json.loads(line) for line in f if line.strip()]

    def _to_text(sample: dict) -> str:
        if "messages" in sample:
            parts = [f"{m['role']}: {m['content']}" for m in sample["messages"]]
            return "\n".join(parts)
        inst   = sample.get("instruction", "")
        inp    = sample.get("input", "")
        output = sample.get("output", "")
        text = f"### Instruction:\n{inst}"
        if inp:
            text += f"\n\n### Input:\n{inp}"
        text += f"\n\n### Response:\n{output}"
        return text

    texts = [_to_text(s) for s in raw_samples]
    dataset = Dataset.from_dict({"text": texts})

    def tokenize(batch):
        return tokenizer(
            batch["text"],
            truncation=True,
            max_length=max_length,
            padding="max_length",
        )

    tokenized = dataset.map(tokenize, batched=True, remove_columns=["text"])

    training_args = TrainingArguments(
        output_dir=output_dir,
        num_train_epochs=num_epochs,
        per_device_train_batch_size=per_device_batch,
        learning_rate=lr,
        fp16=True,
        logging_steps=10,
        save_strategy="no",          # save manually after training
        report_to="none",
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=tokenized,
        data_collator=DataCollatorForLanguageModeling(tokenizer, mlm=False),
    )
    trainer.train()
    model.save_pretrained(output_dir)
    tokenizer.save_pretrained(output_dir)


def get_finetune_job(job_id: str) -> LoRAJob | None:
    """Return job by ID, or None. STUB (returns from in-memory dict)."""
    return _jobs.get(job_id)


def list_finetune_jobs(status: str | None = None) -> list[LoRAJob]:
    """List all fine-tuning jobs, optionally filtered by status."""
    jobs = list(_jobs.values())
    if status:
        jobs = [j for j in jobs if j.status == status]
    return jobs


def cancel_finetune_job(job_id: str) -> bool:
    """
    Cancel a queued or running fine-tuning job.

    STUB: raises NotImplementedError for running jobs.
    """
    job = _jobs.get(job_id)
    if not job:
        return False
    if job.status == "queued":
        job.status = "cancelled"
        return True
    raise NotImplementedError(
        "cancel_finetune_job for running jobs is not yet implemented. "
        "Planned: send SIGTERM to subprocess and clean up partial weights."
    )


# ---------------------------------------------------------------------------
# Adapter management
# ---------------------------------------------------------------------------

def list_adapters(base_model: str | None = None) -> list[LoRAAdapter]:
    """List all available LoRA adapters, optionally filtered by base model."""
    adapters = list(_adapters.values())
    if base_model:
        adapters = [a for a in adapters if a.base_model == base_model]
    return adapters


def get_adapter(adapter_id: str) -> LoRAAdapter | None:
    """Return adapter by ID, or None."""
    return _adapters.get(adapter_id)


def apply_adapter(adapter_id: str, base_model: str) -> dict:
    """Hot-load a LoRA adapter for inference via HuggingFace PEFT.

    Returns {"ok": True, "model_tag": "<base_model>+<adapter_name>"} so the
    caller can use the PEFT-merged model for inference. For Ollama-backed
    deployments, creates a Modelfile with the ADAPTER directive if the adapter
    was exported in GGUF format; otherwise falls back to HF PEFT merge.
    """
    adapter = _adapters.get(adapter_id)
    if not adapter:
        raise ValueError(f"Adapter '{adapter_id}' not found")
    if not os.path.isdir(adapter.path):
        raise FileNotFoundError(f"Adapter weights not found at: {adapter.path}")

    model_tag = f"{base_model}+{adapter.adapter_name}"

    # Try Ollama Modelfile approach first (for quantised/GGUF models)
    gguf_files = [f for f in os.listdir(adapter.path) if f.endswith(".gguf")]
    if gguf_files:
        modelfile_path = os.path.join(adapter.path, "Modelfile")
        with open(modelfile_path, "w", encoding="utf-8") as mf:
            mf.write(f"FROM {base_model}\n")
            mf.write(f"ADAPTER {os.path.join(adapter.path, gguf_files[0])}\n")
        import subprocess as _sp
        result = _sp.run(
            ["ollama", "create", model_tag, "-f", modelfile_path],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0:
            adapter.is_active = True
            return {"ok": True, "model_tag": model_tag, "method": "ollama_modelfile"}

    # HuggingFace PEFT merge (non-GGUF adapters)
    try:
        from peft import PeftModel  # type: ignore
        from transformers import AutoModelForCausalLM, AutoTokenizer  # type: ignore
        tokenizer = AutoTokenizer.from_pretrained(base_model, trust_remote_code=True)
        base = AutoModelForCausalLM.from_pretrained(base_model, torch_dtype="auto",
                                                     trust_remote_code=True)
        peft_model = PeftModel.from_pretrained(base, adapter.path)
        merged = peft_model.merge_and_unload()
        merged_path = os.path.join(adapter.path, "merged")
        merged.save_pretrained(merged_path)
        tokenizer.save_pretrained(merged_path)
        adapter.is_active = True
        return {"ok": True, "model_tag": model_tag, "method": "peft_merge",
                "merged_path": merged_path}
    except Exception as exc:
        raise RuntimeError(f"apply_adapter failed: {exc}") from exc


def rollback_adapter(adapter_name: str, version: int) -> dict:
    """Roll back the active adapter for *adapter_name* to the specified version.

    Looks for an adapter with matching name and version number in the registry.
    Deactivates all other adapters with the same name, then marks the target as active.
    """
    matches = [a for a in _adapters.values()
               if a.adapter_name == adapter_name and a.version == version]
    if not matches:
        raise ValueError(f"No adapter '{adapter_name}' at version {version}")
    target = matches[0]
    for a in _adapters.values():
        if a.adapter_name == adapter_name:
            a.is_active = False
    target.is_active = True
    return {"ok": True, "adapter_id": target.adapter_id, "version": version,
            "path": target.path}


# ---------------------------------------------------------------------------
# Training signal pipeline
# ---------------------------------------------------------------------------

def export_feedback_dataset(
    format: str = "alpaca",
    min_rating: int = 4,
    output_path: str | None = None,
) -> str:
    """Export stored feedback signals as a fine-tuning dataset.

    Queries the message_feedback table for reactions ≥ min_rating (👍/positive),
    joins with chat messages to reconstruct instruction/response pairs, and writes
    them as Alpaca-format JSONL.

    Args:
        format: "alpaca" (default) or "sharegpt"
        min_rating: minimum reaction score to include (4=positive, 1=any)
        output_path: write to this path; if None writes to a temp file

    Returns:
        Path to the exported JSONL file.
    """
    import json as _json
    import tempfile

    from src.db import load_chats, _load_json_pref

    # Collect positive-feedback messages from stored chats
    chats = load_chats()
    samples: list[dict] = []
    for chat in chats:
        messages = chat.get("messages") or []
        for idx, msg in enumerate(messages):
            if msg.get("role") == "assistant":
                # Find preceding user message
                user_msg = next(
                    (m for m in reversed(messages[:idx]) if m.get("role") == "user"),
                    None,
                )
                if user_msg is None:
                    continue
                instruction = str(user_msg.get("content") or "").strip()
                output      = str(msg.get("content") or "").strip()
                rating      = int(msg.get("rating") or msg.get("feedback_score") or 0)
                if rating >= min_rating and instruction and output:
                    if format == "sharegpt":
                        samples.append({
                            "messages": [
                                {"role": "user",      "content": instruction},
                                {"role": "assistant", "content": output},
                            ]
                        })
                    else:
                        samples.append({
                            "instruction": instruction,
                            "input":       "",
                            "output":      output,
                        })

    if not samples:
        raise ValueError("No feedback samples with sufficient rating found.")

    if output_path is None:
        fd, output_path = tempfile.mkstemp(suffix=".jsonl", prefix="nexus_ft_")
        os.close(fd)

    with open(output_path, "w", encoding="utf-8") as f:
        for sample in samples:
            f.write(_json.dumps(sample, ensure_ascii=False) + "\n")

    return output_path


def generate_synthetic_training_data(
    agent: str = "general",
    n_samples: int = 100,
    topic: str | None = None,
) -> list[dict]:
    """Generate synthetic instruction-response pairs via the configured LLM.

    Uses the best available provider (Claude > GPT-4o > Groq Llama3) to generate
    diverse instruction pairs on *topic*, safety-filters each pair, and returns
    a list of Alpaca-format dicts suitable for export_feedback_dataset.
    """
    import json as _json

    topic_hint = f" Focus on: {topic}." if topic else ""
    prompt = (
        f"Generate {n_samples} diverse instruction-response pairs for fine-tuning an AI assistant."
        f"{topic_hint}"
        " Format: JSON array of objects with keys 'instruction', 'input' (may be empty), 'output'."
        " Instructions should be varied in length and complexity."
        " Return only the JSON array, no markdown."
    )

    from src.agent import _call_single, PROVIDERS, _has_key  # type: ignore
    for pid in ("claude", "gpt-4o", "groq", "gemini"):
        cfg = PROVIDERS.get(pid, {})
        if not cfg or not _has_key(cfg):
            continue
        try:
            resp = _call_single(pid, [{"role": "user", "content": prompt}])
            text = resp.get("content") or str(resp)
            # Strip markdown fences if present
            text = text.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            samples = _json.loads(text)
            if isinstance(samples, list) and samples:
                # Safety-filter each pair
                from src.safety.safety_pipeline import screen_input  # type: ignore
                clean = []
                for s in samples:
                    verdict = screen_input(str(s.get("instruction", "")) + " " + str(s.get("output", "")))
                    if verdict.allowed:
                        clean.append(s)
                return clean
        except Exception:
            continue

    raise RuntimeError("No LLM provider available for synthetic data generation.")


# ---------------------------------------------------------------------------
# Production-ready job management API (used by routes.py)
# These functions use SQLite persistence via db.py.
# ---------------------------------------------------------------------------

def create_lora_job(
    base_model: str,
    dataset_path: str,
    adapter_name: str = "adapter",
    config: dict | None = None,
) -> dict:
    """
    Create and persist a new LoRA fine-tuning job with status 'queued'.

    The actual training is not dispatched here — a background worker or
    external orchestrator is expected to pick up queued jobs and advance
    their status via db updates.  This makes the endpoint idempotent and
    testable without GPU hardware.
    """
    from datetime import datetime, timezone
    from src.db import create_finetune_job_record

    if not base_model:
        raise ValueError("base_model is required")
    if not dataset_path:
        raise ValueError("dataset_path is required")

    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    return create_finetune_job_record(
        job_id=job_id,
        base_model=base_model,
        dataset_path=dataset_path,
        adapter_name=adapter_name or "adapter",
        config=config or {},
        created_at=now,
    )


def list_lora_jobs(status: str | None = None) -> list[dict]:
    """Return all fine-tuning jobs, optionally filtered by status."""
    from src.db import list_finetune_job_records
    return list_finetune_job_records(status=status)


def get_lora_job(job_id: str) -> dict | None:
    """Return a single fine-tuning job by ID, or None."""
    from src.db import get_finetune_job_record
    return get_finetune_job_record(job_id)


def cancel_lora_job(job_id: str) -> bool:
    """
    Cancel a queued or running fine-tuning job.
    Returns True if the job was cancelled, False if not found or already terminal.
    """
    from src.db import cancel_finetune_job_record
    return cancel_finetune_job_record(job_id)
