"""
RLHF and DPO Training Guide

This document provides a comprehensive guide to Nexus AI's RLHF and DPO
preference-based alignment training capabilities.
"""

# RLHF and DPO Training in Nexus AI

## Overview

**RLHF (Reinforcement Learning from Human Feedback)** and **DPO (Direct Preference Optimization)** are modern alignment techniques that fine-tune language models based on human preferences rather than just supervised labels.

- **DPO**: Directly optimizes the model to prefer chosen responses over rejected ones without an external reward model.
- **RLHF**: Uses a separate reward model to score responses, then fine-tunes via RL.

Both are implemented in `src/rlhf_dpo.py` with production-ready APIs in `src/routes/rlhf.py`.

---

## Architecture

### Components

```
┌─────────────────────────────────────────────────────────┐
│  Nexus AI RLHF/DPO System                              │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌──────────────────────────────────────────────┐     │
│  │ Data Preparation (src/rlhf_dpo.py)          │     │
│  │ - prepare_dpo_dataset()                      │     │
│  │   * Validate preference pairs               │     │
│  │   * Filter by confidence margin             │     │
│  │   * Deduplicate prompts                     │     │
│  │   * Normalize text                          │     │
│  └──────────────────────────────────────────────┘     │
│                        ↓                                │
│  ┌──────────────────────────────────────────────┐     │
│  │ Training Engines                             │     │
│  │ - run_dpo_training(job)                      │     │
│  │   * Load base model (4-bit quantized)       │     │
│  │   * Apply LoRA adapters                     │     │
│  │   * Train with DPO loss                     │     │
│  │ - run_rlhf_training(job)                     │     │
│  │   * Iterative refinement (N rounds)         │     │
│  │   * Reward model scoring                    │     │
│  │   * Supervised FT on top-K                  │     │
│  └──────────────────────────────────────────────┘     │
│                        ↓                                │
│  ┌──────────────────────────────────────────────┐     │
│  │ Job Management (src/routes/rlhf.py)          │     │
│  │ - POST /v1/rlhf/dpo/prepare                  │     │
│  │ - POST /v1/rlhf/dpo/job                      │     │
│  │ - GET  /v1/rlhf/dpo/job/{id}                 │     │
│  │ - POST /v1/rlhf/job                          │     │
│  │ - GET  /v1/rlhf/job/{id}                     │     │
│  └──────────────────────────────────────────────┘     │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### Data Flow

```
User Feedback
     │
     ↓
┌────────────────────────────────────────────┐
│ Collect Preferences (chats, ratings, etc)  │
└────────────────────────────────────────────┘
     │
     ↓
┌────────────────────────────────────────────┐
│ DPO Dataset Preparation                    │
│ - Validate (prompt, chosen, rejected)      │
│ - Filter by confidence margin              │
│ - Deduplicate                              │
│ - Output: JSONL with pairs                 │
└────────────────────────────────────────────┘
     │
     ├─────────────────────┬─────────────────────┐
     ↓                     ↓                     ↓
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ DPO Training │  │RLHF Training │  │Manual Review │
│  (Direct FT) │  │  (Iterative) │  │  (Optional)  │
└──────────────┘  └──────────────┘  └──────────────┘
     │                     │                     │
     └─────────────────────┴─────────────────────┘
                     │
                     ↓
         ┌──────────────────────────┐
         │ Eval-Gated Promotion     │
         │ - Benchmark improvement? │
         │ - Deploy to production   │
         └──────────────────────────┘
                     │
                     ↓
              Production Adapter
```

---

## DPO Workflow

### Step 1: Prepare Dataset

```python
from src.rlhf_dpo import prepare_dpo_dataset

# Input: JSONL with preference pairs
# {"prompt": "...", "chosen": "...", "rejected": "...", "margin": 1.0}

output_path = prepare_dpo_dataset(
    input_path="feedback.jsonl",
    min_margin=0.6,          # Filter low-confidence pairs
    dedup_window=7,          # Keep latest pair per prompt (7-day window)
    max_length=2048,         # Token limit per response
)
# Returns: Path to cleaned dataset
```

### Step 2: Create DPO Job

```python
from src.rlhf_dpo import create_dpo_job

job = create_dpo_job(
    base_model="meta-llama/Llama-2-7b",
    dataset_path=output_path,
    adapter_name="dpo_v1",
    config={
        "lora_r": 16,
        "lora_alpha": 32,
        "lora_dropout": 0.05,
        "num_epochs": 1,
        "per_device_batch_size": 4,
        "learning_rate": 5e-4,
        "dpo_beta": 0.1,        # DPO temperature
        "max_length": 512,
    }
)

print(f"Job ID: {job.job_id}, Status: {job.status}")
# Status: "queued"
```

### Step 3: Run Training

```python
from src.rlhf_dpo import run_dpo_training

