# Apex Model Family: Executable Implementation Plan

This repository now supports a model-family workflow where:
- `apex-foundation` remains immutable after release.
- Specialist tracks (starting with `apex-code`) are trained independently.
- `apex-voltron` is optional and can be trained as an aggregator model later.

## 1) Family topology and policy

- Config: `configs/apex_models/family_plan.json`
- Key policy: foundation model is immutable (`policy: immutable`).

## 2) Data schema + ingestion for code training

- Schema module: `src/training/code/schema.py`
- Dataset normalizer: `scripts/build_apex_code_dataset.py`
- Output rows include language/license/edition/source tags and `messages` for training.

Run:

```bash
make train-apex-code APEX_CODE_INPUT=/path/to/raw_code_data.jsonl
```

Or just normalize data:

```bash
python scripts/build_apex_code_dataset.py \
  --input /path/to/raw_code_data.jsonl \
  --output /tmp/apex_code/normalized.jsonl \
  --allow-licenses MIT,Apache-2.0,BSD-3-Clause \
  --require-edition
```

## 3) Apex-Code training presets

- `configs/apex_models/presets/apex_code_0p5b.json`
- `configs/apex_models/presets/apex_code_1p5b.json`

Pipeline orchestrator:
- `scripts/run_apex_code_pipeline.py`

Run with preset:

```bash
make train-apex-code \
  APEX_CODE_INPUT=/path/to/raw_code_data.jsonl \
  APEX_CODE_PRESET=apex_code_0p5b \
  APEX_CODE_OUTPUT_DIR=/tmp/apex_code/run_001
```

## 4) Coding benchmark harness wired to pipeline

- Harness: `src/training/coding_benchmark.py`
- CLI runner: `scripts/run_apex_code_benchmarks.py`
- The Apex-Code pipeline runs benchmark automatically unless `--skip-benchmark` is used.

Manual run:

```bash
make bench-apex-code \
  APEX_CODE_BASE_URL=http://localhost:8000 \
  APEX_CODE_MODEL=nexus-ai/apex
```

## 5) Tool-augmented inference loop (generate -> test -> self-fix)

- Engine: `src/training/tool_augmented_loop.py`
- CLI runner: `scripts/run_apex_code_autofix.py`

Run:

```bash
make autofix-apex-code \
  APEX_CODE_AUTOFIX_TASK="Implement function add(a, b) that returns sum" \
  APEX_CODE_AUTOFIX_TARGET_FILE=/tmp/apex_code/work/candidate.py \
  APEX_CODE_AUTOFIX_TEST_CMD="python3 -c \"from pathlib import Path; ns={}; exec(Path('/tmp/apex_code/work/candidate.py').read_text(), ns); assert ns['add'](2,3)==5\""
```

## 6) Multi-model strategy (specialists first, Voltron later)

Execution order:
1. Keep `apex-foundation` frozen.
2. Train specialist tracks independently (`apex-code`, `apex-security`, `apex-research`, etc.).
3. Evaluate each track on dedicated benchmarks.
4. Build `apex-voltron` by mixture/distillation only after specialist quality is stable.

This avoids catastrophic forgetting and keeps each specialist high-signal.
