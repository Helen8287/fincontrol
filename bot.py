# bot.py

import asyncio
import logging
import os
import secrets
import sys

from datetime import timedelta
from decimal import Decimal, InvalidOperation

from dotenv import load_dotenv


# ============================================================
# Environment
# ============================================================

BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

load_dotenv(
    os.path.join(
        BASE_DIR,
        ".env",
    )
)

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "fincontrol.settings",
)


# ============================================================
# Django setup
# ============================================================

import django

django.setup()


# ============================================================
# Django imports
# ============================================================

from asgiref.sync import sync_to_async

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import close_old_connections, transaction
from django.db.models import Q, Sum
from django.utils import timezone


# ============================================================
# Finances imports
# ============================================================

from finances.models import (
    Category,
    Notification,
    TelegramLinkCode,
    Transaction,
    UserBudget,
    UserTelegram,
)

from finances.utils.defaults import (
    create_default_categories,
)

from finances.utils.recommendations import (
    RecommendationEngine,
)


# ============================================================
# Telegram imports
# ============================================================

from aiogram import (
    Bot,
    Dispatcher,
    html,
)

from aiogram.client.default import (
    DefaultBotProperties,
)

from aiogram.enums import (
    ParseMode,
)

from aiogram.filters import (
    Command,
    CommandObject,
    CommandStart,
)

from aiogram.types import (
    Message,
)


# ============================================================
# Logging
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s | "
        "%(levelname)s | "
        "%(name)s | "
        "%(message)s"
    ),
)

logger = logging.getLogger(
    "FinControlBot"
)


# ============================================================
# Constants
# ============================================================

MAX_DESCRIPTION_LENGTH = 255
MAX_CATEGORY_LENGTH = 100

DEFAULT_TRANSACTION_TYPE = "expense"

MAX_TRANSACTION_AMOUNT = Decimal(
    "99999999.99"
)

TELEGRAM_LINK_CODE_TTL = 300

PERIOD_NAMES = {
    "daily": "дневной",
    "weekly": "недельный",
    "monthly": "месячный",
    "yearly": "годовой",
}


# ============================================================
# Telegram token
# ============================================================

TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN"
)

if not TOKEN:
    raise RuntimeError(
        "Переменная окружения "
        "TELEGRAM_BOT_TOKEN отсутствует."
    )


# ============================================================
# Bot / Dispatcher
# ============================================================

bot = Bot(
    token=TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML,
    ),
)

dp = Dispatcher()

User = get_user_model()


# ============================================================
# Utility helpers
# ============================================================

def format_money(
    amount: Decimal,
) -> str:
    """
    Форматирует денежное значение.
    """

    return f"{amount:.2f}"


def safe_html(
    value,
) -> str:
    """
    Безопасно экранирует значение для Telegram HTML.
    """

    return html.quote(
        str(value)
    )


def validation_error_text(
    exc: ValidationError,
) -> str:
    """
    Преобразует Django ValidationError
    в понятный пользователю текст.
    """

    if getattr(
        exc,
        "message_dict",
        None,
    ):

        messages = []

        for field_messages in (
            exc.message_dict.values()
        ):

            if isinstance(
                field_messages,
                (list, tuple),
            ):

                messages.extend(
                    str(message)
                    for message in field_messages
                )

            else:

                messages.append(
                    str(field_messages)
                )

        if messages:
            return "\n".join(
                messages
            )

    if getattr(
        exc,
        "messages",
        None,
    ):

        return "\n".join(
            str(message)
            for message in exc.messages
        )

    return str(exc)


def normalize_amount(
    value: str,
) -> Decimal | None:
    """
    Преобразует строковое значение
    в Decimal.

    Поддерживает:

        500
        1250.50
        1250,50
        1 250,50
        1_250.50
    """

    normalized = (
        value
        .strip()
        .replace(" ", "")
        .replace("_", "")
        .replace(",", ".")
    )

    if not normalized:
        return None

    try:

        amount = Decimal(
            normalized
        )

    except (
        InvalidOperation,
        ValueError,
    ):

        return None

    if not amount.is_finite():
        return None

    return amount


# ============================================================
# Period helpers
# ============================================================

def get_period_start(
    period: str,
):
    """
    Возвращает начало текущего периода.

    daily: сегодня 00:00
    weekly: понедельник текущей недели 00:00
    monthly: первый день текущего месяца 00:00
    yearly: 1 января текущего года 00:00
    """

    now = timezone.now()

    start_of_today = now.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )

    if period == "daily":
        return start_of_today
    if period == "weekly":
        return (
            start_of_today
            - timedelta(
                days=now.weekday()
            )
        )

    if period == "monthly":

        return now.replace(
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )

    if period == "yearly":

        return now.replace(
            month=1,
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )

    raise ValueError(
        f"Неизвестный период бюджета: {period}"
    )


