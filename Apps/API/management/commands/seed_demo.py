# Copyright NGGT.LightKeeper. All Rights Reserved.

from __future__ import annotations

import math
import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from django.core.management import call_command
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
    PushSubscription,
    QuestionKind,
    Survey,
    SurveyMode,
    SurveyParticipation,
    SurveyResponse,
    SurveyStatus,
    User,
    UserRole,
)

DEMO_DOMAIN = "demo.pulsehr.local"


# Company

# Divisions with their departments: (name, headcount, mood). The mood shifts the scores of the
# department; Дирекция and Юридический отдел stay below the anonymity threshold on purpose.
DEPARTMENTS = {
    "Управление": [("Дирекция", 4, 1.0), ("HR", 7, 0.8), ("Финансы", 9, 0.2), ("Юридический отдел", 3, 0.5)],
    "Производство": [("Цех № 1", 28, -0.5), ("Цех № 2", 24, -1.4), ("Контроль качества", 10, 0.0), ("Склад и логистика", 18, -0.8)],
    "Продажи": [("Корпоративные продажи", 14, 0.4), ("Региональные продажи", 12, -0.3), ("Маркетинг", 8, 0.4)],
    "ИТ": [("Разработка", 16, 1.2), ("Инфраструктура", 8, 0.3), ("Поддержка пользователей", 9, -0.2)],
}

# Accounts with known logins for the demo: (department, first name, last name, username, e-mail, role).
FIXED_PEOPLE = [
    ("HR", "Елена", "Волкова", "hr_demo", f"hr@{DEMO_DOMAIN}", UserRole.HR),
    ("HR", "Марина", "Орлова", "m.orlova", f"m.orlova@{DEMO_DOMAIN}", UserRole.HR),
    ("Поддержка пользователей", "Анна", "Смирнова", "a.smirnova", f"a.smirnova@{DEMO_DOMAIN}", UserRole.EMPLOYEE),
]

MALE_NAMES = [
    "Александр", "Дмитрий", "Максим", "Сергей", "Андрей", "Алексей", "Артём", "Илья", "Кирилл", "Михаил", "Никита",
    "Роман", "Егор", "Иван", "Павел", "Евгений", "Владимир", "Константин", "Олег", "Денис", "Николай", "Антон", "Игорь",
]
FEMALE_NAMES = [
    "Анна", "Мария", "Елена", "Ольга", "Наталья", "Екатерина", "Татьяна", "Ирина", "Светлана", "Юлия", "Дарья",
    "Алина", "Ксения", "Виктория", "Полина", "Марина", "Людмила", "Вера",
]
SURNAMES = [
    "Иванов", "Смирнов", "Кузнецов", "Попов", "Васильев", "Петров", "Соколов", "Михайлов", "Новиков", "Фёдоров",
    "Морозов", "Волков", "Алексеев", "Лебедев", "Семёнов", "Егоров", "Павлов", "Козлов", "Степанов", "Николаев",
    "Орлов", "Андреев", "Макаров", "Никитин", "Захаров", "Зайцев", "Соловьёв", "Борисов", "Яковлев", "Григорьев",
    "Романов", "Воробьёв", "Сергеев", "Кузьмин", "Фролов", "Александров", "Дмитриев", "Королёв", "Гусев", "Киселёв",
    "Ильин", "Максимов", "Поляков", "Сорокин", "Виноградов", "Ковалёв", "Белов", "Медведев", "Антонов", "Тарасов",
    "Жуков", "Баранов", "Филиппов", "Комаров", "Давыдов", "Беляев", "Герасимов", "Богданов", "Осипов", "Сидоров",
    "Матвеев", "Титов", "Марков", "Миронов", "Крылов", "Куликов", "Карпов", "Власов", "Мельников", "Денисов",
    "Покровский", "Никольский", "Тихонов", "Казаков", "Данилов", "Савельев", "Фомин", "Чернов", "Щербаков", "Калинин",
]

TRANSLIT = dict(zip(
    "абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
    ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t", "u", "f",
     "kh", "ts", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"],
))

# Browsers of the demo push subscriptions.
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0 Safari/537.36 Edg/142.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:145.0) Gecko/20100101 Firefox/145.0",
]


# Surveys

MONTHS = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]

# Company mood and the completion rate of the monthly eNPS surveys, oldest first: a dip in the
# second month, then a steady rise.
ENPS_MONTHS = [(-0.5, 0.56), (-0.9, 0.6), (-0.4, 0.66), (0.0, 0.71), (0.3, 0.76), (0.6, 0.8)]

