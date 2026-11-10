# Copyright NGGT.LightKeeper. All Rights Reserved.

from __future__ import annotations

import logging
import time

from django.db import close_old_connections
from django.utils import timezone

from Apps.API import accounts, notifications, surveys
from Apps.API.models import Channel, Survey, User
from Apps.API.notifications import SendResult, Sender
from Services.TelegramBot import client as telegram
from Services.WebNotifications.push import send_push
from Settings.settings import load_settings

logger = logging.getLogger(__name__)

# Old one-time codes are deleted once in this many seconds.
CLEANUP_INTERVAL_SECONDS = 60 * 60


# Senders

# Send the invitation to every live push subscription of the user; it counts as sent when at least
# one browser got it. Subscriptions the push service no longer knows are turned off.
def send_push_invitation(user: User, survey: Survey, link: str) -> SendResult:
    cfg = load_settings()
    private_key = str(cfg.get("vapid_private_key") or "")
    if not private_key:
        return SendResult(False, "Web Push keys are not configured")

    payload = {
        "title": "PULSEHR: новый опрос",
        "body": survey.title,
        "url": link,
        "tag": f"survey-{survey.id}",
    }
    delivered = 0
    errors = []
    for subscription in user.push_subscriptions.filter(is_active=True):
        outcome = send_push(
            {"endpoint": subscription.endpoint, "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth}},
            payload,
            private_key=private_key,
            subject=str(cfg.get("vapid_subject") or "mailto:admin@pulsehr.local"),
        )
        if outcome.ok:
            delivered += 1
            subscription.last_success_at = timezone.now()
            subscription.save(update_fields=["last_success_at"])
            continue

        errors.append(outcome.detail)
        if outcome.gone:
            subscription.is_active = False
            subscription.save(update_fields=["is_active"])
    return SendResult(delivered > 0, "; ".join(errors))


def send_telegram_invitation(user: User, survey: Survey, link: str) -> SendResult:
    ok = telegram.send_survey_invitation(user.telegram_chat_id, survey.title, link)
    return SendResult(ok, "" if ok else "Telegram did not accept the message")


def send_email_invitation(user: User, survey: Survey, link: str) -> SendResult:
    ok = notifications.send_survey_email(user.email, survey.title, link)
    return SendResult(ok, "" if ok else "the mail server did not accept the message")


# Return the senders of all channels.
def build_senders() -> dict[str, Sender]:
    return {
        Channel.PUSH: send_push_invitation,
        Channel.TELEGRAM: send_telegram_invitation,
        Channel.EMAIL: send_email_invitation,
    }


# Service loop

# Run one pass: start and close surveys by their dates, then send the due notifications.
def run_once(senders: dict[str, Sender]) -> None:
    close_old_connections()
    started, closed = surveys.process_schedule()
    if started or closed:
        logger.info("Schedule: %s survey(s) started, %s closed.", started, closed)
    notifications.process_due_dispatches(senders)


# Run the service until the process is stopped. Return the exit code.
def run_service() -> int:
    cfg = load_settings()
    poll_seconds = max(2, int(cfg.get("notifications_poll_seconds") or 10))
    if not cfg.get("vapid_private_key"):
        logger.warning("Web Push keys are missing in Settings/settings.json; push notifications are off.")
    logger.info("Notification service is running, checks every %s s.", poll_seconds)

    senders = build_senders()
    last_cleanup = 0.0
    while True:
        try:
            run_once(senders)
            if time.monotonic() - last_cleanup > CLEANUP_INTERVAL_SECONDS:
                accounts.delete_old_codes()
                last_cleanup = time.monotonic()
        except Exception:
            logger.exception("Notification pass failed.")
        time.sleep(poll_seconds)