def get_period_end(
    period: str,
):
    """
    Возвращает начало следующего периода.
    """

    start = get_period_start(
        period
    )

    if period == "daily":
        return start + timedelta(
            days=1
        )

    if period == "weekly":
        return start + timedelta(
            days=7
        )

    if period == "monthly":

        if start.month == 12:

            return start.replace(
                year=start.year + 1,
                month=1,
                day=1,
            )

        return start.replace(
            month=start.month + 1,
            day=1,
        )

    if period == "yearly":

        return start.replace(
            year=start.year + 1,
            month=1,
            day=1,
        )

    raise ValueError(
        f"Неизвестный период бюджета: {period}"
    )


def get_report_start(
    period: str,
):
    """
    Возвращает начало периода отчёта.

    today:
        сегодня 00:00

    month:
        первый день текущего месяца 00:00
    """

    now = timezone.now()

    if period == "today":

        return now.replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )

    if period == "month":

        return now.replace(
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )

    raise ValueError(
        f"Неизвестный период отчёта: {period}"
    )


def get_report_end(
    period: str,
):
    """
    Возвращает начало следующего периода отчёта.
    """

    start = get_report_start(
        period
    )

    if period == "today":

        return start + timedelta(
            days=1
        )

    if period == "month":

        if start.month == 12:

            return start.replace(
                year=start.year + 1,
                month=1,
                day=1,
            )

        return start.replace(
            month=start.month + 1,
            day=1,
        )

    raise ValueError(
        f"Неизвестный период отчёта: {period}"
    )


# ============================================================
# Telegram link helpers
# ============================================================

def _consume_telegram_link_code(
    code: str,
):
    """
    Проверяет код привязки и возвращает user_id.

    ВАЖНО:
    код НЕ помечается использованным здесь.

    Он будет помечен использованным только после
    успешной привязки Telegram к пользователю.
    """

    close_old_connections()

    try:

        code = str(code).strip()

        if not code:
            return None

        with transaction.atomic():

            link_code = (
                TelegramLinkCode.objects
                .select_for_update()
                .filter(
                    code=code,
                    used_at__isnull=True,
                )
                .first()
            )

            if link_code is None:
                return None

            if link_code.is_expired():
                return None

            return link_code.user_id

    finally:

        close_old_connections()


consume_telegram_link_code = sync_to_async(
    _consume_telegram_link_code,
    thread_sensitive=True,
)


def _mark_link_code_used(
    code: str,
):
    """
    Помечает код привязки использованным.

    Операция выполняется атомарно.
    """

    close_old_connections()

    try:

        code = str(code).strip()

        if not code:
            return False

        with transaction.atomic():

            link_code = (
                TelegramLinkCode.objects
                .select_for_update()
                .filter(
                    code=code,
                    used_at__isnull=True,
                )
                .first()
            )

            if link_code is None:
                return False

            if link_code.is_expired():
                return False

            link_code.used_at = timezone.now()

            link_code.save(
                update_fields=[
                    "used_at",
                ]
            )

            return True

    finally:

        close_old_connections()


mark_link_code_used = sync_to_async(
    _mark_link_code_used,
    thread_sensitive=True,
)


def _create_telegram_link_code(
    user,
):
    """
    Создаёт одноразовый код привязки Telegram.
    """

    close_old_connections()

    try:

        for _ in range(5):

            code = secrets.token_urlsafe(
                32
            )

            try:

                return TelegramLinkCode.objects.create(
                    user=user,
                    code=code,
                    expires_at=(
                        timezone.now()
                        + timedelta(
                            seconds=TELEGRAM_LINK_CODE_TTL
                        )
                    ),
                )

            except Exception:

                # Крайне маловероятная коллизия.
                continue

        raise RuntimeError(
            "Не удалось создать уникальный "
            "код привязки Telegram."
        )

    finally:

        close_old_connections()


create_telegram_link_code = sync_to_async(
    _create_telegram_link_code,
    thread_sensitive=True,
)


# ============================================================
# User / Telegram helpers
# ============================================================

def _get_user_by_telegram_id(
    telegram_id: int,
):
    """
    Получает активного пользователя
    по Telegram ID.
    """

    close_old_connections()

    try:

        telegram_user = (
            UserTelegram.objects
            .select_related("user")
            .filter(
                telegram_id=str(
                    telegram_id
                ),
                is_active=True,
            )
            .first()
        )

        if telegram_user is None:
            return None

        return telegram_user.user

    finally:

        close_old_connections()


get_user_by_telegram_id = sync_to_async(
    _get_user_by_telegram_id,
    thread_sensitive=True,
)


