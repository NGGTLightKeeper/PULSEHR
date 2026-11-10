# Copyright NGGT.LightKeeper. All Rights Reserved.

from __future__ import annotations

import csv
import io
from collections import Counter, defaultdict
from datetime import timedelta
from typing import Any

from django.db.models import QuerySet

from Apps.API.models import (
    AttemptStatus,
    Channel,
    Department,
    Feedback,
    FeedbackStatus,
    NotificationAttempt,
    Question,
    QuestionKind,
    Survey,
    SurveyParticipation,
    SurveyResponse,
    SurveyStatus,
    User,
)

# eNPS groups: promoters answer 9–10, detractors 0–6, the rest are passives.
PROMOTER_MIN = 9
DETRACTOR_MAX = 6

# KPI window: a response within this time after the first push counts as a response through push.
PUSH_RESPONSE_WINDOW = timedelta(hours=24)

MAX_TEXT_ANSWERS = 300
NO_DEPARTMENT = "Без подразделения"


def _percent(part: int, total: int) -> float | None:
    return round(part / total * 100, 1) if total else None


# eNPS

# Return the eNPS of the scores: share of promoters minus share of detractors, from -100 to 100.
def enps_summary(scores: list[int]) -> dict[str, Any]:
    total = len(scores)
    promoters = sum(1 for score in scores if score >= PROMOTER_MIN)
    detractors = sum(1 for score in scores if score <= DETRACTOR_MAX)
    return {
        "total": total,
        "promoters": promoters,
        "passives": total - promoters - detractors,
        "detractors": detractors,
        "score": round((promoters - detractors) / total * 100) if total else None,
    }


# Return the eNPS scores of a survey (its first eNPS question), or None when it has no such question.
def survey_enps_scores(survey: Survey) -> list[int] | None:
    question = survey.questions.filter(kind=QuestionKind.ENPS).order_by("order").first()
    if question is None:
        return None
    return [number for number in question.answers.values_list("number", flat=True) if number is not None]


# Participation and channels

def participation_stats(participations: QuerySet[SurveyParticipation]) -> dict[str, Any]:
    invited = participations.count()
    opened = participations.filter(opened_at__isnull=False).count()
    completed = participations.filter(completed_at__isnull=False).count()
    return {"invited": invited, "opened": opened, "completed": completed, "rate": _percent(completed, invited)}


# Return per channel how many notifications were sent, how many links were followed and how many
# participants completed the survey after following that channel.
def channel_funnel(participations: QuerySet[SurveyParticipation]) -> list[dict[str, Any]]:
    attempts = NotificationAttempt.objects.filter(dispatch__participation__in=participations)
    sent = Counter(attempts.filter(status=AttemptStatus.SENT).values_list("channel", flat=True))
    clicked = Counter(attempts.filter(clicked_at__isnull=False).values_list("channel", flat=True))
    completed = Counter(
        participations.filter(completed_at__isnull=False).exclude(completed_channel="").values_list("completed_channel", flat=True)
    )
    return [
        {
            "channel": channel.value,
            "label": channel.label,
            "sent": sent[channel.value],
            "clicked": clicked[channel.value],
            "completed": completed[channel.value],
        }
        for channel in Channel
    ]


# KPI "response rate through push": the share of participants who got a push and completed the
# survey within 24 hours after the first one.
def push_response_rate(participations: QuerySet[SurveyParticipation]) -> dict[str, Any]:
    first_push: dict[int, Any] = {}
    pushes = NotificationAttempt.objects.filter(
        dispatch__participation__in=participations,
        channel=Channel.PUSH,
        status=AttemptStatus.SENT,
    ).values_list("dispatch__participation_id", "created_at")
    for participation_id, sent_at in pushes:
        if participation_id not in first_push or sent_at < first_push[participation_id]:
            first_push[participation_id] = sent_at

    completed_at = dict(participations.filter(id__in=first_push).values_list("id", "completed_at"))
    responded = sum(
        1
        for participation_id, sent_at in first_push.items()
        if completed_at.get(participation_id) and completed_at[participation_id] - sent_at <= PUSH_RESPONSE_WINDOW
    )
    return {"notified": len(first_push), "responded": responded, "rate": _percent(responded, len(first_push))}


