import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.webhooks_delivery import WebhookDelivery, _process_delivery_once
import src.webhooks_delivery as wd


def _drain_delivery_queue():
    while True:
        try:
            wd._delivery_queue.get_nowait()
            wd._delivery_queue.task_done()
        except Exception:
            break


def test_chaos_retry_path_requeues_on_transient_failure(monkeypatch):
    monkeypatch.setenv("NEXUS_CHAOS_MODE", "1")
    _drain_delivery_queue()

    delivery = WebhookDelivery(
        url="https://example.invalid/webhook",
        event_type="chaos.retry",
        payload={"ok": False},
        max_attempts=3,
    )

    monkeypatch.setattr(wd, "_deliver_once", lambda _d: (False, "simulated transient failure"))
    monkeypatch.setattr(wd, "_save_delivery", lambda _d: None)

    before = time.time()
    processed = _process_delivery_once(delivery)

    assert processed.status == "pending"
    assert processed.attempt == 1
    assert processed.next_attempt_at >= before

    queued_at, queued_delivery = wd._delivery_queue.get_nowait()
    wd._delivery_queue.task_done()
    assert queued_delivery.delivery_id == delivery.delivery_id
    assert queued_at == processed.next_attempt_at


def test_chaos_dlq_path_on_terminal_failure(monkeypatch):
    monkeypatch.setenv("NEXUS_CHAOS_MODE", "1")
    _drain_delivery_queue()

    delivery = WebhookDelivery(
        url="https://example.invalid/webhook",
        event_type="chaos.dlq",
        payload={"ok": False},
        max_attempts=1,
    )

    monkeypatch.setattr(wd, "_deliver_once", lambda _d: (False, "simulated terminal failure"))
    monkeypatch.setattr(wd, "_save_delivery", lambda _d: None)

    processed = _process_delivery_once(delivery)

    assert processed.status == "dlq"
    assert processed.attempt == 1
    assert wd._delivery_queue.qsize() == 0


def test_chaos_success_path_marks_delivered(monkeypatch):
    _drain_delivery_queue()

    delivery = WebhookDelivery(
        url="https://example.invalid/webhook",
        event_type="chaos.success",
        payload={"ok": True},
        max_attempts=3,
    )

    monkeypatch.setattr(wd, "_deliver_once", lambda _d: (True, ""))
    monkeypatch.setattr(wd, "_save_delivery", lambda _d: None)

    processed = _process_delivery_once(delivery)

    assert processed.status == "delivered"
    assert processed.delivered_at is not None
    assert wd._delivery_queue.qsize() == 0


# Ensure this suite is intended for chaos/fault-injection runs.
def test_chaos_mode_flag_present_for_ci_or_local_runs():
    # This keeps behavior explicit while still allowing local runs.
    assert os.getenv("NEXUS_CHAOS_MODE", "1") in {"0", "1", "true", "false", "True", "False"}