def _link_telegram_user(
    user_id: int,
    telegram_id: int,
    username: str | None,
    first_name: str | None,
    last_name: str | None,
):
    """
    Привязывает Telegram к существующему Django User.

    Гарантирует:

    - один Telegram -> один Django User;
    - один Django User -> один Telegram.
    """

    close_old_connections()

    try:

        telegram_id = str(
            telegram_id
        )

        username = (
            username or ""
        ).strip()

        first_name = (
            first_name or ""
        ).strip()

        last_name = (
            last_name or ""
        ).strip()

        with transaction.atomic():

            user = (
                User.objects
                .select_for_update()
                .get(
                    pk=user_id
                )
            )

            existing_telegram = (
                UserTelegram.objects
                .select_for_update()
                .filter(
                    telegram_id=telegram_id
                )
                .first()
            )

            if (
                existing_telegram is not None
                and existing_telegram.user_id != user.id
            ):

                raise ValueError(
                    "Этот Telegram уже "
                    "привязан к другому пользователю."
                )

            telegram_user = (
                UserTelegram.objects
                .select_for_update()
                .filter(
                    user=user
                )
                .first()
            )

            if (
                telegram_user is not None
                and telegram_user.telegram_id != telegram_id
            ):

                raise ValueError(
                    "У пользователя уже "
                    "привязан другой Telegram."
                )

            if telegram_user is None:

                UserTelegram.objects.create(
                    user=user,
                    telegram_id=telegram_id,
                    telegram_username=username,
                    first_name=first_name,
                    last_name=last_name,
                    is_active=True,
                )

            else:

                telegram_user.telegram_username = (
                    username
                )

                telegram_user.first_name = (
                    first_name
                )

                telegram_user.last_name = (
                    last_name
                )

                telegram_user.is_active = True

                telegram_user.save(
                    update_fields=[
                        "telegram_username",
                        "first_name",
                        "last_name",
                        "is_active",
                        "updated_at",
                    ]
                )

            changed_user_fields = []

            if user.first_name != first_name:

                user.first_name = first_name

                changed_user_fields.append(
                    "first_name"
                )

            if user.last_name != last_name:

                user.last_name = last_name

                changed_user_fields.append(
                    "last_name"
                )

            if changed_user_fields:

                user.save(
                    update_fields=(
                        changed_user_fields
                    )
                )

            create_default_categories(
                user
            )

            return user

    finally:

        close_old_connections()


link_telegram_user = sync_to_async(
    _link_telegram_user,
    thread_sensitive=True,
)


def _create_telegram_user(
    telegram_id: int,
    username: str | None,
    first_name: str | None,
    last_name: str | None,
):
    """
    Создаёт или восстанавливает Telegram-пользователя.

    Связь:

        User
          |
          └── UserTelegram

    Благодаря OneToOneField:
        один Django User = один Telegram.
    """

    close_old_connections()

    try:

        telegram_id = str(
            telegram_id
        )

        username = (
            username or ""
        ).strip()

        first_name = (
            first_name or ""
        ).strip()

        last_name = (
            last_name or ""
        ).strip()

        with transaction.atomic():

            telegram_user = (
                UserTelegram.objects
                .select_for_update()
                .select_related("user")
                .filter(
                    telegram_id=telegram_id
                )
                .first()
            )

            # ------------------------------------------------
            # Telegram уже существует
            # ------------------------------------------------

            if telegram_user is not None:

                user = telegram_user.user

                telegram_user.telegram_username = (
                    username
                )

                telegram_user.first_name = (
                    first_name
                )

                telegram_user.last_name = (
                    last_name
                )

                telegram_user.is_active = True

                telegram_user.save(
                    update_fields=[
                        "telegram_username",
                        "first_name",
                        "last_name",
                        "is_active",
                        "updated_at",
                    ]
                )

                user_fields = []

                if user.first_name != first_name:

                    user.first_name = first_name

                    user_fields.append(
                        "first_name"
                    )

                if user.last_name != last_name:

                    user.last_name = last_name

                    user_fields.append(
                        "last_name"
                    )

                if user_fields:

                    user.save(
                        update_fields=user_fields
                    )

                create_default_categories(
                    user
                )

                return user

            # ------------------------------------------------
            # Новый Telegram
            # ------------------------------------------------

            username_db = (
                f"tg_{telegram_id}"
            )

            user = (
                User.objects
                .filter(
                    username=username_db
                )
                .first()
            )

            if user is None:

                user = User.objects.create(
                    username=username_db,
                    first_name=first_name,
                    last_name=last_name,
                )

            else:

                user_fields = []

                if user.first_name != first_name:

                    user.first_name = first_name

                    user_fields.append(
                        "first_name"
                    )

                if user.last_name != last_name:

                    user.last_name = last_name

                    user_fields.append(
                        "last_name"
                    )

                if user_fields:

                    user.save(
                        update_fields=user_fields
                    )

            try:

                UserTelegram.objects.create(
                    user=user,
                    telegram_id=telegram_id,
                    telegram_username=username,
                    first_name=first_name,
                    last_name=last_name,
                    is_active=True,
                )

            except Exception:

                # Если запись появилась конкурентно,
                # пробуем получить её.
                telegram_user = (
                    UserTelegram.objects
                    .select_related("user")
                    .filter(
                        telegram_id=telegram_id
                    )
                    .first()
                )

                if telegram_user is None:
                    raise

                user = telegram_user.user

            create_default_categories(
                user
            )

            logger.info(
                "Telegram пользователь подключён: %s",
                telegram_id,
            )

            return user

    finally:

        close_old_connections()


