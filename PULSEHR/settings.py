# Copyright NGGT.LightKeeper. All Rights Reserved.

from __future__ import annotations

import sys
from pathlib import Path


# Project root on the import path for the top-level Settings and Services packages
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from Settings.settings import ensure_settings, get_site_url  # noqa: E402

# Local settings from Settings/settings.json; the file is created with fresh secrets on the first start
_cfg = ensure_settings()


# Core Django settings
SECRET_KEY = _cfg.get("secret_key") or "django-insecure-pulsehr-fallback-key"
DEBUG = bool(_cfg.get("debug", False))
ALLOWED_HOSTS = list(_cfg.get("allowed_hosts") or ["127.0.0.1", "localhost"])

# Public site address for links in notifications
SITE_URL = get_site_url(_cfg)


# Installed apps
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "Apps.API",
    "Apps.UI",
]


# Middleware pipeline
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]


# Accounts: employees sign in with one-time codes, passwords are used only by Django admin accounts
AUTH_USER_MODEL = "API.User"
LOGIN_URL = "/login/"
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.ScryptPasswordHasher",
]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# URL, template and application entry points
ROOT_URLCONF = "PULSEHR.urls"
WSGI_APPLICATION = "PULSEHR.wsgi.application"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]


# Database
# The site and the background services write to one SQLite file: WAL lets reads go on during a write,
# IMMEDIATE transactions and the timeout make concurrent writers wait instead of failing.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        "OPTIONS": {
            "timeout": 20,
            "transaction_mode": "IMMEDIATE",
            "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;",
        },
    }
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# Django REST Framework: session authentication of the site pages and JSON only
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "EXCEPTION_HANDLER": "Apps.API.views.exception_handler",
    "DEFAULT_THROTTLE_RATES": {
        "auth_code": "10/min",
        "auth_confirm": "30/min",
    },
}
if DEBUG:
    REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"].append("rest_framework.renderers.BrowsableAPIRenderer")


# Localization
LANGUAGE_CODE = "ru-ru"
TIME_ZONE = str(_cfg.get("time_zone") or "UTC")
USE_I18N = True
USE_TZ = True


# Static files; WhiteNoise serves them straight from the app folders, so collectstatic is not used
STATIC_URL = "static/"
WHITENOISE_USE_FINDERS = True
WHITENOISE_AUTOREFRESH = DEBUG


# E-mail: SMTP when a host is configured, otherwise the messages are printed to the console
EMAIL_HOST = str(_cfg.get("email_host") or "")
EMAIL_PORT = int(_cfg.get("email_port") or 587)
EMAIL_HOST_USER = str(_cfg.get("email_host_user") or "")
EMAIL_HOST_PASSWORD = str(_cfg.get("email_host_password") or "")
EMAIL_USE_TLS = bool(_cfg.get("email_use_tls", True))
EMAIL_TIMEOUT = 15
DEFAULT_FROM_EMAIL = str(_cfg.get("email_from") or "PULSEHR <noreply@pulsehr.local>")
if EMAIL_HOST:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
else:
    EMAIL_BACKEND = "Apps.API.notifications.ConsoleLogEmailBackend"


# Logging to the shared console, where every line carries the time and its source process.
# HTTP client loggers stay quiet: their request lines contain the Telegram bot token.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "console": {"()": "Settings.console.ConsoleFormatter"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "console"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
        "httpx": {"level": "WARNING"},
        "httpcore": {"level": "WARNING"},
        "urllib3": {"level": "WARNING"},
    },
}
