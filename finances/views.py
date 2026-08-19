import os
import json
import secrets

from datetime import datetime, timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import (
    CategoryForm,
    TransactionForm,
    UserRegistrationForm,
)

from .models import (
    Category,
    Notification,
    SavedReport,
    Transaction,
    UserBudget,
    UserTelegram,
)

from .utils.analytics import AnalyticsEngine
from .utils.defaults import create_default_categories
from .utils.recommendations import RecommendationEngine


# ============================================================
# TELEGRAM LINK
# ============================================================

TELEGRAM_LINK_CODE_TTL = 300  # 5 минут


@login_required
@require_POST
def create_telegram_link(request):
    """
    Создаёт одноразовый код для привязки Telegram.
    """

    code = secrets.token_urlsafe(32)

    cache_key = (
        f"telegram_link:{code}"
    )

    cache.set(
        cache_key,
        request.user.id,
        timeout=TELEGRAM_LINK_CODE_TTL,
    )

    bot_username = os.getenv(
        "TELEGRAM_BOT_USERNAME",
        "",
    ).strip()

    if not bot_username:

        cache.delete(
            cache_key
        )

        return JsonResponse(
            {
                "success": False,
                "error": (
                    "TELEGRAM_BOT_USERNAME "
                    "не настроен."
                ),
            },
            status=500,
        )

    telegram_url = (
        f"https://t.me/{bot_username}"
        f"?start={code}"
    )

    return JsonResponse(
        {
            "success": True,
            "code": code,
            "url": telegram_url,
            "expires_in": TELEGRAM_LINK_CODE_TTL,
        }
    )


# ============================================================
# AUTHENTICATION
# ============================================================

def register_view(request):
    """Регистрация нового пользователя."""

    if request.method == "POST":
        form = UserRegistrationForm(request.POST)

        if form.is_valid():
            user = form.save()

            create_default_categories(user)

            login(request, user)

            messages.success(
                request,
                "Регистрация успешно завершена!"
            )

            return redirect(
                "finances:dashboard"
            )

    else:
        form = UserRegistrationForm()

    return render(
        request,
        "finances/register.html",
        {
            "form": form,
        },
    )


def login_view(request):
    """Авторизация пользователя."""

    if request.method == "POST":

        username = request.POST.get(
            "username",
            "",
        ).strip()

        password = request.POST.get(
            "password",
            "",
        )

        user = authenticate(
            request,
            username=username,
            password=password,
        )

        if user is not None:

            login(
                request,
                user,
            )

            return redirect(
                "finances:dashboard"
            )

        messages.error(
            request,
            "Неверное имя пользователя или пароль."
        )

    return render(
        request,
        "finances/login.html",
    )


@login_required
def logout_view(request):
    """Выход пользователя из аккаунта."""

    logout(request)

    return redirect(
        "finances:login"
    )


# ============================================================
# DASHBOARD
# ============================================================

@login_required
def dashboard(request):
    """Главная страница пользователя."""

    now = timezone.now()

    start_of_month = now.replace(
        day=1,
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )

    if start_of_month.month == 12:

        end_of_month = start_of_month.replace(
            year=start_of_month.year + 1,
            month=1,
            day=1,
        )

    else:

        end_of_month = start_of_month.replace(
            month=start_of_month.month + 1,
            day=1,
        )

    transactions = (
        Transaction.objects
        .filter(
            user=request.user,
            date__gte=start_of_month,
            date__lt=end_of_month,
        )
    )

    total_income = (
        transactions
        .filter(type="income")
        .aggregate(
            total=Sum("amount")
        )
        .get("total")
        or Decimal("0")
    )

    total_expense = (
        transactions
        .filter(type="expense")
        .aggregate(
            total=Sum("amount")
        )
        .get("total")
        or Decimal("0")
    )

    balance = (
        total_income
        - total_expense
    )

    recent_transactions = (
        Transaction.objects
        .filter(
            user=request.user
        )
        .select_related(
            "category"
        )
        .order_by(
            "-date"
        )[:10]
    )

    notifications = (
        Notification.objects
        .filter(
            user=request.user,
            is_read=False,
        )
        .order_by(
            "-created_at"
        )[:5]
    )

    categories = (
        Category.objects
        .filter(
            Q(user=request.user)
            |
            Q(user__isnull=True)
        )
        .order_by(
            "name"
        )
    )

    context = {
        "total_income": total_income,
        "total_expense": total_expense,
        "balance": balance,
        "recent_transactions": recent_transactions,
        "notifications": notifications,
        "categories": categories,
        "form": TransactionForm(
            user=request.user
        ),
    }

    return render(
        request,
        "finances/dashboard.html",
        context,
    )