create_telegram_user = sync_to_async(
    _create_telegram_user,
    thread_sensitive=True,
)


# ============================================================
# Category helpers
# ============================================================

def _find_category_from_input(
    user,
    text: str,
    category_type: str = DEFAULT_TRANSACTION_TYPE,
):
    """
    Ищет категорию в начале строки.

    Примеры:

        Еда Обед
        Кафе и рестораны Ужин
        Коммунальные услуги Свет

    Выбирается самая длинная подходящая категория.

    Пользовательская категория имеет приоритет
    над глобальной.
    """

    close_old_connections()

    try:

        text = (
            text or ""
        ).strip()

        if not text:
            return None, ""

        categories = list(
            Category.objects
            .filter(
                type=category_type,
            )
            .filter(
                Q(user=user)
                |
                Q(user__isnull=True)
            )
        )

        categories.sort(
            key=lambda category: (
                category.user_id != user.id,
                -len(
                    category.name.strip()
                ),
            )
        )

        text_casefold = text.casefold()

        for category in categories:

            category_name = (
                category.name.strip()
            )

            if not category_name:
                continue

            category_casefold = (
                category_name.casefold()
            )

            if text_casefold == category_casefold:

                return category, ""

            prefix = (
                category_casefold
                + " "
            )

            if text_casefold.startswith(
                prefix
            ):

                description = text[
                    len(category_name):
                ].strip()

                return (
                    category,
                    description,
                )

        return None, text

    finally:

        close_old_connections()


find_category_from_input = sync_to_async(
    _find_category_from_input,
    thread_sensitive=True,
)


# ============================================================
# Report helpers
# ============================================================

def _calculate_report(
    user,
    period: str,
):
    """
    Рассчитывает доходы, расходы и баланс
    за указанный период.
    """

    close_old_connections()

    try:

        start = get_report_start(
            period
        )

        end = get_report_end(
            period
        )

        queryset = (
            Transaction.objects
            .filter(
                user=user,
                date__gte=start,
                date__lt=end,
            )
        )

        income = (
            queryset
            .filter(
                type="income"
            )
            .aggregate(
                total=Sum("amount")
            )
            .get("total")
            or Decimal("0")
        )

        expense = (
            queryset
            .filter(
                type="expense"
            )
            .aggregate(
                total=Sum("amount")
            )
            .get("total")
            or Decimal("0")
        )

        return (
            income,
            expense,
            income - expense,
        )

    finally:

        close_old_connections()


calculate_report = sync_to_async(
    _calculate_report,
    thread_sensitive=True,
)


def _make_report_sync(user, period: str):
    """Sync-версия формирования отчёта."""
    close_old_connections()
    try:
        income, expense, balance = _calculate_report(user, period)
        title = "Сегодня" if period == "today" else "Текущий месяц"

        return (
            f"📊 <b>Отчёт — {title}</b>\n"
            f"━━━━━━━━━━━━━━\n"
            f"💰 Доходы: {format_money(income)} руб.\n"
            f"💸 Расходы: {format_money(expense)} руб.\n"
            f"📈 Баланс: {format_money(balance)} руб.\n"
            f"━━━━━━━━━━━━━━"
        )
    finally:
        close_old_connections()


make_report = sync_to_async(_make_report_sync, thread_sensitive=True)


def _get_period_transactions(
    user,
    period: str = "month",
):
    """
    Получает материализованный список транзакций
    за конкретный период.
    """

    close_old_connections()

    try:

        start = get_report_start(
            period
        )

        end = get_report_end(
            period
        )

        return list(
            Transaction.objects
            .filter(
                user=user,
                date__gte=start,
                date__lt=end,
            )
            .select_related(
                "category"
            )
            .order_by(
                "-date"
            )
        )

    finally:

        close_old_connections()


get_period_transactions = sync_to_async(
    _get_period_transactions,
    thread_sensitive=True,
)


# ============================================================
# Budget helpers
# ============================================================

def get_budget_spent(
    user,
    budget,
    *,
    exclude_transaction_id=None,
):
    """
    Возвращает сумму расходов за текущий период бюджета.

    Учитывается:
        start <= date < end

    Для категориального бюджета:
        только соответствующая категория.

    Вызывается только из sync-контекста.
    """

    start = get_period_start(
        budget.period
    )

    end = get_period_end(
        budget.period
    )

    query = (
        Transaction.objects
        .filter(
            user=user,
            type="expense",
            date__gte=start,
            date__lt=end,
        )
    )

    if not budget.is_global:

        query = query.filter(
            category_id=budget.category_id
        )

    if exclude_transaction_id is not None:

        query = query.exclude(
            pk=exclude_transaction_id
        )

    return (
        query
        .aggregate(
            total=Sum("amount")
        )
        .get("total")
        or Decimal("0")
    )


