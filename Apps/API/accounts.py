# Copyright NGGT.LightKeeper. All Rights Reserved.

from __future__ import annotations

import logging
import math
import re
import secrets
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac
from rest_framework.exceptions import NotFound, Throttled, ValidationError

from Apps.API import notifications
from Apps.API.models import CodePurpose, Department, User, UserRole, VerificationCode
from Services.TelegramBot import client as telegram
from Settings.settings import load_settings

logger = logging.getLogger(__name__)

# One-time codes: six digits, valid ten minutes, five tries, one new code a minute.
CODE_LENGTH = 6
CODE_TTL_MINUTES = 10
CODE_TTL = timedelta(minutes=CODE_TTL_MINUTES)
CODE_MAX_ATTEMPTS = 5
CODE_RESEND_SECONDS = 60

_PHONE_RE = re.compile(r"^\+\d{10,15}$")
_PHONE_LIKE_RE = re.compile(r"^[+\d][\d\s()\-]{9,}$")
_TELEGRAM_USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")


# Where a code went and when the next one may be requested.
@dataclass
class CodeDelivery:
    channels: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"channels": self.channels, "expires_in": int(CODE_TTL.total_seconds()), "resend_in": CODE_RESEND_SECONDS}


# Return a validation error bound to a form field.
def _invalid(message: str, field_name: str | None = None) -> ValidationError:
    return ValidationError({field_name: [message]} if field_name else [message])


# Return the first message of a DRF error detail, which may be a string, a list or a dict.
def first_message(detail: Any) -> str:
    if isinstance(detail, dict):
        return first_message(next(iter(detail.values()), ""))
    if isinstance(detail, list):
        return first_message(detail[0]) if detail else ""
    return str(detail)


# Normalization

def normalize_email(value: Any) -> str:
    return str(value or "").strip().lower()


# Return the phone in +<digits> form; Russian numbers written with 8 or 7 get the +7 prefix.
def normalize_phone(value: Any) -> str:
    phone = re.sub(r"[\s()\-]", "", str(value or "").strip())
    if len(phone) == 11 and phone[0] in "78":
        phone = "+7" + phone[1:]
    if not _PHONE_RE.match(phone):
        raise _invalid("Укажите номер телефона в формате +7 900 000-00-00.", "phone")
    return phone


# Return the Telegram username without "@", or an empty string for an empty value.
def normalize_telegram_username(value: Any) -> str:
    name = str(value or "").strip().lstrip("@")
    if not name:
        return ""
    if not _TELEGRAM_USERNAME_RE.match(name):
        raise _invalid(
            "Имя в Telegram: 5–32 символа — латинские буквы, цифры и подчёркивание, начинается с буквы.",
            "telegram_username",
        )
    return name


# Hide most of an e-mail address for messages like "code sent to i***@corp.ru".
def mask_email(email: str) -> str:
    name, _, domain = email.partition("@")
    return f"{name[:1]}***@{domain}"


def mask_telegram(username: str) -> str:
    return f"@{username[:2]}***"


# Lookup and checks

# Find the active account by e-mail, username or verified phone.
def find_user_by_login(login: Any) -> User | None:
    value = str(login or "").strip()
    if not value:
        return None

    users = User.objects.filter(is_active=True)
    if "@" in value:
        return users.filter(email__iexact=value).first()

    if _PHONE_LIKE_RE.match(value):
        try:
            phone = normalize_phone(value)
        except ValidationError:
            phone = ""
        user = users.filter(phone=phone, phone_verified=True).first() if phone else None
        if user is not None:
            return user

    return users.filter(username__iexact=value).first()


# Raise when the e-mail or the username is taken by another account.
def _check_unique(email: str, username: str, exclude: User | None = None) -> None:
    users = User.objects.all()
    if exclude is not None:
        users = users.exclude(pk=exclude.pk)
    if email and users.filter(email__iexact=email).exists():
        raise _invalid("Аккаунт с таким e-mail уже есть. Войдите в него.", "email")
    if username and users.filter(username__iexact=username).exists():
        raise _invalid("Это имя пользователя уже занято.", "username")


