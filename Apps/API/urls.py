# Copyright NGGT.LightKeeper. All Rights Reserved.

from django.urls import path

from . import views

# JSON API routes, mounted under api/v1/.
urlpatterns = [
    # Sign-in, registration and the account.
    path("auth/login/", views.LoginCodeView.as_view(), name="api_login"),
    path("auth/login/confirm/", views.LoginConfirmView.as_view(), name="api_login_confirm"),
    path("auth/register/", views.RegisterView.as_view(), name="api_register"),
    path("auth/register/confirm/", views.RegisterConfirmView.as_view(), name="api_register_confirm"),
    path("auth/logout/", views.LogoutView.as_view(), name="api_logout"),
    path("departments/", views.DepartmentsView.as_view(), name="api_departments"),
    path("me/", views.MeView.as_view(), name="api_me"),
    path("me/telegram/", views.TelegramView.as_view(), name="api_telegram"),
    path("me/telegram/confirm/", views.TelegramConfirmView.as_view(), name="api_telegram_confirm"),

    # Web Push.
    path("push/key/", views.PushKeyView.as_view(), name="api_push_key"),
    path("push/subscriptions/", views.PushSubscriptionsView.as_view(), name="api_push_subscriptions"),

    # Surveys of the employee.
    path("surveys/", views.MySurveysView.as_view(), name="api_my_surveys"),
    path("surveys/<uuid:survey_id>/", views.SurveyRunnerView.as_view(), name="api_survey"),
    path("surveys/<uuid:survey_id>/submit/", views.SurveySubmitView.as_view(), name="api_survey_submit"),
    path("feedback/", views.FeedbackView.as_view(), name="api_feedback"),

    # HR surveys and analytics.
    path("hr/dashboard/", views.HrDashboardView.as_view(), name="api_hr_dashboard"),
    path("hr/surveys/", views.HrSurveyListView.as_view(), name="api_hr_surveys"),
    path("hr/surveys/<uuid:survey_id>/", views.HrSurveyDetailView.as_view(), name="api_hr_survey"),
    path("hr/surveys/<uuid:survey_id>/structure/", views.HrSurveyStructureView.as_view(), name="api_hr_survey_structure"),
    path("hr/surveys/<uuid:survey_id>/publish/", views.HrSurveyActionView.as_view(), {"action": "publish"}, name="api_hr_survey_publish"),
    path("hr/surveys/<uuid:survey_id>/close/", views.HrSurveyActionView.as_view(), {"action": "close"}, name="api_hr_survey_close"),
    path("hr/surveys/<uuid:survey_id>/duplicate/", views.HrSurveyActionView.as_view(), {"action": "duplicate"}, name="api_hr_survey_duplicate"),
    path("hr/surveys/<uuid:survey_id>/analytics/", views.HrSurveyAnalyticsView.as_view(), name="api_hr_survey_analytics"),
    path("hr/surveys/<uuid:survey_id>/export/", views.HrSurveyExportView.as_view(), name="api_hr_survey_export"),

    # HR directory and feedback inbox.
    path("hr/departments/", views.HrDepartmentsView.as_view(), name="api_hr_departments"),
    path("hr/departments/<int:department_id>/", views.HrDepartmentDetailView.as_view(), name="api_hr_department"),
    path("hr/employees/", views.HrEmployeesView.as_view(), name="api_hr_employees"),
    path("hr/employees/<int:user_id>/", views.HrEmployeeDetailView.as_view(), name="api_hr_employee"),
    path("hr/feedback/", views.HrFeedbackListView.as_view(), name="api_hr_feedback"),
    path("hr/feedback/<uuid:feedback_id>/", views.HrFeedbackDetailView.as_view(), name="api_hr_feedback_item"),

    # Service state.
    path("health/", views.HealthView.as_view(), name="api_health"),
]