def create_budget_notification(
    user,
    budget,
    new_transaction,
):
    """
    Проверяет переход через лимит.

    Уведомление создаётся, если:

        до операции < лимит
        после операции >= лимит

    То есть пользователь получает уведомление
    ровно в момент достижения/перехода лимита.

    Вызывается только из sync-контекста.
    """

    if budget.is_global is False:

        if (
            budget.category_id
            != new_transaction.category_id
        ):

            return False

    spent_after = get_budget_spent(
        user,
        budget,
    )

    spent_before = get_budget_spent(
        user,
        budget,
        exclude_transaction_id=(
            new_transaction.id
        ),
    )

    crossed_limit = (
        spent_before < budget.amount
        and spent_after >= budget.amount
    )

    if not crossed_limit:
        return False

    if budget.is_global:

        title = "Общий бюджет"

    else:

        title = (
            budget.category.name
            if budget.category_id
            else "Категория"
        )

    period_title = PERIOD_NAMES.get(
        budget.period,
        budget.period,
    )

    Notification.objects.create(
        user=user,
        type="warning",
        message=(
            "⚠️ Превышен бюджет\n\n"
            f"Категория: {title}\n"
            f"Период: {period_title}\n"
            f"Лимит: "
            f"{format_money(budget.amount)}\n"
            f"Потрачено: "
            f"{format_money(spent_after)}"
        ),
    )

    logger.info(
        "Бюджет достигнут пользователем %s: "
        "%s, %s",
        user.id,
        period_title,
        title,
    )

    return True


# ============================================================
# Transaction creation
# ============================================================

def _create_transaction_with_budget_check(
    user,
    amount: Decimal,
    category,
    description: str = "",
):
    """
    Создаёт транзакцию и проверяет бюджеты.

    Вся работа с Django ORM выполняется
    в одном sync-контексте.
    """

    close_old_connections()

    try:

        with transaction.atomic():

            # ------------------------------------------------
            # Дополнительная защита входных данных
            # ------------------------------------------------

            if amount <= 0:

                raise ValidationError(
                    {
                        "amount": (
                            "Сумма должна быть "
                            "больше нуля."
                        )
                    }
                )

            if amount > MAX_TRANSACTION_AMOUNT:

                raise ValidationError(
                    {
                        "amount": (
                            "Сумма слишком большая."
                        )
                    }
                )

            if (
                amount.as_tuple().exponent
                < -2
            ):

                raise ValidationError(
                    {
                        "amount": (
                            "Сумма может содержать "
                            "не более 2 знаков "
                            "после запятой."
                        )
                    }
                )

            if category is None:

                raise ValidationError(
                    {
                        "category": (
                            "Категория не указана."
                        )
                    }
                )

            if category.type not in (
                "income",
                "expense",
            ):

                raise ValidationError(
                    {
                        "category": (
                            "Некорректный тип категории."
                        )
                    }
                )

            # ------------------------------------------------
            # Проверяем принадлежность категории
            # ------------------------------------------------

            category_is_allowed = (
                category.user_id == user.id
                or category.user_id is None
            )

            if not category_is_allowed:

                raise ValidationError(
                    {
                        "category": (
                            "Категория принадлежит "
                            "другому пользователю."
                        )
                    }
                )

            # ------------------------------------------------
            # Создание операции
            # ------------------------------------------------

            new_transaction = Transaction(
                user=user,
                amount=amount,
                type=category.type,
                category=category,
                description=(
                    description or ""
                ),
                date=timezone.now(),
            )

            new_transaction.full_clean()

            new_transaction.save()

            # ------------------------------------------------
            # Расходы -> бюджеты
            # ------------------------------------------------

            if new_transaction.type == "expense":

                category_budgets = list(
                    UserBudget.objects
                    .select_related(
                        "category"
                    )
                    .filter(
                        user=user,
                        category_id=(
                            new_transaction.category_id
                        ),
                        is_global=False,
                    )
                    .order_by(
                        "period"
                    )
                )

                global_budgets = list(
                    UserBudget.objects
                    .filter(
                        user=user,
                        is_global=True,
                    )
                    .order_by(
                        "period"
                    )
                )

                for budget in (
                    category_budgets
                ):

                    create_budget_notification(
                        user=user,
                        budget=budget,
                        new_transaction=(
                            new_transaction
                        ),
                    )

                for budget in (
                    global_budgets
                ):

                    create_budget_notification(
                        user=user,
                        budget=budget,
                        new_transaction=(
                            new_transaction
                        ),
                    )

            logger.info(
                "Создана операция %s "
                "для пользователя %s",
                new_transaction.id,
                user.id,
            )

            return new_transaction

    finally:

        close_old_connections()