# Typically run in background via worker
run_dpo_training(job, output_dir="/tmp/nexus_dpo/")

# Monitor progress
while job.status == "running":
    print(f"Training... Metrics: {job.metrics}")
    time.sleep(10)

print(f"Final: {job.status}, Loss: {job.metrics.get('loss_final')}")
# Status: "completed"
```

### Step 4: Deploy Adapter

```python
# Load adapter onto running model
from src.lora import load_adapter

adapter = load_adapter(
    base_model_id="llama",
    adapter_path=job.adapter_path,
)

# Use in inference
response = adapter.generate(prompt, max_new_tokens=100)
```

---

## RLHF Workflow

### Step 1: Prepare Base Dataset

```python
# Input: Instruction-output pairs (simpler than DPO)
# {"instruction": "...", "output": "..."}

base_dataset = "dataset.jsonl"
```

### Step 2: Create RLHF Job

```python
from src.rlhf_dpo import create_rlhf_job

job = create_rlhf_job(
    base_model="meta-llama/Llama-2-7b",
    dataset_path=base_dataset,
    adapter_name="rlhf_v1",
    config={
        "num_rounds": 2,
        "num_rollouts": 5,
        "top_k": 2,
        "learning_rate": 5e-4,
    }
)
```

### Step 3: Run Training

```python
from src.rlhf_dpo import run_rlhf_training

# Iterative loop with reward model and supervised FT
run_rlhf_training(job, max_rounds=2)

print(f"Rounds completed: {job.rounds_completed}")
print(f"Metrics per round: {job.metrics}")
```

---

## API Usage

### Via HTTP

#### 1. Prepare DPO Dataset

```bash
curl -X POST http://localhost:8000/v1/rlhf/dpo/prepare \
  -H "Content-Type: multipart/form-data" \
  -F "file=@feedback.jsonl" \
  -F "min_margin=0.6"

# Response:
{
  "output_path": "/tmp/nexus_dpo_xyz.jsonl",
  "num_pairs": 1234,
  "status": "success"
}
```

#### 2. Create DPO Job

```bash
curl -X POST http://localhost:8000/v1/rlhf/dpo/job \
  -H "Content-Type: application/json" \
  -d '{
    "base_model": "meta-llama/Llama-2-7b",
    "dataset_path": "/tmp/nexus_dpo_xyz.jsonl",
    "adapter_name": "dpo_v1",
    "config": {
      "num_epochs": 1,
      "learning_rate": 5e-4
    }
  }'

# Response:
{
  "job_id": "abc-123",
  "status": "queued",
  "base_model": "meta-llama/Llama-2-7b",
  "adapter_name": "dpo_v1",
  ...
}
```

#### 3. Check Job Status

```bash
curl http://localhost:8000/v1/rlhf/dpo/job/abc-123

# Response:
{
  "job_id": "abc-123",
  "status": "running",  # or "completed", "failed"
  "metrics": {
    "loss_final": 0.45,
    "config": {...}
  },
  "adapter_path": null,  # Set when complete
  ...
}
```

#### 4. List Jobs

```bash
# All DPO jobs
curl http://localhost:8000/v1/rlhf/dpo/jobs

# Filtered by status
curl http://localhost:8000/v1/rlhf/dpo/jobs?status=completed
```

#### 5. RLHF Endpoints

```bash
# Create RLHF job
curl -X POST http://localhost:8000/v1/rlhf/job \
  -H "Content-Type: application/json" \
  -d '{"base_model": "llama", "dataset_path": "..."}'

# Get status
curl http://localhost:8000/v1/rlhf/job/xyz-456

# List all
curl http://localhost:8000/v1/rlhf/jobs
```

---

## Data Formats

### DPO Dataset (Input)

```jsonl
{"prompt": "What is AI?", "chosen": "AI is artificial intelligence...", "rejected": "AI is aluminum oxide", "margin": 1.0, "source": "feedback"}
{"prompt": "Explain ML", "chosen": "Machine learning enables systems to learn from data", "rejected": "ML is bad", "margin": 0.9, "source": "human_eval"}
```

### RLHF Dataset (Input)

```jsonl
{"instruction": "What is Python?", "output": "Python is a programming language..."}
{"instruction": "Explain lists", "output": "Lists are ordered collections of items..."}
```

### Job Metadata

```python
@dataclass
class DPOJob:
    job_id: str                         # UUID
    base_model: str                     # "meta-llama/Llama-2-7b"
    dataset_path: str                   # Path to DPO JSONL
    adapter_name: str                   # "dpo_v1"
    status: str                         # queued|running|completed|failed
    created_at: str                     # ISO timestamp
    completed_at: str | None            # ISO timestamp
    error: str | None                   # Error message if failed
    metrics: dict                       # Training metrics
    adapter_path: str | None            # Path to trained adapter
