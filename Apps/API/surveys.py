# Copyright NGGT.LightKeeper. All Rights Reserved.

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError

from Apps.API import notifications
from Apps.API.models import (
    Answer,
    BranchRule,
    Department,
    DispatchStatus,
    Question,
    QuestionKind,
    QuestionOption,
    Survey,
    SurveyMode,
    SurveyParticipation,
    SurveyResponse,
    SurveyStatus,
    User,
)

logger = logging.getLogger(__name__)

# Question kinds and rule operators of the branching. The same rules are mirrored in
# Apps/UI/static/js/main/branching.js for the survey page; the server check is the final one.
CHOICE_KINDS = frozenset({QuestionKind.SINGLE, QuestionKind.MULTIPLE})
NUMBER_KINDS = frozenset({QuestionKind.SCALE, QuestionKind.ENPS})
OPTION_OPERATORS = frozenset({"chosen", "not_chosen"})
OPERATORS = OPTION_OPERATORS | {"range", "answered", "skipped", "always"}
MAX_TEXT_LENGTH = 2000
MAX_SCALE_SPAN = 10

# Answer of a question that got no answer.
EMPTY_ANSWER: dict[str, Any] = {"options": [], "number": None, "text": ""}

# Settings that can change only while the survey is a draft.
DRAFT_ONLY_FIELDS = frozenset({
    "mode",
    "audience_all",
    "audience_departments",
    "starts_at",
    "min_group_size",
    "cascade_channels",
    "cascade_delay_minutes",
})


# Branching

# Branch rule: when it matches the answer, go to the target question key, or finish on None.
@dataclass(frozen=True)
class RuleNode:
    operator: str
    option: str | None = None
    min: int | None = None
    max: int | None = None
    target: str | None = None


# Question as the branching sees it; keys are strings (database ids or keys from the builder).
@dataclass(frozen=True)
class QuestionNode:
    key: str
    kind: str
    required: bool = True
    options: tuple[str, ...] = ()
    low: int | None = None
    high: int | None = None
    rules: tuple[RuleNode, ...] = ()


# Return the number of an answer as an int, or the raw value when it is not a whole number.
def _normalize_number(value: Any) -> Any:
    if value is None or value == "":
        return None
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return value