# Raise when registration is limited to some e-mail domains and this one is not among them.
def _check_email_domain(email: str) -> None:
    allowed = [str(domain).strip().lower().lstrip("@") for domain in load_settings().get("allowed_email_domains") or []]
    allowed = [domain for domain in allowed if domain]
    if allowed and email.partition("@")[2] not in allowed:
        raise _invalid("Регистрация доступна только для корпоративной почты.", "email")


# Codes

def _hash_code(purpose: str, code: str) -> str:
    return salted_hmac(f"pulsehr.code.{purpose}", code, algorithm="sha256").hexdigest()


# Raise Throttled when the owner of these codes got one less than a minute ago.
def _check_cooldown(owner_codes: QuerySet) -> None:
    latest = owner_codes.order_by("-created_at").first()
    if latest is None:
        return
    left = math.ceil(CODE_RESEND_SECONDS - (timezone.now() - latest.created_at).total_seconds())
    if left > 0:
        raise Throttled(wait=left, detail="Новый код пока нельзя запросить.")


# Create a new code for the owner of the given codes and expire the older ones. Return the record
# and the code itself, which exists only in memory.
def _create_code(
    purpose: str,
    owner_codes: QuerySet,
    *,
    user: User | None = None,
    email: str = "",
    payload: dict[str, Any] | None = None,
) -> tuple[VerificationCode, str]:
    now = timezone.now()
    owner_codes.filter(used_at__isnull=True, expires_at__gt=now).update(expires_at=now)

    code = f"{secrets.randbelow(10 ** CODE_LENGTH):0{CODE_LENGTH}d}"
    record = VerificationCode.objects.create(
        purpose=purpose,
        user=user,
        email=email,
        code_hash=_hash_code(purpose, code),
        payload=payload or {},
        expires_at=now + CODE_TTL,
    )
    return record, code


def _expire(record: VerificationCode) -> None:
    record.expires_at = timezone.now()
    record.save(update_fields=["expires_at"])


# Check a code against the newest active code of the owner and use it up. Failed tries are saved
# before the error is raised, so the transaction does not roll them back.
def _consume_code(owner_codes: QuerySet, purpose: str, code: Any) -> VerificationCode:
    now = timezone.now()
    entered = re.sub(r"\s", "", str(code or ""))
    error = ""

    with transaction.atomic():
        record = owner_codes.filter(used_at__isnull=True, expires_at__gt=now).order_by("-created_at").first()
        if record is None:
            error = "Код истёк или не запрашивался. Запросите новый код."
        elif record.attempts >= CODE_MAX_ATTEMPTS:
            error = "Слишком много неверных попыток. Запросите новый код."
        elif not constant_time_compare(record.code_hash, _hash_code(purpose, entered)):
            record.attempts += 1
            record.save(update_fields=["attempts"])
            left = CODE_MAX_ATTEMPTS - record.attempts
            error = f"Неверный код. Осталось попыток: {left}." if left else "Неверный код. Запросите новый код."
        else:
            record.used_at = now
            record.save(update_fields=["used_at"])

    if error:
        raise _invalid(error, "code")
    return record


# Send the same code to every channel of the account: e-mail always, Telegram once it is confirmed.
# Return the masked destinations that accepted it.
def _deliver_code(user: User, code: str, purpose: str) -> list[str]:
    delivered = []
    if notifications.send_code_email(user.email, code, purpose, CODE_TTL_MINUTES):
        delivered.append(f"e-mail {mask_email(user.email)}")
    if user.telegram_verified and telegram.send_code(
        user.telegram_chat_id,
        code,
        purpose,
        CODE_TTL_MINUTES,
        account=user.username,
    ):
        delivered.append(f"Telegram {mask_telegram(user.telegram_username)}")
    return delivered


# Delete the codes that expired more than a day ago.
def delete_old_codes() -> int:
    deleted, _ = VerificationCode.objects.filter(expires_at__lt=timezone.now() - timedelta(days=1)).delete()
    return deleted


# Sign in

