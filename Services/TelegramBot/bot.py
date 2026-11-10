# Copyright NGGT.LightKeeper. All Rights Reserved.

from __future__ import annotations

import functools
import logging
from collections.abc import Callable

from django.conf import settings
from django.db import close_old_connections
from rest_framework.exceptions import APIException
from telebot.formatting import escape_markdown, mbold
from telebot.types import BotCommand, Message
from telebot.util import content_type_media

from Apps.API import accounts, surveys
from Services.TelegramBot import client as telegram

logger = logging.getLogger(__name__)

# Long polling wait of one getUpdates call, in seconds.
POLL_TIMEOUT_SECONDS = 25

# Commands shown in the Telegram menu.
COMMANDS = [
    BotCommand("start", "Подтвердить Telegram для PULSEHR"),
    BotCommand("surveys", "Мои активные опросы"),
    BotCommand("help", "Что умеет бот"),
]


# Handlers

# Wrap a handler: refresh the database connection first and log a failure instead of raising it.
def _handler(func: Callable[[Message], None]) -> Callable[[Message], None]:
    @functools.wraps(func)
    def run(message: Message) -> None:
        close_old_connections()
        try:
            func(message)
        except Exception:
            logger.exception("Message from chat %s could not be handled.", message.chat.id)

    return run


@_handler
def _send_help(message: Message) -> None:
    about = escape_markdown("— корпоративные pulse-опросы.")
    steps = escape_markdown(
        "Укажите свой @username в профиле PULSEHR и напишите сюда любое сообщение — я пришлю код "
        "подтверждения. После этого сюда будут приходить коды входа и приглашения в опросы."
    )
    commands = escape_markdown("/surveys — активные опросы")
    telegram.send_markdown(message.chat.id, f"{mbold('PULSEHR')} {about}\n\n{steps}\n\n{commands}")


# List the surveys the linked account still has to take.
@_handler
def _send_surveys(message: Message) -> None:
    chat_id = message.chat.id
    user = accounts.user_for_chat(chat_id)
    if user is None:
        telegram.send_markdown(chat_id, escape_markdown("Сначала подтвердите Telegram в профиле PULSEHR."))
        return

    pending = surveys.pending_surveys(user)
    if not pending:
        telegram.send_markdown(chat_id, escape_markdown("Активных опросов нет."))
        return

    lines = [mbold("Активные опросы:")]
    for survey in pending:
        lines.append(escape_markdown(f"• {survey.title}\n  {settings.SITE_URL}/surveys/{survey.id}/"))
    telegram.send_markdown(chat_id, "\n".join(lines))


# Send a confirmation code to every account that claims the sender's username; otherwise explain
# what to do. Every message except the other commands lands here, /start included.
@_handler
def _confirm_account(message: Message) -> None:
    chat_id = message.chat.id
    telegram_username = message.from_user.username or ""

    claims = accounts.find_telegram_claims(telegram_username)
    for user in claims:
        try:
            code = accounts.issue_telegram_code(user, chat_id, telegram_username)
        except APIException as exc:
            telegram.send_markdown(chat_id, escape_markdown(f"@{user.username}: {accounts.first_message(exc.detail)}"))
            continue
        telegram.send_code(chat_id, code, "telegram", accounts.CODE_TTL_MINUTES, account=user.username)

    if claims:
        return

    linked = accounts.user_for_chat(chat_id)
    if linked is not None:
        text = f"{escape_markdown('Telegram подключён к аккаунту')} {mbold('@' + linked.username)}\\. /surveys"
    elif not telegram_username:
        text = escape_markdown(
            "У вашего Telegram нет имени пользователя (@username). Задайте его в настройках Telegram, "
            "укажите в профиле PULSEHR и напишите сюда снова."
        )
    else:
        text = escape_markdown(
            f"Укажите @{telegram_username} в профиле PULSEHR ({settings.SITE_URL}/profile/) "
            "и напишите сюда снова — я пришлю код подтверждения."
        )
    telegram.send_markdown(chat_id, text)


# Polling

# Run the bot until the process is stopped. Return the exit code.
def run_bot() -> int:
    bot = telegram.get_bot()
    if bot is None:
        logger.error("telegram_bot_token is not set in Settings/settings.json; the bot cannot start.")
        return 1

    try:
        me = bot.get_me()
        bot.delete_webhook()
        bot.set_my_commands(COMMANDS)
    except telegram.BOT_ERRORS as exc:
        logger.error("Bot could not start: %s", telegram.describe_error(exc))
        return 1

    private = ["private"]
    bot.register_message_handler(_send_help, commands=["help"], chat_types=private)
    bot.register_message_handler(_send_surveys, commands=["surveys"], chat_types=private)
    bot.register_message_handler(_confirm_account, chat_types=private, content_types=content_type_media)

    logger.info("Bot @%s is running.", me.username)
    bot.infinity_polling(long_polling_timeout=POLL_TIMEOUT_SECONDS, allowed_updates=["message"])
    return 0
