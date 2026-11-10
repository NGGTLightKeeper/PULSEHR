# Copyright NGGT.LightKeeper. All Rights Reserved.

from django.apps import AppConfig


# Configure the UI application: site pages and their static files.
class UiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "Apps.UI"