# ============================================================
# TRANSACTIONS
# ============================================================

@login_required
@require_POST
def add_transaction(request):
    """Добавление новой финансовой операции."""

    form = TransactionForm(
        request.POST,
        user=request.user,
    )

    if form.is_valid():

        transaction = form.save(
            commit=False
        )

        transaction.user = request.user

        category = transaction.category

        if category is not None:

            if (
                category.user_id is not None
                and
                category.user_id != request.user.id
            ):

                messages.error(
                    request,
                    "Вы не можете использовать эту категорию."
                )

                return redirect(
                    "finances:dashboard"
                )

        transaction.full_clean()
        transaction.save()

        _check_budget_limits(
            request.user,
            transaction,
        )

        messages.success(
            request,
            "Операция успешно добавлена!"
        )

        return redirect(
            "finances:dashboard"
        )

    now = timezone.now()

    start_of_month = now.replace(
        day=1,
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )

    if start_of_month.month == 12:

        end_of_month = start_of_month.replace(
            year=start_of_month.year + 1,
            month=1,
            day=1,
        )

    else:

        end_of_month = start_of_month.replace(
            month=start_of_month.month + 1,
            day=1,
        )

    transactions = (
        Transaction.objects
        .filter(
            user=request.user,
            date__gte=start_of_month,
            date__lt=end_of_month,
        )
    )

    total_income = (
        transactions
        .filter(type="income")
        .aggregate(
            total=Sum("amount")
        )
        .get("total")
        or Decimal("0")
    )

    total_expense = (
        transactions
        .filter(type="expense")
        .aggregate(
            total=Sum("amount")
        )
        .get("total")
        or Decimal("0")
    )

    context = {
        "total_income": total_income,
        "total_expense": total_expense,
        "balance": (
            total_income
            - total_expense
        ),
        "recent_transactions": (
            Transaction.objects
            .filter(
                user=request.user
            )
            .select_related(
                "category"
            )
            .order_by(
                "-date"
            )[:10]
        ),
        "notifications": (
            Notification.objects
            .filter(
                user=request.user,
                is_read=False,
            )
            .order_by(
                "-created_at"
            )[:5]
        ),
        "categories": (
            Category.objects
            .filter(
                Q(user=request.user)
                |
                Q(user__isnull=True)
            )
            .order_by(
                "name"
            )
        ),
        "form": form,
    }

    return render(
        request,
        "finances/dashboard.html",
        context,
    )


