"""
examples/rlhf_dpo_workflows.py — End-to-end RLHF and DPO workflow examples

Demonstrates:
1. Collecting user feedback → DPO training
2. Iterative RLHF with reward model
3. Multi-stage alignment pipeline
4. Monitoring and evaluation
"""

import json as _json
import os
import tempfile
import time
from typing import Optional

from src.rlhf_dpo import (
    prepare_dpo_dataset,
    create_dpo_job,
    run_dpo_training,
    create_rlhf_job,
    run_rlhf_training,
    get_dpo_job,
    get_rlhf_job,
)
from src.lora import load_adapter


# ───────────────────────────────────────────────────────────────────────────
# Workflow 1: Collect Feedback → DPO Training
# ───────────────────────────────────────────────────────────────────────────


def workflow_feedback_to_dpo(
    feedback_path: str,
    base_model: str = "meta-llama/Llama-2-7b",
    adapter_name: str = "dpo_from_feedback",
) -> dict:
    """
    End-to-end workflow: Collect user feedback → prepare dataset → train DPO.

    Assumes feedback is stored as JSONL with fields:
      {
        "prompt": "User question",
        "response_a": "Model response A",
        "response_b": "Model response B",
        "preferred": "a"  or "b",
        "rating": 4,  # 1-5
        "timestamp": "2024-01-15T10:30:00Z"
      }

    Args:
        feedback_path: Path to feedback JSONL
        base_model: Base model ID
        adapter_name: Name for trained adapter

    Returns:
        Dict with {job_id, status, metrics, adapter_path}
    """
    print("[1] Converting feedback to preference pairs...")

    # Step 1: Transform feedback → DPO format
    dpo_pairs = []
    with open(feedback_path) as f:
        for line in f:
            if not line.strip():
                continue
            feedback = _json.loads(line)

            prompt = feedback.get("prompt")
            response_a = feedback.get("response_a")
            response_b = feedback.get("response_b")
            preferred = feedback.get("preferred")
            rating = int(feedback.get("rating", 3))

            if not all([prompt, response_a, response_b, preferred]):
                continue

            # Convert rating to confidence margin
            margin = rating / 5.0

            # Determine chosen/rejected
            if preferred == "a":
                chosen, rejected = response_a, response_b
            else:
                chosen, rejected = response_b, response_a

            dpo_pairs.append({
                "prompt": prompt,
                "chosen": chosen,
                "rejected": rejected,
                "margin": margin,
                "source": "user_feedback",
            })

    # Write intermediate DPO pairs file
    fd, dpo_input = tempfile.mkstemp(suffix="_dpo_raw.jsonl")
    try:
        with os.fdopen(fd, "w") as f:
            for pair in dpo_pairs:
                f.write(_json.dumps(pair) + "\n")

        print(f"[2] Prepared {len(dpo_pairs)} preference pairs")

        # Step 2: Prepare/clean dataset
        print("[3] Validating and deduplicating dataset...")
        dpo_output = prepare_dpo_dataset(
            input_path=dpo_input,
            min_margin=0.6,  # Only high-confidence preferences
            dedup_window=7,
        )

        # Count final pairs
        with open(dpo_output) as f:
            final_pairs = len([l for l in f if l.strip()])
        print(f"[4] Final dataset: {final_pairs} pairs (filtered from {len(dpo_pairs)})")

        # Step 3: Create DPO job
        print(f"[5] Creating DPO job for {base_model}...")
        job = create_dpo_job(
            base_model=base_model,
            dataset_path=dpo_output,
            adapter_name=adapter_name,
            config={
                "lora_r": 16,
                "lora_alpha": 32,
                "num_epochs": 2,
                "per_device_batch_size": 8,
                "learning_rate": 5e-4,
                "dpo_beta": 0.1,
            },
        )
        print(f"[6] Job created: {job.job_id}")

        # Step 4: Run training (in production, use background worker)
        print("[7] Running DPO training...")
        run_dpo_training(job)

        if job.status == "completed":
            print(f"[8] ✓ Training completed!")
            print(f"    Loss: {job.metrics.get('loss_final', 'N/A')}")
            print(f"    Adapter: {job.adapter_path}")
        else:
            print(f"[8] ✗ Training failed: {job.error}")

        return {
            "job_id": job.job_id,
            "status": job.status,
            "metrics": job.metrics,
            "adapter_path": job.adapter_path,
            "num_pairs": final_pairs,
        }

    finally:
        if os.path.exists(dpo_input):
            os.remove(dpo_input)


