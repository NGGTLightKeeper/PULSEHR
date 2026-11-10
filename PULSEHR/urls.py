# Copyright NGGT.LightKeeper. All Rights Reserved.

from django.contrib import admin
from django.urls import include, path

# Root routes: the Django admin, the JSON API and the site pages.
urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("Apps.API.urls")),
    path("", include("Apps.UI.urls")),
]