@login_required
def transactions_view(request):
    """Список операций с фильтрацией и пагинацией."""

    transactions = (
        Transaction.objects
        .filter(
            user=request.user
        )
        .select_related(
            "category"
        )
        .order_by(
            "-date"
        )
    )

    start_date = request.GET.get(
        "start_date",
        "",
    ).strip()

    end_date = request.GET.get(
        "end_date",
        "",
    ).strip()

    category_id = request.GET.get(
        "category",
        "",
    ).strip()

    type_filter = request.GET.get(
        "type",
        "",
    ).strip()

    # --------------------------------------------------------
    # Начальная дата
    # --------------------------------------------------------

    if start_date:

        try:

            start_datetime = datetime.strptime(
                start_date,
                "%Y-%m-%d",
            )

            start_datetime = timezone.make_aware(
                start_datetime,
                timezone.get_current_timezone(),
            )

            transactions = transactions.filter(
                date__gte=start_datetime,
            )

        except ValueError:

            start_date = ""

    # --------------------------------------------------------
    # Конечная дата
    # --------------------------------------------------------

    if end_date:

        try:

            end_datetime = (
                datetime.strptime(
                    end_date,
                    "%Y-%m-%d",
                )
                + timedelta(days=1)
            )

            end_datetime = timezone.make_aware(
                end_datetime,
                timezone.get_current_timezone(),
            )

            transactions = transactions.filter(
                date__lt=end_datetime,
            )

        except ValueError:

            end_date = ""

    # --------------------------------------------------------
    # Категория
    # --------------------------------------------------------

    if category_id:

        try:

            category_id_int = int(
                category_id
            )

            allowed_category = (
                Category.objects
                .filter(
                    Q(user=request.user)
                    |
                    Q(user__isnull=True),
                    id=category_id_int,
                )
                .exists()
            )

            if allowed_category:

                transactions = transactions.filter(
                    category_id=category_id_int,
                )

            else:

                category_id = ""

        except (
            ValueError,
            TypeError,
        ):

            category_id = ""

    # --------------------------------------------------------
    # Тип
    # --------------------------------------------------------

    allowed_types = {
        "income",
        "expense",
    }

    if type_filter not in allowed_types:
        type_filter = ""

    if type_filter:

        transactions = transactions.filter(
            type=type_filter,
        )

    # --------------------------------------------------------
    # Пагинация
    # --------------------------------------------------------

    paginator = Paginator(
        transactions,
        20,
    )

    page_number = request.GET.get(
        "page"
    )

    page_obj = paginator.get_page(
        page_number
    )

    categories = (
        Category.objects
        .filter(
            Q(user=request.user)
            |
            Q(user__isnull=True)
        )
        .order_by(
            "name"
        )
    )

    context = {
        "transactions": page_obj,
        "categories": categories,
        "filters": {
            "start_date": start_date,
            "end_date": end_date,
            "category": category_id,
            "type": type_filter,
        },
    }

    return render(
        request,
        "finances/transactions.html",
        context,
    )


@login_required
@require_POST
def delete_transaction(
    request,
    transaction_id,
):
    """Удаление собственной операции."""

    transaction = get_object_or_404(
        Transaction,
        id=transaction_id,
        user=request.user,
    )

    transaction.delete()

    messages.success(
        request,
        "Операция удалена."
    )

    return redirect(
        "finances:transactions"
    )


@login_required
def edit_transaction(
    request,
    transaction_id,
):
    """Редактирование собственной операции."""

    transaction = get_object_or_404(
        Transaction,
        id=transaction_id,
        user=request.user,
    )

    if request.method == "POST":

        form = TransactionForm(
            request.POST,
            instance=transaction,
            user=request.user,
        )

        if form.is_valid():

            updated_transaction = form.save(
                commit=False
            )

            updated_transaction.user = (
                request.user
            )

            updated_transaction.full_clean()
            updated_transaction.save()

            _check_budget_limits(
                request.user,
                updated_transaction,
            )

            messages.success(
                request,
                "Операция успешно обновлена."
            )

            return redirect(
                "finances:transactions"
            )

    else:

        form = TransactionForm(
            instance=transaction,
            user=request.user,
        )

    return render(
        request,
        "finances/edit_transaction.html",
        {
            "form": form,
            "transaction": transaction,
        },
    )


# ============================================================
# CATEGORIES
# ============================================================

@login_required
def categories_view(request):
    """Просмотр и создание категорий."""

    if request.method == "POST":

        form = CategoryForm(
            request.POST
        )

        if form.is_valid():

            category = form.save(
                commit=False
            )

            category.user = request.user
            category.is_default = False
            category.save()

            messages.success(
                request,
                "Категория успешно добавлена!"
            )

            return redirect(
                "finances:categories"
            )

    else:

        form = CategoryForm()

    categories = (
        Category.objects
        .filter(
            Q(user=request.user)
            |
            Q(user__isnull=True)
        )
        .order_by(
            "type",
            "name",
        )
    )

    return render(
        request,
        "finances/categories.html",
        {
            "categories": categories,
            "form": form,
        },
    )


