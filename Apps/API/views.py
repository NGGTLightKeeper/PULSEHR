# Copyright NGGT.LightKeeper. All Rights Reserved.

from __future__ import annotations

from collections import Counter
from typing import Any

from django.contrib.auth import login, logout
from django.db.models import Count, ProtectedError, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework.exceptions import APIException, Throttled, ValidationError
from rest_framework.permissions import AllowAny, BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework.views import exception_handler as drf_exception_handler

from Apps.API import accounts, analytics, notifications, surveys
from Apps.API.models import Department, Feedback, FeedbackStatus, Survey, SurveyStatus, User, UserRole
from Apps.API.serializers import (
    CodeSerializer,
    DepartmentWriteSerializer,
    EmployeeSerializer,
    EmployeeUpdateSerializer,
    FeedbackCreateSerializer,
    HrFeedbackSerializer,
    HrFeedbackUpdateSerializer,
    LoginConfirmSerializer,
    LoginSerializer,
    MeSerializer,
    MyFeedbackSerializer,
    ParticipationCardSerializer,
    ProfileSerializer,
    PushSubscriptionSerializer,
    PushUnsubscribeSerializer,
    RegisterConfirmSerializer,
    RegisterSerializer,
    StructureSerializer,
    SubmitSerializer,
    SurveyCreateSerializer,
    SurveySerializer,
    SurveySettingsSerializer,
    TelegramUsernameSerializer,
)
from Services.TelegramBot import client as telegram
from Settings.settings import load_settings

# Employees shown in one page of the HR directory.
EMPLOYEES_LIMIT = 500


# Common

# Return every API error as {"detail": message, "code": DRF code} plus {"errors": {field: messages}}
# for form errors, so the pages can show the message, mark the fields and notice an expired session.
def exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    response = drf_exception_handler(exc, context)
    if response is None:
        return None

    detail = response.data
    if isinstance(detail, dict) and set(detail) == {"detail"}:
        data: dict[str, Any] = {"detail": str(detail["detail"])}
    elif isinstance(detail, dict):
        data = {"detail": accounts.first_message(detail), "errors": detail}
    else:
        data = {"detail": accounts.first_message(detail)}

    if isinstance(exc, APIException):
        data["code"] = exc.default_code
    if isinstance(exc, Throttled) and exc.wait:
        data["retry_after"] = int(exc.wait)
    response.data = data
    return response


class IsHR(BasePermission):
    message = "Раздел доступен только HR."

    def has_permission(self, request: Request, view: APIView) -> bool:
        return bool(request.user and request.user.is_authenticated and request.user.is_hr)


# Base of the views for HR.
class HrView(APIView):
    permission_classes = [IsAuthenticated, IsHR]


# Base of the sign-in views: open to anonymous visitors, protected from CSRF and rate-limited.
@method_decorator(csrf_protect, name="dispatch")
class PublicAuthView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth_code"


# Start the session of the user and return the account.
def _sign_in(request: Request, user: User) -> Response:
    login(request._request, user)
    return Response(MeSerializer(user).data)


# Accounts

class LoginCodeView(PublicAuthView):
    def post(self, request: Request) -> Response:
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(accounts.send_login_code(serializer.validated_data["login"]).as_dict())


class LoginConfirmView(PublicAuthView):
    throttle_scope = "auth_confirm"

    def post(self, request: Request) -> Response:
        serializer = LoginConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = accounts.confirm_login(serializer.validated_data["login"], serializer.validated_data["code"])
        return _sign_in(request, user)


class RegisterView(PublicAuthView):
    def post(self, request: Request) -> Response:
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(accounts.start_registration(serializer.validated_data).as_dict())


class RegisterConfirmView(PublicAuthView):
    throttle_scope = "auth_confirm"

    def post(self, request: Request) -> Response:
        serializer = RegisterConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = accounts.complete_registration(serializer.validated_data["email"], serializer.validated_data["code"])
        return _sign_in(request, user)


class LogoutView(APIView):
    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        logout(request._request)
        return Response(status=204)


