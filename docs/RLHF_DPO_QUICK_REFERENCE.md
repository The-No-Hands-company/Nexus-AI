# RLHF/DPO Quick Reference Card

**Nexus AI Preference-Based Alignment Training** - Common tasks and code snippets.

---

## 🚀 Quick Start (5 minutes)

```python
from src.rlhf_dpo import prepare_dpo_dataset, create_dpo_job, run_dpo_training

# 1. Prepare dataset
output = prepare_dpo_dataset("feedback.jsonl", min_margin=0.6)

# 2. Create job
job = create_dpo_job(
    base_model="meta-llama/Llama-2-7b",
    dataset_path=output,
    adapter_name="dpo_v1"
)

# 3. Train
run_dpo_training(job)

# 4. Check status
print(f"Status: {job.status}, Loss: {job.metrics.get('loss_final')}")
```

---

## 📊 Common Tasks

### Create DPO Dataset from Feedback

```python
from src.rlhf_dpo import prepare_dpo_dataset

dataset = prepare_dpo_dataset(
    input_path="user_feedback.jsonl",
    min_margin=0.6,          # Confidence threshold
    dedup_window=7,          # Days for dedup
    max_length=2048,         # Token limit
    output_path="/tmp/dpo.jsonl"  # Optional: custom output
)
```

**Input format:**
```json
{"prompt": "Q", "chosen": "Good answer", "rejected": "Bad answer", "margin": 0.9}
```

### Create DPO Job

```python
from src.rlhf_dpo import create_dpo_job, run_dpo_training

job = create_dpo_job(
    base_model="meta-llama/Llama-2-7b",
    dataset_path="/tmp/dpo.jsonl",
    adapter_name="dpo_v1",
    config={
        "lora_r": 16,
        "lora_alpha": 32,
        "num_epochs": 1,
        "learning_rate": 5e-4,
        "dpo_beta": 0.1,           # DPO temperature
    }
)

# Run training
run_dpo_training(job)
print(f"Job {job.job_id}: {job.status}")
```

### Create RLHF Job

```python
from src.rlhf_dpo import create_rlhf_job, run_rlhf_training

job = create_rlhf_job(
    base_model="meta-llama/Llama-2-7b",
    dataset_path="data.jsonl",
    adapter_name="rlhf_v1",
    config={"num_rounds": 2}
)

# Run training
run_rlhf_training(job, max_rounds=2)
print(f"Completed {job.rounds_completed} rounds")
```

### Monitor Job Status

```python
from src.rlhf_dpo import get_dpo_job, get_rlhf_job

# Get single job
dpo_job = get_dpo_job("job-id-123")
print(f"Status: {dpo_job.status}")
print(f"Metrics: {dpo_job.metrics}")

# Or RLHF
rlhf_job = get_rlhf_job("job-id-456")
print(f"Rounds: {rlhf_job.rounds_completed}")
```

### List All Jobs

```python
from src.rlhf_dpo import list_dpo_jobs, list_rlhf_jobs

# All DPO jobs
all_jobs = list_dpo_jobs()

# Only queued
queued = list_dpo_jobs(status="queued")

# Only completed
done = list_dpo_jobs(status="completed")

# Or RLHF
rlhf_jobs = list_rlhf_jobs(status="running")
```

---

## 🔌 API Endpoints

### Prepare DPO Dataset

```bash
curl -X POST http://localhost:8000/v1/rlhf/dpo/prepare \
  -F "file=@feedback.jsonl" \
  -F "min_margin=0.6" \
  -F "dedup_window=7"

# Response:
# {
#   "output_path": "/tmp/nexus_dpo_xyz.jsonl",
#   "num_pairs": 1234,
#   "status": "success"
# }
```

### Create DPO Job

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

# Response: {"job_id": "abc-123", "status": "queued", ...}
```

### Get Job Status

```bash
curl http://localhost:8000/v1/rlhf/dpo/job/abc-123

# Response: {"job_id": "abc-123", "status": "running", "metrics": {...}}
```

### List All Jobs

```bash
curl http://localhost:8000/v1/rlhf/dpo/jobs

# Optional: filter by status
curl http://localhost:8000/v1/rlhf/dpo/jobs?status=completed
```

### Health Check

```bash
curl http://localhost:8000/v1/rlhf/health