# ───────────────────────────────────────────────────────────────────────────
# Workflow 2: Iterative RLHF with Evaluation
# ───────────────────────────────────────────────────────────────────────────


def workflow_iterative_rlhf(
    base_dataset_path: str,
    eval_dataset_path: str,
    base_model: str = "meta-llama/Llama-2-7b",
    adapter_name: str = "rlhf_iterative",
    max_rounds: int = 2,
) -> dict:
    """
    End-to-end workflow: Iterative RLHF with eval-gated promotion.

    Process:
      Round 1: Generate rollouts → Score with reward model → Fine-tune top-K
      Round 2: Repeat with updated model
      Eval: Compare metrics before/after
      Deploy: Only if improvement verified

    Args:
        base_dataset_path: Path to instruction-output pairs
        eval_dataset_path: Path to evaluation set (hold-out)
        base_model: Base model ID
        adapter_name: Adapter name
        max_rounds: Max RLHF iterations

    Returns:
        Dict with {status, rounds_completed, metrics, adapter_path, promoted}
    """
    print(f"\n[RLHF Workflow] Starting {max_rounds}-round training...")

    # Step 1: Create RLHF job
    print(f"[1] Creating RLHF job for {base_model}...")
    job = create_rlhf_job(
        base_model=base_model,
        dataset_path=base_dataset_path,
        adapter_name=adapter_name,
        config={
            "num_rounds": max_rounds,
            "num_rollouts": 5,
            "top_k": 2,
            "learning_rate": 5e-4,
        },
    )
    print(f"[2] Job ID: {job.job_id}")

    # Step 2: Run training
    print(f"[3] Running RLHF training ({max_rounds} rounds)...")
    run_rlhf_training(job, max_rounds=max_rounds)

    print(f"[4] Training completed: {job.rounds_completed} rounds")
    print(f"    Metrics: {job.metrics}")

    # Step 3: Evaluate
    print(f"[5] Running evaluation on hold-out set...")
    eval_result = _evaluate_adapter(job.adapter_path, eval_dataset_path)
    print(f"    Improvement: {eval_result.get('improvement_pct', 'N/A')}%")

    # Step 4: Promotion decision
    promoted = False
    if eval_result.get("improvement_pct", 0) > 2.0:
        print(f"[6] ✓ Improvement verified! Promoting to production...")
        promoted = True
    else:
        print(f"[6] ✗ No significant improvement. Keeping current adapter.")

    return {
        "job_id": job.job_id,
        "status": job.status,
        "rounds_completed": job.rounds_completed,
        "metrics": job.metrics,
        "adapter_path": job.adapter_path if promoted else None,
        "promoted": promoted,
        "eval_result": eval_result,
    }


# ───────────────────────────────────────────────────────────────────────────
# Workflow 3: Multi-Stage Alignment Pipeline
# ───────────────────────────────────────────────────────────────────────────


def workflow_multi_stage_alignment(
    feedback_path: str,
    base_model: str = "meta-llama/Llama-2-7b",
) -> dict:
    """
    Multi-stage pipeline:
      Stage 1: Supervised fine-tuning (SFT) on high-quality feedback
      Stage 2: DPO refinement using preference pairs
      Stage 3: RLHF fine-tuning with reward model (optional)

    Args:
        feedback_path: Raw user feedback JSONL
        base_model: Base model

    Returns:
        Dict with all stage results
    """
    print("\n[Multi-Stage Pipeline] Starting 3-stage alignment...\n")

    results = {}

    # ─── Stage 1: SFT (if available via separate mechanism)
    print("=" * 60)
    print("Stage 1: Supervised Fine-Tuning (SFT)")
    print("=" * 60)
    print("[Note: SFT uses export_feedback_dataset() from lora.py]")
    print("Skipping for this example (would run separately)")
    results["sft"] = {"status": "skipped"}

    # ─── Stage 2: DPO
    print("\n" + "=" * 60)
    print("Stage 2: Direct Preference Optimization (DPO)")
    print("=" * 60)
    dpo_result = workflow_feedback_to_dpo(
        feedback_path,
        base_model=base_model,
        adapter_name="multi_stage_dpo",
    )
    results["dpo"] = dpo_result

    if dpo_result["status"] != "completed":
        print("Stage 2 failed, skipping Stage 3")
        return results

    # ─── Stage 3: RLHF (optional, using DPO results as warm-start)
    print("\n" + "=" * 60)
    print("Stage 3: Reinforcement Learning from Human Feedback (RLHF)")
    print("=" * 60)
    print("[Note: Would warm-start from DPO adapter]")
    print("Skipping for this example (GPU-intensive)")
    results["rlhf"] = {"status": "skipped"}

    # Summary
    print("\n" + "=" * 60)
    print("Pipeline Summary")
    print("=" * 60)
    print(f"SFT:  {results['sft']['status']}")
    print(f"DPO:  {results['dpo']['status']} ({results['dpo'].get('num_pairs')} pairs)")
    print(f"RLHF: {results['rlhf']['status']}")

    return results


