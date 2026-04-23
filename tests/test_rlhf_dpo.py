"""
tests/test_rlhf_dpo.py — Test suite for RLHF and DPO training modules

Tests:
- DPO dataset preparation (validation, filtering, deduplication)
- DPO job lifecycle
- RLHF job lifecycle
- Error handling and recovery
- Synthetic data generation
"""

import json as _json
import os
import tempfile
import importlib
import pytest

from src.rlhf_dpo import (
    PreferencePair,
    DPOJob,
    RLHFJob,
    prepare_dpo_dataset,
    create_dpo_job,
    run_dpo_training,
    create_rlhf_job,
    run_rlhf_training,
    get_dpo_job,
    list_dpo_jobs,
    get_rlhf_job,
    list_rlhf_jobs,
)


class TestPreferencePair:
    """PreferencePair data model tests."""

    def test_preference_pair_creation(self):
        """Test basic PreferencePair creation."""
        pair = PreferencePair(
            prompt="What is 2+2?",
            chosen="2+2=4",
            rejected="2+2=5",
        )
        assert pair.prompt == "What is 2+2?"
        assert pair.chosen == "2+2=4"
        assert pair.rejected == "2+2=5"
        assert pair.margin == 1.0
        assert pair.source == "feedback"

    def test_preference_pair_with_metadata(self):
        """Test PreferencePair with custom margin and source."""
        pair = PreferencePair(
            prompt="Explain Python",
            chosen="Python is a programming language...",
            rejected="Python is a snake",
            margin=0.8,
            source="human_eval",
        )
        assert pair.margin == 0.8
        assert pair.source == "human_eval"


class TestDPOJobLifecycle:
    """DPO job creation and status management tests."""

    @pytest.fixture
    def temp_dataset(self):
        """Create a temporary DPO dataset file."""
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        try:
            with os.fdopen(fd, "w") as f:
                pairs = [
                    {
                        "prompt": "What is AI?",
                        "chosen": "AI is artificial intelligence...",
                        "rejected": "AI is aluminum oxide",
                        "margin": 1.0,
                    },
                    {
                        "prompt": "Explain ML",
                        "chosen": "Machine learning enables systems to learn...",
                        "rejected": "ML is bad",
                        "margin": 0.9,
                    },
                ]
                for pair in pairs:
                    f.write(_json.dumps(pair) + "\n")
            yield path
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_create_dpo_job(self, temp_dataset):
        """Test DPO job creation."""
        job = create_dpo_job(
            base_model="meta-llama/Llama-2-7b",
            dataset_path=temp_dataset,
            adapter_name="test_adapter",
        )
        assert job.status == "queued"
        assert job.base_model == "meta-llama/Llama-2-7b"
        assert job.adapter_name == "test_adapter"
        assert job.job_id is not None

    def test_create_dpo_job_validation(self):
        """Test DPO job creation validation."""
        with pytest.raises(ValueError):
            create_dpo_job(base_model="", dataset_path="/tmp/fake.jsonl")

        with pytest.raises(FileNotFoundError):
            create_dpo_job(
                base_model="llama",
                dataset_path="/tmp/nonexistent_xyzzz.jsonl",
            )

    def test_get_dpo_job(self, temp_dataset):
        """Test retrieving a DPO job."""
        job = create_dpo_job(
            base_model="llama",
            dataset_path=temp_dataset,
        )
        retrieved = get_dpo_job(job.job_id)
        assert retrieved is not None
        assert retrieved.job_id == job.job_id

    def test_list_dpo_jobs(self, temp_dataset):
        """Test listing DPO jobs with filtering."""
        job1 = create_dpo_job(base_model="llama", dataset_path=temp_dataset)
        job2 = create_dpo_job(base_model="mistral", dataset_path=temp_dataset)

        all_jobs = list_dpo_jobs()
        assert len(all_jobs) >= 2

        queued_jobs = list_dpo_jobs(status="queued")
        assert job1 in queued_jobs
        assert job2 in queued_jobs