```

---

## Configuration

### DPO Hyperparameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `lora_r` | 16 | LoRA rank |
| `lora_alpha` | 32 | LoRA alpha (scaling) |
| `lora_dropout` | 0.05 | Dropout rate |
| `num_epochs` | 1 | Training epochs |
| `per_device_batch_size` | 4 | Batch size |
| `learning_rate` | 5e-4 | Learning rate |
| `dpo_beta` | 0.1 | DPO temperature (higher = stricter) |
| `max_length` | 512 | Token limit |

### RLHF Hyperparameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `num_rounds` | 2 | Iteration rounds |
| `num_rollouts` | 5 | Rollouts per prompt |
| `top_k` | 2 | Select top-K best |
| `learning_rate` | 5e-4 | Learning rate per round |

---

## Best Practices

### 1. Data Quality

- **High-quality pairs**: Ensure "chosen" is genuinely better than "rejected"
- **Diverse prompts**: Cover various use cases and domains
- **Sufficient margin**: Filter pairs with low confidence (margin < 0.6)
- **Deduplicate**: Remove duplicate prompts to prevent overfitting

### 2. Training

- **Start small**: Use 1-2 epochs to avoid overfitting
- **Monitor metrics**: Track loss, accuracy, and margins
- **Conservative LR**: Use 5e-4 or lower to preserve base knowledge
- **Batch size**: Use 4-8 per GPU for stability

### 3. Evaluation

- **Pre/post comparison**: Compare outputs before/after fine-tuning
- **Benchmark gating**: Only deploy if metrics improve
- **Hold-out test set**: Reserve 10% of pairs for evaluation
- **A/B testing**: Compare with production baseline

### 4. Deployment

- **Gradual rollout**: Enable for 10% of users first
- **Fallback plan**: Keep base model active for rollback
- **Monitoring**: Track quality metrics and user feedback
- **Retraining**: Periodically retrain with new feedback

---

## Troubleshooting

### Out of Memory

```python
# Reduce batch size
config = {"per_device_batch_size": 1, "gradient_accumulation_steps": 4}

# Or use lower LoRA rank
config = {"lora_r": 8}  # Instead of 16
```

### Slow Training

```python
# Use mixed precision
config = {"fp16": True}

# Reduce max_length
config = {"max_length": 256}

# Use more GPUs
# Requires distributed training setup
```

### Poor Quality After Training

```python
# Check data quality
# - Verify chosen > rejected in all pairs
# - Look for margin distribution

# Lower learning rate
config = {"learning_rate": 1e-4}

# Use more training data
# - Collect additional feedback
# - Increase num_epochs slightly (but not too much)
```

### Job Stuck in "running"

```python
# Check logs
job = get_dpo_job(job_id)
print(f"Status: {job.status}, Error: {job.error}")

# Monitor GPU/memory usage
# Check disk space for adapter output

# Cancel and retry
job.status = "cancelled"
```

---

## Testing

Run test suite:

```bash
pytest tests/test_rlhf_dpo.py -v
```

Key tests:
- Dataset preparation (validation, filtering, deduplication)
- Job creation and lifecycle
- Error handling
- Integration workflows

---

## Production Deployment

### 1. Background Worker

```python
# workers/rlhf_worker.py
from src.rlhf_dpo import list_dpo_jobs, run_dpo_training

while True:
    queued_jobs = list_dpo_jobs(status="queued")
    for job in queued_jobs:
        job.status = "running"
        run_dpo_training(job)
    time.sleep(60)
```

### 2. Database Persistence

```python
# Extend to use DB instead of in-memory dict
from src.db import persist_dpo_job

job = create_dpo_job(...)
persist_dpo_job(job)  # Save to SQLite
```

### 3. Monitoring

```python
# Track job metrics, failures, latency
from src.monitoring import log_job_completed

log_job_completed(job, metrics=job.metrics)
```

### 4. Scaling

- **Multiple workers**: Run training on separate GPUs
- **Queue system**: Use Redis or message broker
- **Distributed training**: Support multi-GPU via accelerate

---

## References

- **DPO Paper**: Rafailov et al., 2023. "Direct Preference Optimization"
- **RLHF**: Ouyang et al., 2022. "Training language models to follow instructions"
- **PEFT/LoRA**: Hu et al., 2021. "LoRA: Low-Rank Adaptation"
- **TRL**: HuggingFace Transformers Reinforcement Learning library

---

## Next Steps

- [ ] Implement multi-GPU training (accelerate)
- [ ] Add reward model fine-tuning
- [ ] Implement evaluation pipeline
- [ ] Add auto-retraining scheduler
- [ ] Support additional LLM architectures
- [ ] Benchmark quality improvements
