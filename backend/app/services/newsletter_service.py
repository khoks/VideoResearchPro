"""Newsletter subscriptions and scheduled delivery (S-6.4.2 / E-6.4).

A reader has at most one subscription. Saving it schedules (or reschedules)
the scheduler row kind ``newsletter`` for it (S-8.3.1, D-077); deleting or
disabling it removes or disables that row, so the next tick does nothing.

``deliver`` is what the tick's task runs for a due row:

1. **Claim the period.** Insert ``newsletter_sends(subscription_id,
   period_key)``, unique, BEFORE anything is generated. A second dispatch
   for the same period (a tick retried after a broker hiccup, a duplicate
   worker) hits the constraint and returns ``duplicate`` without generating
   or sending. The period key is the slot's ISO week, date or month in the
   subscription's own timezone.
2. **Make the issue** through the newsletter outputter (S-6.4.1) over
   ``(last_issue_at, now]``, with the subscription's sections.
3. **Deliver it.** A ``skipped`` issue (nothing new) sends nothing; the
   outputs list says why. A completed issue is emailed (HTML with a
   plain-text part and a deterministic ``Message-ID``, through the fail-soft
   ``email_service``) and announced in the bell. ``last_issue_at`` moves to
   the end of the window either way, so windows never overlap or gap.

"Send now" uses the same path with a period key of its own, so it never
blocks or is blocked by the scheduled issue.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models.newsletter_subscription import NewsletterSend, NewsletterSubscription
from app.models.output import Output
from app.models.user import User
from app.services import email_service, notification_service, output_artifacts, output_service, scheduler_service
from app.services.outputters.newsletter import DEFAULT_SECTIONS, sections_from

logger = logging.getLogger(__name__)

KIND = "newsletter"
DEFAULT_CADENCE = {"cadence": "weekly", "weekday": 0, "hour": 8, "minute": 0, "timezone": "UTC"}
DEFAULT_WINDOW = timedelta(days=7)


class NewsletterError(ValueError):
    pass


def _now() -> datetime:
    # Full precision: truncating to the second put rows written earlier in
    # the same second just after the window, a second late (S-6.4.2 tests).
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Subscriptions
# ---------------------------------------------------------------------------


def get_for(db: Session, tenant_id: str) -> NewsletterSubscription | None:
    return db.query(NewsletterSubscription).filter(NewsletterSubscription.tenant_id == tenant_id).first()


def save(
    db: Session,
    user: User,
    *,
    cadence: dict[str, Any] | None = None,
    sections: dict[str, Any] | None = None,
    enabled: bool | None = None,
    title: str | None = None,
) -> NewsletterSubscription:
    """Create or update the reader's subscription and its scheduler row.
    Validation (cadence, section names) happens before anything is written."""
    sub = get_for(db, user.id)
    try:
        canonical = scheduler_service.normalise_cadence(cadence if cadence is not None else (
            json.loads(sub.cadence_json) if sub else DEFAULT_CADENCE))
    except scheduler_service.CadenceError as e:
        raise NewsletterError(str(e)) from e
    try:
        resolved_sections = sections_from({"sections": sections} if sections is not None else (
            {"sections": json.loads(sub.sections_json)} if sub else {}))
    except output_service.OutputError as e:
        raise NewsletterError(str(e)) from e
    if not any(resolved_sections.values()):
        raise NewsletterError("Turn on at least one section.")

    if sub is None:
        sub = NewsletterSubscription(tenant_id=user.id)
        db.add(sub)
    sub.cadence_json = json.dumps(canonical)
    sub.sections_json = json.dumps(resolved_sections)
    if title is not None:
        clean = title.strip()
        if not clean:
            raise NewsletterError("The title cannot be empty.")
        sub.title = clean[:200]
    if enabled is not None:
        sub.enabled = bool(enabled)
    elif sub.enabled is None:
        sub.enabled = True
    db.commit()
    db.refresh(sub)
    scheduler_service.schedule(db, kind=KIND, target_id=sub.id, cadence=canonical, tenant_id=user.id, enabled=sub.enabled)
    return sub


def delete(db: Session, sub: NewsletterSubscription) -> None:
    scheduler_service.unschedule(db, KIND, sub.id)
    db.query(NewsletterSend).filter(NewsletterSend.subscription_id == sub.id).delete(synchronize_session=False)
    db.delete(sub)
    db.commit()


def to_dict(db: Session, sub: NewsletterSubscription) -> dict[str, Any]:
    run = scheduler_service.get_run(db, KIND, sub.id)
    sends = (
        db.query(NewsletterSend).filter(NewsletterSend.subscription_id == sub.id)
        .order_by(NewsletterSend.created_at.desc()).limit(10).all()
    )
    return {
        "id": sub.id,
        "title": sub.title,
        "cadence": json.loads(sub.cadence_json),
        "sections": json.loads(sub.sections_json),
        "enabled": sub.enabled,
        "last_issue_at": sub.last_issue_at,
        "next_issue_at": run.next_run_at if run and run.enabled else None,
        "created_at": sub.created_at,
        "sends": [
            {"period_key": s.period_key, "status": s.status, "output_id": s.output_id, "trigger": s.trigger,
             "detail": s.detail, "created_at": s.created_at, "finished_at": s.finished_at}
            for s in sends
        ],
    }


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------


def period_key(cadence: dict[str, Any], slot: datetime) -> str:
    """The period a slot belongs to, in the subscription's timezone: a
    retried dispatch minutes later lands in the same period."""
    tz = ZoneInfo(cadence.get("timezone") or "UTC")
    local = slot.replace(tzinfo=timezone.utc).astimezone(tz)
    kind = cadence.get("cadence")
    if kind == "weekly":
        year, week, _ = local.isocalendar()
        return f"{year}-W{week:02d}"
    if kind == "daily":
        return local.strftime("%Y-%m-%d")
    if kind == "monthly":
        return local.strftime("%Y-%m")
    return local.strftime("%Y-%m-%dT%H:%M")  # "every N seconds": one per slot minute


def _period_label(cadence: dict[str, Any], key: str) -> str:
    kind = cadence.get("cadence")
    if kind == "weekly":
        return f"week {key.split('-W')[1]}, {key.split('-W')[0]}"
    if kind == "monthly":
        return datetime.strptime(key, "%Y-%m").strftime("%B %Y")
    if kind == "daily":
        return datetime.strptime(key, "%Y-%m-%d").strftime("%d %B %Y")
    return key


def _claim(db: Session, sub: NewsletterSubscription, key: str, trigger: str) -> NewsletterSend | None:
    send = NewsletterSend(subscription_id=sub.id, period_key=key, trigger=trigger, status="started")
    db.add(send)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return None
    db.refresh(send)
    return send


def _finish(db: Session, send: NewsletterSend, status: str, *, output_id: str | None = None, detail: str | None = None) -> None:
    send.status = status
    send.output_id = output_id
    send.detail = (detail or "")[:2000] or None
    send.finished_at = _now()
    db.commit()


def message_id(sub_id: str, key: str) -> str:
    host = (settings.APP_BASE_URL.split("//")[-1].split("/")[0].split(":")[0]) or "pratidhvani"
    return f"<newsletter.{sub_id}.{key}@{host}>"


def deliver(db: Session, subscription_id: str, *, slot: datetime | None = None, trigger: str = "schedule") -> dict[str, Any]:
    """Make and send one issue for ``subscription_id`` (see the module doc)."""
    sub = db.get(NewsletterSubscription, subscription_id)
    if sub is None or not sub.enabled:
        return {"status": "inactive"}
    user = db.get(User, sub.tenant_id)
    if user is None:
        return {"status": "inactive"}

    cadence = json.loads(sub.cadence_json)
    now = _now()
    slot = slot or now
    key = period_key(cadence, slot) if trigger == "schedule" else f"manual:{now:%Y-%m-%dT%H:%M:%S}"
    send = _claim(db, sub, key, trigger)
    if send is None:
        logger.info("newsletter %s: period %s already claimed; nothing to do", sub.id, key)
        return {"status": "duplicate", "period_key": key}

    since = sub.last_issue_at or (now - DEFAULT_WINDOW)
    if since >= now:
        since = now - timedelta(seconds=1)
    title = f"{sub.title} — {_period_label(cadence, key)}" if trigger == "schedule" else sub.title
    output = output_service.create_output(
        db, user_id=user.id, kind="newsletter", title=title[:256], source_ids=[],
        parameters={"since": since.isoformat(), "until": now.isoformat(), "sections": json.loads(sub.sections_json)},
    )
    output = output_service.run_generation(db, user, output)

    if output.status == output_service.OutputStatus.SKIPPED.value:
        sub.last_issue_at = now
        db.commit()
        _finish(db, send, "skipped", output_id=output.id, detail=output.progress_message)
        return {"status": "skipped", "period_key": key, "output_id": output.id}
    if output.status != output_service.OutputStatus.COMPLETED.value:
        _finish(db, send, "failed", output_id=output.id, detail=output.error_message)
        return {"status": "failed", "period_key": key, "output_id": output.id, "error": output.error_message}

    sub.last_issue_at = now
    db.commit()
    html_path = output_artifacts.artifact_file(output, "html")
    html = html_path.read_text(encoding="utf-8") if html_path.is_file() else None
    sent = bool(user.email) and email_service.send_email(
        user.email, f"Pratidhvani — {output.title}", output.content_text or "", html=html, message_id=message_id(sub.id, key),
    )
    try:
        notification_service.create(
            db, user.id, kind=notification_service.KIND_NEWSLETTER_ISSUE,
            title=f"Your digest is ready: {output.title}", body=None, href=f"/author/outputs/{output.id}",
        )
    except Exception:  # pragma: no cover - never fail a delivered issue
        logger.exception("newsletter %s: notification not stored", sub.id)
        db.rollback()
    _finish(db, send, "sent" if sent else "email_failed", output_id=output.id,
            detail=None if sent else "The email could not be sent; the issue is in your outputs.")
    return {"status": "sent" if sent else "email_failed", "period_key": key, "output_id": output.id}


__all__ = ["KIND", "DEFAULT_SECTIONS", "deliver", "get_for", "save", "delete", "to_dict", "period_key", "NewsletterError"]