# Response:
# {
#   "status": "healthy",
#   "dpo_jobs_queued": 2,
#   "rlhf_jobs_queued": 1
# }
```

---

## 📝 Data Formats

### DPO Preference Pairs

```jsonl
{"prompt": "What is AI?", "chosen": "AI is artificial intelligence...", "rejected": "AI is aluminum", "margin": 1.0}
{"prompt": "Explain ML", "chosen": "Machine learning...", "rejected": "ML is bad", "margin": 0.8}
```

**Fields:**
- `prompt` (required): Question or instruction
- `chosen` (required): Preferred/positive response
- `rejected` (required): Non-preferred/negative response
- `margin` (optional): Confidence (0-1), default 1.0
- `source` (optional): Pair origin (feedback, synthetic, etc.)

### RLHF Dataset

```jsonl
{"instruction": "What is Python?", "output": "Python is a programming language..."}
{"instruction": "Explain lists", "output": "Lists are ordered collections..."}
```

### Job Status Response

```json
{
  "job_id": "abc-123-def",
  "base_model": "meta-llama/Llama-2-7b",
  "adapter_name": "dpo_v1",
  "status": "running",
  "created_at": "2024-01-15T10:30:00Z",
  "completed_at": null,
  "error": null,
  "metrics": {
    "loss_final": 0.45,
    "config": {...}
  },
  "adapter_path": null
}
```

---

## ⚙️ Hyperparameters

### DPO Training

| Parameter | Default | Range | Notes |
|-----------|---------|-------|-------|
| `lora_r` | 16 | 4-32 | LoRA rank (higher = more capacity) |
| `lora_alpha` | 32 | 8-64 | LoRA scaling factor |
| `lora_dropout` | 0.05 | 0-0.1 | Regularization |
| `num_epochs` | 1 | 1-3 | Training epochs (more = slower) |
| `per_device_batch_size` | 4 | 1-16 | Batch size per GPU |
| `learning_rate` | 5e-4 | 1e-5 to 1e-3 | Gradient step size |
| `dpo_beta` | 0.1 | 0.05-0.5 | DPO temperature (higher = stricter) |
| `max_length` | 512 | 256-2048 | Token limit |

### Tuning Guide

```
Out of memory?
  → Reduce per_device_batch_size (e.g., 4 → 2)
  → Reduce lora_r (e.g., 16 → 8)
  → Reduce max_length

Poor quality?
  → Check data quality (chosen really > rejected?)
  → Lower learning_rate (e.g., 5e-4 → 1e-4)
  → Increase num_epochs (e.g., 1 → 2)
  → Use more training data

Fast training needed?
  → Reduce num_epochs to 1
  → Use smaller max_length
  → Increase learning_rate slightly
  → Use fp16=True for 2x speedup
```

---

## 🧪 Testing

### Run Tests

```bash
pytest tests/test_rlhf_dpo.py -v
```

### Test Specific Class

```bash
pytest tests/test_rlhf_dpo.py::TestDPODatasetPreparation -v
```

### Run Examples

```bash
python examples/rlhf_dpo_workflows.py
```

### Import Check

```bash
python -c "from src.rlhf_dpo import prepare_dpo_dataset; print('✓')"
```

---

## 🔍 Debugging

### Check Job Status Codes

```
queued    → Waiting to run
running   → Currently training
completed → Finished successfully
failed    → Training failed (check job.error)
```

### Common Issues

**Job stuck in "queued":**
```bash
# Check if worker is running
ps aux | grep rlhf_worker

