# Copyright NGGT.LightKeeper. All Rights Reserved.

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable

from django.conf import settings
from django.core.mail import send_mail
from django.core.mail.backends.base import BaseEmailBackend
from django.db.models import QuerySet
from django.utils import timezone

from Apps.API.models import (
    AttemptStatus,
    Channel,
    DispatchStatus,
    NotificationAttempt,
    NotificationDispatch,
    PushSubscription,
    Survey,
    SurveyParticipation,
    SurveyStatus,
    User,
)
from Settings.settings import load_settings

logger = logging.getLogger(__name__)

# Dispatches handled in one pass of the notification service.
BATCH_SIZE = 100

# Subject and first line of the code e-mail for every code purpose.
CODE_EMAIL_TEXTS = {
    "login": ("Код для входа в PULSEHR", "Ваш код для входа в PULSEHR."),
    "register": ("Подтверждение регистрации в PULSEHR", "Ваш код для завершения регистрации в PULSEHR."),
}


# Result of sending one notification through one channel.
@dataclass
class SendResult:
    ok: bool
    detail: str = ""


# Sends a survey invitation through one channel: (user, survey, tracked link) -> result.
Sender = Callable[[User, Survey, str], SendResult]


# E-mail

# E-mail backend for setups without SMTP: every message goes to the shared console, so the one-time
# codes can be read there.
class ConsoleLogEmailBackend(BaseEmailBackend):
    def send_messages(self, email_messages) -> int:
        for message in email_messages:
            logger.info("E-mail to %s: %s\n%s", ", ".join(message.to), message.subject, message.body)
        return len(email_messages)


# Send one plain-text e-mail; return whether the mail server accepted it.
def _send_email(recipient: str, subject: str, body: str) -> bool:
    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [recipient], fail_silently=False)
    except Exception as exc:
        logger.warning("E-mail to %s could not be sent: %s", recipient, exc)
        return False
    return True


def send_code_email(email: str, code: str, purpose: str, ttl_minutes: int) -> bool:
    subject, intro = CODE_EMAIL_TEXTS.get(purpose, CODE_EMAIL_TEXTS["login"])
    body = (
        f"{intro}\n\n"
        f"Код: {code}\n\n"
        f"Код действует {ttl_minutes} минут. Если вы его не запрашивали, просто проигнорируйте это письмо."
    )
    return _send_email(email, subject, body)


def send_survey_email(email: str, survey_title: str, link: str) -> bool:
    body = (
        "Здравствуйте!\n\n"
        f"Вас приглашают пройти опрос «{survey_title}». Это займёт несколько минут.\n\n"
        f"Пройти опрос: {link}\n\n"
        "Спасибо, что помогаете нам становиться лучше."
    )
    return _send_email(email, f"Опрос: {survey_title}", body)


# Cascades

# Start a cascade for every participation that has none yet; the first step is due at once.
def create_dispatches(participations: QuerySet[SurveyParticipation], now: datetime) -> int:
    pending = participations.filter(dispatch__isnull=True, completed_at__isnull=True)
    dispatches = [NotificationDispatch(participation=participation, next_run_at=now) for participation in pending]
    NotificationDispatch.objects.bulk_create(dispatches)
    return len(dispatches)


# Stop the cascade of a participant, for example once the survey is opened.
def stop_dispatch(participation: SurveyParticipation, status: str = DispatchStatus.DONE) -> None:
    NotificationDispatch.objects.filter(participation=participation, status=DispatchStatus.ACTIVE).update(
        status=status,
        next_run_at=None,
    )


def cancel_survey_dispatches(survey: Survey) -> None:
    NotificationDispatch.objects.filter(participation__survey=survey, status=DispatchStatus.ACTIVE).update(
        status=DispatchStatus.CANCELLED,
        next_run_at=None,
    )


def tracked_link(token: Any) -> str:
    return f"{settings.SITE_URL}/n/{token}/"


# Return whether the user can be reached through the channel at all.
def channel_available(channel: str, user: User) -> bool:
    if channel == Channel.PUSH:
        return user.push_subscriptions.filter(is_active=True).exists()
    if channel == Channel.TELEGRAM:
        return user.telegram_verified
    if channel == Channel.EMAIL:
        return bool(user.email)
    return False


# Return the end of the quiet hours when now falls inside them, otherwise None.
def quiet_until(now: datetime, cfg: dict[str, Any]) -> datetime | None:
    if not cfg.get("quiet_hours_enabled"):
        return None

    try:
        start, end = (int(hour) % 24 for hour in cfg.get("quiet_hours") or [])
    except (TypeError, ValueError):
        return None
    if start == end:
        return None

    local = timezone.localtime(now)
    hour = local.hour
    inside = start <= hour < end if start < end else hour >= start or hour < end
    if not inside:
        return None

    wake = local.replace(hour=end, minute=0, second=0, microsecond=0)
    if wake <= local:
        wake += timedelta(days=1)
    return wake


