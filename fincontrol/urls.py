
from django.contrib import admin
from django.urls import path, include

from finances.views import create_telegram_link

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('finances.urls')),
    path(
            "api/telegram/link/",
            create_telegram_link,
            name="create_telegram_link",
    ),
]
