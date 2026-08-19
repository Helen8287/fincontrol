# finances/models.py


from decimal import Decimal
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q, Sum
from django.utils import timezone



class TelegramLinkCode(models.Model):

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="telegram_link_codes",
    )

    code = models.CharField(
        max_length=128,
        unique=True,
        db_index=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    expires_at = models.DateTimeField()

    used_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Код {self.code[:8]}... для {self.user.username}"

    def is_expired(self):
        return timezone.now() >= self.expires_at

    def is_used(self):
        return self.used_at is not None


# ============================================================
# Category
# ============================================================

class Category(models.Model):
    TYPE_CHOICES = [
        ("income", "Доход"),
        ("expense", "Расход"),
    ]

    name = models.CharField(
        max_length=100,
        verbose_name="Название",
    )

    type = models.CharField(
        max_length=10,
        choices=TYPE_CHOICES,
        verbose_name="Тип",
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="categories",
        verbose_name="Пользователь",
    )

    is_default = models.BooleanField(
        default=False,
        blank=True,
        verbose_name="Системная категория",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Создано",
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Обновлено",
    )

    class Meta:
        verbose_name = "Категория"
        verbose_name_plural = "Категории"

        constraints = [
            models.UniqueConstraint(
                fields=["user", "name", "type"],
                condition=Q(user__isnull=False),
                name="unique_user_category",
            ),
            models.UniqueConstraint(
                fields=["name", "type"],
                condition=Q(user__isnull=True),
                name="unique_global_category",
            ),
        ]

        indexes = [
            models.Index(
                fields=["user", "type"],
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.get_type_display()})"


# ============================================================
# Transaction
# ============================================================

class Transaction(models.Model):
    TYPE_CHOICES = [
        ("income", "Доход"),
        ("expense", "Расход"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="transactions",
        verbose_name="Пользователь",
    )

    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[
            MinValueValidator(
                Decimal("0.01")
            )
        ],
        verbose_name="Сумма",
    )

    type = models.CharField(
        max_length=10,
        choices=TYPE_CHOICES,
        verbose_name="Тип",
    )

    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="transactions",
        verbose_name="Категория",
    )

    description = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="Описание",
    )

    date = models.DateTimeField(
        default=timezone.now,
        verbose_name="Дата",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Создано",
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Обновлено",
    )

    class Meta:
        verbose_name = "Операция"
        verbose_name_plural = "Операции"

        ordering = ["-date"]

        indexes = [
            models.Index(
                fields=["user", "date"]
            ),
            models.Index(
                fields=["user", "type", "date"]
            ),
            models.Index(
                fields=["user", "category", "date"]
            ),
        ]

    def __str__(self):
        return (
            f"{self.get_type_display()}: "
            f"{self.amount} "
            f"({self.category.name})"
        )


# ============================================================
# UserTelegram
# ============================================================

class UserTelegram(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="telegram_account",
        verbose_name="Пользователь",
    )

    telegram_id = models.CharField(
        max_length=50,
        unique=True,
        verbose_name="Telegram ID",
    )

    telegram_username = models.CharField(
        max_length=100,
        blank=True,
        default="",
        db_index=True,
        verbose_name="Username",
    )

    first_name = models.CharField(
        max_length=100,
        blank=True,
        default="",
        verbose_name="Имя",
    )

    last_name = models.CharField(
        max_length=100,
        blank=True,
        default="",
        verbose_name="Фамилия",
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name="Активен",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Подключён",
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Обновлено",
    )

    class Meta:
        verbose_name = "Telegram пользователь"
        verbose_name_plural = "Telegram пользователи"

        indexes = [
            models.Index(
                fields=["is_active"]
            ),
        ]

    def __str__(self):
        username = (
            self.user.username
            or str(self.user.pk)
        )

        return (
            f"{username} - "
            f"{self.telegram_id}"
        )


# ============================================================
# UserBudget
# ============================================================

