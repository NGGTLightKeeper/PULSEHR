# Copyright NGGT.LightKeeper. All Rights Reserved.

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "PULSEHR.settings")

# WSGI callable served by main.py runserver (PULSEHR.wsgi:application).
application = get_wsgi_application()
