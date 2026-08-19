from django.urls import path
from . import views

app_name = 'finances'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),
    path('logout/', views.logout_view, name='logout'),
    path('add-transaction/', views.add_transaction, name='add_transaction'),
    path('analytics/', views.analytics_view, name='analytics'),
    path('transactions/', views.transactions_view, name='transactions'),
    path('categories/', views.categories_view, name='categories'),
    path('delete-category/<int:category_id>/', views.delete_category, name='delete_category'),
    path('delete-transaction/<int:transaction_id>/', views.delete_transaction,
         name='delete_transaction'),
    path('edit-transaction/<int:transaction_id>/', views.edit_transaction,
         name='edit_transaction'),
    path('saved-reports/', views.saved_reports_view, name='saved_reports'),
    path('connect-telegram/', views.connect_telegram, name='connect_telegram'),
    path('api/chart-data/', views.get_chart_data, name='chart_data'),
    path('api/notifications/mark-read/', views.mark_notifications_read, name='mark_notifications_read'),
]
