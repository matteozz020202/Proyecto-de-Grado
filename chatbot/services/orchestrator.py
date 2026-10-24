import time as clock
from datetime import date, datetime, time, timedelta
from urllib.parse import urlencode
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone
from courts.models import Court, Venue
from reservations.services import get_availability, calculate_reservation_values, validate_minimum_booking_advance
from .conversation import (DRAFT_KEY, OPTION_TTL, current_options, option_token, save_state, state_for)
from .dates import relative_request
from .openai_service import BookingInterpreter


class BookingSelectionError(Exception):
    pass


def booking_url(draft):
    return reverse('reservations:resumen_reserva', args=[draft['court_id']]) + '?' + urlencode({
        'fecha': draft['date'], 'inicio': draft['start_time'], 'fin': draft['end_time']})


def validate_draft(draft):
    """Revalida datos de sesión contra la disponibilidad oficial, sin crear reservas."""
    try:
        if clock.time() - draft['created_at'] > OPTION_TTL:
            raise BookingSelectionError
        court = Court.objects.select_related('venue').get(pk=draft['court_id'], is_active=True, venue__is_active=True)
        day = date.fromisoformat(draft['date'])
        start = time.fromisoformat(draft['start_time'])
        end = time.fromisoformat(draft['end_time'])
        validate_minimum_booking_advance(day, start)
        if not any(slot['start_time'] == start and slot['end_time'] == end for slot in get_availability(court, day)):
            raise BookingSelectionError
        return booking_url(draft)
    except (KeyError, TypeError, ValueError, Court.DoesNotExist, ValidationError):
        raise BookingSelectionError from None


def consume_draft(session):
    draft = session.pop(DRAFT_KEY, None)
    if not draft:
        raise BookingSelectionError
    return validate_draft(draft)


