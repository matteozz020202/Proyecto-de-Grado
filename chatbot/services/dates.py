"""Normalización lingüística; nunca calcula disponibilidad ni reglas de reserva."""
import re
import unicodedata
from datetime import timedelta
from django.utils import timezone


def relative_request(message, now=None):
    now = now or timezone.localtime()
    text = ''.join(c for c in unicodedata.normalize('NFD', message.lower()) if not unicodedata.combining(c))
    relative = re.search(r'dentro de (\d{1,3})\s*(minutos?|horas?)', text)
    if relative:
        amount = int(relative[1]) * (60 if relative[2].startswith('hora') else 1)
        target = now + timedelta(minutes=amount)
        if target.second or target.microsecond:
            target += timedelta(minutes=1)
        return target.date().isoformat(), target.strftime('%H:%M')
    weekdays = ['lunes', 'martes', 'miercoles', 'jueves', 'viernes', 'sabado', 'domingo']
    for index, word in enumerate(weekdays):
        if re.search(r'\b' + word + r'\b', text):
            offset = (index - now.weekday()) % 7
            if offset == 0 and re.search(r'proximo|que viene', text):
                offset = 7
            return (now.date() + timedelta(days=offset)).isoformat(), None
    if 'pasado manana' in text:
        return (now.date() + timedelta(days=2)).isoformat(), None
    if re.search(r'\bmanana\b', text) and not re.search(r'(?:por|en|de) la manana', text):
        return (now.date() + timedelta(days=1)).isoformat(), None
    if re.search(r'\bhoy\b', text):
        return now.date().isoformat(), None
    return None, None