WEEKLY_STRUCTURE = [
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
        "rules": [{"operator": "always", "target": "easier"}],
    },
    {
        "key": "reasons",
        "kind": "multiple",
        "text": "Что сильнее всего добавляет нагрузки?",
        "options": [
            {"key": "people", "text": "Нехватка людей"},
            {"key": "deadlines", "text": "Сжатые сроки"},
            {"key": "meetings", "text": "Совещания"},
            {"key": "tools", "text": "Неудобные инструменты"},
        ],
    },
    {"key": "easier", "kind": "text", "text": "Что могло бы облегчить следующую неделю?", "is_required": False},
]

PRODUCTION_STRUCTURE = [
    {
        "key": "place",
        "kind": "scale",
        "text": "Как вы оцениваете условия на своём рабочем месте?",
        "scale_min": 1,
        "scale_max": 5,
        "min_label": "Очень плохо",
        "max_label": "Отлично",
        "rules": [{"operator": "range", "min": 1, "max": 3, "target": "issues"}, {"operator": "always", "target": "safety"}],
    },
    {
        "key": "issues",
        "kind": "multiple",
        "text": "Что мешает больше всего?",
        "options": [
            {"key": "heat", "text": "Жара или холод"},
            {"key": "noise", "text": "Шум"},
            {"key": "equipment", "text": "Устаревшее оборудование"},
            {"key": "light", "text": "Освещение"},
            {"key": "space", "text": "Тесные проходы и захламлённость"},
        ],
    },
    {
        "key": "safety",
        "kind": "single",
        "text": "Хватает ли средств индивидуальной защиты?",
        "options": [{"key": "always", "text": "Всегда хватает"}, {"key": "usually", "text": "Обычно хватает"}, {"key": "lack", "text": "Часто не хватает"}],
    },
    {"key": "first", "kind": "text", "text": "Что улучшить на участке в первую очередь?", "is_required": False},
]

TRAINING_STRUCTURE = [
    {
        "key": "done",
        "kind": "single",
        "text": "Вы прошли обучение по охране труда в этом году?",
        "options": [{"key": "yes", "text": "Да, полностью"}, {"key": "part", "text": "Частично"}, {"key": "no", "text": "Ещё нет"}],
        "rules": [{"operator": "chosen", "option": "no", "target": "why"}],
    },
    {"key": "useful", "kind": "scale", "text": "Насколько полезным было обучение?", "scale_min": 1, "scale_max": 5, "min_label": "Бесполезно", "max_label": "Очень полезно"},
    {
        "key": "comment",
        "kind": "text",
        "text": "Что добавить в программу обучения?",
        "is_required": False,
        "rules": [{"operator": "always", "target": None}],
    },
    {
        "key": "why",
        "kind": "single",
        "text": "Что помешало пройти обучение?",
        "options": [{"key": "time", "text": "Не хватило времени"}, {"key": "dates", "text": "Не знал(а) о сроках"}, {"key": "schedule", "text": "Неудобное расписание"}],
    },
]

TOOLS_STRUCTURE = [
    {
        "key": "overall",
        "kind": "scale",
        "text": "Насколько вам удобно работать с текущими инструментами?",
        "scale_min": 1,
        "scale_max": 5,
        "min_label": "Совсем неудобно",
        "max_label": "Очень удобно",
        "rules": [{"operator": "range", "min": 1, "max": 2, "target": "pain"}],
    },
    {
        "key": "laptop",
        "kind": "single",
        "text": "Устраивает ли вас рабочий компьютер?",
        "options": [{"key": "yes", "text": "Полностью"}, {"key": "mostly", "text": "В целом да"}, {"key": "no", "text": "Нет, нужна замена"}],
        "rules": [{"operator": "always", "target": "wish"}],
    },
    {
        "key": "pain",
        "kind": "multiple",
        "text": "Что неудобнее всего?",
        "options": [
            {"key": "vpn", "text": "Медленный VPN"},
            {"key": "access", "text": "Доступы и согласования"},
            {"key": "tracker", "text": "Таск-трекер"},
            {"key": "mail", "text": "Почта и календарь"},
        ],
    },
    {"key": "wish", "kind": "text", "text": "Какого инструмента вам не хватает?", "is_required": False},
]

ONBOARDING_STRUCTURE = [
    {"key": "clear", "kind": "scale", "text": "Насколько понятными были первые две недели работы?", "scale_min": 1, "scale_max": 5},
    {
        "key": "mentor",
        "kind": "single",
        "text": "Был ли у вас наставник?",
        "options": [{"key": "yes", "text": "Да"}, {"key": "no", "text": "Нет"}],
        "rules": [{"operator": "chosen", "option": "no", "target": "advice"}],
    },
    {"key": "mentor_rate", "kind": "scale", "text": "Насколько наставник помог вам освоиться?", "scale_min": 1, "scale_max": 5},
    {"key": "advice", "kind": "text", "text": "Что улучшить в адаптации новичков?", "is_required": False},
]