class TestRLHFJobLifecycle:
    """RLHF job creation and management tests."""

    @pytest.fixture
    def temp_rlhf_dataset(self):
        """Create a temporary RLHF dataset file."""
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        try:
            with os.fdopen(fd, "w") as f:
                samples = [
                    {
                        "instruction": "What is Python?",
                        "output": "Python is a programming language...",
                    },
                    {
                        "instruction": "Explain lists",
                        "output": "Lists are ordered collections...",
                    },
                ]
                for sample in samples:
                    f.write(_json.dumps(sample) + "\n")
            yield path
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_create_rlhf_job(self, temp_rlhf_dataset):
        """Test RLHF job creation."""
        job = create_rlhf_job(
            base_model="meta-llama/Llama-2-7b",
            dataset_path=temp_rlhf_dataset,
            adapter_name="rlhf_test",
        )
        assert job.status == "queued"
        assert job.base_model == "meta-llama/Llama-2-7b"
        assert job.rounds_completed == 0

    def test_get_rlhf_job(self, temp_rlhf_dataset):
        """Test retrieving an RLHF job."""
        job = create_rlhf_job(
            base_model="llama",
            dataset_path=temp_rlhf_dataset,
        )
        retrieved = get_rlhf_job(job.job_id)
        assert retrieved is not None
        assert retrieved.job_id == job.job_id

    def test_list_rlhf_jobs(self, temp_rlhf_dataset):
        """Test listing RLHF jobs."""
        job1 = create_rlhf_job(base_model="llama", dataset_path=temp_rlhf_dataset)
        job2 = create_rlhf_job(base_model="mistral", dataset_path=temp_rlhf_dataset)

        all_jobs = list_rlhf_jobs()
        assert len(all_jobs) >= 2

        queued_jobs = list_rlhf_jobs(status="queued")
        assert job1 in queued_jobs


class TestDPODatasetPreparation:
    """DPO dataset validation and preparation tests."""

    @pytest.fixture
    def valid_dpo_pairs(self):
        """Create a valid DPO dataset."""
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        try:
            with os.fdopen(fd, "w") as f:
                pairs = [
                    {
                        "prompt": "What is AI?",
                        "chosen": "AI is artificial intelligence...",
                        "rejected": "AI is aluminum oxide",
                        "margin": 1.0,
                        "source": "feedback",
                    },
                    {
                        "prompt": "Explain ML",
                        "chosen": "Machine learning is a subset of AI...",
                        "rejected": "ML is bad",
                        "margin": 0.95,
                        "source": "human_eval",
                    },
                ]
                for pair in pairs:
                    f.write(_json.dumps(pair) + "\n")
            yield path
        finally:
            if os.path.exists(path):
                os.remove(path)

    @pytest.fixture
    def invalid_dpo_pairs(self):
        """Create an invalid DPO dataset."""
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        try:
            with os.fdopen(fd, "w") as f:
                # Missing fields
                f.write(_json.dumps({"prompt": "test"}) + "\n")
                # Empty
                f.write("\n")
                # Invalid JSON
                f.write("{ invalid json\n")
        finally:
            pass
        return path

    def test_prepare_dpo_dataset_valid(self, valid_dpo_pairs):
        """Test preparing a valid DPO dataset."""
        output_path = prepare_dpo_dataset(valid_dpo_pairs)
        assert os.path.exists(output_path)

        # Verify output
        with open(output_path) as f:
            lines = f.readlines()
            assert len(lines) == 2  # Both pairs included

        # Clean up
        os.remove(output_path)

    def test_prepare_dpo_dataset_filtering(self):
        """Test DPO dataset filtering by margin."""
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        try:
            with os.fdopen(fd, "w") as f:
                pairs = [
                    {
                        "prompt": "Q1",
                        "chosen": "Good",
                        "rejected": "Bad",
                        "margin": 0.9,
                    },
                    {
                        "prompt": "Q2",
                        "chosen": "Good",
                        "rejected": "Bad",
                        "margin": 0.4,  # Will be filtered out
                    },
                ]
                for pair in pairs:
                    f.write(_json.dumps(pair) + "\n")

            output_path = prepare_dpo_dataset(path, min_margin=0.6)
            with open(output_path) as f:
                lines = f.readlines()
                assert len(lines) == 1  # Only high-margin pair

            os.remove(output_path)
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_prepare_dpo_dataset_deduplication(self):
        """Test deduplication of identical prompts."""
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        try:
            with os.fdopen(fd, "w") as f:
                # Same prompt, different responses
                pairs = [
                    {
                        "prompt": "Same Q",
                        "chosen": "Response A",
                        "rejected": "Bad A",
                        "margin": 0.9,
                    },
                    {
                        "prompt": "Same Q",
                        "chosen": "Response B (newer)",
                        "rejected": "Bad B",
                        "margin": 0.95,
                    },
                ]
                for pair in pairs:
                    f.write(_json.dumps(pair) + "\n")

            output_path = prepare_dpo_dataset(path)
            with open(output_path) as f:
                lines = f.readlines()
                assert len(lines) == 1  # Deduplicated to 1

                # Should keep the newer (last) one
                obj = _json.loads(lines[0])
                assert "newer" in obj["chosen"]

            os.remove(output_path)
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_prepare_dpo_dataset_empty_raises(self, invalid_dpo_pairs):
        """Test that empty datasets raise ValueError."""
        with pytest.raises(ValueError, match="No valid"):
            prepare_dpo_dataset(invalid_dpo_pairs)

        os.remove(invalid_dpo_pairs)

    def test_prepare_dpo_dataset_not_found(self):
        """Test FileNotFoundError for missing input."""
        with pytest.raises(FileNotFoundError):
            prepare_dpo_dataset("/tmp/nonexistent_xyz.jsonl")

    def test_prepare_dpo_dataset_output_path_override(self, valid_dpo_pairs):
        """Test custom output path."""
        fd, custom_output = tempfile.mkstemp(suffix="_custom.jsonl")
        os.close(fd)

        try:
            result_path = prepare_dpo_dataset(valid_dpo_pairs, output_path=custom_output)
            assert result_path == custom_output
            assert os.path.exists(custom_output)
        finally:
            if os.path.exists(custom_output):
                os.remove(custom_output)


