from .models import Notification

def notifications_processor(request):
    """
    Добавляет непрочитанные уведомления в контекст всех шаблонов
    """
    if request.user.is_authenticated:
        notifications = Notification.objects.filter(
            user=request.user,
            is_read=False
        ).order_by('-created_at')[:5]
        return {'notifications': notifications}
    return {'notifications': []}