# Copyright NGGT.LightKeeper. All Rights Reserved.

from __future__ import annotations

from rest_framework import serializers

from Apps.API.models import (
    BranchOperator,
    Channel,
    Department,
    Feedback,
    FeedbackCategory,
    FeedbackStatus,
    QuestionKind,
    Survey,
    SurveyMode,
    User,
    UserRole,
    username_validator,
)

# Limits of the survey structure.
MAX_QUESTIONS = 100
MAX_OPTIONS = 30
MAX_RULES = 30


# Accounts

class DepartmentShortSerializer(serializers.ModelSerializer):
    class Meta:
        model = Department
        fields = ["id", "name"]


# Account of the signed-in user as the pages see it.
class MeSerializer(serializers.ModelSerializer):
    department = DepartmentShortSerializer(read_only=True)
    telegram_verified = serializers.BooleanField(read_only=True)
    is_hr = serializers.BooleanField(read_only=True)
    role_label = serializers.CharField(source="get_role_display", read_only=True)
    push_enabled = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "username",
            "phone",
            "phone_verified",
            "telegram_username",
            "telegram_verified",
            "department",
            "role",
            "role_label",
            "is_hr",
            "push_enabled",
        ]

    def get_push_enabled(self, user: User) -> bool:
        return user.push_subscriptions.filter(is_active=True).exists()


class LoginSerializer(serializers.Serializer):
    login = serializers.CharField(max_length=254)


class LoginConfirmSerializer(serializers.Serializer):
    login = serializers.CharField(max_length=254)
    code = serializers.CharField(max_length=16)


# Registration form; a department is required as soon as the company has departments.
class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)
    username = serializers.CharField(max_length=32, validators=[username_validator])
    phone = serializers.CharField(max_length=32)
    department_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    telegram_username = serializers.CharField(max_length=33, required=False, allow_blank=True, default="")

    def validate(self, data: dict) -> dict:
        if not data.get("department_id") and Department.objects.exists():
            raise serializers.ValidationError({"department_id": "Выберите подразделение."})
        return data


class RegisterConfirmSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)
    code = serializers.CharField(max_length=16)


# Editable profile fields; absent fields stay unchanged.
class ProfileSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=32, required=False, validators=[username_validator])
    phone = serializers.CharField(max_length=32, required=False, allow_blank=True)
    department_id = serializers.IntegerField(required=False, allow_null=True)
    telegram_username = serializers.CharField(max_length=33, required=False, allow_blank=True)


class TelegramUsernameSerializer(serializers.Serializer):
    telegram_username = serializers.CharField(max_length=33, allow_blank=True)


class CodeSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=16)


class PushSubscriptionSerializer(serializers.Serializer):
    endpoint = serializers.URLField(max_length=1000)
    keys = serializers.DictField(child=serializers.CharField(max_length=200))

    def validate_keys(self, keys: dict) -> dict:
        if not keys.get("p256dh") or not keys.get("auth"):
            raise serializers.ValidationError("Нужны ключи p256dh и auth.")
        return keys


class PushUnsubscribeSerializer(serializers.Serializer):
    endpoint = serializers.URLField(max_length=1000)


# Survey structure

class OptionSerializer(serializers.Serializer):
    key = serializers.CharField(max_length=64)
    text = serializers.CharField(max_length=300)


class RuleSerializer(serializers.Serializer):
    operator = serializers.ChoiceField(choices=BranchOperator.choices)
    option = serializers.CharField(max_length=64, required=False, allow_null=True, allow_blank=True, default=None)
    min = serializers.IntegerField(required=False, allow_null=True, min_value=-100, max_value=100, default=None)
    max = serializers.IntegerField(required=False, allow_null=True, min_value=-100, max_value=100, default=None)
    target = serializers.CharField(max_length=64, required=False, allow_null=True, allow_blank=True, default=None)


class QuestionSerializer(serializers.Serializer):
    key = serializers.CharField(max_length=64)
    kind = serializers.ChoiceField(choices=QuestionKind.choices)
    text = serializers.CharField(max_length=500)
    help_text = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")
    is_required = serializers.BooleanField(required=False, default=True)
    scale_min = serializers.IntegerField(required=False, min_value=-10, max_value=10, default=1)
    scale_max = serializers.IntegerField(required=False, min_value=-10, max_value=10, default=5)
    min_label = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    max_label = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    options = OptionSerializer(many=True, required=False, default=list, max_length=MAX_OPTIONS)
    rules = RuleSerializer(many=True, required=False, default=list, max_length=MAX_RULES)


class StructureSerializer(serializers.Serializer):
    questions = QuestionSerializer(many=True, max_length=MAX_QUESTIONS)


# HR surveys

class SurveyCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200, required=False, default="Новый опрос")
    description = serializers.CharField(required=False, allow_blank=True, default="")
    mode = serializers.ChoiceField(choices=SurveyMode.choices, required=False, default=SurveyMode.ANONYMOUS)
    template = serializers.ChoiceField(choices=["enps"], required=False, allow_null=True, default=None)