PARTY_STRUCTURE = [
    {
        "key": "format",
        "kind": "multiple",
        "text": "Какой формат новогоднего праздника вам интереснее?",
        "options": [
            {"key": "dinner", "text": "Ужин в ресторане"},
            {"key": "quest", "text": "Квест или активная игра"},
            {"key": "family", "text": "Праздник для семей с детьми"},
            {"key": "office", "text": "Вечер в офисе"},
        ],
    },
    {"key": "wish", "kind": "text", "text": "Ваши пожелания к празднику", "is_required": False},
]

# Scales where a high value is the bad answer.
REVERSED_SCALES = {"Как вы оцениваете свою нагрузку на этой неделе?"}

# Free-form answers by question text.
TEXT_ANSWERS = {
    "Что нам стоит изменить в первую очередь?": [
        "Пересмотреть график смен: о переносах узнаём в последний день.",
        "Индексировать зарплату, последний раз пересматривали два года назад.",
        "Починить вентиляцию в цехе, летом работать очень тяжело.",
        "Меньше бумажной отчётности, половину форм никто не читает.",
        "Объяснять решения руководства, а не ставить перед фактом.",
        "Закупить нормальный инструмент, старый постоянно ломается.",
        "Не перебрасывать людей между участками без предупреждения.",
        "Убрать переработки в конце месяца или оплачивать их.",
        "Сделать комнату отдыха и горячее питание для второй смены.",
        "Понятные критерии премии: сейчас непонятно, за что её снимают.",
        "Нанять людей в отдел, нас трое на пять ставок.",
        "Чаще говорить с сотрудниками, а не только через приказы.",
    ],
    "Что могло бы повысить вашу оценку?": [
        "Понятный план карьерного роста.",
        "Обучение за счёт компании: курсы, конференции.",
        "Гибкий график хотя бы пару дней в неделю.",
        "Регулярная обратная связь от руководителя, а не раз в год.",
        "Дополнительный выходной за стаж.",
        "ДМС, который распространяется на семью.",
        "Меньше совещаний, больше времени на работу.",
        "Современная техника на рабочих местах.",
        "Компенсация спорта или питания.",
        "Прозрачная система премий.",
    ],
    "Что вам больше всего нравится в работе у нас?": [
        "Сильная команда, всегда помогут.",
        "Стабильность: зарплата вовремя, всё официально.",
        "Интересные задачи и возможность расти внутри компании.",
        "Руководитель слушает и защищает команду.",
        "Хорошая атмосфера в отделе.",
        "Можно предлагать идеи, и их действительно внедряют.",
        "Удобный офис и нормальная техника.",
        "Гибкий график и удалёнка, когда нужно.",
        "Обучение и наставничество для новичков.",
        "Чувство, что делаем полезное дело.",
    ],
    "Что могло бы облегчить следующую неделю?": [
        "Меньше срочных задач в пятницу вечером.",
        "Закрыть вакансию в отделе.",
        "Перенести планёрку на утро вторника.",
        "Чётко расставить приоритеты по задачам.",
        "Отменить хотя бы часть совещаний.",
    ],
    "Что улучшить на участке в первую очередь?": [
        "Кондиционеры или хотя бы вентиляторы на участке сборки.",
        "Заменить станок на третьей линии, простаивает через день.",
        "Разобрать склад у входа в цех, проходы заставлены.",
        "Выдавать перчатки и очки без очереди.",
        "Поставить нормальное освещение над рабочими местами.",
        "Сделать шумоизоляцию у компрессорной.",
    ],
    "Что добавить в программу обучения?": [
        "Больше практики, меньше слайдов.",
        "Разбор реальных случаев с нашего производства.",
        "Сделать онлайн-версию для второй смены.",
        "Отдельный блок по первой помощи.",
    ],
    "Какого инструмента вам не хватает?": [
        "Общей базы знаний вместо переписки в чатах.",
        "Нормального доступа к тестовым стендам.",
        "Второго монитора.",
        "Self-service для выдачи доступов.",
        "Единой системы заявок вместо почты.",
    ],
}

# Chance to react to a notification of the channel and the reaction delay range, in minutes.
REACTIONS = {
    Channel.PUSH: (0.62, 2, 360),
    Channel.TELEGRAM: (0.5, 5, 600),
    Channel.EMAIL: (0.35, 30, 2880),
}


# Feedback

