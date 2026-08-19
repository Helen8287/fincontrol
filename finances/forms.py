# finances/forms.py
from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone

from .models import Transaction, Category

User = get_user_model()


class UserRegistrationForm(UserCreationForm):
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(
            attrs={
                "class": "form-control",
                "placeholder": "Email",
            }
        ),
    )

    class Meta:
        model = User
        fields = [
            "username",
            "email",
            "password1",
            "password2",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["username"].widget.attrs.update({
            "class": "form-control",
            "placeholder": "Имя пользователя",
        })

        self.fields["password1"].widget.attrs.update({
            "class": "form-control",
            "placeholder": "Пароль",
        })

        self.fields["password2"].widget.attrs.update({
            "class": "form-control",
            "placeholder": "Подтверждение пароля",
        })


class TransactionForm(forms.ModelForm):
    class Meta:
        model = Transaction

        fields = [
            "amount",
            "type",
            "category",
            "description",
            "date",
        ]

        widgets = {
            "amount": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "step": "0.01",
                    "placeholder": "Сумма",
                }
            ),

            "type": forms.Select(
                attrs={
                    "class": "form-control",
                }
            ),

            "category": forms.Select(
                attrs={
                    "class": "form-control",
                }
            ),

            "description": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Описание (необязательно)",
                }
            ),

            "date": forms.DateTimeInput(
                attrs={
                    "class": "form-control",
                    "type": "datetime-local",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)

        super().__init__(*args, **kwargs)

        # Показываем только системные категории
        # и категории текущего пользователя.
        if self.user is not None:
            self.fields["category"].queryset = (
                Category.objects.filter(
                    Q(user=self.user) |
                    Q(user__isnull=True)
                ).order_by("type", "name")
            )

        # Для новой операции устанавливаем
        # текущую дату и время.
        if not self.instance.pk:
            current_time = timezone.localtime()

            self.fields["date"].initial = (
                current_time.strftime("%Y-%m-%dT%H:%M")
            )

    def clean_category(self):
        category = self.cleaned_data.get("category")

        if category is None:
            return category

        # Если пользователь не передан, не пытаемся
        # обращаться к self.user.id.
        if self.user is None:
            if category.user_id is not None:
                raise forms.ValidationError(
                    "Нельзя использовать эту категорию."
                )

            return category

        # Системная категория разрешена.
        if category.user_id is None:
            return category

        # Пользовательская категория должна принадлежать
        # текущему пользователю.
        if category.user_id != self.user.id:
            raise forms.ValidationError(
                "Категория принадлежит другому пользователю."
            )

        return category


class CategoryForm(forms.ModelForm):
    """
    Форма создания пользовательской категории.
    """

    class Meta:
        model = Category

        fields = [
            "name",
            "type",
        ]

        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Название категории",
                }
            ),

            "type": forms.Select(
                attrs={
                    "class": "form-control",
                }
            ),
        }

    def clean_name(self):
        name = self.cleaned_data.get("name")

        if not name:
            raise forms.ValidationError(
                "Название категории не может быть пустым."
            )

        name = name.strip()

        if not name:
            raise forms.ValidationError(
                "Название категории не может быть пустым."
            )

        return name