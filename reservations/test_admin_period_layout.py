"""Día/Mes adapta el rango existente; navegación y ownership se preservan."""
from datetime import date, datetime, time
from unittest.mock import patch
from zoneinfo import ZoneInfo
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from courts.models import Venue, Court, CourtSchedule
from .forms import DashboardFilterForm
from .models import Reservation


class AdminPeriodLayoutTests(TestCase):
    def setUp(self):
        self.freeze = patch('django.utils.timezone.now', return_value=datetime(2026, 10, 27, 12, tzinfo=ZoneInfo('America/Bogota')))
        self.freeze.start()
        self.addCleanup(self.freeze.stop)
        self.admin = get_user_model().objects.create_user('admin_period', is_staff=True)
        self.other = get_user_model().objects.create_user('other_admin', is_staff=True)
        self.venue = Venue.objects.create(venue_name='Arena propia', manager=self.admin)
        foreign = Venue.objects.create(venue_name='Arena ajena', manager=self.other)
        self.court = Court.objects.create(venue=self.venue, court_name='Cancha propia', price_per_hour=130000)
        self.foreign_court = Court.objects.create(venue=foreign, court_name='Cancha ajena', price_per_hour=90000)
        for court in (self.court, self.foreign_court):
            for weekday in range(1, 8):
                CourtSchedule.objects.create(court=court, day_of_week=weekday, start_time=time(8), end_time=time(22))
        self.reservation = Reservation.objects.create(court=self.court, user=self.admin, reservation_date=date(2026, 9, 15),
            start_time=time(18), end_time=time(19), total_amount=130000, reservation_status='COMPLETED')
        Reservation.objects.create(court=self.foreign_court, user=self.other, reservation_date=date(2026, 9, 15),
            start_time=time(18), end_time=time(19), total_amount=90000, reservation_status='COMPLETED')
        self.client.force_login(self.admin)

    def form(self, **data):
        return DashboardFilterForm(data, user=self.admin)

    def test_day_normalizes_and_ignores_tampered_range(self):
        form = self.form(periodo='day', fecha='2026-09-15', fecha_inicio='2000-01-01', fecha_fin='2099-01-01')
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['fecha_inicio'], date(2026, 9, 15))
        self.assertEqual(form.cleaned_data['fecha_fin'], date(2026, 9, 15))
        self.assertEqual(set(form.cleaned_data), {'origen', 'establecimiento', 'cancha', 'fecha_inicio', 'fecha_fin', 'tipo'})

    def test_month_uses_calendar_including_leap_year_and_year_boundary(self):
        for month, last in [('2024-02', 29), ('2025-02', 28), ('2026-04', 30), ('2025-12', 31)]:
            with self.subTest(month=month):
                form = self.form(periodo='month', mes=month)
                self.assertTrue(form.is_valid(), form.errors)
                self.assertEqual(form.cleaned_data['fecha_inicio'], date.fromisoformat(month+'-01'))
                self.assertEqual(form.cleaned_data['fecha_fin'], date.fromisoformat(month+f'-{last}'))

    @patch('django.utils.timezone.localdate',return_value=date(2026,10,27))
    def test_current_month_respects_analysis_type(self,mocked_localdate):
        historical=self.form(periodo='month',mes='2026-10',tipo='HISTORICAL')
        self.assertTrue(historical.is_valid(),historical.errors)
        self.assertEqual(historical.cleaned_data['fecha_inicio'],date(2026,10,1))
        self.assertEqual(historical.cleaned_data['fecha_fin'],date(2026,10,27))

        future=self.form(periodo='month',mes='2026-10',tipo='FUTURE')
        self.assertTrue(future.is_valid(),future.errors)
        self.assertEqual(future.cleaned_data['fecha_inicio'],date(2026,10,27))
        self.assertEqual(future.cleaned_data['fecha_fin'],date(2026,10,31))

    def test_bad_input_and_incompatible_period_are_rejected(self):
        for data in [dict(periodo='month', mes='2026-13'), dict(periodo='month', mes=''),
                     dict(periodo='day', fecha='2026-02-30'), dict(periodo='day', fecha=''),
                     dict(periodo='year'), dict(periodo='month', mes='2026-11', tipo='HISTORICAL'),
                     dict(periodo='month', mes='2026-09', tipo='FUTURE'),
                     dict(periodo='day', fecha='2026-10-28', tipo='HISTORICAL')]:
            with self.subTest(data=data):
                self.assertFalse(self.form(**data).is_valid())

    def test_default_uses_local_day_and_legacy_range_is_supported(self):
        with patch('django.utils.timezone.now', return_value=datetime(2026, 10, 28, 2, tzinfo=ZoneInfo('UTC'))):
            form = self.form()
            self.assertTrue(form.is_valid(), form.errors)
            self.assertEqual(form.cleaned_data['fecha_inicio'], date(2026, 10, 27))
            self.assertEqual(form.cleaned_data['fecha_fin'], date(2026, 10, 27))
        old = self.form(fecha_inicio='2026-09-01', fecha_fin='2026-09-30')
        self.assertTrue(old.is_valid())
        self.assertEqual(old.cleaned_data['fecha_fin'], date(2026, 9, 30))

    def test_kpis_charts_and_analysis_contract_match_existing_range(self):
        url = reverse('reservations:admin_dashboard')
        old = self.client.get(url, {'fecha_inicio':'2026-09-01', 'fecha_fin':'2026-09-30'})
        new = self.client.get(url, {'periodo':'month', 'mes':'2026-09'})
        self.assertEqual(new.context['dashboard_data'], old.context['dashboard_data'])
        self.assertEqual(new.context['chart_data'], old.context['chart_data'])
        self.assertEqual(new.context['analysis_filters'], old.context['analysis_filters'])
        self.assertEqual(new.context['total_canchas'], 1)
        self.assertEqual(new.context['completadas'], 1)
        self.assertNotContains(new, 'Cancha ajena')
        self.assertNotContains(new, 'Arena ajena')
        self.assertNotContains(new, '<label for="id_fecha_inicio"')
        self.assertNotContains(new, '<label for="id_fecha_fin"')

    def test_venue_court_source_and_type_filters_are_preserved(self):
        response = self.client.get(reverse('reservations:admin_dashboard'), dict(periodo='day', fecha='2026-09-15',
            origen='SYSTEM', tipo='HISTORICAL', establecimiento=self.venue.pk, cancha=self.court.pk))
        self.assertTrue(response.context['filtros_validos'])
        self.assertEqual(response.context['completadas'], 1)
        forbidden = self.form(periodo='month', mes='2026-09', cancha=self.foreign_court.pk)
        self.assertFalse(forbidden.is_valid())

    def test_all_admin_pages_share_base_and_exact_navigation(self):
        from html.parser import HTMLParser
        class Links(HTMLParser):
            def __init__(self):
                super().__init__(); self.in_nav=False; self.links=[]
            def handle_starttag(self, tag, attrs):
                attrs=dict(attrs)
                if tag=='nav':self.in_nav=True
                if tag=='a' and self.in_nav:self.links.append(attrs)
            def handle_endtag(self, tag):
                if tag=='nav':self.in_nav=False
        cases=[('reservations:admin_dashboard', (), 'reservations:admin_dashboard'),
               ('reservations:admin_reservas', (), 'reservations:admin_reservas'),
               ('reservations:admin_crear_reserva', (), 'reservations:admin_reservas'),
               ('reservations:admin_detalle_reserva', (self.reservation.pk,), 'reservations:admin_reservas'),
               ('courts:admin_canchas', (), 'courts:admin_canchas'),
               ('courts:admin_editar_cancha', (self.court.pk,), 'courts:admin_canchas'),
               ('courts:admin_editar_establecimiento', (self.venue.pk,), 'courts:admin_canchas'),
               ('users:profile', (), 'users:profile'),
               ('users:password_change', (), 'users:profile'),
               ('users:password_change_done', (), 'users:profile')]
        for route,args,active in cases:
            with self.subTest(route=route):
                response=self.client.get(reverse(route,args=args))
                self.assertEqual(response.status_code,200)
                self.assertTemplateUsed(response,'users/admin_base.html')
                self.assertContains(response,'users/css/admin.css')
                self.assertContains(response,'Cerrar sesión',count=1)
                parser=Links();parser.feed(response.content.decode())
                self.assertEqual([a['href'] for a in parser.links], [reverse('reservations:admin_dashboard'),reverse('reservations:admin_dashboard'),reverse('reservations:admin_reservas'),reverse('courts:admin_canchas'),reverse('users:profile')])
                self.assertEqual([a['href'] for a in parser.links if a.get('aria-current')=='page'],[reverse(active)])

    def test_normal_user_keeps_public_account_layout(self):
        normal=get_user_model().objects.create_user('normal_period')
        self.client.force_login(normal)
        response=self.client.get(reverse('users:profile'))
        self.assertTemplateNotUsed(response,'users/admin_base.html')
        self.assertContains(response,'Mis reservas')
        self.assertNotContains(response,'users/css/admin.css')
