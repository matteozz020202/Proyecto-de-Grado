"""Regresiones aisladas: nunca llaman OpenAI ni escriben en Neon."""
import json
import time as clock
from datetime import datetime, time, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase, SimpleTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from courts.models import Venue, Court, CourtSchedule
from reservations.models import Reservation
from .schemas import BookingIntent
from .services.dates import relative_request
from .services.conversation import DRAFT_KEY, STATE_KEY, OPTION_TTL
from .services.openai_service import BookingInterpreter, InterpretationError
from .services.orchestrator import BookingOrchestrator, BookingSelectionError, consume_draft


def intent(**changes):
    values = dict(intent='search_availability', date=None, time=None, venue_query=None,
                  court_query=None, duration_minutes=None, time_band=None, any_venue=None,
                  missing_fields=[], clarification_question=None)
    values.update(changes)
    return BookingIntent(**values)


@override_settings(OPENAI_API_KEY='test-only', OPENAI_MODEL='configured-model')
class InterpreterTests(SimpleTestCase):
    def sdk_client(self, response):
        client = Mock()
        client.with_options.return_value = client
        client.responses.parse.return_value = response
        return client

    def test_structured_output_uses_configured_model_and_minimal_context(self):
        expected = intent(time='20:00')
        client = self.sdk_client(SimpleNamespace(status='completed', output=[], output_parsed=expected))
        result = BookingInterpreter(client).interpret('a las ocho', {'date': '2026-10-22'})
        self.assertEqual(result, expected)
        args = client.responses.parse.call_args.kwargs
        self.assertIs(args['text_format'], BookingIntent)
        self.assertEqual(args['model'], 'configured-model')
        self.assertFalse(args['store'])
        payload = json.loads(args['input'][1]['content'])
        self.assertEqual(set(payload), {'now', 'timezone', 'state', 'message'})
        self.assertEqual(payload['timezone'], 'America/Bogota')
        self.assertNotIn('test-only', args['input'][1]['content'])

    def test_refusal_incomplete_and_bad_schema_are_safe(self):
        refusal = SimpleNamespace(content=[SimpleNamespace(type='refusal')])
        for response in [SimpleNamespace(status='completed', output=[refusal], output_parsed=None),
                         SimpleNamespace(status='incomplete', output=[], output_parsed=None),
                         SimpleNamespace(status='completed', output=[], output_parsed={'made_up': True})]:
            with self.subTest(response=response), self.assertRaises(InterpretationError):
                BookingInterpreter(self.sdk_client(response)).interpret('hola', {})

    def test_timeout_and_sdk_errors_do_not_expose_provider_details(self):
        from openai import APITimeoutError
        client = self.sdk_client(None)
        client.responses.parse.side_effect = APITimeoutError(request=Mock())
        with self.assertRaisesRegex(InterpretationError, '^timeout$'):
            BookingInterpreter(client).interpret('hola', {})

    @override_settings(OPENAI_API_KEY='')
    def test_missing_configuration(self):
        with self.assertRaises(InterpretationError):
            BookingInterpreter().interpret('hola', {})

    def test_relative_dates_bogota(self):
        now = datetime(2026, 10, 21, 18, 0, tzinfo=ZoneInfo('America/Bogota'))
        for text, expected in [('mañana a las 8', '2026-10-22'), ('el viernes a las 7 pm', '2026-10-23'),
                               ('quiero Arena Caribe el sábado', '2026-10-24'), ('pasado mañana', '2026-10-23'),
                               ('hoy', '2026-10-21'), ('el próximo domingo', '2026-10-25')]:
            self.assertEqual(relative_request(text, now)[0], expected)
        self.assertIsNone(relative_request('por la mañana', now)[0])
        self.assertEqual(relative_request('dentro de 30 minutos', now), ('2026-10-21', '18:30'))


