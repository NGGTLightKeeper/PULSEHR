# Copyright NGGT.LightKeeper. All Rights Reserved.

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from Apps.API.models import (
    Department,
    Feedback,
    NotificationDispatch,
    PushSubscription,
    Question,
    QuestionOption,
    Survey,
    SurveyParticipation,
    SurveyResponse,
    User,
)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ["username"]
    list_display = ["username", "email", "department", "role", "telegram_username", "is_active"]
    list_filter = ["role", "is_active", "department"]
    search_fields = ["username", "email", "phone", "telegram_username"]
    readonly_fields = ["date_joined", "last_login", "telegram_chat_id", "telegram_verified_at"]
    fieldsets = [
        (None, {"fields": ["email", "username", "password"]}),
        ("Профиль", {"fields": ["phone", "phone_verified", "department", "role"]}),
        ("Telegram", {"fields": ["telegram_username", "telegram_chat_id", "telegram_verified_at"]}),
        ("Доступ", {"fields": ["is_active", "is_staff", "is_superuser", "groups", "user_permissions"]}),
        ("Даты", {"fields": ["date_joined", "last_login"]}),
    ]
    add_fieldsets = [
        (None, {"classes": ["wide"], "fields": ["email", "username", "password1", "password2"]}),
    ]


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ["name", "parent"]
    search_fields = ["name"]


class QuestionOptionInline(admin.TabularInline):
    model = QuestionOption
    extra = 0


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ["__str__", "survey", "kind", "is_required"]
    list_filter = ["kind"]
    inlines = [QuestionOptionInline]


@admin.register(Survey)
class SurveyAdmin(admin.ModelAdmin):
    list_display = ["title", "status", "mode", "published_at", "ends_at"]
    list_filter = ["status", "mode"]
    search_fields = ["title"]


@admin.register(SurveyParticipation)
class SurveyParticipationAdmin(admin.ModelAdmin):
    list_display = ["survey", "user", "opened_at", "completed_at", "completed_channel"]
    list_filter = ["survey"]


# Responses are listed by their random ids only: no author, no time and no ordering by submission.
@admin.register(SurveyResponse)
class SurveyResponseAdmin(admin.ModelAdmin):
    list_display = ["id", "survey", "department", "submitted_on"]
    list_filter = ["survey"]
    exclude = ["user", "submitted_at"]

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False


@admin.register(NotificationDispatch)
class NotificationDispatchAdmin(admin.ModelAdmin):
    list_display = ["participation", "status", "step_index", "next_run_at"]
    list_filter = ["status"]


@admin.register(PushSubscription)
class PushSubscriptionAdmin(admin.ModelAdmin):
    list_display = ["user", "is_active", "created_at", "last_success_at"]
    list_filter = ["is_active"]


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = ["category", "status", "is_anonymous", "created_on"]
    list_filter = ["status", "category", "is_anonymous"]
    exclude = ["author", "created_at"]