# KPI "employees with Web Push": the share of active accounts with at least one live subscription.
def push_coverage() -> dict[str, Any]:
    users = User.objects.filter(is_active=True)
    total = users.count()
    with_push = users.filter(push_subscriptions__is_active=True).distinct().count()
    return {"users": total, "with_push": with_push, "rate": _percent(with_push, total)}


# Survey analytics

# Return the results of one question from its answers.
def _question_result(question: Question, answers: list[Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": question.id,
        "number": question.order + 1,
        "text": question.text,
        "kind": question.kind,
        "answered": len(answers),
    }

    if question.kind in {QuestionKind.SINGLE, QuestionKind.MULTIPLE}:
        counts = Counter(option_id for answer in answers for option_id in answer.selected_options)
        result["options"] = [
            {"id": option.id, "text": option.text, "count": counts[option.id], "percent": _percent(counts[option.id], len(answers))}
            for option in question.options.all()
        ]
    elif question.kind in {QuestionKind.SCALE, QuestionKind.ENPS}:
        numbers = [answer.number for answer in answers if answer.number is not None]
        low, high = question.value_range()
        distribution = Counter(numbers)
        result["distribution"] = [{"value": value, "count": distribution[value]} for value in range(low, high + 1)]
        result["average"] = round(sum(numbers) / len(numbers), 2) if numbers else None
        result["min_label"] = question.min_label
        result["max_label"] = question.max_label
        if question.kind == QuestionKind.ENPS:
            result["enps"] = enps_summary(numbers)
    else:
        result["texts"] = [answer.text for answer in answers if answer.text][:MAX_TEXT_ANSWERS]
    return result


# Return the per-department participation and eNPS. In an anonymous survey the eNPS of a department
# with fewer responses than the threshold is hidden.
def _department_rows(
    survey: Survey,
    participations: QuerySet[SurveyParticipation],
    responses: list[SurveyResponse],
    enps_question: Question | None,
    threshold: int,
    hide_all: bool,
) -> list[dict[str, Any]]:
    names = dict(Department.objects.values_list("id", "name"))
    invited = Counter(participations.values_list("department_id", flat=True))
    completed = Counter(participations.filter(completed_at__isnull=False).values_list("department_id", flat=True))

    scores_by_department: dict[int | None, list[int]] = defaultdict(list)
    responses_by_department: Counter = Counter()
    for response in responses:
        responses_by_department[response.department_id] += 1
        if enps_question is None:
            continue
        for answer in response.answers.all():
            if answer.question_id == enps_question.id and answer.number is not None:
                scores_by_department[response.department_id].append(answer.number)

    rows = []
    for department_id in set(invited) | set(responses_by_department):
        count = responses_by_department[department_id]
        hidden = hide_all or (survey.is_anonymous and count < threshold)
        rows.append({
            "id": department_id,
            "name": names.get(department_id, NO_DEPARTMENT),
            "invited": invited[department_id],
            "completed": completed[department_id],
            "rate": _percent(completed[department_id], invited[department_id]),
            "hidden": hidden,
            "enps": None if hidden or enps_question is None else enps_summary(scores_by_department[department_id]),
        })
    return sorted(rows, key=lambda row: (row["id"] is None, row["name"].lower()))


# Return the analytics of a survey. Answers of an anonymous survey stay hidden until the number of
# responses reaches the threshold of the survey.
def survey_analytics(survey: Survey) -> dict[str, Any]:
    participations = survey.participations.all()
    responses = list(survey.responses.prefetch_related("answers"))
    threshold = survey.min_group_size if survey.is_anonymous else 1
    hidden = survey.is_anonymous and len(responses) < threshold
    questions = list(survey.questions.prefetch_related("options").order_by("order"))
    enps_question = next((question for question in questions if question.kind == QuestionKind.ENPS), None)

    answers_by_question: dict[int, list[Any]] = defaultdict(list)
    for response in responses:
        for answer in response.answers.all():
            answers_by_question[answer.question_id].append(answer)

    result: dict[str, Any] = {
        "survey": {
            "id": str(survey.id),
            "title": survey.title,
            "mode": survey.mode,
            "status": survey.status,
            "status_label": survey.get_status_display(),
            "published_at": survey.published_at,
            "ends_at": survey.ends_at,
            "closed_at": survey.closed_at,
        },
        "participation": participation_stats(participations),
        "responses": len(responses),
        "min_group_size": threshold,
        "hidden": hidden,
        "enps": None,
        "questions": [],
        "departments": _department_rows(survey, participations, responses, enps_question, threshold, hidden),
        "channels": channel_funnel(participations),
        "push_response": push_response_rate(participations),
    }
    if not hidden:
        result["questions"] = [_question_result(question, answers_by_question[question.id]) for question in questions]
        if enps_question is not None:
            scores = [answer.number for answer in answers_by_question[enps_question.id] if answer.number is not None]
            result["enps"] = enps_summary(scores)
    return result


# Dashboard

# Return the eNPS of every published survey with an eNPS question, oldest first. A survey below its
# anonymity threshold has no score.
def enps_trend() -> list[dict[str, Any]]:
    trend = []
    surveys = (
        Survey.objects.exclude(status=SurveyStatus.DRAFT)
        .filter(questions__kind=QuestionKind.ENPS)
        .distinct()
        .order_by("published_at")
    )
    for survey in surveys:
        scores = survey_enps_scores(survey) or []
        responses = survey.responses.count()
        hidden = survey.is_anonymous and responses < survey.min_group_size
        summary = enps_summary(scores)
        trend.append({
            "survey_id": str(survey.id),
            "title": survey.title,
            "date": survey.published_at.date().isoformat() if survey.published_at else None,
            "responses": responses,
            "hidden": hidden,
            "score": None if hidden else summary["score"],
            "summary": None if hidden else summary,
        })
    return trend


# Return the HR dashboard: KPI, eNPS trend, departments of the latest eNPS survey, channels and
# the running surveys.
def dashboard() -> dict[str, Any]:
    published = Survey.objects.exclude(status=SurveyStatus.DRAFT)
    participations = SurveyParticipation.objects.filter(survey__in=published)
    trend = enps_trend()
    latest = next((item for item in reversed(trend) if item["score"] is not None), None)

    departments: list[dict[str, Any]] = []
    if latest is not None:
        departments = survey_analytics(Survey.objects.get(pk=latest["survey_id"]))["departments"]

    active_surveys = []
    for survey in Survey.objects.filter(status=SurveyStatus.ACTIVE).order_by("-published_at"):
        stats = participation_stats(survey.participations.all())
        active_surveys.append({"id": str(survey.id), "title": survey.title, "ends_at": survey.ends_at, **stats})

    status_counts = Counter(Survey.objects.values_list("status", flat=True))
    return {
        "enps": latest,
        "enps_trend": trend,
        "departments": departments,
        "participation": participation_stats(participations),
        "push_coverage": push_coverage(),
        "push_response": push_response_rate(participations),
        "channels": channel_funnel(participations),
        "survey_counts": {status.value: status_counts[status.value] for status in SurveyStatus},
        "active_surveys": active_surveys,
        "feedback_new": Feedback.objects.filter(status=FeedbackStatus.NEW).count(),
    }


# Exports

# Placeholder of a value that is hidden to keep the answers anonymous.
HIDDEN = "—"


# Return the answer as a table cell: chosen option texts, the number or the text.
def _cell(question: Question, answer: Any, option_texts: dict[int, str]) -> Any:
    if answer is None:
        return ""
    if question.kind in {QuestionKind.SINGLE, QuestionKind.MULTIPLE}:
        return "; ".join(option_texts.get(option_id, "?") for option_id in answer.selected_options)
    if question.kind in {QuestionKind.SCALE, QuestionKind.ENPS}:
        return answer.number
    return answer.text


# Return the export table of a survey: header, rows and notes. An anonymous survey exports nothing
# below its threshold, and departments smaller than the threshold are not named.
def build_export_table(survey: Survey) -> tuple[list[str], list[list[Any]], list[str]]:
    questions = list(survey.questions.prefetch_related("options").order_by("order"))
    option_texts = {option.id: option.text for question in questions for option in question.options.all()}
    responses = list(survey.responses.select_related("department", "user").prefetch_related("answers"))
    threshold = survey.min_group_size if survey.is_anonymous else 1

    header = ["Дата", "Подразделение"]
    if not survey.is_anonymous:
        header += ["Сотрудник", "E-mail"]
    header += [f"{question.order + 1}. {question.text}" for question in questions]

    notes: list[str] = []
    if survey.is_anonymous and len(responses) < threshold:
        notes.append(f"Ответов меньше {threshold}: в анонимном опросе они не выгружаются.")
        return header, [], notes

    department_sizes = Counter(response.department_id for response in responses)
    if survey.is_anonymous and any(size < threshold for size in department_sizes.values()):
        notes.append(f"Подразделения, где ответов меньше {threshold}, не указаны.")

    rows = []
    for response in responses:
        answers = {answer.question_id: answer for answer in response.answers.all()}
        if survey.is_anonymous and department_sizes[response.department_id] < threshold:
            department = HIDDEN
        else:
            department = response.department.name if response.department else NO_DEPARTMENT

        row: list[Any] = [response.submitted_on.isoformat(), department]
        if not survey.is_anonymous:
            row += [response.user.username if response.user else HIDDEN, response.user.email if response.user else ""]
        row += [_cell(question, answers.get(question.id), option_texts) for question in questions]
        rows.append(row)
    return header, rows, notes


# Return the CSV export: UTF-8 with BOM and ";" separators, as Excel with Russian settings expects.
def export_csv(survey: Survey) -> bytes:
    header, rows, notes = build_export_table(survey)
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(header)
    writer.writerows(rows)
    for note in notes:
        writer.writerow([note])
    return buffer.getvalue().encode("utf-8-sig")


# Return the XLSX export with the answers sheet and the summary sheet.
def export_xlsx(survey: Survey) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    header, rows, notes = build_export_table(survey)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Ответы"
    sheet.append(header)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for row in rows:
        sheet.append(row)
    for note in notes:
        sheet.append([note])
    for index, title in enumerate(header, start=1):
        sheet.column_dimensions[sheet.cell(row=1, column=index).column_letter].width = min(max(len(str(title)), 12), 60)

    data = survey_analytics(survey)
    participation = data["participation"]
    lines: list[list[Any]] = [
        ["Опрос", survey.title],
        ["Режим", survey.get_mode_display()],
        ["Статус", survey.get_status_display()],
        ["Приглашено", participation["invited"]],
        ["Прошли", participation["completed"]],
        ["Отклик, %", participation["rate"]],
    ]
    if data["enps"]:
        enps = data["enps"]
        lines += [
            ["eNPS", enps["score"]],
            ["Промоутеры (9–10)", enps["promoters"]],
            ["Нейтралы (7–8)", enps["passives"]],
            ["Критики (0–6)", enps["detractors"]],
        ]
    if data["hidden"]:
        lines.append([f"Результаты скрыты: ответов меньше {data['min_group_size']}."])

    summary = workbook.create_sheet("Сводка")
    for line in lines:
        summary.append(line)
    summary.column_dimensions["A"].width = 24
    summary.column_dimensions["B"].width = 50

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
