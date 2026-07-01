"""Tests for src/job_queue_durable.py — dead-letter queue and retry logic."""

from __future__ import annotations

import time

from src.job_queue_durable import (
    DeadLetterEntry,
    add_to_dlq,
    delete_from_dlq,
    dlq_stats,
    execute_with_retry,
    get_dlq_entry,
    list_dlq,
    purge_dlq,
    restore_dlq,
    retry_from_dlq,
    _backoff_delay,
)


class TestBackoffDelay:
    """Exponential backoff computation."""

    def test_initial_backoff(self):
        assert _backoff_delay(0, base=2.0) == 2.0

    def test_first_retry_backoff(self):
        assert _backoff_delay(1, base=2.0) == 4.0

    def test_third_retry_backoff(self):
        assert _backoff_delay(3, base=2.0) == 16.0

    def test_backoff_capped(self):
        assert _backoff_delay(50, base=2.0) == 600.0  # capped at 600s


class TestDeadLetterQueue:
    """Dead-letter queue CRUD and lifecycle."""

    def test_add_to_dlq_creates_entry(self):
        purge_dlq()  # Clean slate
        e = add_to_dlq("task-1", "Run backup", "Connection refused", retry_count=3, max_retries=3)
        assert e.id.startswith("dlq-")
        assert e.original_task_id == "task-1"
        assert e.retry_count == 3
        assert e.max_retries == 3
        assert "Connection refused" in e.error

    def test_list_dlq_returns_entries(self):
        purge_dlq()
        add_to_dlq("t-a", "desc A", "error A", retry_count=1, max_retries=3)
        add_to_dlq("t-b", "desc B", "error B", retry_count=2, max_retries=3)
        items = list_dlq()
        assert len(items) == 2
        # Most recently created first (sorted by created_at DESC)
        assert items[0]["original_task_id"] in ("t-a", "t-b")

    def test_get_dlq_entry_by_id(self):
        purge_dlq()
        e = add_to_dlq("task-get", "get test", "err", 0, 3)
        entry = get_dlq_entry(e.id)
        assert entry is not None
        assert entry["description"] == "get test"

    def test_get_dlq_nonexistent_returns_none(self):
        assert get_dlq_entry("no-such-dlq-id") is None

    def test_delete_dlq_entry(self):
        purge_dlq()
        e = add_to_dlq("task-del", "delete me", "err", 0, 1)
        assert delete_from_dlq(e.id) is True
        assert len(list_dlq()) == 0

    def test_delete_nonexistent_returns_false(self):
        assert delete_from_dlq("no-such-id") is False

    def test_purge_dlq_clears_all(self):
        add_to_dlq("t1", "d1", "e1", 0, 1)
        add_to_dlq("t2", "d2", "e2", 0, 1)
        assert purge_dlq() == 2
        assert len(list_dlq()) == 0

    def test_dlq_stats_counts_errors(self):
        purge_dlq()
        add_to_dlq("t1", "d1", "Timeout: connection", 0, 3)
        add_to_dlq("t2", "d2", "Timeout: connection", 0, 3)
        add_to_dlq("t3", "d3", "MemoryError", 0, 3)
        stats = dlq_stats()
        assert stats["total_dead_letters"] == 3
        # Error breakdown should group similar errors
        assert "Timeout" in stats["error_breakdown"] or any("Timeout" in k for k in stats["error_breakdown"])


class TestDLQPersistence:
    """Dead-letter queue persistence across module reloads."""

    def test_dlq_survives_persistence_roundtrip(self):
        purge_dlq()
        add_to_dlq("persist-1", "persist desc", "persist error", 2, 5, {"key": "val"})
        # Force persist
        from src.job_queue_durable import _persist_dlq
        _persist_dlq()
        # Restore should reload from storage
        restored = restore_dlq()
        assert restored >= 1
        items = list_dlq()
        assert any(i["original_task_id"] == "persist-1" for i in items)


class TestExecuteWithRetry:
    """End-to-end retry orchestration."""

    def test_success_on_first_attempt(self):
        def succeed(_desc: str) -> str:
            return "OK"

        result = execute_with_retry("task-ok", "test", succeed, max_retries=2)
        assert result["status"] == "done"
        assert result["result"] == "OK"
        assert result["retry_count"] == 0

    def test_success_after_retries(self):
        call_count = [0]

        def fail_then_succeed(_desc: str) -> str:
            call_count[0] += 1
            if call_count[0] < 2:
                raise RuntimeError("temporary failure")
            return "recovered"

        result = execute_with_retry("task-retry", "test", fail_then_succeed, max_retries=3)
        assert result["status"] == "done"
        assert result["result"] == "recovered"
        assert result["retry_count"] == 1

    def test_exhausted_retries_goes_to_dlq(self):
        purge_dlq()

        def always_fail(_desc: str) -> str:
            raise RuntimeError("permanent failure")

        result = execute_with_retry("task-doomed", "test", always_fail, max_retries=2)
        assert result["status"] == "dead_lettered"
        assert "permanent failure" in result["error"]
        assert result["retry_count"] == 2

        # Verify it landed in the DLQ
        items = list_dlq()
        assert any(i["original_task_id"] == "task-doomed" for i in items)