create_transaction_with_budget_check = (
    sync_to_async(
        _create_transaction_with_budget_check,
        thread_sensitive=True,
    )
)


# ============================================================
# /start
# ============================================================

@dp.message(
    CommandStart()
)
async def start_command(
    message: Message,
    command: CommandObject,
):

    if message.from_user is None:
        return

    # --------------------------------------------------------
    # Deep-link:
    #
    # /start <code>
    # --------------------------------------------------------

    if command.args:

        code = command.args.strip()

        user_id = (
            await consume_telegram_link_code(
                code
            )
        )

        if user_id is None:

            await message.answer(
                "❌ Код привязки недействителен, "
                "истёк или уже использован."
            )

            return

        try:

            user = await link_telegram_user(
                user_id=user_id,
                telegram_id=(
                    message.from_user.id
                ),
                username=(
                    message.from_user.username
                ),
                first_name=(
                    message.from_user.first_name
                ),
                last_name=(
                    message.from_user.last_name
                ),
            )

            code_marked = (
                await mark_link_code_used(
                    code
                )
            )

            if not code_marked:

                logger.warning(
                    "Не удалось пометить код "
                    "привязки использованным: %s",
                    code,
                )

        except ValueError as exc:

            logger.warning(
                "Ошибка привязки Telegram ID %s: %s",
                message.from_user.id,
                exc,
            )

            await message.answer(
                "❌ Не удалось привязать Telegram.\n\n"
                f"{safe_html(exc)}"
            )

            return

        except Exception:

            logger.exception(
                "Ошибка deep-link привязки "
                "Telegram ID %s",
                message.from_user.id,
            )

            await message.answer(
                "❌ Не удалось выполнить привязку."
            )

            return

        display_name = (
            user.first_name
            or getattr(
                user,
                "username",
                None,
            )
            or "пользователь"
        )

        await message.answer(
            "✅ <b>Telegram успешно привязан!</b>\n\n"
            f"Привет, "
            f"<b>{safe_html(display_name)}</b>!\n\n"
            "Теперь FinControl подключён."
        )

        return

    # --------------------------------------------------------
    # Обычный /start
    # --------------------------------------------------------

    user = await get_user_by_telegram_id(
        message.from_user.id
    )

    if user is None:

        await message.answer(
            "👋 Добро пожаловать "
            "в FinControl!\n\n"
            "Ваш Telegram ещё "
            "не подключён.\n\n"
            "Используйте команду:\n"
            "<b>/register</b>"
        )

        return

    display_name = (
        user.first_name
        or getattr(
            user,
            "username",
            None,
        )
        or "пользователь"
    )

    await message.answer(
        "👋 Привет, "
        f"<b>{safe_html(display_name)}</b>!\n\n"
        "💰 FinControl готов работать.\n\n"
        "<b>Команды:</b>\n"
        "/add — добавить операцию\n"
        "/today — отчёт за сегодня\n"
        "/month — отчёт за месяц\n"
        "/report — отчёт + советы\n"
        "/help — помощь"
    )


# ============================================================
# /register
# ============================================================

@dp.message(
    Command("register")
)
async def register_command(
    message: Message,
):

    if message.from_user is None:
        return

    try:

        user = await create_telegram_user(
            telegram_id=(
                message.from_user.id
            ),
            username=(
                message.from_user.username
            ),
            first_name=(
                message.from_user.first_name
            ),
            last_name=(
                message.from_user.last_name
            ),
        )

    except Exception:

        logger.exception(
            "Ошибка регистрации "
            "Telegram ID %s",
            message.from_user.id,
        )

        await message.answer(
            "❌ Не удалось завершить "
            "регистрацию.\n"
            "Попробуйте ещё раз позже."
        )

        return

    display_name = (
        user.first_name
        or "пользователь"
    )

    await message.answer(
        "✅ <b>Регистрация завершена!</b>\n\n"
        f"Привет, "
        f"<b>{safe_html(display_name)}</b>!\n\n"
        "Теперь FinControl подключён.\n\n"
        "Попробуйте добавить расход:\n"
        "<code>500 Еда Обед</code>"
    )


# ============================================================
# /help
# ============================================================

@dp.message(
    Command("help")
)
async def help_command(
    message: Message,
):

    await message.answer(
        "<b>FinControl</b>\n\n"

        "<b>Команды:</b>\n"
        "/start — запуск бота\n"
        "/register — регистрация\n"
        "/add — добавить операцию\n"
        "/today — отчёт за сегодня\n"
        "/month — отчёт за текущий месяц\n"
        "/report — отчёт + финансовые советы\n"
        "/help — помощь\n\n"

        "<b>Быстрый ввод расхода:</b>\n\n"
        "<code>500 Еда Обед</code>\n\n"

        "где:\n"
        "500 — сумма\n"
        "Еда — категория\n"
        "Обед — описание\n\n"

        "Быстрый ввод через Telegram "
        "создаёт расход."
    )


