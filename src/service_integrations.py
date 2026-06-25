"""Service integration stubs for external services (calendar, email, notifications).

These provide clean, typed interfaces that can be wired to real APIs later.
Each service returns structured data and logs activity, ensuring no silent failures.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


# ── Calendar service ──────────────────────────────────────────────────────────

@dataclass
class CalendarEvent:
    """A calendar event."""
    id: str
    title: str
    start: str
    end: str
    description: str = ""
    location: str = ""
    attendees: List[str] = field(default_factory=list)


@dataclass
class CalendarResult:
    """Result of a calendar operation."""
    success: bool
    events: List[CalendarEvent] = field(default_factory=list)
    error: str = ""
    source: str = "stub"


def fetch_calendar_events(
    user_id: str,
    time_range_days: int = 7,
    max_events: int = 10,
) -> CalendarResult:
    """Fetch upcoming calendar events for a user.

    Stub implementation — replace with actual Google Calendar / Outlook API call.
    """
    logger.info(
        "Calendar fetch requested for user=%s range=%dd max=%d (stub)",
        user_id, time_range_days, max_events,
    )
    # TODO: Replace with actual API call:
    #   events = google_calendar_api.list_events(user_id, time_min=now, time_max=now+timedelta(days=time_range_days))
    return CalendarResult(
        success=True,
        events=[],
        source="stub",
    )


# ── Email service ─────────────────────────────────────────────────────────────

@dataclass
class EmailMessage:
    """An email message."""
    id: str
    subject: str
    sender: str
    recipients: List[str] = field(default_factory=list)
    body: str = ""
    received_at: str = ""
    is_read: bool = False


@dataclass
class EmailResult:
    """Result of an email operation."""
    success: bool
    messages: List[EmailMessage] = field(default_factory=list)
    error: str = ""
    source: str = "stub"


def fetch_unread_emails(
    user_id: str,
    max_messages: int = 10,
) -> EmailResult:
    """Fetch unread email messages for a user.

    Stub implementation — replace with actual Gmail / Outlook API call.
    """
    logger.info(
        "Email fetch requested for user=%s max=%d (stub)",
        user_id, max_messages,
    )
    # TODO: Replace with actual API call:
    #   messages = gmail_api.list_messages(user_id, q="is:unread", max_results=max_messages)
    return EmailResult(
        success=True,
        messages=[],
        source="stub",
    )


def send_email(
    user_id: str,
    to: List[str],
    subject: str,
    body: str,
    cc: List[str] | None = None,
) -> EmailResult:
    """Send an email.

    Stub implementation — replace with actual email API call.
    """
    logger.info(
        "Email send requested from=%s to=%s subject=%r (stub)",
        user_id, to, subject,
    )
    # TODO: Replace with actual API call:
    #   gmail_api.send_message(user_id, to=to, subject=subject, body=body)
    return EmailResult(
        success=True,
        messages=[],
        source="stub",
    )


# ── Notification service ──────────────────────────────────────────────────────

@dataclass
class Notification:
    """A notification to deliver."""
    id: str
    title: str
    body: str
    channel: str = "push"  # push, email, sms, in_app
    priority: str = "normal"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class NotificationResult:
    """Result of a notification delivery."""
    success: bool
    delivered: int = 0
    failed: int = 0
    errors: List[str] = field(default_factory=list)
    source: str = "stub"


def send_notification(
    user_id: str,
    title: str,
    body: str,
    channel: str = "push",
    priority: str = "normal",
) -> NotificationResult:
    """Send a notification to a user via the specified channel.

    Stub implementation — replace with actual push/FCM/email/SMS API calls.
    """
    logger.info(
        "Notification send requested user=%s title=%r channel=%s (stub)",
        user_id, title, channel,
    )
    # TODO: Replace with actual notification delivery:
    #   fcm_api.send(user_id, title=title, body=body)
    #   or twilio_api.send_sms(user_id, body=body)
    #   or email_api.send(user_id, subject=title, body=body)
    return NotificationResult(
        success=True,
        delivered=0,
        source="stub",
    )


def send_bulk_notifications(
    user_ids: List[str],
    title: str,
    body: str,
    channel: str = "push",
) -> NotificationResult:
    """Send notifications to multiple users.

    Stub implementation.
    """
    logger.info(
        "Bulk notification requested users=%d title=%r (stub)",
        len(user_ids), title,
    )
    return NotificationResult(
        success=True,
        delivered=0,
        source="stub",
    )


# ── Service health check ──────────────────────────────────────────────────────

def get_service_health() -> Dict[str, Any]:
    """Return health status of all integrated services."""
    return {
        "calendar": {
            "status": "available",
            "provider": "stub",
            "message": "Not yet connected to a real calendar API. Set CALENDAR_PROVIDER env var.",
        },
        "email": {
            "status": "available",
            "provider": "stub",
            "message": "Not yet connected to a real email API. Set EMAIL_PROVIDER env var.",
        },
        "notifications": {
            "status": "available",
            "provider": "stub",
            "message": "Not yet connected to a real notification service. Set NOTIFICATION_PROVIDER env var.",
        },
    }
