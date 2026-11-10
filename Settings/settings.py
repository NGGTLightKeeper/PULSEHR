# Copyright NGGT.LightKeeper. All Rights Reserved.

from __future__ import annotations

import copy
import json
import logging
import os
import secrets
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Project root and the local settings file created on the first run.
BASE_DIR = Path(__file__).resolve().parent.parent
SETTINGS_FILE = BASE_DIR / "Settings" / "settings.json"

# Site address set by main.py runserver when --host or --port overrides the settings.
SITE_URL_ENV = "PULSEHR_SITE_URL"

# Values of the keys the settings file does not define.
DEFAULT_SETTINGS: dict[str, Any] = {
    "secret_key": "",
    "debug": False,
    "allowed_hosts": ["127.0.0.1", "localhost"],
    "host": "127.0.0.1",
    "port": 8000,
    # Public site address used in notification links; empty means http://host:port.
    "site_url": "",
    "time_zone": "Asia/Yekaterinburg",
    # Registration is limited to these e-mail domains; an empty list allows any domain.
    "allowed_email_domains": [],
    # SMTP server; without a host e-mails are printed to the console.
    "email_host": "",
    "email_port": 587,
    "email_host_user": "",
    "email_host_password": "",
    "email_use_tls": True,
    "email_from": "PULSEHR <noreply@pulsehr.local>",
    # Telegram bot token from @BotFather; without it the bot service does not start.
    "telegram_bot_token": "",
    # Web Push keys, generated on the first run.
    "vapid_public_key": "",
    "vapid_private_key": "",
    "vapid_subject": "mailto:admin@pulsehr.local",
    # How often the notification service checks for due work, in seconds.
    "notifications_poll_seconds": 10,
    # Night hours [start, end] when the notification cascade waits for the morning.
    "quiet_hours_enabled": False,
    "quiet_hours": [22, 8],
}

# Serializes writes of the settings file.
_write_lock = threading.Lock()


# Settings file

# Return the stored settings as they are in the file; a missing or broken file reads as empty.
def read_stored_settings() -> dict[str, Any]:
    try:
        payload = json.loads(SETTINGS_FILE.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Settings file %s could not be read: %s", SETTINGS_FILE, exc)
        return {}

    if not isinstance(payload, dict):
        logger.warning("Settings file %s does not hold a JSON object.", SETTINGS_FILE)
        return {}
    return payload


# Return the stored settings completed with the defaults of the missing keys.
def load_settings() -> dict[str, Any]:
    settings = copy.deepcopy(DEFAULT_SETTINGS)
    settings.update(read_stored_settings())
    return settings


# Replace the settings file with the given payload. The file is written next to the target first,
# so a crash never leaves a half-written file behind.
def save_settings(settings: dict[str, Any]) -> None:
    with _write_lock:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        temp_file = SETTINGS_FILE.with_name(SETTINGS_FILE.name + ".tmp")
        temp_file.write_text(json.dumps(settings, indent=4, ensure_ascii=False) + "\n", encoding="utf-8")
        temp_file.replace(SETTINGS_FILE)


# Create the settings file or add the keys it is missing: stored values are kept, missing keys get
# their defaults, and the secret key and the Web Push keys are generated once. Return the settings.
def ensure_settings() -> dict[str, Any]:
    stored = read_stored_settings()
    settings = copy.deepcopy(DEFAULT_SETTINGS)
    settings.update(stored)
    if not settings.get("secret_key"):
        settings["secret_key"] = secrets.token_urlsafe(50)
    if not settings.get("vapid_public_key") or not settings.get("vapid_private_key"):
        from Services.WebNotifications.push import generate_vapid_keys

        settings["vapid_public_key"], settings["vapid_private_key"] = generate_vapid_keys()

    if settings != stored:
        save_settings(settings)
    return settings


# Derived values

# Return the public site address without a trailing slash: the site_url setting, then the address
# main.py runserver listens on, then http://host:port from the settings.
def get_site_url(settings: dict[str, Any] | None = None) -> str:
    settings = settings if settings is not None else load_settings()
    configured = str(settings.get("site_url") or "").strip()
    if configured:
        return configured.rstrip("/")

    from_env = os.environ.get(SITE_URL_ENV, "").strip()
    if from_env:
        return from_env.rstrip("/")

    host = str(settings.get("host") or "127.0.0.1")
    if host in {"0.0.0.0", "::", ""}:
        host = "127.0.0.1"
    return f"http://{host}:{int(settings.get('port') or 8000)}"