@login_required
@require_POST
def delete_category(
    request,
    category_id,
):
    """Удаление пользовательской категории."""

    category = get_object_or_404(
        Category,
        id=category_id,
        user=request.user,
    )

    if category.is_default:

        messages.error(
            request,
            "Нельзя удалить системную категорию."
        )

    else:

        category.delete()

        messages.success(
            request,
            "Категория удалена."
        )

    return redirect(
        "finances:categories"
    )


# ============================================================
# BUDGET
# ============================================================

def _get_start_date(period):
    """
    Возвращает начало указанного периода.

    Поддерживаемые значения:
        daily
        weekly
        monthly
        month
        yearly
    """

    now = timezone.now()

    if period == "daily":
        return now.replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )

    if period == "weekly":

        start_of_today = now.replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )

        return (
            start_of_today
            - timedelta(
                days=now.weekday()
            )
        )

    if period in (
        "monthly",
        "month",
    ):
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

    return now.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )


def _check_budget_limits(
    user,
    transaction,
):
    """Проверяет превышение лимитов бюджета."""

    if transaction.type != "expense":
        return

    budgets = (
        UserBudget.objects
        .select_related("category")
        .filter(
            user=user,
        )
    )

    for budget in budgets:

        start = budget._get_period_start()

        transactions = Transaction.objects.filter(
            user=user,
            type="expense",
            date__gte=start,
        )

        if not budget.is_global:

            if (
                budget.category_id
                != transaction.category_id
            ):
                continue

            transactions = transactions.filter(
                category_id=transaction.category_id
            )

        spent = (
            transactions
            .aggregate(
                total=Sum("amount")
            )
            .get("total")
            or Decimal("0")
        )

        if spent < budget.amount:
            continue

        if budget.is_global:
            category_name = "Общий бюджет"
        else:
            category_name = budget.category.name

        message = (
            "⚠️ Превышен бюджет\n\n"
            f"Категория: {category_name}\n"
            f"Лимит: {budget.amount:.2f} руб.\n"
            f"Потрачено: {spent:.2f} руб."
        )

        already_exists = (
            Notification.objects
            .filter(
                user=user,
                message=message,
                is_read=False,
            )
            .exists()
        )

        if not already_exists:

            Notification.objects.create(
                user=user,
                message=message,
                type="warning",
            )


# ============================================================
# ANALYTICS
# ============================================================

@login_required
def analytics_view(request):
    """Страница аналитики."""

    period = request.GET.get(
        "period",
        "monthly",
    )

    allowed_periods = {
        "daily",
        "weekly",
        "monthly",
        "month",
        "yearly",
    }

    if period not in allowed_periods:
        period = "monthly"

    start_date = _get_start_date(
        period
    )

    transactions = (
        Transaction.objects
        .filter(
            user=request.user,
            date__gte=start_date,
        )
        .select_related(
            "category"
        )
        .order_by(
            "date"
        )
    )

    total_income = (
        transactions
        .filter(type="income")
        .aggregate(
            total=Sum("amount")
        )
        .get("total")
        or Decimal("0")
    )

    total_expense = (
        transactions
        .filter(type="expense")
        .aggregate(
            total=Sum("amount")
        )
        .get("total")
        or Decimal("0")
    )

    balance = (
        total_income
        - total_expense
    )

    income_data = list(
        transactions
        .filter(type="income")
        .values(
            "date",
            "amount",
        )
        .order_by(
            "date"
        )
    )

    expense_data = list(
        transactions
        .filter(type="expense")
        .values(
            "date",
            "amount",
        )
        .order_by(
            "date"
        )
    )

    category_data = list(
        transactions
        .filter(type="expense")
        .values(
            "category__name"
        )
        .annotate(
            total=Sum("amount")
        )
        .exclude(
            category__name__isnull=True
        )
        .exclude(
            category__name=""
        )
        .order_by(
            "-total"
        )
    )

    recommendations = (
        RecommendationEngine.get_recommendations(
            list(transactions)
        )
    )

    anomalies = (
        AnalyticsEngine.detect_anomalies(
            transactions
        )
    )

    context = {
        "total_income": total_income,
        "total_expense": total_expense,
        "balance": balance,

        "income_data": json.dumps(
            income_data,
            default=str,
        ),

        "expense_data": json.dumps(
            expense_data,
            default=str,
        ),

        "category_data": json.dumps(
            category_data,
            default=str,
        ),

        "recommendations": recommendations,
        "anomalies": anomalies,
        "current_period": period,
    }

    return render(
        request,
        "finances/analytics.html",
        context,
    )


