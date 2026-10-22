"""Límites locales; usar un caché compartido entre workers en producción."""
import time
import secrets
from django.core.cache import cache
from django.utils.crypto import salted_hmac


def identity(request):
    if 'booking_chat_client' not in request.session:
        request.session['booking_chat_client'] = secrets.token_urlsafe(18)
    return request.session['booking_chat_client']


def acquire(request):
    client = identity(request)
    # REMOTE_ADDR es confiable; no confiar en X-Forwarded-For del cliente.
    ip = salted_hmac('booking-chat', request.META.get('REMOTE_ADDR', '')).hexdigest()
    window = int(time.time() // 60)
    for subject, limit in ((client, 8), (ip, 30)):
        key = f'booking-chat:rate:{subject}:{window}'
        cache.add(key, 0, 65)
        try:
            count = cache.incr(key)
        except ValueError:
            return None
        if count > limit:
            return None
    lock = f'booking-chat:lock:{client}'
    return lock if cache.add(lock, True, 40) else None