# (days ago, category, text, anonymous, status, HR reply, sent by the demo employee).
FEEDBACK = [
    (118, FeedbackCategory.PROBLEM, "В раздевалке цеха № 2 третью неделю не работает горячая вода.", True, FeedbackStatus.CLOSED, "", False),
    (104, FeedbackCategory.IDEA, "Предлагаю публиковать меню столовой на неделю вперёд.", False, FeedbackStatus.CLOSED, "Спасибо! Меню теперь выкладываем в общем чате по понедельникам.", False),
    (96, FeedbackCategory.PROBLEM, "Ноутбуки в поддержке не тянут новую CRM, всё зависает.", False, FeedbackStatus.CLOSED, "Согласовали замену 6 ноутбуков, поставка в течение месяца.", True),
    (88, FeedbackCategory.OTHER, "Хотелось бы корпоративных мероприятий, куда можно прийти с семьёй.", True, FeedbackStatus.CLOSED, "", False),
    (81, FeedbackCategory.GRATITUDE, "Спасибо отделу кадров за быструю помощь с документами для ипотеки.", False, FeedbackStatus.CLOSED, "Рады помочь!", False),
    (73, FeedbackCategory.PROBLEM, "Мастер смены повышает голос на сотрудников при всех.", True, FeedbackStatus.IN_PROGRESS, "", False),
    (66, FeedbackCategory.IDEA, "Можно ли перенести планёрку с 8:30 на 9:30? Половина отдела едет из пригорода.", False, FeedbackStatus.CLOSED, "Со следующего месяца планёрка в 9:30.", False),
    (59, FeedbackCategory.PROBLEM, "На складе не хватает погрузчиков, очередь на разгрузку по часу.", False, FeedbackStatus.IN_PROGRESS, "Передали запрос директору по логистике, ждём бюджет.", False),
    (52, FeedbackCategory.OTHER, "Непонятно, как считается квартальная премия. Можно где-то посмотреть правила?", False, FeedbackStatus.CLOSED, "Положение о премировании выложили на портале в разделе «Документы».", False),
    (45, FeedbackCategory.IDEA, "Сделайте, пожалуйста, курсы английского для желающих.", False, FeedbackStatus.IN_PROGRESS, "Собираем группу, напишем всем в декабре.", True),
    (41, FeedbackCategory.GRATITUDE, "Спасибо ИТ за то, что за один вечер подняли упавшую почту.", True, FeedbackStatus.CLOSED, "", False),
    (36, FeedbackCategory.PROBLEM, "В цехе № 1 летом было +34, вентиляторы не помогают.", True, FeedbackStatus.IN_PROGRESS, "", False),
    (30, FeedbackCategory.IDEA, "Предлагаю ввести наставничество для новичков на производстве.", False, FeedbackStatus.CLOSED, "Запускаем программу наставников с января, спасибо за идею.", False),
    (24, FeedbackCategory.OTHER, "Будет ли индексация зарплат в следующем году?", True, FeedbackStatus.NEW, "", False),
    (19, FeedbackCategory.PROBLEM, "Пропуск на парковку оформляется две недели, это слишком долго.", False, FeedbackStatus.IN_PROGRESS, "Уточняем у службы безопасности, можно ли ускорить.", False),
    (15, FeedbackCategory.GRATITUDE, "Спасибо руководителю отдела продаж за поддержку после тяжёлого квартала.", False, FeedbackStatus.CLOSED, "Передали ваши слова, спасибо!", False),
    (12, FeedbackCategory.IDEA, "Повесить в столовой микроволновки, их всего две на всю смену.", True, FeedbackStatus.NEW, "", False),
    (9, FeedbackCategory.PROBLEM, "Опять задержали аванс на два дня, без объяснений.", True, FeedbackStatus.NEW, "", False),
    (7, FeedbackCategory.IDEA, "Добавьте в опросы вопрос про удалённую работу.", False, FeedbackStatus.NEW, "", False),
    (5, FeedbackCategory.OTHER, "Где узнать график отпусков на следующий год?", False, FeedbackStatus.IN_PROGRESS, "График согласуем до 15 декабря, пришлём всем на почту.", False),
    (3, FeedbackCategory.GRATITUDE, "Спасибо за новые кресла в отделе поддержки!", False, FeedbackStatus.NEW, "", True),
    (2, FeedbackCategory.PROBLEM, "В переговорке на третьем этаже не работает проектор.", False, FeedbackStatus.NEW, "", False),
    (1, FeedbackCategory.OTHER, "Нагрузка в конце года просто огромная, люди выгорают.", True, FeedbackStatus.NEW, "", False),
]


