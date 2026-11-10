# Copyright NGGT.LightKeeper. All Rights Reserved.

from __future__ import annotations

import random
from datetime import timedelta
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from Apps.API import surveys
from Apps.API.models import (
    Answer,
    AttemptStatus,
    Channel,
    Department,
    DispatchStatus,
    Feedback,
    FeedbackCategory,
    FeedbackStatus,
    NotificationAttempt,
    NotificationDispatch,
    QuestionKind,
    Survey,
    SurveyMode,
    SurveyParticipation,
    SurveyResponse,
    SurveyStatus,
    User,
    UserRole,
)

# Domain of the demo accounts and the number of demo employees.
DEMO_DOMAIN = "demo.pulsehr.local"
EMPLOYEE_COUNT = 40

# Department tree: parent name -> child names.
DEPARTMENTS = {
    "Управление": ["HR", "Финансы"],
    "Производство": ["Цех № 1", "Цех № 2", "Логистика"],
    "ИТ": ["Разработка", "Поддержка"],
}

# Free-form answers for the follow-up questions of the eNPS template.
TEXT_ANSWERS = {
    "изменить": [
        "Прозрачнее объяснять решения руководства.",
        "Пересмотреть график смен, сейчас тяжело планировать выходные.",
        "Больше внимания обучению новых сотрудников.",
        "Обновить оборудование на участке.",
    ],
    "повысить": [
        "Понятный карьерный рост.",
        "Чаще получать обратную связь от руководителя.",
        "Меньше переработок в конце месяца.",
    ],
    "нравится": [
        "Сильная команда и взаимовыручка.",
        "Интересные задачи и возможность расти.",
        "Стабильность и честные условия.",
        "Руководитель всегда готов помочь.",
    ],
}

# Month names for the titles of the demo surveys.
MONTHS = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]

# Feedback examples: category, text, anonymous, status, HR reply.
FEEDBACK = [
    (FeedbackCategory.IDEA, "Предлагаю сделать в столовой меню на неделю вперёд.", False, FeedbackStatus.CLOSED, "Спасибо! Меню уже публикуется в общем чате по понедельникам."),
    (FeedbackCategory.PROBLEM, "В цехе № 2 не работает вентиляция во второй половине дня.", True, FeedbackStatus.IN_PROGRESS, ""),
    (FeedbackCategory.GRATITUDE, "Спасибо команде поддержки за быструю помощь с ноутбуком!", False, FeedbackStatus.NEW, ""),
    (FeedbackCategory.OTHER, "Хотелось бы больше корпоративных мероприятий для семей.", True, FeedbackStatus.NEW, ""),
    (FeedbackCategory.IDEA, "Можно ли перенести планёрку на 10:00?", False, FeedbackStatus.IN_PROGRESS, "Обсудим на совещании руководителей в четверг."),
]