class TestDPOTrainingMock:
    """Mock tests for DPO training (without actual GPU)."""

    @pytest.fixture
    def temp_dataset(self):
        """Create a minimal dataset."""
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(_json.dumps({
                    "prompt": "Test", "chosen": "Good", "rejected": "Bad"
                }) + "\n")
            yield path
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_dpo_job_status_transitions(self, temp_dataset):
        """Test DPO job status transitions."""
        job = create_dpo_job(
            base_model="llama",
            dataset_path=temp_dataset,
        )
        assert job.status == "queued"

        # Simulate running
        job.status = "running"
        assert job.status == "running"

        # Simulate completion
        job.status = "completed"
        job.adapter_path = "/tmp/adapter"
        assert job.status == "completed"
        assert job.adapter_path is not None

    def test_dpo_job_error_handling(self, temp_dataset):
        """Test DPO job error tracking."""
        job = create_dpo_job(
            base_model="llama",
            dataset_path=temp_dataset,
        )
        job.status = "failed"
        job.error = "CUDA out of memory"

        assert job.status == "failed"
        assert "memory" in job.error.lower()


class TestRLHFTrainingMock:
    """Mock tests for RLHF training."""

    @pytest.fixture
    def temp_dataset(self):
        """Create a minimal RLHF dataset."""
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(_json.dumps({
                    "instruction": "Test", "output": "Good output"
                }) + "\n")
            yield path
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_rlhf_job_round_tracking(self, temp_dataset):
        """Test RLHF job round completion tracking."""
        job = create_rlhf_job(
            base_model="llama",
            dataset_path=temp_dataset,
        )
        assert job.rounds_completed == 0

        # Simulate rounds
        job.rounds_completed = 1
        job.metrics["round_1_samples"] = 10
        assert job.rounds_completed == 1
        assert job.metrics["round_1_samples"] == 10

        job.rounds_completed = 2
        job.metrics["round_2_samples"] = 8
        assert job.rounds_completed == 2

    def test_rlhf_job_error_recovery(self, temp_dataset):
        """Test RLHF job error state."""
        job = create_rlhf_job(
            base_model="llama",
            dataset_path=temp_dataset,
        )
        job.status = "failed"
        job.error = "Out of memory on round 2"
        job.rounds_completed = 1

        assert job.status == "failed"
        assert job.rounds_completed == 1  # Can retry from here