# Departments for the registration and profile forms, in tree order.
class DepartmentsView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]

    def get(self, request: Request) -> Response:
        return Response(surveys.department_tree())


class MeView(APIView):
    def get(self, request: Request) -> Response:
        return Response(MeSerializer(request.user).data)

    def patch(self, request: Request) -> Response:
        serializer = ProfileSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        user = accounts.update_profile(request.user, serializer.validated_data)
        return Response(MeSerializer(user).data)


# Return the Telegram state of the user with the bot link for the confirmation.
def _telegram_status(user: User) -> dict[str, Any]:
    bot_username = telegram.get_bot_username()
    return {
        "telegram_username": user.telegram_username,
        "verified": user.telegram_verified,
        "bot_available": bot_username is not None,
        "bot_username": bot_username,
        "bot_link": f"https://t.me/{bot_username}?start=verify" if bot_username else None,
    }


class TelegramView(APIView):
    def get(self, request: Request) -> Response:
        return Response(_telegram_status(request.user))

    def put(self, request: Request) -> Response:
        serializer = TelegramUsernameSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        accounts.set_telegram_username(request.user, serializer.validated_data["telegram_username"])
        return Response(_telegram_status(request.user))

    def delete(self, request: Request) -> Response:
        accounts.disconnect_telegram(request.user)
        return Response(_telegram_status(request.user))


