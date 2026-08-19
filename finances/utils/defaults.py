# finances/utils/defaults.py
from django.db import transaction

from ..models import Category


DEFAULT_CATEGORIES = [
    # Расходы
    ("Еда", "expense"),
    ("Транспорт", "expense"),
    ("Развлечения", "expense"),
    ("Коммунальные услуги", "expense"),
    ("Здоровье", "expense"),
    ("Образование", "expense"),
    ("Одежда", "expense"),
    ("Техника", "expense"),
    ("Кафе и рестораны", "expense"),
    ("Супермаркеты", "expense"),
    ("Интернет и связь", "expense"),
    ("Дом и ремонт", "expense"),
    ("Красота и уход", "expense"),

    # Доходы
    ("Зарплата", "income"),
    ("Подарки", "income"),
    ("Фриланс", "income"),
    ("Инвестиции", "income"),
]


@transaction.atomic
def create_default_categories(user=None):
    """
    Создаёт стандартные категории.

    user=None:
        системные категории.

    user=<User>:
        личные категории пользователя.

    Повторный вызов безопасен.
    """

    created_count = 0

    for name, category_type in DEFAULT_CATEGORIES:
        _, created = Category.objects.get_or_create(
            user=user,
            name=name,
            type=category_type,
            defaults={
                "is_default": True,
            },
        )

        if created:
            created_count += 1

    return created_count