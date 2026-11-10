# Copyright NGGT.LightKeeper. All Rights Reserved.

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "PULSEHR.settings")

# ASGI callable for ASGI servers (PULSEHR.asgi:application).
application = get_asgi_application()
