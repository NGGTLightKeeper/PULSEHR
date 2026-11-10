# Copyright NGGT.LightKeeper. All Rights Reserved.

from __future__ import annotations

import uuid

from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.core.validators import RegexValidator
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone

# Allowed display names: letters, digits, dot, dash and underscore.
username_validator = RegexValidator(
    r"^[\w.-]{3,32}$",
    "Имя пользователя: 3–32 символа — буквы, цифры, точка, дефис или подчёркивание.",
)


# Accounts

# Roles of the service: employees take surveys, HR builds them and sees the analytics.
class UserRole(models.TextChoices):
    EMPLOYEE = "employee", "Сотрудник"
    HR = "hr", "HR"
    ADMIN = "admin", "Администратор"


# Company department; departments form a tree through the parent link.
class Department(models.Model):
    name = models.CharField(max_length=200)
    parent = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="children")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name", "id"]
        constraints = [
            models.UniqueConstraint(fields=["parent", "name"], name="unique_department_name_per_parent"),
        ]

    def __str__(self) -> str:
        return self.name

    # Return the ids of this department and of all departments below it.
    def subtree_ids(self) -> set[int]:
        children_by_parent: dict[int | None, list[int]] = {}
        for department_id, parent_id in Department.objects.values_list("id", "parent_id"):
            children_by_parent.setdefault(parent_id, []).append(department_id)

        ids = {self.id}
        stack = [self.id]
        while stack:
            for child_id in children_by_parent.get(stack.pop(), []):
                if child_id not in ids:
                    ids.add(child_id)
                    stack.append(child_id)
        return ids


# Create accounts: employees sign in with one-time codes and have no password, admins get one.
class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email: str, username: str, password: str | None = None, **extra_fields) -> "User":
        if not email:
            raise ValueError("E-mail is required.")
        user = self.model(email=email.strip().lower(), username=username.strip(), **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, email: str, username: str, password: str | None = None, **extra_fields) -> "User":
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", UserRole.ADMIN)
        return self.create_user(email, username, password, **extra_fields)


# Service account. The username is shown everywhere instead of the e-mail and phone. The phone is
# stored unverified for now; Telegram is linked only after the code from the bot is confirmed.
class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True)
    username = models.CharField(max_length=32, unique=True, validators=[username_validator])
    phone = models.CharField(max_length=20, blank=True, default="")
    phone_verified = models.BooleanField(default=False)
    # Claimed Telegram @username without "@"; the chat id is set when the claim is confirmed.
    telegram_username = models.CharField(max_length=32, blank=True, default="")
    telegram_chat_id = models.BigIntegerField(null=True, blank=True, unique=True)
    telegram_verified_at = models.DateTimeField(null=True, blank=True)
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, related_name="employees")
    role = models.CharField(max_length=16, choices=UserRole.choices, default=UserRole.EMPLOYEE)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    class Meta:
        ordering = ["username"]
        constraints = [
            models.UniqueConstraint(Lower("username"), name="unique_username_case_insensitive"),
            models.UniqueConstraint(fields=["phone"], condition=models.Q(phone_verified=True), name="unique_verified_phone"),
        ]

    def __str__(self) -> str:
        return self.username

    # Return whether the account can build surveys and see the analytics.
    @property
    def is_hr(self) -> bool:
        return self.is_superuser or self.role in {UserRole.HR, UserRole.ADMIN}

    # Return whether the Telegram account is confirmed and can receive messages.
    @property
    def telegram_verified(self) -> bool:
        return self.telegram_chat_id is not None and self.telegram_verified_at is not None


class CodePurpose(models.TextChoices):
    LOGIN = "login", "Вход"
    REGISTER = "register", "Регистрация"
    TELEGRAM = "telegram", "Подтверждение Telegram"


# One-time code. Only its keyed hash is stored. A registration code keeps the form data in the
# payload until the code is confirmed; a Telegram code keeps the chat that asked for it.
class VerificationCode(models.Model):
    purpose = models.CharField(max_length=16, choices=CodePurpose.choices)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True, related_name="codes")
    email = models.EmailField(blank=True, default="")
    code_hash = models.CharField(max_length=128)
    payload = models.JSONField(default=dict, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["purpose", "email"]), models.Index(fields=["purpose", "user"])]

    def __str__(self) -> str:
        return f"{self.purpose} code for {self.user or self.email}"


# Surveys