class BookingTests(TestCase):
    def setUp(self):
        cache.clear()
        self.now = datetime(2026, 10, 21, 18, 0, tzinfo=ZoneInfo('America/Bogota'))
        self.freeze = patch('django.utils.timezone.now', return_value=self.now)
        self.freeze.start()
        self.addCleanup(self.freeze.stop)
        self.day = timezone.localdate() + timedelta(days=1)
        self.venue = Venue.objects.create(venue_name='Arena Caribe')
        self.court = Court.objects.create(venue=self.venue, court_name='Cancha 2', price_per_hour=130000)
        for day in range(1, 8):
            CourtSchedule.objects.create(court=self.court, day_of_week=day, start_time=time(18), end_time=time(23))
        self.user = get_user_model().objects.create_user('player', password='Secure!93Testing')
        self.interpreter = Mock()
        self.bot = BookingOrchestrator(self.interpreter)
        self.session = {}

    def search(self, **changes):
        self.interpreter.interpret.return_value = intent(date=self.day.isoformat(), time='20:00', any_venue=True, **changes)
        return self.bot.reply(self.session, 'busca opciones')

    def reserve(self, start=time(20), end=time(21)):
        return Reservation.objects.create(court=self.court, user=self.user, reservation_date=self.day,
                                          start_time=start, end_time=end, total_amount=130000,
                                          reservation_status='CONFIRMED')

    def test_free_slot_price_and_no_reservation_created(self):
        result = self.search()
        self.assertEqual(len(result['options']), 1)
        self.assertEqual(result['options'][0]['price'], '130000.00')
        self.assertEqual(result['options'][0]['start_time'], '20:00')
        self.assertEqual(Reservation.objects.count(), 0)

    def test_occupied_slot_returns_only_real_alternatives(self):
        self.reserve()
        result = self.search()
        self.assertIn('alternativas reales', result['message'])
        self.assertTrue(result['options'])
        self.assertNotIn('20:00', [o['start_time'] for o in result['options']])

    def test_inexistent_venue(self):
        self.interpreter.interpret.return_value = intent(date=self.day.isoformat(), time='20:00', venue_query='No existe')
        result = self.bot.reply(self.session, 'en No existe')
        self.assertEqual(result['options'], [])
        self.assertIn('No encontré canchas', result['message'])

    def test_no_results_for_inactive_court_and_unconfigured_duration(self):
        self.assertEqual(self.search(duration_minutes=90)['options'], [])
        self.court.is_active = False
        self.court.save()
        self.assertEqual(self.search()['options'], [])

    def test_context_asks_one_missing_field_at_a_time(self):
        self.interpreter.interpret.return_value = intent()
        self.assertIn('qué día', self.bot.reply(self.session, 'quiero jugar')['message'])
        self.interpreter.interpret.return_value = intent(date='2099-01-01')
        self.assertIn('qué hora', self.bot.reply(self.session, 'mañana')['message'])
        self.interpreter.interpret.return_value = intent(time='20:00')
        self.assertIn('establecimiento', self.bot.reply(self.session, 'a las ocho')['message'])
        self.interpreter.interpret.return_value = intent(any_venue=True)
        self.assertEqual(self.bot.reply(self.session, 'cualquiera')['options'][0]['date'], self.day.isoformat())
        self.assertEqual(self.interpreter.interpret.call_args.args[1]['time'], '20:00')

    def test_relative_dates_override_model_and_night_band(self):
        for text, expected, hour in [('mañana a las 8', '2026-10-22', '20:00'), ('el viernes a las 7 pm', '2026-10-23', '19:00')]:
            self.session = {}
            self.interpreter.interpret.return_value = intent(date='2099-01-01', time=hour, any_venue=True)
            result = self.bot.reply(self.session, text)
            self.assertEqual(result['options'][0]['date'], expected)
            self.assertEqual(result['options'][0]['start_time'], hour)
        self.session = {}
        self.interpreter.interpret.return_value = intent(time_band='evening', any_venue=True)
        self.assertTrue(self.bot.reply(self.session, 'el viernes en la noche')['options'])

    def test_one_hour_boundary_is_django_rule(self):
        for minutes, allowed in [(30, False), (60, True)]:
            self.session = {}
            self.interpreter.interpret.return_value = intent(any_venue=True)
            result = self.bot.reply(self.session, f'dentro de {minutes} minutos')
            self.assertEqual(bool(result['options']), allowed)
            if not allowed:
                self.assertIn('una hora de anticipación', result['message'])

    def test_minimum_advance_is_checked_before_asking_venue(self):
        self.interpreter.interpret.return_value = intent()
        result = self.bot.reply(self.session, 'quiero jugar dentro de 30 minutos')
        self.assertIn('una hora de anticipación', result['message'])
        self.assertFalse(result['options'])

    def test_selection_and_consume_use_only_session_data(self):
        option = self.search()['options'][0]
        url = self.bot.select(self.session, option['option_id'])
        self.assertIn(f'/reservas/nueva/{self.court.pk}/', url)
        self.assertNotIn('price', self.session[DRAFT_KEY])
        self.assertEqual(consume_draft(self.session), url)
        self.assertNotIn(DRAFT_KEY, self.session)
        self.assertEqual(Reservation.objects.count(), 0)

    def test_tampered_expired_lost_and_consumed_selection(self):
        option = self.search()['options'][0]
        with self.assertRaises(BookingSelectionError):
            self.bot.select(self.session, 'made-up-court-id')
        self.session[STATE_KEY]['options_at'] = clock.time() - OPTION_TTL - 1
        with self.assertRaises(BookingSelectionError):
            self.bot.select(self.session, option['option_id'])
        option = self.search()['options'][0]
        self.bot.select(self.session, option['option_id'])
        self.reserve()
        with self.assertRaises(BookingSelectionError):
            consume_draft(self.session)
        self.assertNotIn(DRAFT_KEY, self.session)

    def test_help_keeps_valid_options_and_context_expires(self):
        option = self.search()['options'][0]
        self.interpreter.interpret.return_value = intent(intent='select_option')
        result = self.bot.reply(self.session, 'elige la primera')
        self.assertEqual(result['options'][0]['option_id'], option['option_id'])
        self.assertNotIn('qué día', result['message'])
        self.session[STATE_KEY]['updated_at'] = clock.time() - 1801
        self.interpreter.interpret.return_value = intent()
        result = self.bot.reply(self.session, 'quiero jugar')
        self.assertIn('qué día', result['message'])
        self.assertFalse(result['options'])

    def test_results_are_bounded_and_model_cannot_supply_business_data(self):
        for number in range(8):
            court = Court.objects.create(venue=self.venue, court_name=f'Cancha {number}', price_per_hour=50000)
            CourtSchedule.objects.create(court=court, day_of_week=self.day.isoweekday(), start_time=time(20), end_time=time(21))
        self.assertEqual(len(self.search()['options']), 6)
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            intent(price=1, court_id=999)

    def test_public_widgets_and_not_admin(self):
        for url in ['/', '/reservar/', f'/reservar/{self.venue.pk}/canchas/', f'/reservar/cancha/{self.court.pk}/disponibilidad/']:
            self.assertContains(self.client.get(url), 'data-booking-chat')
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)
        self.assertNotContains(self.client.get('/reservas/admin/dashboard/'), 'data-booking-chat')