# Run the due cascade steps. Every step tries the next channels of the survey in order until one
# accepts the notification; the next step waits for the survey delay. Return the handled count.
def process_due_dispatches(senders: dict[str, Sender]) -> int:
    now = timezone.now()
    cfg = load_settings()
    due = list(
        NotificationDispatch.objects.filter(status=DispatchStatus.ACTIVE, next_run_at__lte=now)
        .select_related("participation__survey", "participation__user")
        .order_by("next_run_at", "id")[:BATCH_SIZE]
    )
    for dispatch in due:
        _advance(dispatch, senders, now, cfg)
    return len(due)


# Run one cascade step of one participant.
def _advance(dispatch: NotificationDispatch, senders: dict[str, Sender], now: datetime, cfg: dict[str, Any]) -> None:
    participation = dispatch.participation
    survey = participation.survey
    user = participation.user

    # The cascade ends once the survey is opened, and makes no sense for a closed survey.
    if participation.opened_at or participation.completed_at:
        _finish(dispatch, DispatchStatus.DONE)
        return
    if survey.status != SurveyStatus.ACTIVE or not user.is_active:
        _finish(dispatch, DispatchStatus.CANCELLED)
        return

    wake = quiet_until(now, cfg)
    if wake is not None:
        dispatch.next_run_at = wake
        dispatch.save(update_fields=["next_run_at", "updated_at"])
        return

    channels = [channel for channel in survey.cascade_channels if channel in senders]
    while dispatch.step_index < len(channels):
        channel = channels[dispatch.step_index]
        dispatch.step_index += 1
        if not channel_available(channel, user):
            continue

        attempt = NotificationAttempt(dispatch=dispatch, channel=channel)
        try:
            result = senders[channel](user, survey, tracked_link(attempt.token))
        except Exception as exc:
            logger.exception("Notification through %s failed.", channel)
            result = SendResult(False, str(exc))

        attempt.status = AttemptStatus.SENT if result.ok else AttemptStatus.FAILED
        attempt.detail = result.detail[:500]
        attempt.save()
        if not result.ok:
            logger.warning("Notification of @%s through %s failed: %s", user.username, channel, result.detail or "no details")
            continue

        logger.info("Survey «%s»: @%s notified through %s.", survey.title, user.username, channel)
        if dispatch.step_index < len(channels):
            dispatch.next_run_at = now + timedelta(minutes=survey.cascade_delay_minutes)
            dispatch.save(update_fields=["step_index", "next_run_at", "updated_at"])
        else:
            _finish(dispatch, DispatchStatus.EXHAUSTED)
        return

    _finish(dispatch, DispatchStatus.EXHAUSTED)


def _finish(dispatch: NotificationDispatch, status: str) -> None:
    dispatch.status = status
    dispatch.next_run_at = None
    dispatch.save(update_fields=["status", "step_index", "next_run_at", "updated_at"])


# Clicks

# Remember the first click on a tracked link and return its survey, or None for an unknown token.
def register_click(token: Any) -> Survey | None:
    attempt = NotificationAttempt.objects.select_related("dispatch__participation__survey").filter(token=token).first()
    if attempt is None:
        return None

    if attempt.clicked_at is None:
        attempt.clicked_at = timezone.now()
        attempt.save(update_fields=["clicked_at"])
    return attempt.dispatch.participation.survey


# Return the channel of the last notification link the participant followed, or "".
def last_clicked_channel(participation: SurveyParticipation) -> str:
    attempt = (
        NotificationAttempt.objects.filter(dispatch__participation=participation, clicked_at__isnull=False)
        .order_by("-clicked_at")
        .first()
    )
    return attempt.channel if attempt else ""


# Push subscriptions

# Store the subscription of this browser for the user; a known endpoint moves to the current user.
def save_push_subscription(user: User, endpoint: str, p256dh: str, auth: str, user_agent: str = "") -> PushSubscription:
    subscription, _ = PushSubscription.objects.update_or_create(
        endpoint=endpoint,
        defaults={"user": user, "p256dh": p256dh, "auth": auth, "user_agent": user_agent[:300], "is_active": True},
    )
    return subscription


def remove_push_subscription(user: User, endpoint: str) -> bool:
    deleted, _ = PushSubscription.objects.filter(user=user, endpoint=endpoint).delete()
    return deleted > 0