# Anonymous answers are never linked to an account; identified answers keep the author.
class SurveyMode(models.TextChoices):
    ANONYMOUS = "anonymous", "Анонимный"
    IDENTIFIED = "identified", "Идентифицированный"


class SurveyStatus(models.TextChoices):
    DRAFT = "draft", "Черновик"
    SCHEDULED = "scheduled", "Запланирован"
    ACTIVE = "active", "Идёт"
    CLOSED = "closed", "Завершён"


# Notification channels, in the default order of the cascade.
class Channel(models.TextChoices):
    PUSH = "push", "Web Push"
    TELEGRAM = "telegram", "Telegram"
    EMAIL = "email", "E-mail"


def default_cascade_channels() -> list[str]:
    return [channel.value for channel in Channel]


# Survey with its audience and notification settings. The mode cannot change after publishing.
class Survey(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    mode = models.CharField(max_length=16, choices=SurveyMode.choices, default=SurveyMode.ANONYMOUS)
    status = models.CharField(max_length=16, choices=SurveyStatus.choices, default=SurveyStatus.DRAFT)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_surveys",
    )
    # Audience: everybody, or the chosen departments together with the departments below them.
    audience_all = models.BooleanField(default=True)
    audience_departments = models.ManyToManyField(Department, blank=True, related_name="surveys")
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    # Smallest group whose answers are shown in the analytics of an anonymous survey.
    min_group_size = models.PositiveSmallIntegerField(default=5)
    cascade_channels = models.JSONField(default=default_cascade_channels)
    cascade_delay_minutes = models.PositiveIntegerField(default=120)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.title

    @property
    def is_anonymous(self) -> bool:
        return self.mode == SurveyMode.ANONYMOUS


class QuestionKind(models.TextChoices):
    SINGLE = "single", "Один вариант"
    MULTIPLE = "multiple", "Несколько вариантов"
    SCALE = "scale", "Шкала"
    ENPS = "enps", "eNPS (0–10)"
    TEXT = "text", "Свободный ответ"


# Survey question; the scale settings are used by the scale type only, eNPS is always 0–10.
class Question(models.Model):
    survey = models.ForeignKey(Survey, on_delete=models.CASCADE, related_name="questions")
    order = models.PositiveIntegerField()
    kind = models.CharField(max_length=16, choices=QuestionKind.choices)
    text = models.CharField(max_length=500)
    help_text = models.CharField(max_length=500, blank=True, default="")
    is_required = models.BooleanField(default=True)
    scale_min = models.SmallIntegerField(default=1)
    scale_max = models.SmallIntegerField(default=5)
    min_label = models.CharField(max_length=100, blank=True, default="")
    max_label = models.CharField(max_length=100, blank=True, default="")

    class Meta:
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(fields=["survey", "order"], name="unique_question_order_per_survey"),
        ]

    def __str__(self) -> str:
        return f"{self.order + 1}. {self.text[:60]}"

    # Return the allowed (min, max) of a numeric question, or None for other types.
    def value_range(self) -> tuple[int, int] | None:
        if self.kind == QuestionKind.ENPS:
            return 0, 10
        if self.kind == QuestionKind.SCALE:
            return self.scale_min, self.scale_max
        return None


class QuestionOption(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="options")
    order = models.PositiveIntegerField()
    text = models.CharField(max_length=300)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self) -> str:
        return self.text


class BranchOperator(models.TextChoices):
    CHOSEN = "chosen", "Выбран вариант"
    NOT_CHOSEN = "not_chosen", "Не выбран вариант"
    RANGE = "range", "Значение в диапазоне"
    ANSWERED = "answered", "Есть ответ"
    SKIPPED = "skipped", "Нет ответа"
    ALWAYS = "always", "Всегда"


# Branch rule: when the answer to the question matches, go to the target question, or finish the
# survey when there is no target. Targets always lie after the question, so loops are impossible.
class BranchRule(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="rules")
    order = models.PositiveIntegerField()
    operator = models.CharField(max_length=16, choices=BranchOperator.choices)
    option = models.ForeignKey(QuestionOption, on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    value_min = models.SmallIntegerField(null=True, blank=True)
    value_max = models.SmallIntegerField(null=True, blank=True)
    target = models.ForeignKey(Question, on_delete=models.CASCADE, null=True, blank=True, related_name="+")

    class Meta:
        ordering = ["order", "id"]

    def __str__(self) -> str:
        return f"{self.question_id}: {self.operator} -> {self.target_id or 'end'}"


# Answers

# Fact of taking part: who is invited, when the survey was opened and completed. It never points to
# the answers, so an anonymous response cannot be traced back through it.
class SurveyParticipation(models.Model):
    survey = models.ForeignKey(Survey, on_delete=models.CASCADE, related_name="participations")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="participations")
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    opened_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    # Channel of the last notification the user followed before completing the survey.
    completed_channel = models.CharField(max_length=16, choices=Channel.choices, blank=True, default="")

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["survey", "user"], name="unique_participation_per_survey"),
        ]

    def __str__(self) -> str:
        return f"{self.user} in {self.survey}"