class TestIntegration:
    """Integration tests combining DPO and RLHF workflows."""

    @pytest.fixture
    def feedback_data(self):
        """Create feedback data."""
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        try:
            with os.fdopen(fd, "w") as f:
                for i in range(5):
                    f.write(_json.dumps({
                        "prompt": f"Q{i}",
                        "chosen": f"Good answer {i}",
                        "rejected": f"Bad answer {i}",
                        "margin": 0.9 + i * 0.02,
                    }) + "\n")
            yield path
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_workflow_dpo_then_rlhf(self, feedback_data):
        """Test a workflow: prepare DPO data → create job → create RLHF job."""
        # 1. Prepare DPO dataset
        dpo_output = prepare_dpo_dataset(feedback_data)
        assert os.path.exists(dpo_output)

        # 2. Create DPO job
        dpo_job = create_dpo_job(
            base_model="llama",
            dataset_path=dpo_output,
            adapter_name="dpo_v1",
        )
        assert dpo_job.status == "queued"

        # 3. Create RLHF job
        rlhf_job = create_rlhf_job(
            base_model="llama",
            dataset_path=feedback_data,
            adapter_name="rlhf_v1",
        )
        assert rlhf_job.status == "queued"

        # Verify both are tracked
        assert get_dpo_job(dpo_job.job_id) is not None
        assert get_rlhf_job(rlhf_job.job_id) is not None

        # Clean up
        os.remove(dpo_output)


class TestPersistenceDurability:
    """Persistence tests for restart recovery and failure-state durability."""

    @pytest.fixture
    def persistent_modules(self, tmp_path, monkeypatch):
        db_path = tmp_path / "rlhf_dpo_persistence.db"
        monkeypatch.setenv("DB_PATH", str(db_path))
        monkeypatch.delenv("DATABASE_URL", raising=False)

        import src.db as db_mod
        import src.rlhf_dpo as rlhf_mod

        db_mod = importlib.reload(db_mod)
        db_mod.init_db()
        rlhf_mod = importlib.reload(rlhf_mod)
        yield db_mod, rlhf_mod

    @pytest.fixture
    def temp_dataset(self):
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(_json.dumps({
                    "prompt": "Persist me",
                    "chosen": "Good answer",
                    "rejected": "Bad answer",
                    "margin": 0.9,
                }) + "\n")
            yield path
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_dpo_job_survives_module_restart(self, persistent_modules, temp_dataset):
        _, rlhf_mod = persistent_modules

        created = rlhf_mod.create_dpo_job(
            base_model="llama",
            dataset_path=temp_dataset,
            adapter_name="persist_restart",
        )
        job_id = created.job_id

        # Simulate process restart by reloading module (clears in-memory registries).
        rlhf_mod = importlib.reload(rlhf_mod)

        recovered = rlhf_mod.get_dpo_job(job_id)
        assert recovered is not None
        assert recovered.job_id == job_id
        assert recovered.status == "queued"
        assert recovered.adapter_name == "persist_restart"

    def test_failed_dpo_job_error_persists(self, persistent_modules, temp_dataset):
        _, rlhf_mod = persistent_modules

        job = rlhf_mod.create_dpo_job(
            base_model="llama",
            dataset_path=temp_dataset,
            adapter_name="persist_failure",
        )

        job.status = "failed"
        job.error = "simulated persistence failure"
        job.completed_at = "2026-04-22T00:00:00Z"
        rlhf_mod.save_dpo_job(job)

        # Simulate process restart and verify failed payload survives.
        rlhf_mod = importlib.reload(rlhf_mod)
        recovered = rlhf_mod.get_dpo_job(job.job_id)
        assert recovered is not None
        assert recovered.status == "failed"
        assert recovered.error is not None
        assert "simulated persistence failure" in recovered.error
        assert recovered.completed_at == "2026-04-22T00:00:00Z"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
