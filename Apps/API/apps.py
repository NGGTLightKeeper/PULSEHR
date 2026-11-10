# Copyright NGGT.LightKeeper. All Rights Reserved.

from django.apps import AppConfig


# Configure the API application: models, business logic and JSON endpoints.
class ApiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "Apps.API"
