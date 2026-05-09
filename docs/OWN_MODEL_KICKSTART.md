# Build Your Own Nexus Model: Kickstart

This guide starts the real path to a Nexus-owned model trained on your data.

If your goal is to create your own base model family (Apex), use the Apex Foundation Pipeline below.

## Reality Check

There are two very different goals:

1. Train from scratch (pretraining)
2. Fine-tune an existing base model (LoRA/QLoRA)

For almost all teams, start with option 2.

Training from scratch requires very large datasets, significant GPU budget, and long experiment cycles. Fine-tuning gives most of the product benefit much faster and can run on a single GPU.

## Recommended Path for Nexus AI

1. Export and curate Nexus interaction data
2. Build instruction/chat training data (SFT)
3. Run LoRA fine-tuning on a strong base model
4. Evaluate against baseline
5. Register and hot-swap adapters in Nexus runtime
6. Add DPO/RLHF for preference alignment

## What Was Added

This repo now includes:

- `src/training/build_sft_dataset.py`: builds SFT JSONL from Nexus feedback/export-like JSONL
- `src/training/train_lora_sft.py`: runs LoRA or QLoRA supervised fine-tuning
- `scripts/run_model_pipeline.py`: one-command orchestration (dataset -> train -> register -> hot-swap -> eval)
- `Makefile` target `train-model-pipeline`: shell-friendly entrypoint for repeat runs
- `src/training/build_apex_corpus.py`: converts Nexus JSONL to plain text corpus for pretraining
- `src/training/train_apex_tokenizer.py`: trains Apex tokenizer from your corpus
- `src/training/pretrain_apex.py`: trains Apex from scratch (GPT architecture initialized from config)
- `scripts/run_apex_foundation_pipeline.py`: one-command Apex foundation pipeline
- `Makefile` target `train-apex-foundation`: one-command Apex launch

## Apex Foundation Pipeline (From Scratch)

Use this when you want Apex to be your own model family, not a Qwen fine-tune.

### One-command Apex run

```bash
python scripts/run_apex_foundation_pipeline.py \
   --input examples/feedback_sample.jsonl \
   --output-dir /tmp/apex_foundation/latest \
   --vocab-size 32000 \
   --block-size 512 \
   --epochs 1 \
   --batch-size 2 \
   --grad-accum 8 \
   --learning-rate 3e-4 \
   --n-layer 8 \
   --n-head 8 \
   --n-embd 512
```

### Make target

```bash
make train-apex-foundation \
   APEX_INPUT=examples/feedback_sample.jsonl \
   APEX_OUTPUT_DIR=/tmp/apex_foundation/latest \
   APEX_VOCAB_SIZE=32000 \
   APEX_BLOCK_SIZE=512
```

### Apex outputs

- `corpus/apex_corpus.txt`
- `tokenizer/` (tokenizer files)
- `model/` (Apex checkpoints + tokenizer)
- `apex_pipeline_summary.json`

### Important note

This is a true from-scratch bootstrap path, but it is still a small-scale training setup.
Qwen-class capability requires much larger data and GPU budget. This pipeline is the correct first engineering foundation for Apex.

## Data Format Input (Accepted)

The dataset builder accepts multiple row styles per JSONL line:

1. Preference row:
   - `{"prompt": "...", "chosen": "...", "rejected": "..."}`
2. Alpaca row:
   - `{"instruction": "...", "input": "...", "output": "..."}`
3. Chat row:
   - `{"messages": [{"role": "user", "content": "..."}, ...]}`

## Quick Start

### 1) Build SFT dataset from your exported data

```bash
python -m src.training.build_sft_dataset \
  --input examples/feedback_sample.jsonl \
  --train-output /tmp/nexus_sft_train.jsonl \
  --val-output /tmp/nexus_sft_val.jsonl \
  --val-ratio 0.1 \
  --min-chars 24
```

### 2) Install training extras

`requirements.txt` already includes core transformer stack. For training, add:

```bash
pip install trl bitsandbytes
```

Notes:
- `bitsandbytes` is optional but recommended for memory savings.
- If `bitsandbytes` is unavailable, training falls back to non-4bit model loading.

### 3) Run LoRA SFT

```bash
python -m src.training.train_lora_sft \
  --base-model Qwen/Qwen2.5-7B-Instruct \
  --train-file /tmp/nexus_sft_train.jsonl \
  --val-file /tmp/nexus_sft_val.jsonl \
  --output-dir /tmp/nexus_adapter_run_001 \
  --epochs 1 \
  --batch-size 2 \
  --grad-accum 8 \
  --lr 2e-4 \
  --max-length 1024 \
  --lora-r 16 \
  --lora-alpha 32 \
  --lora-dropout 0.05 \
  --use-4bit
```

### 3b) One-command pipeline (recommended)

```bash
python scripts/run_model_pipeline.py \
   --input examples/feedback_sample.jsonl \
   --base-model Qwen/Qwen2.5-7B-Instruct \
   --output-dir /tmp/nexus_model_pipeline/latest \
   --adapter-id nexus-prime-alpha-sft \
   --use-4bit \
   --eval-provider offline
```

Or with Make:

```bash
make train-model-pipeline \
   INPUT=examples/feedback_sample.jsonl \
   BASE_MODEL=Qwen/Qwen2.5-7B-Instruct \
   OUTPUT_DIR=/tmp/nexus_model_pipeline/latest \
   ADAPTER_ID=nexus-prime-alpha-sft
```

Pipeline outputs include:

- `dataset/train.jsonl` and `dataset/val.jsonl`
- trained adapter files
- `metrics.json`
- `baseline_vs_adapter_eval.json`
- `pipeline_summary.json`

### 4) Evaluate before promotion

Do not deploy adapters without regression checks. Use your existing eval pipeline and compare:

- baseline model quality
- fine-tuned adapter quality
- safety regressions
- latency and cost

### 5) Integrate with Nexus

After validation:

1. Register adapter metadata through your finetune/adapters APIs
2. Use hot-swap endpoints for controlled activation
3. Keep rollback-ready previous adapter versions

## Suggested Milestones

1. Milestone A: First clean SFT dataset generated from real Nexus usage
2. Milestone B: First adapter trained and validated on internal benchmark set
3. Milestone C: Staging hot-swap with rollback exercised
4. Milestone D: DPO training on high-confidence preference pairs
5. Milestone E: Continuous retraining policy with eval gate

## Common Pitfalls

1. Training on noisy feedback without curation
2. Using a tiny validation set and overestimating gains
3. Deploying without safety regression checks
4. Mixing domains in one adapter without tags/slicing
5. Forgetting provenance metadata (dataset version/checksum)

## Next Upgrade Path

Once SFT is stable:

1. Add domain slices (coding, reasoning, research) with separate adapters
2. Add DPO with curated high-margin pairs
3. Add distillation to smaller student models for cheaper inference