class UserBudget(models.Model):
    PERIOD_CHOICES = [
        ("daily", "День"),
        ("weekly", "Неделя"),
        ("monthly", "Месяц"),
        ("yearly", "Год"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="budgets",
        verbose_name="Пользователь",
    )

    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="budgets",
        verbose_name="Категория",
    )

    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[
            MinValueValidator(
                Decimal("0.01")
            )
        ],
        verbose_name="Лимит",
    )

    period = models.CharField(
        max_length=10,
        choices=PERIOD_CHOICES,
        default="monthly",
        verbose_name="Период",
    )

    is_global = models.BooleanField(
        default=False,
        blank=True,
        verbose_name="Глобальный бюджет",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Создано",
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Обновлено",
    )

    class Meta:
        verbose_name = "Бюджет"
        verbose_name_plural = "Бюджеты"

        constraints = [
            models.UniqueConstraint(
                fields=["user", "period"],
                condition=Q(is_global=True),
                name="unique_global_budget",
            ),
            models.UniqueConstraint(
                fields=[
                    "user",
                    "category",
                    "period",
                ],
                condition=Q(is_global=False),
                name="unique_category_budget",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        is_global=True,
                        category__isnull=True,
                    )
                    |
                    Q(
                        is_global=False,
                        category__isnull=False,
                    )
                ),
                name="budget_global_category_consistency",
            ),
        ]

        indexes = [
            models.Index(
                fields=["user", "category"]
            ),
            models.Index(
                fields=["user", "is_global"]
            ),
            models.Index(
                fields=["user", "period"]
            ),
        ]

    def clean(self):
        super().clean()

        # ----------------------------------------------------
        # Общий бюджет
        # ----------------------------------------------------

        if self.is_global:

            if self.category_id:
                raise ValidationError({
                    "category": (
                        "Глобальный бюджет "
                        "не должен иметь категорию."
                    )
                })

            return

        # ----------------------------------------------------
        # Категориальный бюджет
        # ----------------------------------------------------

        if not self.category_id:
            raise ValidationError({
                "category": (
                    "Для бюджета категории "
                    "необходимо указать категорию."
                )
            })

        category = self.category

        if (
            category.user_id is not None
            and category.user_id != self.user_id
        ):
            raise ValidationError({
                "category": (
                    "Категория принадлежит "
                    "другому пользователю."
                )
            })

        if category.type != "expense":
            raise ValidationError({
                "category": (
                    "Бюджет можно установить "
                    "только для расходной категории."
                )
            })

    # ========================================================
    # Period
    # ========================================================

    def _get_period_start(self):
        now = timezone.now()

        if self.period == "daily":
            return now.replace(
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )

        if self.period == "weekly":
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

        if self.period == "monthly":
            return now.replace(
                day=1,
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )

        if self.period == "yearly":
            return now.replace(
                month=1,
                day=1,
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )

        raise ValueError(
            f"Неизвестный период: {self.period}"
        )

    # ========================================================
    # Spent
    # ========================================================

    def get_spent_amount(self):
        start = self._get_period_start()

        query = Transaction.objects.filter(
            user=self.user,
            type="expense",
            date__gte=start,
        )

        if not self.is_global:
            query = query.filter(
                category_id=self.category_id
            )

        return (
            query
            .aggregate(
                total=Sum("amount")
            )
            .get("total")
            or Decimal("0")
        )

    # ========================================================
    # Remaining
    # ========================================================

    def get_remaining(self):
        return (
            self.amount
            - self.get_spent_amount()
        )

    # ========================================================
    # Exceeded
    # ========================================================

    def is_exceeded(self):
        """
        True только если расходы
        действительно превысили лимит.
        """

        return (
            self.get_spent_amount()
            > self.amount
        )

    # ========================================================
    # Percent
    # ========================================================

    def get_percent_used(self):
        """
        Возвращает фактический процент использования.

        Например:
            50%
            100%
            150%
        """

        if self.amount <= 0:
            return Decimal("0")

        spent = self.get_spent_amount()

        return (
            spent
            / self.amount
            * Decimal("100")
        )

    def __str__(self):
        category_name = self.category.name if self.category_id else "Общий"
        username = self.user.username or f"User #{self.user.pk}"
        return f"{username}: {category_name} - {self.amount}"

# ============================================================
# SavedReport
# ============================================================

class SavedReport(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="saved_reports",
        verbose_name="Пользователь",
    )

    name = models.CharField(
        max_length=100,
        verbose_name="Название",
    )

    report_type = models.CharField(
        max_length=50,
        verbose_name="Тип отчёта",
    )

    filters = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="Фильтры",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Создан",
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Обновлено",
    )

    class Meta:
        verbose_name = "Сохранённый отчёт"
        verbose_name_plural = "Сохранённые отчёты"

        indexes = [
            models.Index(
                fields=["user", "report_type"]
            ),
        ]

    def clean(self):
        super().clean()

        if not isinstance(self.filters, dict):
            raise ValidationError({
                "filters": (
                    "Фильтры должны быть "
                    "в формате JSON объекта."
                )
            })

    def __str__(self):
        username = (
            self.user.username
            or str(self.user.pk)
        )

        return (
            f"{username}: {self.name}"
        )


# ============================================================
# Notification
# ============================================================

class Notification(models.Model):
    NOTIFICATION_TYPES = [
        ("info", "Информация"),
        ("warning", "Предупреждение"),
        ("success", "Успех"),
        ("error", "Ошибка"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name="Пользователь",
    )

    message = models.TextField(
        verbose_name="Сообщение",
    )

    type = models.CharField(
        max_length=10,
        choices=NOTIFICATION_TYPES,
        default="info",
        verbose_name="Тип",
    )

    is_read = models.BooleanField(
        default=False,
        verbose_name="Прочитано",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Создано",
    )

    read_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Прочитано в",
    )

    class Meta:
        verbose_name = "Уведомление"
        verbose_name_plural = "Уведомления"

        ordering = ["-created_at"]

        indexes = [
            models.Index(
                fields=["user", "is_read"]
            ),
            models.Index(
                fields=["user", "created_at"]
            ),
        ]

    def mark_as_read(self):
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()

            self.save(
                update_fields=[
                    "is_read",
                    "read_at",
                ]
            )

    @classmethod
    def get_unread_count(cls, user):
        return cls.objects.filter(
            user=user,
            is_read=False,
        ).count()

    def __str__(self):
        username = (
            self.user.username
            or str(self.user.pk)
        )

        message = self.message[:50]

        if len(self.message) > 50:
            message += "..."

        return (
            f"{username}: {message}"
        )