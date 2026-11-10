# Copyright NGGT.LightKeeper. All Rights Reserved.

from __future__ import annotations

import argparse
import importlib
import importlib.util
import os
import sys
from pathlib import Path
from typing import Any


# Project root on the import path and the Django settings module for every command.
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "PULSEHR.settings")

from Services.process_supervisor import ServiceSpec, ServiceSupervisor  # noqa: E402
from Settings import console  # noqa: E402
from Settings.settings import SITE_URL_ENV, ensure_settings  # noqa: E402

# Oldest Python version supported by Django 6.
MIN_PYTHON_VERSION = (3, 12)

# Background services: console name, main.py command and the function that runs the service.
SERVICE_RUNNERS = {
    "web_notifications": ("WebNotifications", "Services.WebNotifications.service.run_service"),
    "telegram_bot": ("TelegramBot", "Services.TelegramBot.bot.run_bot"),
}


# Print one line of the entry point to the shared console.
def _print(message: str) -> None:
    console.write(message, source="PULSEHR")


# End the command with the install hint when the dependencies are missing.
def _check_dependencies() -> None:
    packages = ("django", "rest_framework", "httpx", "pywebpush", "openpyxl", "whitenoise")
    missing = [name for name in packages if importlib.util.find_spec(name) is None]
    if missing:
        _print(f"Missing packages: {', '.join(missing)}. Run: pip install -r requirements.txt")
        sys.exit(1)


def _setup_django() -> None:
    _check_dependencies()
    import django

    django.setup()


# Site

# Return the host to show in the site address: a wildcard bind is reachable through loopback.
def _display_host(host: str) -> str:
    return "127.0.0.1" if host in {"0.0.0.0", "::", ""} else host


# Return the background services started together with the site; the bot needs its token.
def _build_services(settings: dict[str, Any]) -> list[ServiceSpec]:
    main_path = str(BASE_DIR / "main.py")
    services = [ServiceSpec("WebNotifications", (sys.executable, "-u", main_path, "web_notifications"))]
    if str(settings.get("telegram_bot_token") or "").strip():
        services.append(ServiceSpec("TelegramBot", (sys.executable, "-u", main_path, "telegram_bot")))
    else:
        _print("telegram_bot_token is empty in Settings/settings.json: the Telegram bot is off.")
    return services


# Serve the Django WSGI application with a threaded server until the process is stopped. Requests
# are printed to the shared console; static files only in verbose mode.
def _serve(host: str, port: int, log: bool) -> None:
    from socketserver import ThreadingMixIn
    from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

    from PULSEHR.wsgi import application

    # Address reuse stays off on Windows, where it would let a second server bind a taken port.
    class ThreadedWSGIServer(ThreadingMixIn, WSGIServer):
        daemon_threads = True
        allow_reuse_address = os.name != "nt"

    class RequestHandler(WSGIRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            if log or not self.path.startswith("/static/"):
                console.write(format % args, source="Site")

    with make_server(host, port, application, server_class=ThreadedWSGIServer, handler_class=RequestHandler) as httpd:
        _print(f"Site is available at http://{_display_host(host)}:{port}/")
        httpd.serve_forever()


# Apply migrations, start the background services and serve the site until Ctrl+C.
def cmd_runserver(host: str | None, port: int | None, log: bool) -> None:
    _check_dependencies()
    settings = ensure_settings()
    host = host or str(settings.get("host") or "127.0.0.1")
    port = port or int(settings.get("port") or 8000)

    # Links in notifications point to the address the site really listens on.
    if not str(settings.get("site_url") or "").strip():
        os.environ[SITE_URL_ENV] = f"http://{_display_host(host)}:{port}"

    _setup_django()
    from django.core.management import call_command

    call_command("migrate", interactive=False, verbosity=1 if log else 0)

    supervisor = ServiceSupervisor(_build_services(settings), cwd=BASE_DIR, log=log)
    supervisor.start()
    try:
        _serve(host, port, log)
    except OSError as exc:
        _print(f"Error: the site could not listen on {host}:{port}. {exc}")
        sys.exit(1)
    except KeyboardInterrupt:
        _print("Stopping...")
    finally:
        supervisor.stop()


# Run one background service in this process until it stops.
def cmd_service(command: str) -> None:
    name, runner_path = SERVICE_RUNNERS[command]
    os.environ.setdefault(console.LOG_SOURCE_ENV, name)
    _setup_django()

    module_name, function_name = runner_path.rsplit(".", 1)
    runner = getattr(importlib.import_module(module_name), function_name)
    try:
        sys.exit(runner())
    except KeyboardInterrupt:
        sys.exit(0)


# Command line

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="PULSEHR entry point. Django commands (createsuperuser, grant_hr, seed_demo...) run through manage.py.",
    )
    parser.add_argument("command", help="runserver, web_notifications, telegram_bot or help")
    parser.add_argument("--host", default=None, help="Host for runserver (default: the host setting)")
    parser.add_argument("--port", type=int, default=None, help="Port for runserver (default: the port setting)")
    parser.add_argument("--log", action="store_true", help="Verbose output: migrations, static requests, service starts")
    return parser


def main() -> None:
    if sys.version_info < MIN_PYTHON_VERSION:
        required = ".".join(str(part) for part in MIN_PYTHON_VERSION)
        print(f"PULSEHR needs Python {required} or newer.")
        sys.exit(1)

    parser = _build_parser()
    args = parser.parse_args()
    if args.command == "runserver":
        cmd_runserver(args.host, args.port, args.log)
    elif args.command in SERVICE_RUNNERS:
        cmd_service(args.command)
    elif args.command == "help":
        parser.print_help()
    else:
        _print(f"Unknown command: '{args.command}'. Run 'python main.py help' for usage.")
        sys.exit(1)


# Run: python main.py runserver [--host HOST] [--port N] [--log]
if __name__ == "__main__":
    main()