# Submitted answers. In anonymous mode there is no user and no time, only the date, and the random
# ids keep the storage order from revealing who answered when.
class SurveyResponse(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    survey = models.ForeignKey(Survey, on_delete=models.CASCADE, related_name="responses")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="survey_responses",
    )
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    submitted_on = models.DateField()
    submitted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        return f"Response {self.id}"


# Answer to one question. Chosen options are stored as a list of option ids, so no auto-increment
# link table reveals the order of the answers.
class Answer(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    response = models.ForeignKey(SurveyResponse, on_delete=models.CASCADE, related_name="answers")
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="answers")
    selected_options = models.JSONField(default=list, blank=True)
    number = models.SmallIntegerField(null=True, blank=True)
    text = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(fields=["response", "question"], name="unique_answer_per_question"),
        ]

    def __str__(self) -> str:
        return f"Answer to {self.question_id}"


# Notifications

# Web Push subscription of one browser; turned off when the push service reports it as gone.
class PushSubscription(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="push_subscriptions")
    endpoint = models.CharField(max_length=1000, unique=True)
    p256dh = models.CharField(max_length=200)
    auth = models.CharField(max_length=100)
    user_agent = models.CharField(max_length=300, blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_success_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Push subscription of {self.user}"


class DispatchStatus(models.TextChoices):
    ACTIVE = "active", "Идёт"
    DONE = "done", "Остановлен: опрос открыт"
    EXHAUSTED = "exhausted", "Все каналы использованы"
    CANCELLED = "cancelled", "Отменён"


# Notification cascade of one participant: the next channel step and the time it is due.
class NotificationDispatch(models.Model):
    participation = models.OneToOneField(SurveyParticipation, on_delete=models.CASCADE, related_name="dispatch")
    status = models.CharField(max_length=16, choices=DispatchStatus.choices, default=DispatchStatus.ACTIVE)
    # Index of the next channel in the survey cascade.
    step_index = models.PositiveSmallIntegerField(default=0)
    next_run_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["next_run_at", "id"]

    def __str__(self) -> str:
        return f"Cascade for {self.participation}"


class AttemptStatus(models.TextChoices):
    SENT = "sent", "Отправлено"
    FAILED = "failed", "Ошибка"


# One notification sent through one channel. The token makes the tracked link /n/<token>/.
class NotificationAttempt(models.Model):
    dispatch = models.ForeignKey(NotificationDispatch, on_delete=models.CASCADE, related_name="attempts")
    channel = models.CharField(max_length=16, choices=Channel.choices)
    status = models.CharField(max_length=16, choices=AttemptStatus.choices)
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    detail = models.CharField(max_length=500, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    clicked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self) -> str:
        return f"{self.channel} {self.status} for {self.dispatch_id}"


# Feedback

class FeedbackCategory(models.TextChoices):
    IDEA = "idea", "Идея"
    PROBLEM = "problem", "Проблема"
    GRATITUDE = "gratitude", "Благодарность"
    OTHER = "other", "Другое"


class FeedbackStatus(models.TextChoices):
    NEW = "new", "Новое"
    IN_PROGRESS = "in_progress", "В работе"
    CLOSED = "closed", "Закрыто"


# Free-form message from an employee to HR. Anonymous feedback keeps neither the author nor the
# time, only the date; the HR reply is visible to the author of signed feedback.
class Feedback(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="feedback")
    is_anonymous = models.BooleanField(default=False)
    category = models.CharField(max_length=16, choices=FeedbackCategory.choices, default=FeedbackCategory.OTHER)
    text = models.TextField(max_length=4000)
    status = models.CharField(max_length=16, choices=FeedbackStatus.choices, default=FeedbackStatus.NEW)
    reply = models.TextField(blank=True, default="", max_length=4000)
    created_on = models.DateField()
    created_at = models.DateTimeField(null=True, blank=True)
    replied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_on", "id"]

    def __str__(self) -> str:
        return f"{self.get_category_display()}: {self.text[:50]}"