class EndpointTests(TestCase):
    reserve = BookingTests.reserve

    def setUp(self):
        BookingTests.setUp(self)
        self.client = Client(enforce_csrf_checks=True)
        self.token = self.client.get('/chatbot/state/').json()['csrf_token']
        self.parse = patch('chatbot.services.openai_service.BookingInterpreter.interpret', return_value=intent(date=self.day.isoformat(), time='20:00', any_venue=True))
        self.parse.start()
        self.addCleanup(self.parse.stop)

    def post(self, path, data, token=None):
        return self.client.post('/chatbot/' + path + '/', data=json.dumps(data), content_type='application/json', HTTP_X_CSRFTOKEN=token or self.token)

    def option(self):
        response = self.post('message', {'message': 'mañana a las 8 cualquiera'})
        self.assertEqual(response.status_code, 200)
        return response.json()['options'][0]

    def test_csrf_required_and_invalid_rejected(self):
        data = json.dumps({'message': 'hola'})
        self.assertEqual(self.client.post('/chatbot/message/', data=data, content_type='application/json').status_code, 403)
        self.assertEqual(self.post('message', {'message': 'hola'}, token='a'*64).status_code, 403)
        self.assertEqual(self.post('message', {'message': 'hola'}).status_code, 200)
        for endpoint in ('select', 'reset'):
            self.assertEqual(self.client.post(f'/chatbot/{endpoint}/', data='{}', content_type='application/json').status_code, 403)

    def test_guest_login_resume_no_create(self):
        option = self.option()
        response = self.post('select', {'option_id': option['option_id']})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['requires_login'])
        self.assertEqual(response.json()['redirect_url'], '/login/?next=%2Fchatbot%2Fresume%2F')
        self.assertIn(DRAFT_KEY, self.client.session)
        login = self.client.post('/login/', {'username': 'player', 'password': 'Secure!93Testing', 'next': '/chatbot/resume/', 'csrfmiddlewaretoken': self.token})
        self.assertEqual(login.url, '/chatbot/resume/')
        response = self.client.get(login.url)
        self.assertIn(f'/reservas/nueva/{self.court.pk}/', response.url)
        self.assertNotIn(DRAFT_KEY, self.client.session)
        self.assertEqual(self.client.get(response.url).status_code, 200)
        self.assertEqual(Reservation.objects.count(), 0)
        # El login rota el secreto; recuperar el token actual permite seguir conversando.
        self.assertEqual(self.post('message', {'message': 'hola'}).status_code, 403)
        self.token = self.client.get('/chatbot/state/').json()['csrf_token']
        self.assertEqual(self.post('message', {'message': 'hola'}).status_code, 200)

    def test_signup_resume_existing_flow(self):
        option = self.option()
        self.post('select', {'option_id': option['option_id']})
        response = self.client.post('/registro/', {'username': 'newplayer', 'full_name': 'Persona Nueva', 'email': 'new@example.test',
                    'password1': 'Secure!93NewAccount', 'password2': 'Secure!93NewAccount', 'next': '/chatbot/resume/', 'csrfmiddlewaretoken': self.token})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/chatbot/resume/')
        self.assertIn('/reservas/nueva/', self.client.get(response.url).url)
        self.assertNotIn(DRAFT_KEY, self.client.session)
        self.assertEqual(Reservation.objects.count(), 0)

    def test_authenticated_direct_and_tampered_metadata(self):
        self.client.force_login(self.user)
        option = self.option()
        self.assertEqual(self.post('select', {'option_id': option['option_id'], 'court_id': 999, 'price': 1}).status_code, 400)
        response = self.post('select', {'option_id': option['option_id']})
        self.assertFalse(response.json()['requires_login'])
        self.assertIn('/reservas/nueva/', response.json()['redirect_url'])
        self.assertNotIn(DRAFT_KEY, self.client.session)

    def test_slot_lost_before_selection_and_after_login(self):
        option = self.option()
        self.reserve()
        self.assertEqual(self.post('select', {'option_id': option['option_id']}).status_code, 409)
        Reservation.objects.all().delete()
        option = self.option()
        self.post('select', {'option_id': option['option_id']})
        self.reserve()
        self.client.force_login(self.user)
        response = self.client.get('/chatbot/resume/')
        self.assertEqual(response.url, '/reservar/')
        self.assertNotIn(DRAFT_KEY, self.client.session)

    def test_oversize_invalid_payload_and_safe_provider_error(self):
        for data in [{'message': 'x'*501}, {'message': ''}, {'message': 3}, {'message': 'hola', 'court_id': 1}]:
            self.assertEqual(self.post('message', data).status_code, 400)
        with patch('chatbot.services.openai_service.BookingInterpreter.interpret', side_effect=InterpretationError('internal-secret')):
            response = self.post('message', {'message': 'hola'})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('internal-secret', response.content.decode())
        self.assertEqual(response.json()['fallback_url'], '/reservar/')

    def test_ip_limit_applies_across_sessions(self):
        from .security import acquire
        from django.test import RequestFactory
        for number in range(31):
            request = RequestFactory().post('/chatbot/message/')
            request.session = {}
            lock = acquire(request)
            if number < 30:
                self.assertIsNotNone(lock)
                cache.delete(lock)
            else:
                self.assertIsNone(lock)

    def test_limits_lock_reset_and_foreign_option(self):
        option = self.option()
        other = Client(enforce_csrf_checks=True)
        token = other.get('/chatbot/state/').json()['csrf_token']
        self.assertEqual(other.post('/chatbot/select/', data=json.dumps({'option_id': option['option_id']}), content_type='application/json', HTTP_X_CSRFTOKEN=token).status_code, 409)
        lock = 'booking-chat:lock:' + self.client.session['booking_chat_client']
        cache.add(lock, True, 40)
        self.assertEqual(self.post('message', {'message': 'hola'}).status_code, 429)
        cache.delete(lock)
        for _ in range(6):
            self.assertEqual(self.post('message', {'message': 'hola'}).status_code, 200)
        self.assertEqual(self.post('message', {'message': 'hola'}).status_code, 429)
        self.assertEqual(self.post('reset', {}).status_code, 200)
        self.assertNotIn(STATE_KEY, self.client.session)