# ───────────────────────────────────────────────────────────────────────────
# Helper: Evaluation
# ───────────────────────────────────────────────────────────────────────────


def _evaluate_adapter(
    adapter_path: Optional[str],
    eval_dataset_path: str,
) -> dict:
    """
    Evaluate adapter on hold-out eval set.

    Simulated evaluation:
      - Load adapter
      - Run inference on eval set
      - Compare against baseline
      - Return improvement %

    In production: Use real evaluation metrics (BLEU, ROUGE, human eval, etc.)

    Args:
        adapter_path: Path to adapter weights (None = baseline)
        eval_dataset_path: Path to eval JSONL

    Returns:
        Dict with metrics and improvement %
    """
    print(f"  Loading adapter: {adapter_path or 'baseline (no adapter)'}")

    # Simulate evaluation
    # In production: Load model + adapter, run inference, compute metrics
    baseline_score = 75.0  # Simulated baseline
    adapter_score = 77.5 if adapter_path else baseline_score

    improvement_pct = ((adapter_score - baseline_score) / baseline_score) * 100

    return {
        "baseline_score": baseline_score,
        "adapter_score": adapter_score,
        "improvement_pct": improvement_pct,
        "samples_evaluated": 100,
    }


# ───────────────────────────────────────────────────────────────────────────
# Example: Create sample data and run workflows
# ───────────────────────────────────────────────────────────────────────────


def create_sample_feedback_data(path: str, n_samples: int = 50) -> str:
    """Create sample feedback data for testing."""
    with open(path, "w") as f:
        for i in range(n_samples):
            feedback = {
                "prompt": f"What is example {i}?",
                "response_a": f"Example {i} is a type of illustration...",
                "response_b": f"Example {i} is not something I know about.",
                "preferred": "a" if i % 3 != 0 else "b",
                "rating": 3 + (i % 3),
                "timestamp": f"2024-01-15T{10 + i//7:02d}:00:00Z",
            }
            f.write(_json.dumps(feedback) + "\n")
    return path


def create_sample_rlhf_data(path: str, n_samples: int = 50) -> str:
    """Create sample RLHF dataset."""
    with open(path, "w") as f:
        for i in range(n_samples):
            sample = {
                "instruction": f"Explain concept {i}",
                "output": f"Concept {i} is important because it demonstrates key principles of learning...",
            }
            f.write(_json.dumps(sample) + "\n")
    return path


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("RLHF/DPO Workflow Examples")
    print("=" * 60)

    # Create temporary data
    fd, feedback_path = tempfile.mkstemp(suffix="_feedback.jsonl")
    os.close(fd)
    create_sample_feedback_data(feedback_path, n_samples=20)

    fd, rlhf_path = tempfile.mkstemp(suffix="_rlhf.jsonl")
    os.close(fd)
    create_sample_rlhf_data(rlhf_path, n_samples=20)

    try:
        # Workflow 1: Feedback → DPO
        print("\n>>> Example 1: Feedback → DPO Training\n")
        result1 = workflow_feedback_to_dpo(feedback_path)
        print(f"\nResult: {result1}\n")

        # Workflow 2: Iterative RLHF (mock, no GPU)
        print("\n>>> Example 2: Iterative RLHF (simulated)\n")
        # result2 = workflow_iterative_rlhf(rlhf_path, feedback_path)
        print("Skipping actual RLHF (GPU-intensive)")
        print("See workflow_iterative_rlhf() for details\n")

        # Workflow 3: Multi-stage pipeline
        print("\n>>> Example 3: Multi-Stage Alignment Pipeline\n")
        result3 = workflow_multi_stage_alignment(feedback_path)
        print(f"\nPipeline complete.\n")

    finally:
        # Cleanup
        os.remove(feedback_path)
        os.remove(rlhf_path)

    print("=" * 60)
    print("All examples completed!")
    print("=" * 60)