class TelegramConfirmView(APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth_confirm"

    def post(self, request: Request) -> Response:
        serializer = CodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        accounts.confirm_telegram(request.user, serializer.validated_data["code"])
        return Response(_telegram_status(request.user))


# Web Push

class PushKeyView(APIView):
    def get(self, request: Request) -> Response:
        public_key = str(load_settings().get("vapid_public_key") or "")
        return Response({"public_key": public_key, "enabled": bool(public_key)})


class PushSubscriptionsView(APIView):
    def post(self, request: Request) -> Response:
        serializer = PushSubscriptionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        notifications.save_push_subscription(
            request.user,
            data["endpoint"],
            data["keys"]["p256dh"],
            data["keys"]["auth"],
            request.headers.get("User-Agent", ""),
        )
        return Response({"push_enabled": True}, status=201)

    def delete(self, request: Request) -> Response:
        serializer = PushUnsubscribeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        notifications.remove_push_subscription(request.user, serializer.validated_data["endpoint"])
        enabled = request.user.push_subscriptions.filter(is_active=True).exists()
        return Response({"push_enabled": enabled})


# Employee surveys

class MySurveysView(APIView):
    def get(self, request: Request) -> Response:
        groups = surveys.surveys_for_user(request.user)
        return Response({name: ParticipationCardSerializer(items, many=True).data for name, items in groups.items()})


# Survey for the survey page: the questions come only while the survey can still be taken.
class SurveyRunnerView(APIView):
    def get(self, request: Request, survey_id: str) -> Response:
        survey, participation = surveys.open_survey(survey_id, request.user)
        can_answer = survey.status == SurveyStatus.ACTIVE and participation.completed_at is None
        return Response({
            "id": str(survey.id),
            "title": survey.title,
            "description": survey.description,
            "mode": survey.mode,
            "status": survey.status,
            "status_label": survey.get_status_display(),
            "ends_at": survey.ends_at,
            "completed": participation.completed_at is not None,
            "can_answer": can_answer,
            "username": request.user.username,
            "questions": surveys.serialize_structure(survey) if can_answer else [],
        })


class SurveySubmitView(APIView):
    def post(self, request: Request, survey_id: str) -> Response:
        serializer = SubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        surveys.submit(survey_id, request.user, serializer.validated_data["answers"])
        return Response({"status": "ok"}, status=201)


# HR surveys

class HrSurveyListView(HrView):
    def get(self, request: Request) -> Response:
        items = (
            Survey.objects.select_related("created_by")
            .prefetch_related("audience_departments")
            .annotate(
                invited_count=Count("participations", distinct=True),
                completed_count=Count("participations", filter=Q(participations__completed_at__isnull=False), distinct=True),
            )
            .order_by("-created_at")
        )
        return Response(SurveySerializer(items, many=True).data)

    def post(self, request: Request) -> Response:
        serializer = SurveyCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if data["template"]:
            survey = surveys.create_from_template(request.user, data["template"])
        else:
            survey = surveys.create_survey(request.user, title=data["title"], description=data["description"], mode=data["mode"])
        return Response(SurveySerializer(survey).data, status=201)


class HrSurveyDetailView(HrView):
    def get(self, request: Request, survey_id: str) -> Response:
        return Response(SurveySerializer(get_object_or_404(Survey, pk=survey_id)).data)

    def patch(self, request: Request, survey_id: str) -> Response:
        survey = get_object_or_404(Survey, pk=survey_id)
        serializer = SurveySettingsSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        surveys.update_settings(survey, serializer.validated_data)
        return Response(SurveySerializer(survey).data)

    def delete(self, request: Request, survey_id: str) -> Response:
        surveys.delete_draft(get_object_or_404(Survey, pk=survey_id))
        return Response(status=204)


class HrSurveyStructureView(HrView):
    def get(self, request: Request, survey_id: str) -> Response:
        survey = get_object_or_404(Survey, pk=survey_id)
        return Response({"questions": surveys.serialize_structure(survey), "editable": survey.status == SurveyStatus.DRAFT})

    def put(self, request: Request, survey_id: str) -> Response:
        survey = get_object_or_404(Survey, pk=survey_id)
        serializer = StructureSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        surveys.save_structure(survey, serializer.validated_data["questions"])
        return Response({"questions": surveys.serialize_structure(survey), "editable": True})


# Publish, close or duplicate a survey; the action comes from the route.
class HrSurveyActionView(HrView):
    def post(self, request: Request, survey_id: str, action: str) -> Response:
        survey = get_object_or_404(Survey, pk=survey_id)
        if action == "publish":
            surveys.publish(survey)
        elif action == "close":
            surveys.close(survey)
        else:
            survey = surveys.duplicate(survey, request.user)
            return Response(SurveySerializer(survey).data, status=201)
        return Response(SurveySerializer(survey).data)


class HrSurveyAnalyticsView(HrView):
    def get(self, request: Request, survey_id: str) -> Response:
        return Response(analytics.survey_analytics(get_object_or_404(Survey, pk=survey_id)))


# Download the answers as XLSX (default) or CSV (?type=csv).
class HrSurveyExportView(HrView):
    def get(self, request: Request, survey_id: str) -> HttpResponse:
        survey = get_object_or_404(Survey, pk=survey_id)
        if request.query_params.get("type") == "csv":
            content, content_type, extension = analytics.export_csv(survey), "text/csv; charset=utf-8", "csv"
        else:
            content = analytics.export_xlsx(survey)
            content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            extension = "xlsx"

        response = HttpResponse(content, content_type=content_type)
        filename = f"pulsehr-{str(survey.id)[:8]}-{timezone.localdate().isoformat()}.{extension}"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


class HrDashboardView(HrView):
    def get(self, request: Request) -> Response:
        return Response(analytics.dashboard())


# HR directory

class HrDepartmentsView(HrView):
    def get(self, request: Request) -> Response:
        counts = Counter(User.objects.filter(is_active=True).values_list("department_id", flat=True))
        return Response([{**item, "employees": counts[item["id"]]} for item in surveys.department_tree()])

    def post(self, request: Request) -> Response:
        serializer = DepartmentWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        name = serializer.validated_data.get("name", "").strip()
        if not name:
            raise ValidationError({"name": ["Укажите название."]})
        parent = _department_or_none(serializer.validated_data.get("parent_id"))
        if Department.objects.filter(parent=parent, name__iexact=name).exists():
            raise ValidationError({"name": ["Такое подразделение уже есть."]})
        department = Department.objects.create(name=name, parent=parent)
        return Response({"id": department.id, "name": department.name, "parent_id": department.parent_id}, status=201)


# Return the department by id, or None for an empty id.
def _department_or_none(department_id: int | None) -> Department | None:
    if not department_id:
        return None
    department = Department.objects.filter(pk=department_id).first()
    if department is None:
        raise ValidationError({"parent_id": ["Подразделение не найдено."]})
    return department


class HrDepartmentDetailView(HrView):
    def patch(self, request: Request, department_id: int) -> Response:
        department = get_object_or_404(Department, pk=department_id)
        serializer = DepartmentWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if "name" in data:
            if not data["name"].strip():
                raise ValidationError({"name": ["Укажите название."]})
            department.name = data["name"].strip()
        if "parent_id" in data:
            parent = _department_or_none(data["parent_id"])
            if parent is not None and parent.id in department.subtree_ids():
                raise ValidationError({"parent_id": ["Подразделение нельзя вложить в само себя."]})
            department.parent = parent
        department.save()
        return Response({"id": department.id, "name": department.name, "parent_id": department.parent_id})

    def delete(self, request: Request, department_id: int) -> Response:
        department = get_object_or_404(Department, pk=department_id)
        try:
            department.delete()
        except ProtectedError:
            raise ValidationError(["Сначала удалите или перенесите вложенные подразделения."]) from None
        return Response(status=204)


class HrEmployeesView(HrView):
    def get(self, request: Request) -> Response:
        users = User.objects.select_related("department").order_by("username")
        query = request.query_params.get("q", "").strip()
        if query:
            users = users.filter(Q(username__icontains=query) | Q(email__icontains=query) | Q(phone__icontains=query))
        department = request.query_params.get("department")
        if department:
            users = users.filter(department_id=department)
        return Response(EmployeeSerializer(users[:EMPLOYEES_LIMIT], many=True).data)


# Change the role, the department or the activity of an employee; HR cannot lock themselves out.
class HrEmployeeDetailView(HrView):
    def patch(self, request: Request, user_id: int) -> Response:
        employee = get_object_or_404(User, pk=user_id)
        serializer = EmployeeUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if employee.pk == request.user.pk and (data.get("role") == UserRole.EMPLOYEE or data.get("is_active") is False):
            raise ValidationError(["Нельзя снять роль HR или заблокировать самого себя."])

        if "role" in data:
            employee.role = data["role"]
        if "is_active" in data:
            employee.is_active = data["is_active"]
        if "department_id" in data:
            employee.department = _department_or_none(data["department_id"])
        employee.save()
        return Response(EmployeeSerializer(employee).data)


# Feedback

class FeedbackView(APIView):
    def get(self, request: Request) -> Response:
        items = Feedback.objects.filter(author=request.user, is_anonymous=False)
        return Response(MyFeedbackSerializer(items, many=True).data)

    # Anonymous feedback keeps neither the author nor the time of writing.
    def post(self, request: Request) -> Response:
        serializer = FeedbackCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        anonymous = data["is_anonymous"]
        Feedback.objects.create(
            author=None if anonymous else request.user,
            is_anonymous=anonymous,
            category=data["category"],
            text=data["text"],
            created_on=timezone.localdate(),
            created_at=None if anonymous else timezone.now(),
        )
        return Response({"status": "ok"}, status=201)


class HrFeedbackListView(HrView):
    def get(self, request: Request) -> Response:
        items = Feedback.objects.select_related("author")
        status = request.query_params.get("status")
        if status in FeedbackStatus.values:
            items = items.filter(status=status)
        return Response(HrFeedbackSerializer(items, many=True).data)


# Change the status of feedback or answer it; only signed feedback can be answered.
class HrFeedbackDetailView(HrView):
    def patch(self, request: Request, feedback_id: str) -> Response:
        feedback = get_object_or_404(Feedback, pk=feedback_id)
        serializer = HrFeedbackUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if "reply" in data:
            if feedback.is_anonymous and data["reply"].strip():
                raise ValidationError({"reply": ["Ответ на анонимное обращение никто не увидит."]})
            feedback.reply = data["reply"].strip()
            feedback.replied_at = timezone.now() if feedback.reply else None
        if "status" in data:
            feedback.status = data["status"]
        feedback.save()
        return Response(HrFeedbackSerializer(feedback).data)


# System

# Report that the site is up.
class HealthView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]

    def get(self, request: Request) -> Response:
        return Response({"status": "ok"})