class BookingOrchestrator:
    def __init__(self, interpreter=None):
        self.interpreter = interpreter or BookingInterpreter()

    def reply(self, session, message):
        state = state_for(session)
        preferences = dict(state['preferences'])
        intent = self.interpreter.interpret(message, preferences)
        if intent.intent in ('greeting', 'help', 'other', 'select_option'):
            text = ('Puedo ayudarte a buscar canchas y horarios. No creo, cambio ni cancelo reservas. '
                    'Para elegir una opción usa su botón. ')
            if not preferences.get('date'):
                text += '¿Para qué día quieres jugar?'
            elif not preferences.get('time') and not preferences.get('time_band'):
                text += '¿A qué hora quieres jugar?'
            elif not preferences.get('venue_query') and not preferences.get('any_venue'):
                text += '¿Tienes un establecimiento en mente o busco en cualquiera?'
            else:
                text += 'Puedes elegir una opción o indicar otra fecha u hora.'
            return self._save(session, state, text)
        state['options'] = {}
        for field in ('date', 'time', 'venue_query', 'court_query', 'duration_minutes', 'time_band'):
            value = getattr(intent, field)
            if value is not None:
                if isinstance(value, str) and len(value) > 100:
                    return self._save(session, state, 'Indica una preferencia más breve para buscar tu cancha.')
                preferences[field] = value
        if intent.any_venue is not None:
            preferences['any_venue'] = intent.any_venue
        if intent.any_venue:
            preferences.pop('venue_query', None)
        if intent.venue_query and intent.venue_query != state['preferences'].get('venue_query'):
            if intent.court_query is None:
                preferences.pop('court_query', None)
        if intent.venue_query:
            preferences['any_venue'] = False
        if intent.time is not None:
            preferences.pop('time_band', None)
        elif intent.time_band is not None:
            preferences.pop('time', None)
        relative_date, relative_time = relative_request(message)
        if relative_date:
            preferences['date'] = relative_date
        if relative_time:
            preferences['time'] = relative_time
        state['preferences'] = preferences
        if not preferences.get('date'):
            return self._save(session, state, 'Claro. ¿Para qué día quieres jugar?')
        try:
            day = date.fromisoformat(preferences['date'])
            if not timezone.localdate() <= day <= timezone.localdate() + timedelta(days=90):
                raise ValueError
            requested_time = time.fromisoformat(preferences['time']) if preferences.get('time') else None
            if requested_time and (requested_time.second or requested_time.microsecond or requested_time.tzinfo):
                raise ValueError
        except (ValueError, TypeError):
            preferences.pop('date', None)
            preferences.pop('time', None)
            return self._save(session, state, 'Indica una fecha válida, desde hoy y hasta los próximos 90 días, y una hora como 20:00.')
        if requested_time is None and not preferences.get('time_band'):
            return self._save(session, state, '¿A qué hora quieres jugar? También puedes indicar mañana, tarde o noche.')
        if requested_time:
            try:
                validate_minimum_booking_advance(day, requested_time)
            except ValidationError:
                return self._save(session, state, 'Las reservas deben hacerse con al menos una hora de anticipación. Indica una hora posterior para revisar opciones reales.')
        if not preferences.get('venue_query') and not preferences.get('any_venue'):
            venues = list(Venue.objects.filter(is_active=True).order_by('venue_name').values_list('venue_name', flat=True)[:5])
            text = '¿Tienes un establecimiento en mente o prefieres que busque en cualquiera?'
            if venues:
                text += ' Puedes consultar: ' + ', '.join(venues) + '.'
            return self._save(session, state, text)
        courts = Court.objects.select_related('venue').filter(is_active=True, venue__is_active=True).order_by('venue__venue_name', 'court_id')
        if preferences.get('venue_query'):
            courts = courts.filter(venue__venue_name__icontains=preferences['venue_query'])
        if preferences.get('court_query'):
            courts = courts.filter(court_name__icontains=preferences['court_query'])
        courts = list(courts[:25])
        if not courts:
            return self._save(session, state, 'No encontré canchas activas con ese establecimiento o nombre. ¿Quieres que busque en otro o en cualquiera?')
        exact, alternatives = [], []
        for court in courts:
            for slot in get_availability(court, day):
                start, end = slot['start_time'], slot['end_time']
                duration = (datetime.combine(day, end) - datetime.combine(day, start)).total_seconds() / 60
                if preferences.get('duration_minutes') and duration != preferences['duration_minutes']:
                    continue
                band = preferences.get('time_band')
                if band and not ({'morning': 0 <= start.hour < 12, 'afternoon': 12 <= start.hour < 18, 'evening': 18 <= start.hour < 24}[band]):
                    continue
                values = calculate_reservation_values(court, day, start, end)
                option = {'court_id': court.pk, 'venue': court.venue.venue_name, 'court': court.court_name,
                          'date': day.isoformat(), 'start_time': start.strftime('%H:%M'), 'end_time': end.strftime('%H:%M'),
                          'price': str(values['total_amount']), 'currency': 'COP'}
                if requested_time is None or start == requested_time:
                    exact.append(option)
                elif abs((start.hour * 60 + start.minute) - (requested_time.hour * 60 + requested_time.minute)) <= 120:
                    alternatives.append(option)
        if requested_time:
            alternatives.sort(key=lambda o: abs(int(o['start_time'][:2])*60+int(o['start_time'][3:])-requested_time.hour*60-requested_time.minute))
        options = (exact or alternatives)[:6]
        state['options_at'] = clock.time()
        for option in options:
            option['option_id'] = option_token()
        state['options'] = {option['option_id']: option for option in options}
        if exact:
            text = f'Encontré estas opciones para el {day.strftime("%d/%m/%Y")}' + (f' a las {requested_time.strftime("%H:%M")}' if requested_time else '') + '. Elige una para revisar tu reserva.'
        elif options:
            text = 'No hay disponibilidad exacta. Estas son alternativas reales cercanas; revisa la hora antes de elegir.'
        else:
            text = 'No encontré horarios para esa búsqueda. Prueba otra fecha, hora o establecimiento.'
        return self._save(session, state, text)

    @staticmethod
    def _save(session, state, message):
        state['last_message'] = message
        save_state(session, state)
        return {'message': message, 'options': current_options(state), 'requires_login': False}

    @staticmethod
    def select(session, option_id):
        state = state_for(session)
        if clock.time() - state.get('options_at', 0) > OPTION_TTL:
            raise BookingSelectionError
        option = state.get('options', {}).get(option_id)
        if not option:
            raise BookingSelectionError
        draft = {key: option[key] for key in ('court_id', 'date', 'start_time', 'end_time')}
        draft['created_at'] = clock.time()
        url = validate_draft(draft)
        session[DRAFT_KEY] = draft
        return url