# Fill the database with demo data for a presentation: departments, an HR account, employees,
# three closed eNPS surveys with a rising trend, a running survey, a draft and feedback.
class Command(BaseCommand):
    help = "Create demo data: departments, HR and employee accounts, surveys with answers and feedback."

    def handle(self, *args, **options) -> None:
        if User.objects.filter(email=f"hr@{DEMO_DOMAIN}").exists():
            raise CommandError("Demo data already exists.")

        rng = random.Random(42)
        with transaction.atomic():
            leaves = self._create_departments()
            hr = User.objects.create_user(
                email=f"hr@{DEMO_DOMAIN}",
                username="hr_demo",
                phone="+79000000001",
                phone_verified=True,
                role=UserRole.HR,
                department=Department.objects.get(name="HR"),
            )
            employees = [
                User.objects.create_user(
                    email=f"employee{number:02d}@{DEMO_DOMAIN}",
                    username=f"employee{number:02d}",
                    phone=f"+7900100{number:04d}",
                    department=rng.choice(leaves),
                )
                for number in range(1, EMPLOYEE_COUNT + 1)
            ]

            now = timezone.now()
            for index, days_ago in enumerate([95, 65, 35]):
                self._closed_enps_survey(hr, employees, now - timedelta(days=days_ago), mood=index, rng=rng)
            self._running_survey(hr, employees, now - timedelta(days=1), rng)
            self._draft_survey(hr)
            self._feedback(employees, now, rng)

        self.stdout.write(self.style.SUCCESS(
            f"Demo data created. HR: hr@{DEMO_DOMAIN} (or hr_demo, or phone +79000000001); "
            f"employees: employee01@{DEMO_DOMAIN} … employee{EMPLOYEE_COUNT:02d}@{DEMO_DOMAIN}. "
            "Without SMTP the sign-in codes are printed to the console."
        ))

    # Create the department tree and return its leaves.
    def _create_departments(self) -> list[Department]:
        leaves = []
        for parent_name, children in DEPARTMENTS.items():
            parent = Department.objects.create(name=parent_name)
            leaves += [Department.objects.create(name=name, parent=parent) for name in children]
        return leaves

    # Return a demo answer to a question; mood from 0 to 2 lifts the scores of later surveys.
    def _answer(self, question: Any, rng: random.Random, mood: int, score: int) -> dict[str, Any]:
        if question.kind == QuestionKind.ENPS:
            return {"options": [], "number": score, "text": ""}
        if question.kind == QuestionKind.SCALE:
            value = max(question.scale_min, min(question.scale_max, round(score / 2.5) + rng.choice([-1, 0, 0, 1])))
            return {"options": [], "number": value, "text": ""}
        if question.kind in {QuestionKind.SINGLE, QuestionKind.MULTIPLE}:
            options = [str(option.id) for option in question.options.all()]
            position = 0 if score >= 9 else 1 if score >= 7 else rng.choice([2, 3])
            return {"options": [options[min(position, len(options) - 1)]], "number": None, "text": ""}

        if rng.random() < 0.4:
            return {"options": [], "number": None, "text": ""}
        for keyword, texts in TEXT_ANSWERS.items():
            if keyword in question.text:
                return {"options": [], "number": None, "text": rng.choice(texts)}
        return {"options": [], "number": None, "text": ""}

    # Walk the branching path of a survey with demo answers.
    def _answers(self, survey: Survey, rng: random.Random, mood: int) -> dict[str, dict[str, Any]]:
        nodes = surveys.build_nodes(survey)
        questions = {str(question.id): question for question in survey.questions.prefetch_related("options")}
        positions = {node.key: index for index, node in enumerate(nodes)}
        score = max(0, min(10, round(rng.gauss(7.0 + mood * 0.8, 2.0))))

        answers: dict[str, dict[str, Any]] = {}
        index: int | None = 0 if nodes else None
        while index is not None:
            node = nodes[index]
            answers[node.key] = self._answer(questions[node.key], rng, mood, score)
            target = surveys.next_key(nodes, index, answers[node.key])
            index = positions.get(target) if target is not None else None
        return answers

    # Store one response with its answers and the participation and notification history.
    def _respond(self, survey: Survey, participation: SurveyParticipation, answers: dict[str, Any], completed_at: Any) -> None:
        response = SurveyResponse.objects.create(
            survey=survey,
            user=participation.user if survey.mode == SurveyMode.IDENTIFIED else None,
            department=participation.department,
            submitted_on=timezone.localdate(completed_at),
            submitted_at=completed_at if survey.mode == SurveyMode.IDENTIFIED else None,
        )
        questions = {str(question.id): question for question in survey.questions.all()}
        Answer.objects.bulk_create([
            Answer(
                response=response,
                question=questions[key],
                selected_options=[int(option) for option in answer["options"]],
                number=answer["number"],
                text=answer["text"],
            )
            for key, answer in answers.items()
            if answer["options"] or answer["number"] is not None or answer["text"]
        ])

    # Invite everybody to a published survey and record who completed it through which channel.
    def _participate(
        self,
        survey: Survey,
        employees: list[User],
        published_at: Any,
        rng: random.Random,
        mood: int,
        completion: float,
    ) -> None:
        attempts = []
        for user in employees:
            participation = SurveyParticipation.objects.create(survey=survey, user=user, department=user.department)
            channel = rng.choices([Channel.PUSH, Channel.TELEGRAM, Channel.EMAIL], weights=[6, 2, 2])[0]
            dispatch = NotificationDispatch.objects.create(participation=participation, status=DispatchStatus.EXHAUSTED, step_index=3)
            sent_at = published_at + timedelta(minutes=rng.randint(1, 5))
            attempt = NotificationAttempt(dispatch=dispatch, channel=channel, status=AttemptStatus.SENT)

            if rng.random() < completion:
                delay = timedelta(hours=rng.choice([0.5, 1, 2, 3, 5, 8, 20, 30, 50]))
                completed_at = sent_at + delay
                attempt.clicked_at = sent_at + delay - timedelta(minutes=3)
                participation.opened_at = attempt.clicked_at
                participation.completed_at = completed_at
                participation.completed_channel = channel
                participation.save(update_fields=["opened_at", "completed_at", "completed_channel"])
                dispatch.status = DispatchStatus.DONE
                dispatch.save(update_fields=["status"])
                self._respond(survey, participation, self._answers(survey, rng, mood), completed_at)

            attempt.save()
            attempt.created_at = sent_at
            attempts.append(attempt)
        NotificationAttempt.objects.bulk_update(attempts, ["created_at"])

    def _closed_enps_survey(self, hr: User, employees: list[User], published_at: Any, mood: int, rng: random.Random) -> None:
        survey = surveys.create_from_template(hr, "enps")
        local = timezone.localtime(published_at)
        survey.title = f"Пульс-опрос eNPS · {MONTHS[local.month - 1]} {local.year}"
        survey.status = SurveyStatus.CLOSED
        survey.published_at = published_at
        survey.ends_at = published_at + timedelta(days=7)
        survey.closed_at = survey.ends_at
        survey.save()
        Survey.objects.filter(pk=survey.pk).update(created_at=published_at - timedelta(days=1))
        self._participate(survey, employees, published_at, rng, mood, completion=0.7 + mood * 0.06)

    def _running_survey(self, hr: User, employees: list[User], published_at: Any, rng: random.Random) -> None:
        survey = surveys.create_survey(
            hr,
            title="Пульс недели: нагрузка и самочувствие",
            description="Три коротких вопроса о прошедшей неделе.",
        )
        surveys.save_structure(survey, [
            {
                "key": "load",
                "kind": "scale",
                "text": "Как вы оцениваете свою нагрузку на этой неделе?",
                "scale_min": 1,
                "scale_max": 5,
                "min_label": "Очень низкая",
                "max_label": "Чрезмерная",
                "rules": [{"operator": "range", "min": 4, "max": 5, "target": "reasons"}],
            },
            {
                "key": "mood",
                "kind": "single",
                "text": "С каким настроением вы заканчиваете неделю?",
                "options": [{"key": "good", "text": "Отличное"}, {"key": "ok", "text": "Нормальное"}, {"key": "bad", "text": "Устал(а)"}],
                "rules": [{"operator": "always", "target": None}],
            },
            {
                "key": "reasons",
                "kind": "multiple",
                "text": "Что сильнее всего добавляет нагрузки?",
                "options": [
                    {"key": "deadlines", "text": "Сроки"},
                    {"key": "meetings", "text": "Совещания"},
                    {"key": "people", "text": "Нехватка людей"},
                    {"key": "tools", "text": "Неудобные инструменты"},
                ],
            },
        ])
        survey.status = SurveyStatus.ACTIVE
        survey.published_at = published_at
        survey.ends_at = published_at + timedelta(days=6)
        survey.save()
        self._participate(survey, employees, published_at, rng, mood=1, completion=0.35)

    def _draft_survey(self, hr: User) -> None:
        survey = surveys.create_survey(
            hr,
            title="Оценка онбординга",
            description="Для сотрудников, которые пришли в последние три месяца.",
            mode=SurveyMode.IDENTIFIED,
        )
        surveys.save_structure(survey, [
            {"key": "clear", "kind": "scale", "text": "Насколько понятными были первые две недели работы?", "scale_min": 1, "scale_max": 5},
            {"key": "mentor", "kind": "single", "text": "Был ли у вас наставник?", "options": [{"key": "y", "text": "Да"}, {"key": "n", "text": "Нет"}]},
            {"key": "advice", "kind": "text", "text": "Что улучшить в адаптации новичков?", "is_required": False},
        ])

    def _feedback(self, employees: list[User], now: Any, rng: random.Random) -> None:
        for days_ago, (category, text, anonymous, status, reply) in zip([20, 12, 6, 3, 1], FEEDBACK):
            Feedback.objects.create(
                author=None if anonymous else rng.choice(employees),
                is_anonymous=anonymous,
                category=category,
                text=text,
                status=status,
                reply=reply,
                created_on=timezone.localdate(now - timedelta(days=days_ago)),
                created_at=None if anonymous else now - timedelta(days=days_ago),
                replied_at=now - timedelta(days=days_ago - 1) if reply else None,
            )
