# Copyright NGGT.LightKeeper. All Rights Reserved.

from __future__ import annotations

from pathlib import Path
from typing import Any

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.views import View
from django.views.generic import TemplateView

from Apps.API import notifications

# Service worker file; it is served from the site root, so its scope covers every page.
SERVICE_WORKER_FILE = Path(__file__).resolve().parent / "static" / "ui" / "js" / "sw.js"


# Page for signed-in users; nav marks the active menu item. The data comes from the API.
class PageView(LoginRequiredMixin, TemplateView):
    nav = ""

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["nav"] = self.nav
        return context


# Page for HR; other users go to their surveys.
class HrPageView(PageView):
    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if request.user.is_authenticated and not request.user.is_hr:
            return redirect("ui_center")
        return super().dispatch(request, *args, **kwargs)


# Sign-in and registration pages; a signed-in user goes straight to the site.
class GuestPageView(TemplateView):
    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if request.user.is_authenticated:
            return redirect("ui_center")
        return super().dispatch(request, *args, **kwargs)


# Link from a notification: remember the click for the channel statistics and open the survey.
class NotificationLinkView(View):
    def get(self, request: HttpRequest, token: str) -> HttpResponse:
        survey = notifications.register_click(token)
        return redirect(f"/surveys/{survey.id}/" if survey else "/")


class ServiceWorkerView(View):
    def get(self, request: HttpRequest) -> HttpResponse:
        response = HttpResponse(SERVICE_WORKER_FILE.read_text(encoding="utf-8"), content_type="application/javascript")
        response["Service-Worker-Allowed"] = "/"
        response["Cache-Control"] = "no-cache"
        return response
