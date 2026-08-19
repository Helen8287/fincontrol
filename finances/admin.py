from django.contrib import admin
from django.contrib.admin import DateFieldListFilter

from .models import Category, Transaction, UserTelegram, UserBudget, SavedReport, Notification

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'type', 'user', 'is_default']
    list_filter = ('type', 'is_default', 'user')
    search_fields = ('name',)

@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('user', 'amount', 'type', 'category', 'date')
    list_filter = (
        'type',
        'category',
        ('date', DateFieldListFilter),
    )
    search_fields = ('description',)
    date_hierarchy = 'date'

@admin.register(UserTelegram)
class UserTelegramAdmin(admin.ModelAdmin):
    list_display = ['user', 'telegram_id', 'is_active']

@admin.register(UserBudget)
class UserBudgetAdmin(admin.ModelAdmin):
    list_display = ['user', 'category', 'amount', 'period']

@admin.register(SavedReport)
class SavedReportAdmin(admin.ModelAdmin):
    list_display = ['user', 'name', 'report_type']

@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ['user', 'message', 'is_read', 'created_at']