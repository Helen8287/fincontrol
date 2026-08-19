# finances/utils/analytics.py
from django.db.models import Sum, Avg, Count
from django.utils import timezone  # <-- ДОБАВЛЕНО
from datetime import timedelta
from decimal import Decimal
import pandas as pd
import numpy as np


class AnalyticsEngine:
    @staticmethod
    def detect_anomalies(transactions):
        """Обнаружение аномалий в транзакциях"""
        anomalies = []

        if not transactions:
            return anomalies

        # Проверяем, является ли transactions QuerySet или списком
        if hasattr(transactions, 'exists') and not transactions.exists():
            return anomalies

        # Преобразуем в список для pandas
        transaction_list = list(transactions)
        if not transaction_list:
            return anomalies

        # Создаем DataFrame
        data = [{
            'category__name': getattr(t, 'category', None) and t.category.name or 'Без категории',
            'amount': float(t.amount),
            'date': t.date
        } for t in transaction_list]

        df = pd.DataFrame(data)
        if df.empty:
            return anomalies

        # Вычисление среднего и std для каждой категории
        stats = df.groupby('category__name')['amount'].agg(['mean', 'std']).reset_index()

        for _, row in stats.iterrows():
            category = row['category__name']
            mean = row['mean']
            std = row['std']

            if std > 0:
                # Находим транзакции, превышающие 2 стандартных отклонения
                cat_transactions = [t for t in transaction_list
                                    if getattr(t, 'category', None) and t.category.name == category]

                for t in cat_transactions:
                    if abs(float(t.amount) - mean) > 2 * std:
                        anomalies.append({
                            'category': category,
                            'amount': t.amount,
                            'date': t.date,
                            'description': t.description or 'Без описания',
                            'message': f"Аномальная операция: {t.amount} руб. "
                                       f"(среднее: {mean:.2f} руб.)"
                        })

        return anomalies[:10]

    @staticmethod
    def get_category_stats(user, period='month'):
        """Статистика по категориям"""
        from ..models import Transaction

        if period == 'month':
            start_date = timezone.now().replace(day=1)  # <-- ТЕПЕРЬ РАБОТАЕТ
        elif period == 'week':
            start_date = timezone.now() - timedelta(days=7)  # <-- ТЕПЕРЬ РАБОТАЕТ
        else:
            start_date = timezone.now() - timedelta(days=30)  # <-- ТЕПЕРЬ РАБОТАЕТ

        transactions = Transaction.objects.filter(
            user=user,
            date__gte=start_date,
            type='expense'
        )

        stats = transactions.values('category__name').annotate(
            total=Sum('amount'),
            count=Count('id'),
            avg=Avg('amount')
        )

        return stats