# Send a sign-in code to all channels of the account found by e-mail, username or verified phone.
def send_login_code(login: Any) -> CodeDelivery:
    user = find_user_by_login(login)
    if user is None:
        raise _invalid("Аккаунт не найден. Проверьте данные или зарегистрируйтесь.", "login")

    owner_codes = VerificationCode.objects.filter(purpose=CodePurpose.LOGIN, user=user)
    _check_cooldown(owner_codes)
    record, code = _create_code(CodePurpose.LOGIN, owner_codes, user=user)
    channels = _deliver_code(user, code, CodePurpose.LOGIN)
    if not channels:
        _expire(record)
        raise _invalid("Не удалось отправить код. Попробуйте позже.")

    logger.info("Sign-in code for @%s sent to: %s.", user.username, ", ".join(channels))
    return CodeDelivery(channels)


# Return the account once the sign-in code is confirmed.
def confirm_login(login: Any, code: Any) -> User:
    user = find_user_by_login(login)
    if user is None:
        raise _invalid("Аккаунт не найден.", "login")

    _consume_code(VerificationCode.objects.filter(purpose=CodePurpose.LOGIN, user=user), CodePurpose.LOGIN, code)
    logger.info("@%s signed in.", user.username)
    return user


# Registration

# Check the registration form and send the confirmation code to the e-mail. The form waits with the
# code until it is confirmed; the account does not exist before that.
def start_registration(data: dict[str, Any]) -> CodeDelivery:
    email = normalize_email(data.get("email"))
    username = str(data.get("username") or "").strip()
    phone = normalize_phone(data.get("phone"))
    telegram_username = normalize_telegram_username(data.get("telegram_username"))
    department_id = data.get("department_id")

    _check_email_domain(email)
    _check_unique(email, username)
    if department_id is not None and not Department.objects.filter(pk=department_id).exists():
        raise _invalid("Подразделение не найдено.", "department_id")

    owner_codes = VerificationCode.objects.filter(purpose=CodePurpose.REGISTER, email=email)
    _check_cooldown(owner_codes)
    payload = {
        "email": email,
        "username": username,
        "phone": phone,
        "telegram_username": telegram_username,
        "department_id": department_id,
    }
    record, code = _create_code(CodePurpose.REGISTER, owner_codes, email=email, payload=payload)
    if not notifications.send_code_email(email, code, CodePurpose.REGISTER, CODE_TTL_MINUTES):
        _expire(record)
        raise _invalid("Не удалось отправить письмо с кодом. Проверьте адрес или попробуйте позже.", "email")

    logger.info("Registration code for %s sent.", mask_email(email))
    return CodeDelivery([f"e-mail {mask_email(email)}"])


# Create the account from the registration form once its code is confirmed.
def complete_registration(email: Any, code: Any) -> User:
    email = normalize_email(email)
    record = _consume_code(
        VerificationCode.objects.filter(purpose=CodePurpose.REGISTER, email=email),
        CodePurpose.REGISTER,
        code,
    )

    data = record.payload
    _check_unique(data["email"], data["username"])
    department = Department.objects.filter(pk=data.get("department_id")).first() if data.get("department_id") else None
    try:
        user = User.objects.create_user(
            email=data["email"],
            username=data["username"],
            phone=data.get("phone") or "",
            telegram_username=data.get("telegram_username") or "",
            department=department,
        )
    except IntegrityError:
        raise _invalid("Аккаунт с такими данными уже существует.") from None

    logger.info("Account @%s registered.", user.username)
    return user


# Profile

# Change the profile fields present in data. A changed phone loses its verification, a changed
# Telegram name loses the linked chat.
def update_profile(user: User, data: dict[str, Any]) -> User:
    if "username" in data:
        username = str(data["username"]).strip()
        if username.lower() != user.username.lower():
            _check_unique("", username, exclude=user)
        user.username = username

    if "phone" in data:
        phone = normalize_phone(data["phone"]) if str(data["phone"] or "").strip() else ""
        if phone != user.phone:
            user.phone = phone
            user.phone_verified = False

    if "department_id" in data:
        department_id = data["department_id"]
        user.department = Department.objects.filter(pk=department_id).first() if department_id else None
        if department_id and user.department is None:
            raise _invalid("Подразделение не найдено.", "department_id")

    if "telegram_username" in data:
        set_telegram_username(user, data["telegram_username"], save=False)

    try:
        user.save()
    except IntegrityError:
        raise _invalid("Это имя пользователя уже занято.", "username") from None
    return user