# Survey settings; every field is optional for partial updates.
class SurveySettingsSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    mode = serializers.ChoiceField(choices=SurveyMode.choices, required=False)
    audience_all = serializers.BooleanField(required=False)
    audience_departments = serializers.PrimaryKeyRelatedField(queryset=Department.objects.all(), many=True, required=False)
    starts_at = serializers.DateTimeField(required=False, allow_null=True)
    ends_at = serializers.DateTimeField(required=False, allow_null=True)
    min_group_size = serializers.IntegerField(required=False, min_value=1, max_value=50)
    cascade_channels = serializers.ListField(child=serializers.ChoiceField(choices=Channel.choices), required=False)
    cascade_delay_minutes = serializers.IntegerField(required=False, min_value=1, max_value=10080)

    def validate_cascade_channels(self, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise serializers.ValidationError("Каналы не должны повторяться.")
        return value


# Survey for the HR pages; invited and completed come from annotations of the list query.
class SurveySerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    mode_label = serializers.CharField(source="get_mode_display", read_only=True)
    created_by = serializers.CharField(source="created_by.username", read_only=True, default=None)
    audience_departments = serializers.PrimaryKeyRelatedField(many=True, read_only=True)
    invited = serializers.SerializerMethodField()
    completed = serializers.SerializerMethodField()

    class Meta:
        model = Survey
        fields = [
            "id",
            "title",
            "description",
            "mode",
            "mode_label",
            "status",
            "status_label",
            "created_by",
            "audience_all",
            "audience_departments",
            "starts_at",
            "ends_at",
            "published_at",
            "closed_at",
            "min_group_size",
            "cascade_channels",
            "cascade_delay_minutes",
            "created_at",
            "updated_at",
            "invited",
            "completed",
        ]

    def get_invited(self, survey: Survey) -> int:
        if hasattr(survey, "invited_count"):
            return survey.invited_count
        return survey.participations.count()

    def get_completed(self, survey: Survey) -> int:
        if hasattr(survey, "completed_count"):
            return survey.completed_count
        return survey.participations.filter(completed_at__isnull=False).count()


# Employee surveys

# Survey card of the employee center, built from a participation.
class ParticipationCardSerializer(serializers.Serializer):
    id = serializers.UUIDField(source="survey.id")
    title = serializers.CharField(source="survey.title")
    description = serializers.CharField(source="survey.description")
    mode = serializers.CharField(source="survey.mode")
    ends_at = serializers.DateTimeField(source="survey.ends_at")
    opened_at = serializers.DateTimeField()
    completed_at = serializers.DateTimeField()


class SubmitSerializer(serializers.Serializer):
    answers = serializers.DictField(child=serializers.DictField(), allow_empty=True)


# HR directory

class DepartmentWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200, required=False)
    parent_id = serializers.IntegerField(required=False, allow_null=True)


class EmployeeSerializer(serializers.ModelSerializer):
    department = DepartmentShortSerializer(read_only=True)
    telegram_verified = serializers.BooleanField(read_only=True)
    role_label = serializers.CharField(source="get_role_display", read_only=True)
    push_enabled = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "phone",
            "phone_verified",
            "telegram_username",
            "telegram_verified",
            "department",
            "role",
            "role_label",
            "is_active",
            "date_joined",
            "push_enabled",
        ]

    def get_push_enabled(self, user: User) -> bool:
        return user.push_subscriptions.filter(is_active=True).exists()


class EmployeeUpdateSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=UserRole.choices, required=False)
    department_id = serializers.IntegerField(required=False, allow_null=True)
    is_active = serializers.BooleanField(required=False)


# Feedback

class FeedbackCreateSerializer(serializers.Serializer):
    category = serializers.ChoiceField(choices=FeedbackCategory.choices, default=FeedbackCategory.OTHER)
    text = serializers.CharField(max_length=4000)
    is_anonymous = serializers.BooleanField(default=False)


# Signed feedback of the employee with the HR reply.
class MyFeedbackSerializer(serializers.ModelSerializer):
    category_label = serializers.CharField(source="get_category_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Feedback
        fields = ["id", "category", "category_label", "text", "status", "status_label", "reply", "created_on", "replied_at"]


# Feedback in the HR inbox; the author of anonymous feedback is unknown by design.
class HrFeedbackSerializer(serializers.ModelSerializer):
    author = serializers.SerializerMethodField()
    category_label = serializers.CharField(source="get_category_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Feedback
        fields = [
            "id",
            "author",
            "is_anonymous",
            "category",
            "category_label",
            "text",
            "status",
            "status_label",
            "reply",
            "created_on",
            "replied_at",
        ]

    def get_author(self, feedback: Feedback) -> str | None:
        return None if feedback.is_anonymous or feedback.author is None else feedback.author.username


class HrFeedbackUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=FeedbackStatus.choices, required=False)
    reply = serializers.CharField(max_length=4000, required=False, allow_blank=True)