# ============================================================
# /add
# ============================================================

@dp.message(
    Command("add")
)
async def add_command(
    message: Message,
):

    await message.answer(
        "Введите операцию:\n\n"
        "<code>500 Еда Обед</code>\n\n"

        "Формат:\n"
        "<b>сумма категория описание</b>\n\n"

        "Например:\n"
        "<code>1250 Продукты Магазин</code>"
    )


# ============================================================
# /today
# ============================================================

@dp.message(
    Command("today")
)
async def today_command(
    message: Message,
):

    if message.from_user is None:
        return

    user = await get_user_by_telegram_id(
        message.from_user.id
    )

    if user is None:

        await message.answer(
            "❌ Сначала выполните "
            "/register"
        )

        return

    try:

        report = await make_report(
            user,
            "today",
        )

        await message.answer(
            report
        )

    except Exception:

        logger.exception(
            "Ошибка формирования "
            "отчёта за сегодня "
            "для пользователя %s",
            user.id,
        )

        await message.answer(
            "❌ Не удалось сформировать "
            "отчёт."
        )


# ============================================================
# /month
# ============================================================

@dp.message(
    Command("month")
)
async def month_command(
    message: Message,
):

    if message.from_user is None:
        return

    user = await get_user_by_telegram_id(
        message.from_user.id
    )

    if user is None:

        await message.answer(
            "❌ Сначала выполните "
            "/register"
        )

        return

    try:

        report = await make_report(
            user,
            "month",
        )

        await message.answer(
            report
        )

    except Exception:

        logger.exception(
            "Ошибка формирования "
            "месячного отчёта "
            "для пользователя %s",
            user.id,
        )

        await message.answer(
            "❌ Не удалось сформировать "
            "отчёт."
        )


# ============================================================
# /report
# ============================================================

def _build_recommendations_report(
    user,
):
    """
    Sync helper для /report.

    ORM и RecommendationEngine работают
    в одном sync-контексте.
    """

    close_old_connections()

    try:

        transactions = list(
            Transaction.objects
            .filter(
                user=user,
                date__gte=get_report_start(
                    "month"
                ),
                date__lt=get_report_end(
                    "month"
                ),
            )
            .select_related(
                "category"
            )
            .order_by(
                "-date"
            )
        )

        (
            income,
            expense,
            balance,
        ) = _calculate_report(
            user,
            "month",
        )

        recommendations = (
            RecommendationEngine
            .get_recommendations(
                transactions
            )
        )

        report = (
            "📊 <b>Отчёт — Текущий месяц</b>\n"
            "━━━━━━━━━━━━━━\n"
            f"💰 Доходы: "
            f"{format_money(income)} руб.\n"
            f"💸 Расходы: "
            f"{format_money(expense)} руб.\n"
            f"📈 Баланс: "
            f"{format_money(balance)} руб.\n"
            "━━━━━━━━━━━━━━"
        )

        if recommendations:

            report += (
                "\n\n"
                "💡 <b>Советы:</b>\n"
            )

            for item in recommendations[:3]:

                report += (
                    "\n• "
                    f"{safe_html(item)}"
                )

        return report

    finally:

        close_old_connections()


build_recommendations_report = sync_to_async(
    _build_recommendations_report,
    thread_sensitive=True,
)


@dp.message(
    Command("report")
)
async def report_command(
    message: Message,
):

    if message.from_user is None:
        return

    user = await get_user_by_telegram_id(
        message.from_user.id
    )

    if user is None:

        await message.answer(
            "❌ Сначала выполните "
            "/register"
        )

        return

    try:

        report = (
            await build_recommendations_report(
                user
            )
        )

        await message.answer(
            report
        )

    except Exception:

        logger.exception(
            "Ошибка формирования "
            "полного отчёта "
            "для пользователя %s",
            user.id,
        )

        await message.answer(
            "❌ Не удалось сформировать "
            "отчёт."
        )


# ============================================================
# Fast transaction input
# ============================================================