# ============================================================
# SAVED REPORTS
# ============================================================

@login_required
def saved_reports_view(request):
    """Сохранённые отчёты пользователя."""
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        report_type = request.POST.get("report_type", "").strip()
        filters_raw = request.POST.get("filters", "{}")

        if not name:
            messages.error(request, "Введите название отчёта.")
            return redirect("finances:saved_reports")

        try:
            filters_dict = json.loads(filters_raw) if filters_raw else {}
            if not isinstance(filters_dict, dict):
                filters_dict = {}

        except (json.JSONDecodeError, TypeError):
            filters_dict = {}

        SavedReport.objects.create(
            user=request.user,
            name=name,
            report_type=report_type,
            filters=filters_dict,
        )

        messages.success(request, "Отчёт успешно сохранён!")
        return redirect("finances:saved_reports")

    reports = SavedReport.objects.filter(user=request.user).order_by("-id")

    return render(request, "finances/saved_reports.html", {"reports": reports})


# ============================================================
# TELEGRAM
# ============================================================

@login_required
def connect_telegram(request):
    """Ручная привязка Telegram ID к пользователю."""

    if request.method == "POST":

        telegram_id = request.POST.get(
            "telegram_id",
            "",
        ).strip()

        if not telegram_id:

            messages.error(
                request,
                "Введите Telegram ID."
            )

        elif not telegram_id.isdigit():

            messages.error(
                request,
                "Telegram ID должен содержать только цифры."
            )

        else:

            existing = (
                UserTelegram.objects
                .filter(
                    telegram_id=telegram_id
                )
                .first()
            )

            if (
                existing is not None
                and
                existing.user_id != request.user.id
            ):

                messages.error(
                    request,
                    "Этот Telegram ID уже привязан "
                    "к другому пользователю."
                )

            else:

                UserTelegram.objects.update_or_create(
                    user=request.user,
                    defaults={
                        "telegram_id": telegram_id,
                        "is_active": True,
                    },
                )

                messages.success(
                    request,
                    "Telegram успешно подключён!"
                )

                return redirect(
                    "finances:dashboard"
                )

    return render(
        request,
        "finances/connect_telegram.html",
    )


# ============================================================
# CHART API
# ============================================================

@login_required
def get_chart_data(request):
    """API для получения данных графиков."""

    period = request.GET.get(
        "period",
        "monthly",
    )

    allowed_periods = {
        "daily",
        "weekly",
        "monthly",
        "month",
        "yearly",
    }

    if period not in allowed_periods:
        period = "monthly"

    start_date = _get_start_date(
        period
    )

    transactions = (
        Transaction.objects
        .filter(
            user=request.user,
            date__gte=start_date,
        )
        .order_by(
            "date"
        )
    )

    income = list(
        transactions
        .filter(type="income")
        .values(
            "date",
            "amount",
        )
    )

    expense = list(
        transactions
        .filter(type="expense")
        .values(
            "date",
            "amount",
        )
    )

    categories = list(
        transactions
        .filter(type="expense")
        .values(
            "category__name"
        )
        .annotate(
            total=Sum("amount")
        )
        .exclude(
            category__name__isnull=True
        )
        .exclude(
            category__name=""
        )
        .order_by(
            "-total"
        )
    )

    return JsonResponse(
        {
            "income": income,
            "expense": expense,
            "categories": categories,
        },
        json_dumps_params={
            "ensure_ascii": False,
        },
    )


# ============================================================
# NOTIFICATIONS
# ============================================================

@login_required
@require_POST
def mark_notifications_read(request):
    """Отмечает все непрочитанные уведомления как прочитанные."""

    now = timezone.now()

    updated = (
        Notification.objects
        .filter(
            user=request.user,
            is_read=False,
        )
        .update(
            is_read=True,
            read_at=now,
        )
    )

    return JsonResponse(
        {
            "status": "success",
            "updated": updated,
        }
    )