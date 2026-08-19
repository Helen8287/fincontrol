# finances/cron.py
from datetime import timedelta
from decimal import Decimal

import requests

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Sum
from django.utils import timezone

from .models import Notification, Transaction, UserBudget

User = get_user_model()



# ============================================================
# TELEGRAM
# ============================================================

def _send_telegram_message(telegram_id, message):
    """
    Отправляет сообщение через Telegram Bot API.

    Токен берётся из settings.py:
        TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    """

    token = getattr(
        settings,
        "TELEGRAM_BOT_TOKEN",
        None,
    )

    if not token:
        print(
            "ERROR: TELEGRAM_BOT_TOKEN не найден."
        )
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": telegram_id, "text": message}

    try:
        response = requests.post(
            url,
            json=payload,
            timeout=10,
        )

        if response.status_code == 200:
            return True

        if response.status_code == 403:
            print(f"Бот заблокирован пользователем {telegram_id}")
            # Деактивируем аккаунт
            from .models import UserTelegram
            UserTelegram.objects.filter(
                telegram_id=str(telegram_id)
            ).update(is_active=False)
            return False

        print(
            f"Telegram API error: "
            f"{response.status_code} "
            f"{response.text}"
        )

        return False

    except requests.RequestException as error:
        print(
            f"Ошибка отправки сообщения "
            f"в Telegram: {error}"
        )
        return False




# ============================================================
# DAILY REPORTS
# ============================================================

def send_daily_reports():
    """Отправляет пользователям ежедневный отчёт."""

    today = timezone.localdate()

    users = (
        User.objects
        .filter(
            telegram_account__is_active=True,
        )
        .select_related("telegram_account")
    )

    for user in users:
        try:
            telegram = user.telegram_account

            if not telegram.telegram_id:
                continue

            transactions = Transaction.objects.filter(
                user=user,
                date__date=today,
            )

            income = (
                transactions
                .filter(type="income")
                .aggregate(total=Sum("amount"))
                .get("total")
                or Decimal("0")
            )

            expense = (
                transactions
                .filter(type="expense")
                .aggregate(total=Sum("amount"))
                .get("total")
                or Decimal("0")
            )

            balance = income - expense

            message = (
                "📊 Ежедневный отчёт\n\n"
                f"📅 Дата: {today.strftime('%d.%m.%Y')}\n\n"
                f"💰 Доходы: {income:.2f} руб.\n"
                f"💸 Расходы: {expense:.2f} руб.\n"
                f"📈 Баланс: {balance:.2f} руб."
            )

            success = _send_telegram_message(
                telegram.telegram_id,
                message,
            )

            if not success:
                print(
                    f"Не удалось отправить ежедневный "
                    f"отчёт пользователю {user.username}"
                )

        except Exception as error:
            print(
                f"Ошибка ежедневного отчёта "
                f"для {user.username}: {error}"
            )


# ============================================================
# WEEKLY REPORTS
# ============================================================

def send_weekly_reports():
    """Отправляет пользователям еженедельный отчёт."""

    today = timezone.localdate()

    # 7 дней включая сегодняшний
    week_start = today - timedelta(days=6)

    users = (
        User.objects
        .filter(
            telegram_account__is_active=True,
        )
        .select_related("telegram_account")
    )

    for user in users:
        try:
            telegram = user.telegram_account

            if not telegram.telegram_id:
                continue

            transactions = Transaction.objects.filter(
                user=user,
                date__date__gte=week_start,
                date__date__lte=today,
            )

            income = (
                transactions
                .filter(type="income")
                .aggregate(total=Sum("amount"))
                .get("total")
                or Decimal("0")
            )

            expense = (
                transactions
                .filter(type="expense")
                .aggregate(total=Sum("amount"))
                .get("total")
                or Decimal("0")
            )

            balance = income - expense

            message = (
                "📊 Еженедельный отчёт\n\n"
                f"📅 Период: "
                f"{week_start.strftime('%d.%m.%Y')} — "
                f"{today.strftime('%d.%m.%Y')}\n\n"
                f"💰 Доходы: {income:.2f} руб.\n"
                f"💸 Расходы: {expense:.2f} руб.\n"
                f"📈 Баланс: {balance:.2f} руб."
            )

            success = _send_telegram_message(
                telegram.telegram_id,
                message,
            )

            if not success:
                print(
                    f"Не удалось отправить еженедельный "
                    f"отчёт пользователю {user.username}"
                )

        except Exception as error:
            print(
                f"Ошибка еженедельного отчёта "
                f"для {user.username}: {error}"
            )


# ============================================================
# BUDGETS
# ============================================================

def check_budgets():
    """Проверяет пользовательские бюджеты."""

    budgets = (
        UserBudget.objects
        .select_related(
            "user",
            "category",
        )
        .all()
    )

    for budget in budgets:

        try:

            start = budget._get_period_start()

            transactions = Transaction.objects.filter(
                user=budget.user,
                type="expense",
                date__gte=start,
            )

            if not budget.is_global:

                transactions = transactions.filter(
                    category_id=budget.category_id
                )

            spent = (
                transactions
                .aggregate(
                    total=Sum("amount")
                )
                .get("total")
                or Decimal("0")
            )

            if budget.amount <= 0:
                continue

            percentage = (spent / budget.amount) * Decimal("100")

            if percentage < Decimal("80"):
                continue

            category_name = "Общий бюджет" if budget.is_global else budget.category.name

            message = (
                f"⚠️ Бюджет почти исчерпан!\n\n"
                f"📁 Категория: {category_name}\n"
                f"💰 Лимит: {budget.amount:.2f} руб.\n"
                f"💸 Потрачено: {spent:.2f} руб.\n"
                f"📊 Использовано: {percentage:.0f}%"
            )

            # Проверяем, существует ли уже такое уведомление
            exists = Notification.objects.filter(
                user=budget.user,
                message=message,
                is_read=False,
            ).exists()

            if not exists:
                Notification.objects.create(
                    user=budget.user,
                    message=message,
                    type="warning",
                )

        except Exception as error:
            print(f"Ошибка проверки бюджета {budget.id}: {error}")

# ============================================================
# MAIN
# ============================================================

def run_cron_tasks():
    """
    Запускает все фоновые задачи.
    """

    print("Запуск фоновых задач...")

    try:
        send_daily_reports()
    except Exception as error:
        print(
            f"Ошибка send_daily_reports: {error}"
        )

    try:
        send_weekly_reports()
    except Exception as error:
        print(
            f"Ошибка send_weekly_reports: {error}"
        )

    try:
        check_budgets()
    except Exception as error:
        print(
            f"Ошибка check_budgets: {error}"
        )

    print("Фоновые задачи завершены.")