# Return the answer in its normal form: option keys as strings, a number or None, a stripped text.
def normalize_answer(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return dict(EMPTY_ANSWER)
    options = raw.get("options") or []
    if not isinstance(options, list):
        options = [options]
    return {
        "options": [str(option) for option in options],
        "number": _normalize_number(raw.get("number")),
        "text": str(raw.get("text") or "").strip(),
    }


def is_answered(answer: dict[str, Any]) -> bool:
    return bool(answer["options"]) or answer["number"] is not None or bool(answer["text"])


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def rule_matches(rule: RuleNode, answer: dict[str, Any]) -> bool:
    match rule.operator:
        case "chosen":
            return rule.option in answer["options"]
        case "not_chosen":
            return rule.option not in answer["options"]
        case "range":
            number = answer["number"]
            if not _is_int(number):
                return False
            return (rule.min is None or number >= rule.min) and (rule.max is None or number <= rule.max)
        case "answered":
            return is_answered(answer)
        case "skipped":
            return not is_answered(answer)
        case "always":
            return True
    return False


# Return the key of the question after the one at index, or None when the survey ends there.
def next_key(questions: list[QuestionNode], index: int, answer: dict[str, Any]) -> str | None:
    for rule in questions[index].rules:
        if rule_matches(rule, answer):
            return rule.target
    return questions[index + 1].key if index + 1 < len(questions) else None


# Return the keys of the questions on the path the answers lead through. A jump to an unknown or an
# earlier question ends the path, so a broken structure can never loop.
def walk(questions: list[QuestionNode], answers: dict[str, dict[str, Any]]) -> list[str]:
    positions = {question.key: index for index, question in enumerate(questions)}
    path: list[str] = []
    index: int | None = 0 if questions else None
    while index is not None:
        question = questions[index]
        path.append(question.key)
        target = next_key(questions, index, answers.get(question.key, EMPTY_ANSWER))
        target_index = positions.get(target) if target is not None else None
        index = target_index if target_index is not None and target_index > index else None
    return path


# Return the error of an answer that does not fit its question, or None.
def _value_error(question: QuestionNode, answer: dict[str, Any]) -> str | None:
    options, number, text = answer["options"], answer["number"], answer["text"]
    if question.kind in CHOICE_KINDS:
        if number is not None or text:
            return "Неверный формат ответа."
        if len(set(options)) != len(options) or not set(options) <= set(question.options):
            return "Выбран неизвестный вариант."
        if question.kind == QuestionKind.SINGLE and len(options) != 1:
            return "Выберите один вариант."
    elif question.kind in NUMBER_KINDS:
        if options or text:
            return "Неверный формат ответа."
        if not _is_int(number) or not question.low <= number <= question.high:
            return f"Оценка должна быть от {question.low} до {question.high}."
    else:
        if options or number is not None:
            return "Неверный формат ответа."
        if len(text) > MAX_TEXT_LENGTH:
            return f"Ответ длиннее {MAX_TEXT_LENGTH} символов."
    return None


# Check the answers against the question types and the path; return {question key: error}.
# Questions off the path must stay unanswered, required questions on it must be answered.
def validate_answers(questions: list[QuestionNode], answers: dict[str, dict[str, Any]]) -> dict[str, str]:
    known_keys = {question.key for question in questions}
    errors = {key: "Неизвестный вопрос." for key in answers if key not in known_keys}
    path = set(walk(questions, answers))
    for question in questions:
        answer = answers.get(question.key, EMPTY_ANSWER)
        if question.key not in path:
            if is_answered(answer):
                errors[question.key] = "Этот вопрос не входит в ваш маршрут по опросу."
        elif not is_answered(answer):
            if question.required:
                errors[question.key] = "Ответ обязателен."
        elif error := _value_error(question, answer):
            errors[question.key] = error
    return errors


# Return the problems of one branch rule of the question at index.
def _rule_errors(question: QuestionNode, rule: RuleNode, index: int, positions: dict[str, int]) -> list[str]:
    if rule.operator not in OPERATORS:
        return ["неизвестное условие перехода."]

    errors: list[str] = []
    if rule.operator in OPTION_OPERATORS:
        if question.kind not in CHOICE_KINDS:
            errors.append("условие по варианту возможно только у вопросов с вариантами.")
        elif rule.option not in question.options:
            errors.append("условие ссылается на вариант другого вопроса.")
    if rule.operator == "range":
        if question.kind not in NUMBER_KINDS:
            errors.append("условие по диапазону возможно только у шкал.")
        elif rule.min is None and rule.max is None:
            errors.append("у диапазона нужна хотя бы одна граница.")
        elif rule.min is not None and rule.max is not None and rule.min > rule.max:
            errors.append("нижняя граница диапазона больше верхней.")
    if rule.target is not None:
        target_index = positions.get(rule.target)
        if target_index is None:
            errors.append("переход к несуществующему вопросу.")
        elif target_index <= index:
            errors.append("переходить можно только к следующим вопросам.")
    return errors


# Return the problems of a survey structure as messages that name the question number.
def validate_structure(questions: list[QuestionNode]) -> list[str]:
    errors: list[str] = []
    positions: dict[str, int] = {}
    for index, question in enumerate(questions):
        if question.key in positions:
            errors.append(f"Вопрос {index + 1}: повторяющийся ключ.")
        positions.setdefault(question.key, index)

    for index, question in enumerate(questions):
        number = index + 1
        if question.kind not in QuestionKind.values:
            errors.append(f"Вопрос {number}: неизвестный тип вопроса.")
            continue
        if question.kind in CHOICE_KINDS and len(question.options) < 2:
            errors.append(f"Вопрос {number}: нужно минимум два варианта ответа.")
        if question.kind in CHOICE_KINDS and len(set(question.options)) != len(question.options):
            errors.append(f"Вопрос {number}: повторяющиеся варианты ответа.")
        if question.kind in NUMBER_KINDS:
            low, high = question.low, question.high
            if low is None or high is None or low >= high or high - low > MAX_SCALE_SPAN:
                errors.append(f"Вопрос {number}: шкала должна содержать от 2 до {MAX_SCALE_SPAN + 1} значений.")
        for rule in question.rules:
            errors.extend(f"Вопрос {number}: {message}" for message in _rule_errors(question, rule, index, positions))
    return errors


# Structure

# Return the (min, max) of a numeric question kind from structure data, or (None, None).
def _payload_range(data: dict[str, Any]) -> tuple[int | None, int | None]:
    if data["kind"] == QuestionKind.ENPS:
        return 0, 10
    if data["kind"] == QuestionKind.SCALE:
        return data.get("scale_min"), data.get("scale_max")
    return None, None


def _key_or_none(value: Any) -> str | None:
    return str(value) if value not in (None, "") else None


# Return the branching view of structure data. Options count only for choice questions.
def nodes_from_payload(questions: list[dict[str, Any]]) -> list[QuestionNode]:
    nodes = []
    for data in questions:
        low, high = _payload_range(data)
        is_choice = data["kind"] in CHOICE_KINDS
        nodes.append(
            QuestionNode(
                key=str(data["key"]),
                kind=data["kind"],
                required=bool(data.get("is_required", True)),
                options=tuple(str(option["key"]) for option in data.get("options") or []) if is_choice else (),
                low=low,
                high=high,
                rules=tuple(
                    RuleNode(
                        operator=rule["operator"],
                        option=_key_or_none(rule.get("option")),
                        min=rule.get("min"),
                        max=rule.get("max"),
                        target=_key_or_none(rule.get("target")),
                    )
                    for rule in data.get("rules") or []
                ),
            )
        )
    return nodes


# Return the questions with their options and rules as the builder and the survey page use them.
def serialize_structure(survey: Survey) -> list[dict[str, Any]]:
    questions = survey.questions.prefetch_related("options", "rules").order_by("order", "id")
    return [
        {
            "key": str(question.id),
            "kind": question.kind,
            "text": question.text,
            "help_text": question.help_text,
            "is_required": question.is_required,
            "scale_min": question.scale_min,
            "scale_max": question.scale_max,
            "min_label": question.min_label,
            "max_label": question.max_label,
            "options": [{"key": str(option.id), "text": option.text} for option in question.options.all()],
            "rules": [
                {
                    "operator": rule.operator,
                    "option": str(rule.option_id) if rule.option_id else None,
                    "min": rule.value_min,
                    "max": rule.value_max,
                    "target": str(rule.target_id) if rule.target_id else None,
                }
                for rule in question.rules.all()
            ],
        }
        for question in questions
    ]


def build_nodes(survey: Survey) -> list[QuestionNode]:
    return nodes_from_payload(serialize_structure(survey))


# Replace the questions of a draft with the structure data in one transaction. The keys of
# questions and options only connect the rules to them; the stored objects get new ids.
def save_structure(survey: Survey, questions: list[dict[str, Any]]) -> None:
    _require_status(survey, {SurveyStatus.DRAFT}, "Вопросы можно менять только у черновика.")
    errors = validate_structure(nodes_from_payload(questions))
    if errors:
        raise ValidationError({"questions": errors})

    with transaction.atomic():
        survey.questions.all().delete()
        created: dict[str, Question] = {}
        options_by_question: dict[str, dict[str, QuestionOption]] = {}

        # Questions and options first, so the rules can point at any of them.
        for order, data in enumerate(questions):
            key = str(data["key"])
            low, high = _payload_range(data)
            created[key] = Question.objects.create(
                survey=survey,
                order=order,
                kind=data["kind"],
                text=data["text"],
                help_text=data.get("help_text") or "",
                is_required=bool(data.get("is_required", True)),
                scale_min=low if low is not None else 1,
                scale_max=high if high is not None else 5,
                min_label=data.get("min_label") or "",
                max_label=data.get("max_label") or "",
            )
            options_by_question[key] = {}
            if data["kind"] in CHOICE_KINDS:
                for option_order, option in enumerate(data.get("options") or []):
                    options_by_question[key][str(option["key"])] = QuestionOption.objects.create(
                        question=created[key],
                        order=option_order,
                        text=option["text"],
                    )

        for data in questions:
            key = str(data["key"])
            for rule_order, rule in enumerate(data.get("rules") or []):
                operator = rule["operator"]
                target_key = _key_or_none(rule.get("target"))
                BranchRule.objects.create(
                    question=created[key],
                    order=rule_order,
                    operator=operator,
                    option=options_by_question[key].get(str(rule.get("option"))) if operator in OPTION_OPERATORS else None,
                    value_min=rule.get("min") if operator == "range" else None,
                    value_max=rule.get("max") if operator == "range" else None,
                    target=created.get(target_key) if target_key else None,
                )

        survey.save(update_fields=["updated_at"])


# Settings

def _require_status(survey: Survey, statuses: set[str], message: str) -> None:
    if survey.status not in statuses:
        raise ValidationError([message])


def _check_dates(survey: Survey) -> None:
    if survey.starts_at and survey.ends_at and survey.ends_at <= survey.starts_at:
        raise ValidationError({"ends_at": ["Дата окончания должна быть позже даты начала."]})


def create_survey(user: User, *, title: str, description: str = "", mode: str = SurveyMode.ANONYMOUS) -> Survey:
    return Survey.objects.create(title=title, description=description, mode=mode, created_by=user)


# Apply new settings. After publishing only the title, the description and the end date may change.
def update_settings(survey: Survey, data: dict[str, Any]) -> Survey:
    if survey.status == SurveyStatus.CLOSED:
        raise ValidationError(["Завершённый опрос изменить нельзя."])
    if survey.status != SurveyStatus.DRAFT and DRAFT_ONLY_FIELDS & set(data):
        raise ValidationError(["После публикации можно менять только название, описание и дату окончания."])

    data = dict(data)
    departments = data.pop("audience_departments", None)
    for name, value in data.items():
        setattr(survey, name, value)
    _check_dates(survey)

    with transaction.atomic():
        survey.save()
        if departments is not None:
            survey.audience_departments.set(departments)
    return survey


# Delete a draft; published surveys keep their answers and can only be closed.
def delete_draft(survey: Survey) -> None:
    _require_status(survey, {SurveyStatus.DRAFT}, "Удалить можно только черновик.")
    survey.delete()


# Copy a survey with its settings and questions into a new draft.
def duplicate(survey: Survey, user: User) -> Survey:
    with transaction.atomic():
        copy = Survey.objects.create(
            title=f"{survey.title} (копия)"[:200],
            description=survey.description,
            mode=survey.mode,
            created_by=user,
            audience_all=survey.audience_all,
            min_group_size=survey.min_group_size,
            cascade_channels=list(survey.cascade_channels),
            cascade_delay_minutes=survey.cascade_delay_minutes,
        )
        copy.audience_departments.set(survey.audience_departments.all())
        save_structure(copy, serialize_structure(survey))
    return copy


# Audience

# Return the active accounts the survey is meant for: everybody, or the members of the chosen
# departments and of the departments below them.
def audience_users(survey: Survey) -> QuerySet[User]:
    users = User.objects.filter(is_active=True)
    if survey.audience_all:
        return users

    department_ids: set[int] = set()
    for department in survey.audience_departments.all():
        department_ids |= department.subtree_ids()
    return users.filter(department_id__in=department_ids)


def in_audience(survey: Survey, user: User) -> bool:
    return audience_users(survey).filter(pk=user.pk).exists()


# Return the departments as a flat list in tree order, with the depth for indentation.
def department_tree() -> list[dict[str, Any]]:
    children: dict[int | None, list[Department]] = {}
    for department in Department.objects.all():
        children.setdefault(department.parent_id, []).append(department)

    result: list[dict[str, Any]] = []
    stack = [(department, 0) for department in reversed(children.get(None, []))]
    while stack:
        department, depth = stack.pop()
        result.append({"id": department.id, "name": department.name, "parent_id": department.parent_id, "depth": depth})
        stack.extend((child, depth + 1) for child in reversed(children.get(department.id, [])))
    return result


# Lifecycle

# Publish a draft: it starts now, or waits for its start date.
def publish(survey: Survey) -> Survey:
    now = timezone.now()
    _require_status(survey, {SurveyStatus.DRAFT}, "Опубликовать можно только черновик.")

    nodes = build_nodes(survey)
    if not nodes:
        raise ValidationError(["Добавьте хотя бы один вопрос."])
    errors = validate_structure(nodes)
    if errors:
        raise ValidationError({"questions": errors})
    if not survey.audience_all and not survey.audience_departments.exists():
        raise ValidationError({"audience_departments": ["Выберите подразделения или отправьте опрос всем сотрудникам."]})
    if survey.ends_at and survey.ends_at <= now:
        raise ValidationError({"ends_at": ["Дата окончания уже прошла."]})
    _check_dates(survey)

    survey.published_at = now
    if survey.starts_at and survey.starts_at > now:
        survey.status = SurveyStatus.SCHEDULED
        survey.save(update_fields=["status", "published_at", "updated_at"])
        logger.info("Survey «%s» is scheduled for %s.", survey.title, timezone.localtime(survey.starts_at))
        return survey

    activate(survey, now)
    return survey


# Start a survey: invite its audience and start their notification cascades. Return the number of
# participants.
def activate(survey: Survey, now: datetime) -> int:
    with transaction.atomic():
        survey.status = SurveyStatus.ACTIVE
        survey.published_at = survey.published_at or now
        survey.save(update_fields=["status", "published_at", "updated_at"])

        users = list(audience_users(survey).only("id", "department_id"))
        SurveyParticipation.objects.bulk_create(
            [SurveyParticipation(survey=survey, user=user, department_id=user.department_id) for user in users],
            ignore_conflicts=True,
        )
        notifications.create_dispatches(survey.participations.all(), now)

    logger.info("Survey «%s» started for %s participant(s).", survey.title, len(users))
    return len(users)


# Finish a survey and cancel the notifications that were not sent yet.
def close(survey: Survey) -> Survey:
    _require_status(survey, {SurveyStatus.ACTIVE, SurveyStatus.SCHEDULED}, "Завершить можно только идущий опрос.")
    with transaction.atomic():
        survey.status = SurveyStatus.CLOSED
        survey.closed_at = timezone.now()
        survey.save(update_fields=["status", "closed_at", "updated_at"])
        notifications.cancel_survey_dispatches(survey)

    logger.info("Survey «%s» closed.", survey.title)
    return survey


# Start the scheduled surveys whose time has come and close the ones past their end date.
# Return the (started, closed) counts.
def process_schedule() -> tuple[int, int]:
    now = timezone.now()
    started = 0
    for survey in Survey.objects.filter(status=SurveyStatus.SCHEDULED, starts_at__lte=now):
        activate(survey, now)
        started += 1

    closed = 0
    for survey in Survey.objects.filter(status=SurveyStatus.ACTIVE, ends_at__lte=now):
        close(survey)
        closed += 1
    return started, closed


# Templates

# Questions of the eNPS template: detractors, passives and promoters get their own follow-up.
ENPS_TEMPLATE: list[dict[str, Any]] = [
    {
        "key": "enps",
        "kind": "enps",
        "text": "Насколько вероятно, что вы порекомендуете нашу компанию как место работы друзьям или знакомым?",
        "help_text": "0 — точно нет, 10 — точно да",
        "min_label": "Точно нет",
        "max_label": "Точно да",
        "rules": [
            {"operator": "range", "min": 0, "max": 6, "target": "improve"},
            {"operator": "range", "min": 7, "max": 8, "target": "raise"},
            {"operator": "range", "min": 9, "max": 10, "target": "like"},
        ],
    },
    {
        "key": "improve",
        "kind": "text",
        "text": "Что нам стоит изменить в первую очередь?",
        "is_required": False,
        "rules": [{"operator": "always", "target": "satisfaction"}],
    },
    {
        "key": "raise",
        "kind": "text",
        "text": "Что могло бы повысить вашу оценку?",
        "is_required": False,
        "rules": [{"operator": "always", "target": "satisfaction"}],
    },
    {
        "key": "like",
        "kind": "text",
        "text": "Что вам больше всего нравится в работе у нас?",
        "is_required": False,
    },
    {
        "key": "satisfaction",
        "kind": "scale",
        "text": "Насколько вы удовлетворены своей работой в целом?",
        "scale_min": 1,
        "scale_max": 5,
        "min_label": "Совсем нет",
        "max_label": "Полностью",
    },
    {
        "key": "support",
        "kind": "single",
        "text": "Чувствуете ли вы поддержку со стороны руководителя?",
        "options": [
            {"key": "yes", "text": "Да"},
            {"key": "rather_yes", "text": "Скорее да"},
            {"key": "rather_no", "text": "Скорее нет"},
            {"key": "no", "text": "Нет"},
        ],
    },
]

# Available templates: title, description and questions.
TEMPLATES = {
    "enps": (
        "Пульс-опрос eNPS",
        "Короткий опрос о том, насколько сотрудники готовы рекомендовать компанию как место работы.",
        ENPS_TEMPLATE,
    ),
}


def create_from_template(user: User, template: str) -> Survey:
    if template not in TEMPLATES:
        raise ValidationError({"template": ["Неизвестный шаблон."]})

    title, description, questions = TEMPLATES[template]
    with transaction.atomic():
        survey = create_survey(user, title=title, description=description)
        save_structure(survey, questions)
    return survey


# Taking surveys

# Invite the user to the running surveys published before the user joined or changed department.
def ensure_participations(user: User) -> None:
    for survey in Survey.objects.filter(status=SurveyStatus.ACTIVE).exclude(participations__user=user):
        if in_audience(survey, user):
            SurveyParticipation.objects.get_or_create(survey=survey, user=user, defaults={"department": user.department})


# Return the participation of the user in a published survey, creating it for a running survey of
# the user's audience. Raise NotFound when the survey is not available to the user.
def _participation(survey: Survey | None, user: User) -> SurveyParticipation:
    if survey is None or survey.status == SurveyStatus.DRAFT:
        raise NotFound("Опрос не найден.")

    participation = survey.participations.filter(user=user).first()
    if participation is None and survey.status == SurveyStatus.ACTIVE and in_audience(survey, user):
        participation, _ = SurveyParticipation.objects.get_or_create(
            survey=survey,
            user=user,
            defaults={"department": user.department},
        )
    if participation is None:
        raise NotFound("Опрос не найден или недоступен.")
    return participation


# Return the running surveys the user has not completed yet, newest first.
def pending_surveys(user: User) -> list[Survey]:
    ensure_participations(user)
    participations = (
        user.participations.select_related("survey")
        .filter(survey__status=SurveyStatus.ACTIVE, completed_at__isnull=True)
        .order_by("-survey__published_at")
    )
    return [participation.survey for participation in participations]


# Return the participations of the user split into the surveys to take and the completed ones.
def surveys_for_user(user: User) -> dict[str, list[SurveyParticipation]]:
    ensure_participations(user)
    participations = list(
        user.participations.select_related("survey").exclude(survey__status=SurveyStatus.DRAFT).order_by("-survey__published_at")
    )
    return {
        "active": [p for p in participations if p.completed_at is None and p.survey.status == SurveyStatus.ACTIVE],
        "completed": [p for p in participations if p.completed_at is not None],
    }


# Open a survey for the user: the first opening is remembered and stops the notification cascade.
def open_survey(survey_id: Any, user: User) -> tuple[Survey, SurveyParticipation]:
    survey = Survey.objects.filter(pk=survey_id).first()
    participation = _participation(survey, user)
    if participation.opened_at is None and survey.status == SurveyStatus.ACTIVE:
        participation.opened_at = timezone.now()
        participation.save(update_fields=["opened_at"])
        notifications.stop_dispatch(participation, DispatchStatus.DONE)
    return survey, participation


# Check and store the answers of the user. An anonymous response gets no user and no time, only the
# date; the participation records the fact of completion separately.
def submit(survey_id: Any, user: User, raw_answers: Any) -> SurveyResponse:
    if not isinstance(raw_answers, dict):
        raise ValidationError({"answers": ["Неверный формат ответов."]})
    answers = {str(key): normalize_answer(value) for key, value in raw_answers.items()}

    with transaction.atomic():
        survey = Survey.objects.filter(pk=survey_id).first()
        participation = _participation(survey, user)
        if survey.status != SurveyStatus.ACTIVE:
            raise ValidationError(["Опрос уже завершён."])
        if participation.completed_at is not None:
            raise ValidationError(["Вы уже прошли этот опрос."])

        nodes = build_nodes(survey)
        errors = validate_answers(nodes, answers)
        if errors:
            raise ValidationError({"answers": errors})

        now = timezone.now()
        identified = survey.mode == SurveyMode.IDENTIFIED
        response = SurveyResponse.objects.create(
            survey=survey,
            user=user if identified else None,
            department=participation.department,
            submitted_on=timezone.localdate(now),
            submitted_at=now if identified else None,
        )

        questions = {str(question.id): question for question in survey.questions.all()}
        stored = []
        for key in walk(nodes, answers):
            answer = answers.get(key, EMPTY_ANSWER)
            if is_answered(answer):
                stored.append(
                    Answer(
                        response=response,
                        question=questions[key],
                        selected_options=[int(option) for option in answer["options"]],
                        number=answer["number"],
                        text=answer["text"],
                    )
                )
        Answer.objects.bulk_create(stored)

        participation.completed_at = now
        participation.opened_at = participation.opened_at or now
        participation.completed_channel = notifications.last_clicked_channel(participation)
        participation.save(update_fields=["completed_at", "opened_at", "completed_channel"])
        notifications.stop_dispatch(participation, DispatchStatus.DONE)

    logger.info("Survey «%s»: a response was received.", survey.title)
    return response
