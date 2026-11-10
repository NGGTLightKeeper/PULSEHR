# Copyright NGGT.LightKeeper. All Rights Reserved.

from __future__ import annotations

import logging
import threading
import time

import telebot
from requests import RequestException
from telebot.apihelper import ApiException
from telebot.formatting import escape_markdown, mbold, mspoiler
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions

from Settings.settings import load_settings

logger = logging.getLogger(__name__)

# Errors of a Bot API call: a refusal from Telegram or a connection failure.
BOT_ERRORS = (ApiException, RequestException)

# How long a failed bot name lookup is remembered before the next try, in seconds.
USERNAME_RETRY_SECONDS = 60.0

# Send the library log to the shared console instead of its own stderr handler.
telebot.logger.handlers.clear()
telebot.logger.setLevel(logging.WARNING)


# Return whether Telegram accepts the link in a button; it rejects local http addresses there.
def can_use_link_button(url: str) -> bool:
    return url.startswith("https://")


# Shared bot

_lock = threading.Lock()
_bot: telebot.TeleBot | None = None
_bot_username: str | None = None
_username_checked_at = 0.0


# Return the bot for the configured token, or None when the bot is not configured.
def get_bot() -> telebot.TeleBot | None:
    global _bot, _bot_username, _username_checked_at

    token = str(load_settings().get("telegram_bot_token") or "").strip()
    if not token:
        return None

    with _lock:
        if _bot is None or _bot.token != token:
            try:
                _bot = telebot.TeleBot(token)
            except ValueError:
                logger.error("telegram_bot_token in Settings/settings.json is not a bot token.")
                return None
            _bot_username = None
            _username_checked_at = 0.0
        return _bot


# Return the error text without the token: connection errors quote the request URL with it.
def describe_error(exc: Exception) -> str:
    text = str(exc)
    token = _bot.token if _bot is not None else ""
    return text.replace(token, "***") if token else text


# Return the bot @username for t.me links, asking Telegram once per process; None while unavailable.
def get_bot_username() -> str | None:
    global _bot_username, _username_checked_at

    bot = get_bot()
    if bot is None:
        return None

    with _lock:
        if _bot_username or time.monotonic() - _username_checked_at < USERNAME_RETRY_SECONDS:
            return _bot_username
        _username_checked_at = time.monotonic()

    try:
        username = bot.get_me().username
    except BOT_ERRORS as exc:
        logger.warning("Bot name could not be read: %s", describe_error(exc))
        return None

    with _lock:
        _bot_username = username
    return username


# Messages

# First line of the code message for every code purpose.
CODE_TITLES = {
    "login": "Код для входа в PULSEHR",
    "telegram": "Код подтверждения Telegram в PULSEHR",
}


# Send MarkdownV2 text to one chat; return whether Telegram accepted it. The button is (text, url).
def send_markdown(chat_id: int, text: str, *, button: tuple[str, str] | None = None) -> bool:
    bot = get_bot()
    if bot is None:
        return False

    markup = None
    if button is not None:
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton(button[0], url=button[1]))

    try:
        bot.send_message(
            chat_id,
            text,
            parse_mode="MarkdownV2",
            reply_markup=markup,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
    except BOT_ERRORS as exc:
        logger.warning("Telegram message to chat %s could not be sent: %s", chat_id, describe_error(exc))
        return False
    return True


# Send a one-time code hidden under a spoiler until it is tapped.
def send_code(chat_id: int, code: str, purpose: str, ttl_minutes: int, *, account: str = "") -> bool:
    title = CODE_TITLES.get(purpose, CODE_TITLES["login"])
    account_part = f" для аккаунта {mbold('@' + account)}" if account else ""
    hint = "Введите его в профиле PULSEHR. " if purpose == "telegram" else ""
    text = (
        f"{escape_markdown(title)}{account_part}: {mspoiler(code)}\n"
        f"{escape_markdown(f'{hint}Код действует {ttl_minutes} минут. Никому его не сообщайте.')}"
    )
    return send_markdown(chat_id, text)


# Send a survey invitation. A public https link becomes a button; a local link stays in the text,
# because Telegram rejects such links in buttons.
def send_survey_invitation(chat_id: int, survey_title: str, link: str) -> bool:
    text = f"Новый опрос: {mbold(survey_title)}\n{escape_markdown('Ответ займёт несколько минут.')}"
    if can_use_link_button(link):
        return send_markdown(chat_id, text, button=("Пройти опрос", link))
    return send_markdown(chat_id, f"{text}\n{escape_markdown(link)}")