# Telegram

# Claim a Telegram username; a new name drops the confirmed chat until it is confirmed again.
def set_telegram_username(user: User, value: Any, *, save: bool = True) -> User:
    name = normalize_telegram_username(value)
    if not name or name.lower() != user.telegram_username.lower():
        user.telegram_chat_id = None
        user.telegram_verified_at = None
    user.telegram_username = name
    if save:
        user.save(update_fields=["telegram_username", "telegram_chat_id", "telegram_verified_at"])
    return user


# Return the active accounts that claim this Telegram username and wait for its confirmation.
def find_telegram_claims(telegram_username: str) -> list[User]:
    if not telegram_username:
        return []
    return list(
        User.objects.filter(is_active=True, telegram_username__iexact=telegram_username, telegram_verified_at__isnull=True)
    )


def user_for_chat(chat_id: int) -> User | None:
    return User.objects.filter(telegram_chat_id=chat_id, is_active=True).first()


# Create the code the bot sends to the chat that wrote to it from a claimed username.
def issue_telegram_code(user: User, chat_id: int, telegram_username: str) -> str:
    other = User.objects.filter(telegram_chat_id=chat_id).exclude(pk=user.pk).first()
    if other is not None:
        raise _invalid(f"Этот Telegram уже подключён к аккаунту @{other.username}. Сначала отключите его там.")

    owner_codes = VerificationCode.objects.filter(purpose=CodePurpose.TELEGRAM, user=user)
    _check_cooldown(owner_codes)
    _, code = _create_code(
        CodePurpose.TELEGRAM,
        owner_codes,
        user=user,
        payload={"chat_id": chat_id, "telegram_username": telegram_username},
    )
    logger.info("Telegram confirmation code for @%s issued.", user.username)
    return code


# Link the Telegram chat once the code from the bot is entered on the site.
def confirm_telegram(user: User, code: Any) -> User:
    if not user.telegram_username:
        raise _invalid("Сначала укажите имя пользователя Telegram.", "telegram_username")

    record = _consume_code(
        VerificationCode.objects.filter(purpose=CodePurpose.TELEGRAM, user=user),
        CodePurpose.TELEGRAM,
        code,
    )
    chat_id = int(record.payload["chat_id"])
    telegram_username = str(record.payload.get("telegram_username") or "")
    if telegram_username.lower() != user.telegram_username.lower():
        raise _invalid("Имя в Telegram изменилось. Напишите боту снова и введите новый код.", "code")
    if User.objects.filter(telegram_chat_id=chat_id).exclude(pk=user.pk).exists():
        raise _invalid("Этот Telegram уже подключён к другому аккаунту.", "code")

    user.telegram_username = telegram_username
    user.telegram_chat_id = chat_id
    user.telegram_verified_at = timezone.now()
    user.save(update_fields=["telegram_username", "telegram_chat_id", "telegram_verified_at"])
    logger.info("Telegram @%s confirmed for @%s.", telegram_username, user.username)
    return user


def disconnect_telegram(user: User) -> User:
    user.telegram_username = ""
    user.telegram_chat_id = None
    user.telegram_verified_at = None
    user.save(update_fields=["telegram_username", "telegram_chat_id", "telegram_verified_at"])
    return user


# Roles

# Give the HR role to the account found by e-mail, username or verified phone.
def grant_hr(login: Any) -> User:
    user = find_user_by_login(login)
    if user is None:
        raise NotFound("Аккаунт не найден.")
    if user.role == UserRole.EMPLOYEE:
        user.role = UserRole.HR
        user.save(update_fields=["role"])
    return user
