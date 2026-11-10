# PULSEHR

## Installing

```
py -3.13 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```
Linux: `python3 -m venv .venv` and `.venv/bin/pip install -r requirements.txt`.

## Commands

- Run server: `python main.py runserver`
- Run server on another address: `python main.py runserver --host 0.0.0.0 --port 8080`
- Run server with verbose log: `python main.py runserver --log`
- Run notification service: `python main.py web_notifications`
- Run Telegram bot: `python main.py telegram_bot`
- Help: `python main.py help`

- Create demo data: `python manage.py seed_demo`
- Recreate demo data: `python manage.py seed_demo --reset`
- Grant HR role: `python manage.py grant_hr <e-mail or username>`
- Create admin: `python manage.py createsuperuser`
- Apply migrations: `python manage.py migrate`

## Settings

`Settings/settings.json`

- `telegram_bot_token` - Telegram Bot Token
- `email_host`, `email_port`, `email_host_user`, `email_host_password`, `email_use_tls`, `email_from` - SMTP. With out `email_host` - verification codes writing in console
- `host`, `port`, `site_url` - Site domain
- `allowed_email_domains` - Allowed e-mali domains ("" - any)
- `quiet_hours_enabled`, `quiet_hours` — Dont send notifications in quiet hours