@dp.message()
async def add_transaction_text(
    message: Message,
):
    """
    Быстрый ввод:

        500 Еда Обед

    Создаёт расход.
    """

    if message.from_user is None:
        return

    if not message.text:
        return

    text = message.text.strip()

    if not text:
        return

    # --------------------------------------------------------
    # Команды
    # --------------------------------------------------------

    if text.startswith("/"):
        return

    # --------------------------------------------------------
    # Пользователь
    # --------------------------------------------------------

    user = await get_user_by_telegram_id(
        message.from_user.id
    )

    if user is None:

        await message.answer(
            "❌ Пользователь не найден.\n"
            "Сначала выполните "
            "/register"
        )

        return

    # --------------------------------------------------------
    # Разбор суммы
    # --------------------------------------------------------

    parts = text.split(
        maxsplit=1
    )

    if len(parts) < 2:

        await message.answer(
            "❌ Неверный формат.\n\n"
            "Используйте:\n"
            "<code>500 Еда Обед</code>"
        )

        return

    amount_text = (
        parts[0].strip()
    )

    operation_text = (
        parts[1].strip()
    )

    if not operation_text:

        await message.answer(
            "❌ Укажите категорию."
        )

        return

    # --------------------------------------------------------
    # Decimal
    # --------------------------------------------------------

    amount = normalize_amount(
        amount_text
    )

    if amount is None:

        await message.answer(
            "❌ Неверный формат суммы.\n\n"
            "Например:\n"
            "<code>500</code>\n"
            "<code>1250.50</code>\n"
            "<code>1250,50</code>"
        )

        return

    if amount <= 0:

        await message.answer(
            "❌ Сумма должна быть "
            "больше нуля."
        )

        return

    if (
        amount.as_tuple().exponent
        < -2
    ):

        await message.answer(
            "❌ Сумма может содержать "
            "не более 2 знаков "
            "после запятой."
        )

        return

    if amount > MAX_TRANSACTION_AMOUNT:

        await message.answer(
            "❌ Сумма слишком большая.\n"
            "Максимум: "
            f"{format_money(MAX_TRANSACTION_AMOUNT)} руб."
        )

        return

    # --------------------------------------------------------
    # Категория
    # --------------------------------------------------------

    category, description = (
        await find_category_from_input(
            user=user,
            text=operation_text,
            category_type=(
                DEFAULT_TRANSACTION_TYPE
            ),
        )
    )

    if category is None:

        safe_operation_text = (
            safe_html(operation_text)
        )

        await message.answer(
            "❌ Категория "
            f"<b>{safe_operation_text}</b> "
            "не найдена.\n\n"
            "Пример:\n"
            "<code>500 Еда Обед</code>\n"
            "<code>1500 Кафе и рестораны Ужин</code>"
        )

        return

    # --------------------------------------------------------
    # Категория
    # --------------------------------------------------------

    category_name = (
        category.name.strip()
    )

    if len(category_name) > (
        MAX_CATEGORY_LENGTH
    ):

        await message.answer(
            "❌ Название категории "
            "слишком длинное."
        )

        return

    # --------------------------------------------------------
    # Description
    # --------------------------------------------------------

    if len(description) > (
        MAX_DESCRIPTION_LENGTH
    ):

        await message.answer(
            "❌ Описание слишком "
            "длинное.\n"
            f"Максимум: "
            f"{MAX_DESCRIPTION_LENGTH} "
            "символов."
        )

        return

    # --------------------------------------------------------
    # Создание транзакции
    # --------------------------------------------------------

    try:

        new_transaction = (
            await create_transaction_with_budget_check(
                user=user,
                amount=amount,
                category=category,
                description=description,
            )
        )

    except ValidationError as exc:

        logger.warning(
            "Ошибка валидации операции "
            "пользователя %s: %s",
            user.id,
            exc,
        )

        await message.answer(
            "❌ Операция не создана.\n\n"
            f"{safe_html(validation_error_text(exc))}"
        )

        return

    except Exception:

        logger.exception(
            "Ошибка создания операции "
            "для пользователя %s",
            user.id,
        )

        await message.answer(
            "❌ Не удалось создать "
            "операцию.\n"
            "Попробуйте ещё раз."
        )

        return

    # --------------------------------------------------------
    # Ответ
    # --------------------------------------------------------

    amount_text_safe = safe_html(
        format_money(
            new_transaction.amount
        )
    )

    category_text_safe = safe_html(
        category.name
    )

    description_text_safe = safe_html(
        new_transaction.description
        or "нет"
    )

    await message.answer(
        "✅ <b>Операция добавлена</b>\n\n"
        f"💰 Сумма: "
        f"{amount_text_safe} руб.\n"
        f"📂 Категория: "
        f"{category_text_safe}\n"
        f"📝 Описание: "
        f"{description_text_safe}"
    )


# ============================================================
# Main
# ============================================================

async def main():
    """
    Запуск Telegram-бота.
    """

    logger.info(
        "FinControl Telegram bot started"
    )

    try:

        await bot.delete_webhook(
            drop_pending_updates=True
        )

        await dp.start_polling(
            bot
        )

    except Exception:

        logger.exception(
            "Критическая ошибка "
            "Telegram-бота"
        )

        raise

    finally:

        await bot.session.close()


# ============================================================
# Entry point
# ============================================================

if __name__ == "__main__":

    try:

        asyncio.run(
            main()
        )

    except KeyboardInterrupt:

        logger.info(
            "Bot stopped"
        )