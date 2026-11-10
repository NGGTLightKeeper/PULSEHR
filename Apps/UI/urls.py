# Copyright NGGT.LightKeeper. All Rights Reserved.

from django.urls import path

from .views import GuestPageView, HrPageView, NotificationLinkView, PageView, ServiceWorkerView

# Site pages.
urlpatterns = [
    # Sign-in and the account.
    path("login/", GuestPageView.as_view(template_name="ui/login.html"), name="ui_login"),
    path("register/", GuestPageView.as_view(template_name="ui/register.html"), name="ui_register"),
    path("onboarding/", PageView.as_view(template_name="ui/onboarding.html"), name="ui_onboarding"),
    path("profile/", PageView.as_view(template_name="ui/profile.html", nav="profile"), name="ui_profile"),

    # Employee center and surveys.
    path("", PageView.as_view(template_name="ui/center.html", nav="center"), name="ui_center"),
    path("surveys/<uuid:survey_id>/", PageView.as_view(template_name="ui/survey.html", nav="center"), name="ui_survey"),
    path("surveys/<uuid:survey_id>/done/", PageView.as_view(template_name="ui/survey_done.html", nav="center"), name="ui_survey_done"),
    path("n/<uuid:token>/", NotificationLinkView.as_view(), name="ui_notification_link"),
    path("sw.js", ServiceWorkerView.as_view(), name="ui_service_worker"),

    # HR.
    path("hr/", HrPageView.as_view(template_name="ui/hr_dashboard.html", nav="hr_dashboard"), name="ui_hr_dashboard"),
    path("hr/surveys/", HrPageView.as_view(template_name="ui/hr_surveys.html", nav="hr_surveys"), name="ui_hr_surveys"),
    path("hr/surveys/<uuid:survey_id>/", HrPageView.as_view(template_name="ui/hr_survey_results.html", nav="hr_surveys"), name="ui_hr_survey"),
    path("hr/surveys/<uuid:survey_id>/edit/", HrPageView.as_view(template_name="ui/hr_survey_edit.html", nav="hr_surveys"), name="ui_hr_survey_edit"),
    path("hr/employees/", HrPageView.as_view(template_name="ui/hr_employees.html", nav="hr_employees"), name="ui_hr_employees"),
    path("hr/feedback/", HrPageView.as_view(template_name="ui/hr_feedback.html", nav="hr_feedback"), name="ui_hr_feedback"),
]