# Check database (if using persistence)
sqlite3 nexus.db "SELECT * FROM dpo_jobs WHERE status='queued';"
```

**Out of memory error:**
```python
config = {
    "per_device_batch_size": 1,  # Reduce
    "lora_r": 8,                  # Reduce
    "max_length": 256,            # Reduce
    "gradient_accumulation_steps": 8  # Add
}
```

**Training too slow:**
```python
config = {
    "num_epochs": 1,              # Reduce
    "max_length": 256,            # Reduce
    "learning_rate": 1e-3,        # Increase slightly
    "fp16": True,                 # Use mixed precision
}
```

**Poor quality after training:**
```
1. Verify data quality (chosen > rejected in all pairs)
2. Check margin distribution (too many low margins?)
3. Use more data (more pairs = better results)
4. Lower learning rate (learning too aggressively)
5. Check if base model is appropriate for task
```

---

## 🚀 Production Checklist

Before deploying:

- [ ] Test with mock data (no GPU needed)
- [ ] Run full test suite: `pytest tests/test_rlhf_dpo.py`
- [ ] Review API documentation: `docs/RLHF_DPO_GUIDE.md`
- [ ] Setup database persistence
- [ ] Create background worker script
- [ ] Add monitoring/alerting
- [ ] Test with real feedback (small sample)
- [ ] Monitor quality metrics
- [ ] Gradual rollout (10% → 50% → 100%)

---

## 📚 References

**Files:**
- `src/rlhf_dpo.py` - Core implementation
- `src/routes/rlhf.py` - API endpoints
- `docs/RLHF_DPO_GUIDE.md` - Full guide
- `examples/rlhf_dpo_workflows.py` - Examples
- `tests/test_rlhf_dpo.py` - Tests

**External:**
- [DPO Paper](https://arxiv.org/abs/2305.18290)
- [TRL Docs](https://huggingface.co/docs/trl/)
- [PEFT/LoRA](https://github.com/huggingface/peft)
- [Transformers](https://huggingface.co/docs/transformers/)

---

## 💡 Tips & Tricks

### Convert Feedback to DPO Format

```python
import json

# From user feedback with ratings
feedback = {
    "prompt": "Q",
    "response_a": "...",
    "response_b": "...",
    "preferred": "a",
    "rating": 4
}

# Convert to DPO
dpo_pair = {
    "prompt": feedback["prompt"],
    "chosen": feedback[f"response_{feedback['preferred']}"],
    "rejected": feedback[f"response_{'ba'[feedback['preferred']=='a']}"],
    "margin": feedback["rating"] / 5.0,
}
```

### Monitor Training Progress

```python
import time

job = create_dpo_job(...)

while job.status in ["queued", "running"]:
    print(f"Status: {job.status}")
    print(f"Metrics: {job.metrics}")
    time.sleep(60)  # Check every minute

print(f"Final: {job.status}")
```

### Batch Process Multiple Datasets

```python
datasets = ["feedback_1.jsonl", "feedback_2.jsonl"]

for dataset in datasets:
    output = prepare_dpo_dataset(dataset)
    job = create_dpo_job(
        base_model="llama",
        dataset_path=output,
        adapter_name=f"dpo_{datasets.index(dataset)}"
    )
    print(f"Job {job.job_id} created")
```

### Generate Synthetic Data

```python
from src.lora import generate_synthetic_training_data

pairs = generate_synthetic_training_data(
    agent="general",
    n_samples=100,
    topic="machine learning"
)

# Save as training data
with open("synthetic.jsonl", "w") as f:
    for pair in pairs:
        f.write(json.dumps(pair) + "\n")
```

---

## ❓ FAQ

**Q: How do I handle private/proprietary data?**
A: Data stays local. Use `output_path` parameter to control where it's saved.

**Q: Can I pause training?**
A: Not yet. Set `status="cancelled"` to stop, then retrain.

**Q: How do I rollback a bad adapter?**
A: Keep the base model as fallback. Each adapter is versioned.

**Q: Can I combine adapters?**
A: Not directly. You'd need to merge via LoRA merge tools (future enhancement).

**Q: What's the cost per training?**
A: Depends on GPU. Roughly: hours_trained × gpu_cost_per_hour.

**Q: How do I handle class imbalance?**
A: Filter by margin. Low-confidence pairs are automatically excluded.

---

## 🎯 Next Actions

1. **Now**: Read `docs/RLHF_DPO_GUIDE.md`
2. **Today**: Run `python examples/rlhf_dpo_workflows.py`
3. **This Week**: Integrate routes (5 minutes)
4. **Next Week**: Run background worker
5. **Next Month**: Deploy to production

---

**Last Updated**: 2024
**Status**: ✅ Production-Ready
**Questions**: See full docs in `docs/RLHF_DPO_GUIDE.md`