# Demo employee with the moments their notification channels appeared.
@dataclass
class Person:
    user: User
    mood: float
    push_since: datetime | None = None
    telegram_since: datetime | None = None
    left_at: datetime | None = None

    # Return the channels the person could get at the moment, in cascade order.
    def channels(self, moment: datetime) -> list[str]:
        channels = []
        if self.push_since and self.push_since <= moment:
            channels.append(Channel.PUSH)
        if self.telegram_since and self.telegram_since <= moment:
            channels.append(Channel.TELEGRAM)
        channels.append(Channel.EMAIL)
        return channels

    def employed(self, moment: datetime) -> bool:
        return self.user.date_joined <= moment and (self.left_at is None or self.left_at > moment)


# Fill the database with a demo company: departments, employees with their channels, half a year of
# eNPS surveys, surveys for departments, running, scheduled and draft surveys, notification history
# and feedback. Notifications of the demo are finished, so the notification service sends nothing.
class Command(BaseCommand):
    help = "Create demo data: a company with employees, surveys with answers, notification history and feedback."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--reset", action="store_true", help="Clear the whole database before creating the demo data")

    def handle(self, *args, **options) -> None:
        if options["reset"]:
            call_command("flush", interactive=False, verbosity=0)
        elif User.objects.filter(email=f"hr@{DEMO_DOMAIN}").exists():
            raise CommandError("Demo data already exists. Run with --reset to clear the database and create it again.")

        self.rng = random.Random(42)
        self.now = timezone.now()
        with transaction.atomic():
            departments = self._create_departments()
            people = self._create_people(departments)
            self._create_push_subscriptions(people)
            counts = self._create_surveys(people, departments)
            feedback = self._create_feedback(people)

        active = sum(1 for person in people if person.user.is_active)
        self.stdout.write(self.style.SUCCESS(
            f"Demo data created: {len(departments)} departments, {active} employees, "
            f"{counts[0]} surveys, {counts[1]} responses, {feedback} feedback messages.\n"
            f"HR: hr_demo (hr@{DEMO_DOMAIN}) or m.orlova; employee: a.smirnova. "
            "Without SMTP the sign-in codes are printed to the console."
        ))

    def _days_ago(self, days: float, hour: int = 10) -> datetime:
        moment = timezone.localtime(self.now - timedelta(days=days))
        return moment.replace(hour=hour, minute=self.rng.randint(0, 59), second=0, microsecond=0)

    # Company

    # Create the divisions and departments; return {department name: (department, headcount, mood)}.
    def _create_departments(self) -> dict[str, tuple[Department, int, float]]:
        departments = {}
        for division, children in DEPARTMENTS.items():
            parent = Department.objects.create(name=division)
            for name, headcount, mood in children:
                departments[name] = (Department.objects.create(name=name, parent=parent), headcount, mood)
        return departments

    def _translit(self, text: str) -> str:
        return "".join(TRANSLIT.get(char, char) for char in text.lower())

    # Return a random (first name, last name) in the right grammatical gender.
    def _random_name(self) -> tuple[str, str]:
        surname = self.rng.choice(SURNAMES)
        if self.rng.random() < 0.45:
            if surname.endswith("ский"):
                return self.rng.choice(FEMALE_NAMES), surname[:-2] + "ая"
            return self.rng.choice(FEMALE_NAMES), surname + "а"
        return self.rng.choice(MALE_NAMES), surname

    def _unique(self, base: str, used: set[str]) -> str:
        value, number = base, 1
        while value in used:
            number += 1
            value = f"{base}{number}"
        used.add(value)
        return value

    # Create the employees of every department with phones, Telegram and the dates they joined;
    # a few newcomers and a few people who already left make the directory realistic.
    def _create_people(self, departments: dict[str, tuple[Department, int, float]]) -> list[Person]:
        rng = self.rng
        fixed_usernames = {item[3] for item in FIXED_PEOPLE}
        usernames = set(fixed_usernames)
        telegram_names: set[str] = set()
        phones: set[str] = {"+79000000001"}
        people = []

        for name, (department, headcount, mood) in departments.items():
            fixed = [item for item in FIXED_PEOPLE if item[0] == name]
            for index in range(headcount):
                is_fixed = index < len(fixed)
                if is_fixed:
                    _, first, last, username, email, role = fixed[index]
                else:
                    first, last = self._random_name()
                    username = self._unique(f"{self._translit(first)[0]}.{self._translit(last)}", usernames)
                    email, role = f"{username}@{DEMO_DOMAIN}", UserRole.EMPLOYEE

                newcomer = not is_fixed and rng.random() < 0.07
                joined = self._days_ago(rng.uniform(10, 75) if newcomer else rng.uniform(200, 2200), hour=9)
                phone = "+79000000001" if username == "hr_demo" else self._unique(f"+79{rng.randint(10**8, 10**9 - 1)}", phones)
                user = User(
                    email=email,
                    username=username,
                    phone=phone,
                    phone_verified=username == "hr_demo" or rng.random() < 0.2,
                    department=department,
                    role=role,
                    date_joined=joined,
                )
                user.set_unusable_password()
                person = Person(user=user, mood=mood + rng.gauss(0, 0.7))

                # The demo employee starts without Telegram and push, so both can be connected live.
                if username != "a.smirnova":
                    channel_roll = rng.random()
                    if channel_roll < 0.35:
                        user.telegram_username = self._unique(f"{self._translit(first)}_{self._translit(last)}", telegram_names)
                        # Negative ids never match a real private chat.
                        user.telegram_chat_id = -(1000 + len(people))
                        person.telegram_since = max(joined + timedelta(days=1), self._days_ago(rng.uniform(5, 300)))
                        user.telegram_verified_at = person.telegram_since
                    elif channel_roll < 0.43:
                        user.telegram_username = self._unique(f"{self._translit(first)}{rng.randint(10, 99)}", telegram_names)
                    if rng.random() < 0.66:
                        person.push_since = max(joined + timedelta(days=1), self._days_ago(220 * rng.random() ** 1.4))
                people.append(person)

        User.objects.bulk_create([person.user for person in people])
        leavers = rng.sample([person for person in people if person.user.username not in fixed_usernames], 3)
        for person in leavers:
            person.left_at = self._days_ago(rng.uniform(20, 100), hour=18)
            person.push_since = None
            person.user.is_active = False
            person.user.save(update_fields=["is_active"])
        return people

    # Give the push users a browser subscription. The endpoints never resolve, so sending to them
    # fails at once without a network request.
    def _create_push_subscriptions(self, people: list[Person]) -> None:
        owners = [person for person in people if person.push_since is not None]
        subscriptions = PushSubscription.objects.bulk_create([
            PushSubscription(
                user=person.user,
                endpoint=f"https://push.invalid/demo/{uuid.uuid4().hex}",
                p256dh="demo",
                auth="demo",
                user_agent=self.rng.choice(USER_AGENTS),
            )
            for person in owners
        ])
        for subscription, person in zip(subscriptions, owners):
            subscription.created_at = person.push_since
        PushSubscription.objects.bulk_update(subscriptions, ["created_at"])

    # Surveys

    def _survey(
        self,
        author: User,
        title: str,
        structure: list[dict[str, Any]],
        *,
        status: str,
        description: str = "",
        mode: str = SurveyMode.ANONYMOUS,
        audience: list[Department] | None = None,
        published: datetime | None = None,
        starts: datetime | None = None,
        days: int = 7,
    ) -> Survey:
        survey = surveys.create_survey(author, title=title, description=description, mode=mode)
        surveys.save_structure(survey, structure)
        survey.audience_all = not audience
        survey.status = status
        survey.published_at = published
        survey.starts_at = starts
        begin = starts or published
        survey.ends_at = begin + timedelta(days=days) if begin else None
        survey.closed_at = survey.ends_at if status == SurveyStatus.CLOSED else None
        survey.save()
        if audience:
            survey.audience_departments.set(audience)
        Survey.objects.filter(pk=survey.pk).update(created_at=(published or self.now) - timedelta(days=2))
        return survey

    # Create every demo survey; return the number of surveys and of responses.
    def _create_surveys(self, people: list[Person], departments: dict[str, tuple[Department, int, float]]) -> tuple[int, int]:
        hr = next(person.user for person in people if person.user.username == "hr_demo")
        hr2 = next(person.user for person in people if person.user.username == "m.orlova")
        demo = next(person.user.id for person in people if person.user.username == "a.smirnova")
        division = {department.parent.name: department.parent for department, _, _ in departments.values()}
        title, description, enps = surveys.TEMPLATES["enps"]
        created = []
        responses = 0

        # Half a year of monthly eNPS surveys.
        for index, (mood, completion) in enumerate(ENPS_MONTHS):
            published = self._days_ago(172 - index * 30)
            survey = self._survey(
                hr,
                f"{title} · {MONTHS[published.month - 1]} {published.year}",
                enps,
                description=description,
                status=SurveyStatus.CLOSED,
                published=published,
            )
            responses += self._run(survey, people, completion, mood, done={demo})
            created.append(survey)

        # Surveys of one division, anonymous and identified.
        production = self._survey(
            hr2,
            "Условия труда на производстве",
            PRODUCTION_STRUCTURE,
            description="Опрос для цехов, склада и контроля качества: что мешает работать.",
            status=SurveyStatus.CLOSED,
            audience=[division["Производство"]],
            published=self._days_ago(66),
            days=10,
        )
        training = self._survey(
            hr2,
            "Обучение по охране труда",
            TRAINING_STRUCTURE,
            description="Ответы с указанием имени: по ним HR назначит повторное обучение.",
            mode=SurveyMode.IDENTIFIED,
            status=SurveyStatus.CLOSED,
            published=self._days_ago(38),
        )
        responses += self._run(production, people, 0.68, -0.3, departments=production.audience_departments.all())
        responses += self._run(training, people, 0.74, 0.2, done={demo})

        # Running surveys: the demo employee still has both of them to take.
        weekly = self._survey(
            hr,
            "Пульс недели: нагрузка и самочувствие",
            WEEKLY_STRUCTURE,
            description="Четыре коротких вопроса о прошедшей неделе.",
            status=SurveyStatus.ACTIVE,
            published=self._days_ago(2),
        )
        tools = self._survey(
            hr2,
            "Удобство рабочих инструментов",
            TOOLS_STRUCTURE,
            description="Ответы с указанием имени, чтобы ИТ могли уточнить детали.",
            mode=SurveyMode.IDENTIFIED,
            status=SurveyStatus.ACTIVE,
            audience=[division["ИТ"]],
            published=self._days_ago(1),
        )
        responses += self._run(weekly, people, 0.5, 0.0, pending={demo})
        responses += self._run(tools, people, 0.45, 0.4, departments=tools.audience_departments.all(), pending={demo})

        # The next eNPS survey waits for its start; two drafts wait for publishing.
        start = self._days_ago(-8)
        scheduled = self._survey(
            hr,
            f"{title} · {MONTHS[start.month - 1]} {start.year}",
            enps,
            description=description,
            status=SurveyStatus.SCHEDULED,
            published=self._days_ago(1),
            starts=start,
        )
        onboarding = self._survey(
            hr2,
            "Адаптация новых сотрудников",
            ONBOARDING_STRUCTURE,
            description="Для тех, кто пришёл в компанию за последние три месяца.",
            mode=SurveyMode.IDENTIFIED,
            status=SurveyStatus.DRAFT,
        )
        party = self._survey(hr, "Новогодний праздник: формат и пожелания", PARTY_STRUCTURE, status=SurveyStatus.DRAFT)
        created += [production, training, weekly, tools, scheduled, onboarding, party]
        return len(created), responses

    # Invite the audience of a published survey and play the notification cascade and the answers
    # of every participant. Return the number of responses.
    def _run(
        self,
        survey: Survey,
        people: list[Person],
        completion: float,
        mood: float,
        *,
        departments: Any = None,
        done: set[int] = frozenset(),
        pending: set[int] = frozenset(),
    ) -> int:
        rng = self.rng
        published = survey.published_at
        end = min(survey.ends_at, self.now)
        step = timedelta(minutes=survey.cascade_delay_minutes)
        allowed = None
        if departments is not None:
            allowed = set()
            for department in departments:
                allowed |= department.subtree_ids()

        nodes = surveys.build_nodes(survey)
        questions = {str(question.id): question for question in survey.questions.prefetch_related("options")}
        rows = []
        for person in people:
            user = person.user
            if not person.employed(published) or (allowed is not None and user.department_id not in allowed):
                continue

            channels = person.channels(published)
            sent_at = [published + step * index + timedelta(minutes=rng.randint(1, 4)) for index in range(len(channels))]
            completes = user.id in done or (user.id not in pending and rng.random() < completion + (0.08 if channels[0] == Channel.PUSH else -0.06))
            clicked_at, clicked_index = None, None
            if user.id not in pending and (completes or rng.random() < 0.06):
                for index, channel in enumerate(channels):
                    chance, low, high = REACTIONS[channel]
                    if index == len(channels) - 1 or rng.random() < chance:
                        clicked_index = index
                        clicked_at = sent_at[index] + timedelta(minutes=math.exp(rng.uniform(math.log(low), math.log(high))))
                        break
                if clicked_at >= end - timedelta(minutes=10):
                    clicked_at, clicked_index = None, None
            completed_at = clicked_at + timedelta(minutes=rng.randint(2, 9)) if clicked_at and completes else None
            rows.append((person, channels, sent_at, clicked_index, clicked_at, completed_at))

        participations = SurveyParticipation.objects.bulk_create([
            SurveyParticipation(
                survey=survey,
                user=person.user,
                department=person.user.department,
                opened_at=clicked_at,
                completed_at=completed_at,
                completed_channel=channels[clicked_index] if completed_at else "",
            )
            for person, channels, _, clicked_index, clicked_at, completed_at in rows
        ])
        dispatches = NotificationDispatch.objects.bulk_create([
            NotificationDispatch(
                participation=participation,
                status=DispatchStatus.DONE if row[4] else DispatchStatus.EXHAUSTED,
                step_index=len(row[1]),
            )
            for participation, row in zip(participations, rows)
        ])

        attempts, times = [], []
        survey_responses, answers = [], []
        for dispatch, (person, channels, sent_at, clicked_index, clicked_at, completed_at) in zip(dispatches, rows):
            for index, channel in enumerate(channels):
                if clicked_at is not None and sent_at[index] > clicked_at:
                    break
                attempts.append(NotificationAttempt(
                    dispatch=dispatch,
                    channel=channel,
                    status=AttemptStatus.SENT,
                    clicked_at=clicked_at if index == clicked_index else None,
                ))
                times.append(sent_at[index])

            if completed_at is None:
                continue
            response = SurveyResponse(
                survey=survey,
                user=person.user if survey.mode == SurveyMode.IDENTIFIED else None,
                department=person.user.department,
                submitted_on=timezone.localdate(completed_at),
                submitted_at=completed_at if survey.mode == SurveyMode.IDENTIFIED else None,
            )
            survey_responses.append(response)
            score = max(0, min(10, round(rng.gauss(7.6 + mood + person.mood, 1.6))))
            answers += [
                Answer(response=response, question=questions[key], **values)
                for key, values in self._walk(nodes, questions, score).items()
            ]

        NotificationAttempt.objects.bulk_create(attempts)
        for attempt, moment in zip(attempts, times):
            attempt.created_at = moment
        NotificationAttempt.objects.bulk_update(attempts, ["created_at"])
        SurveyResponse.objects.bulk_create(survey_responses)
        Answer.objects.bulk_create(answers)
        return len(survey_responses)

    # Walk the branching path with answers that follow the score from 0 to 10; return the stored
    # values of every answered question.
    def _walk(self, nodes: list[Any], questions: dict[str, Any], score: int) -> dict[str, dict[str, Any]]:
        positions = {node.key: index for index, node in enumerate(nodes)}
        given: dict[str, dict[str, Any]] = {}
        stored: dict[str, dict[str, Any]] = {}
        index: int | None = 0 if nodes else None
        while index is not None:
            node = nodes[index]
            values = self._answer(questions[node.key], score)
            given[node.key] = {
                "options": [str(option) for option in values["selected_options"]],
                "number": values["number"],
                "text": values["text"],
            }
            if values["selected_options"] or values["number"] is not None or values["text"]:
                stored[node.key] = values
            target = surveys.next_key(nodes, index, given[node.key])
            index = positions.get(target) if target is not None else None
        return stored

    # Return one answer. Options of single choice questions go from the best to the worst answer.
    def _answer(self, question: Any, score: int) -> dict[str, Any]:
        rng = self.rng
        mood = score / 10
        values: dict[str, Any] = {"selected_options": [], "number": None, "text": ""}
        options = [option.id for option in question.options.all()]

        if question.kind == QuestionKind.ENPS:
            values["number"] = score
        elif question.kind == QuestionKind.SCALE:
            if question.text in REVERSED_SCALES:
                mood = 1 - mood
            value = round(question.scale_min + mood * (question.scale_max - question.scale_min) + rng.gauss(0, 0.6))
            values["number"] = max(question.scale_min, min(question.scale_max, value))
        elif question.kind == QuestionKind.SINGLE:
            position = round((1 - mood) * (len(options) - 1) + rng.gauss(0, 0.8))
            values["selected_options"] = [options[max(0, min(len(options) - 1, position))]]
        elif question.kind == QuestionKind.MULTIPLE:
            weights = [len(options) - position for position in range(len(options))]
            chosen: list[int] = []
            for _ in range(rng.choice([1, 1, 2, 2, 3])):
                chosen.append(rng.choices(options, weights=weights)[0])
            values["selected_options"] = sorted(set(chosen), key=options.index)
        else:
            pool = TEXT_ANSWERS.get(question.text)
            if pool and (question.is_required or rng.random() < 0.55):
                values["text"] = rng.choice(pool)
        return values

    # Feedback

    def _create_feedback(self, people: list[Person]) -> int:
        demo = next(person.user for person in people if person.user.username == "a.smirnova")
        authors = [person.user for person in people if person.user.is_active and person.user.role == UserRole.EMPLOYEE]
        for days_ago, category, text, anonymous, status, reply, mine in FEEDBACK:
            created = self._days_ago(days_ago, hour=self.rng.randint(9, 18))
            Feedback.objects.create(
                author=None if anonymous else demo if mine else self.rng.choice(authors),
                is_anonymous=anonymous,
                category=category,
                text=text,
                status=status,
                reply=reply,
                created_on=timezone.localdate(created),
                created_at=None if anonymous else created,
                replied_at=created + timedelta(days=1) if reply else None,
            )
        return len(FEEDBACK)
