# finances/utils/recommendations.py
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone


class RecommendationEngine:
    """
    Движок финансовых рекомендаций.

    Получает уже загруженный список Transaction,
    поэтому сам с БД не работает.
    """

    @staticmethod
    def get_recommendations(
        transactions: list
    ) -> list[str]:

        recommendations: list[str] = []

        if not transactions:
            return [
                "📊 Пока нет операций для анализа."
            ]

        zero = Decimal("0")

        # ====================================================
        # Разделяем операции
        # ====================================================

        expense_transactions = [
            transaction
            for transaction in transactions
            if transaction.type == "expense"
        ]

        income_transactions = [
            transaction
            for transaction in transactions
            if transaction.type == "income"
        ]

        # ====================================================
        # Общие расходы
        # ====================================================

        total_expense = sum(
            (
                transaction.amount
                for transaction in expense_transactions
            ),
            zero,
        )

        if total_expense <= zero:
            return [
                "📊 Пока нет расходов для анализа."
            ]

        # ====================================================
        # Расходы по категориям
        # ====================================================

        category_totals = defaultdict(
            lambda: zero
        )

        for transaction in expense_transactions:

            category = transaction.category

            if category is None:
                continue

            category_totals[
                category.name
            ] += transaction.amount

        top_category = max(
            category_totals.items(),
            key=lambda item: item[1],
            default=None,
        )

        if top_category:

            category_name, category_total = (
                top_category
            )

            percent = (
                category_total
                / total_expense
                * Decimal("100")
            )

            if percent >= Decimal("40"):

                recommendations.append(
                    f"💡 Категория "
                    f"'{category_name}' "
                    f"занимает {percent:.0f}% "
                    "расходов. "
                    "Можно поискать способы "
                    "оптимизации."
                )

        # ====================================================
        # Средние расходы в день
        # ====================================================

        first_transaction = min(
            expense_transactions,
            key=lambda transaction: transaction.date,
            default=None,
        )

        last_transaction = max(
            expense_transactions,
            key=lambda transaction: transaction.date,
            default=None,
        )

        if (
            first_transaction
            and last_transaction
        ):
            delta = (
                last_transaction.date.date()
                - first_transaction.date.date()
            )

            period_days = (
                delta.days + 1
            )

        else:
            period_days = 1

        period_days = max(
            period_days,
            1,
        )

        daily_average = (
            total_expense
            / Decimal(period_days)
        )

        if daily_average > Decimal("5000"):

            recommendations.append(
                f"💡 Средние расходы: "
                f"{daily_average:.0f} "
                "руб./день. "
                "Стоит проверить крупные "
                "статьи расходов."
            )

        # ====================================================
        # Доходы
        # ====================================================

        total_income = sum(
            (
                transaction.amount
                for transaction in income_transactions
            ),
            zero,
        )

        if (
            total_income > zero
            and total_expense > total_income
        ):
            recommendations.append(
                "⚠️ Расходы превышают доходы. "
                "Рекомендуется пересмотреть бюджет."
            )

        # ====================================================
        # Активность
        # ====================================================

        month_ago = (
            timezone.now()
            - timedelta(days=30)
        )

        recent_count = sum(
            1
            for transaction in transactions
            if transaction.date >= month_ago
        )

        if recent_count < 5:

            recommendations.append(
                "📊 Добавляйте больше операций "
                "для более точного анализа."
            )

        # ====================================================
        # Если проблем нет
        # ====================================================

        if not recommendations:

            recommendations.append(
                "✅ Ваши расходы выглядят "
                "сбалансированно."
            )

        return recommendations

    @staticmethod
    def get_saving_tips() -> list[str]:

        return [
            "🍽️ Готовьте дома — это помогает "
            "снизить расходы.",

            "🚌 Используйте транспорт "
            "с меньшей стоимостью.",

            "🛒 Планируйте покупки заранее.",

            "📱 Проверьте ненужные подписки.",

            "💡 Контролируйте расходы "
            "на коммунальные услуги.",
        ]