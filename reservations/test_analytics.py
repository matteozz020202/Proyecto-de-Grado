from datetime import date, datetime, time, timedelta
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from courts.models import Court, CourtSchedule, Venue
from .analytics import dashboard_data, occupancy
from .forms import DashboardFilterForm
from .models import Payment, Reservation


class AnalyticsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="admin", is_staff=True)
        self.venue = Venue.objects.create(venue_name="Arena", address="Calle 1")
        self.court = Court.objects.create(venue=self.venue, court_name="A", price_per_hour=120000)
        self.day = date(2026, 1, 5)  # Lunes: isoweekday() == 1.
        clock = patch("django.utils.timezone.now",
                      return_value=datetime(2026, 10, 4, 12, tzinfo=ZoneInfo("America/Bogota")))
        clock.start()
        self.addCleanup(clock.stop)

    def schedule(self, court=None, start=8, end=20, day=1, active=True):
        return CourtSchedule.objects.create(court=court or self.court, day_of_week=day,
                                            start_time=time(start), end_time=time(end), is_active=active)

    def reserve(self, court=None, start=8, end=9, status="COMPLETED", day=None, source="SYNTHETIC"):
        return Reservation.objects.create(user=self.user, court=court or self.court,
                                          reservation_date=day or self.day,
                                          start_time=time(start), end_time=time(end),
                                          total_amount=120000, reservation_status=status, data_source=source)

    def metric(self, kind="HISTORICAL", start=None, end=None):
        return occupancy(Court.objects.select_related("venue"), Reservation.objects.all(),
                         start or self.day, end or self.day, kind)

    def test_historical_excludes_all_states_except_completed(self):
        self.schedule()
        for hour, state in enumerate(["COMPLETED", "CONFIRMED", "CANCELLED", "EXPIRED", "PENDING_PAYMENT"], 8):
            self.reserve(start=hour, end=hour+1, status=state)
        metric = self.metric()
        self.assertEqual(metric["horas_reservadas"], Decimal(1))
        self.assertEqual(metric["horas_disponibles"], Decimal(12))
        self.assertEqual(metric["reservas_validas"], 1)

    def test_global_occupancy_uses_weighted_capacity_instead_of_average(self):
        second = Court.objects.create(venue=self.venue, court_name="B", price_per_hour=120000)
        self.schedule(start=8, end=10)
        self.schedule(court=second, start=8, end=14)
        self.reserve(start=8, end=10)
        metric = self.metric()
        self.assertEqual(metric["ocupacion"], Decimal(25))
        self.assertEqual([row["ocupacion"] for row in metric["por_cancha"]], [Decimal(100), Decimal(0)])

    def test_overlapping_schedules_are_unioned_and_inactive_ones_excluded(self):
        self.schedule(start=8, end=12)
        self.schedule(start=10, end=14)
        self.schedule(start=8, end=20, active=False)
        self.assertEqual(self.metric()["horas_disponibles"], Decimal(6))

    def test_zero_capacity_returns_null_and_reports_inconsistency(self):
        self.reserve()
        metric = self.metric()
        self.assertIsNone(metric["ocupacion"])
        self.assertIsNone(metric["por_cancha"][0]["ocupacion"])
        self.assertEqual(metric["horas_reservadas"], Decimal(1))
        self.assertTrue(metric["capacidad_inconsistente"])

    def test_future_uses_confirmed_and_ignores_inactive_court_capacity(self):
        second = Court.objects.create(venue=self.venue, court_name="Inactiva", price_per_hour=120000,
                                      is_active=False)
        self.schedule(start=8, end=10)
        self.schedule(court=second, start=8, end=20)
        future = date(2026, 10, 5)
        self.reserve(day=future, status="CONFIRMED")
        self.reserve(day=future, start=9, end=10, status="PENDING_PAYMENT")
        self.reserve(day=future, start=10, end=11, status="COMPLETED")
        metric = self.metric(kind="FUTURE", start=future, end=future)
        self.assertEqual(metric["horas_disponibles"], Decimal(2))
        self.assertEqual(metric["horas_reservadas"], Decimal(1))
        self.assertEqual(metric["ocupacion"], Decimal(50))

    def test_date_boundaries_are_inclusive_and_weekdays_use_one_to_seven(self):
        self.schedule(start=8, end=10, day=7)
        self.schedule(start=8, end=11, day=1)
        sunday = self.day - timedelta(days=1)
        self.reserve(day=sunday)
        self.reserve(day=self.day)
        self.reserve(day=self.day + timedelta(days=1))
        metric = self.metric(start=sunday, end=self.day)
        self.assertEqual(metric["horas_disponibles"], Decimal(5))
        self.assertEqual(metric["reservas_validas"], 2)
        self.assertEqual(metric["ocupacion"], Decimal(40))

    def test_future_today_counts_only_remaining_hours_in_bogota(self):
        today = date(2026, 10, 4)  # Domingo, el reloj de la prueba marca las 12:00.
        self.schedule(start=8, end=16, day=7)
        self.reserve(day=today, start=8, end=9, status="CONFIRMED")
        self.reserve(day=today, start=11, end=13, status="CONFIRMED")
        self.reserve(day=today, start=14, end=15, status="CONFIRMED")
        metric = self.metric(kind="FUTURE", start=today, end=today)
        self.assertEqual(metric["horas_disponibles"], Decimal(4))
        self.assertEqual(metric["horas_reservadas"], Decimal(2))
        self.assertEqual(metric["reservas_validas"], 2)
        self.assertEqual(metric["ocupacion"], Decimal(50))

    def test_invalid_filters_show_errors_without_unfiltered_metrics(self):
        self.client.force_login(self.user)
        url = reverse("reservations:admin_dashboard")
        other = Venue.objects.create(venue_name="Otro", address="Otra")
        cases = [
            {"fecha_inicio": "bad-date"},
            {"fecha_inicio": "2026-01-02", "fecha_fin": "2026-01-01"},
            {"fecha_inicio": "2025-01-01", "fecha_fin": "2026-10-04"},
            {"establecimiento": other.pk, "cancha": self.court.pk},
            {"cancha": "9999999999999999999999999999999999"},
            {"tipo": "UNKNOWN"},
            {"tipo": "HISTORICAL", "fecha_fin": "2026-11-01"},
            {"tipo": "FUTURE", "fecha_inicio": "2026-01-01"},
        ]
        for params in cases:
            with self.subTest(params=params):
                response = self.client.get(url, params)
                self.assertEqual(response.status_code, 200)
                self.assertFalse(response.context["filtros_validos"])
                self.assertTrue(response.context["form"].errors)
                self.assertNotIn("ocupacion", response.context)

    def test_filters_apply_to_occupancy_payments_and_status_counts(self):
        self.schedule(start=8, end=10)
        chosen = self.reserve()
        other_court = Court.objects.create(venue=self.venue, court_name="Otra", price_per_hour=120000)
        self.schedule(court=other_court, start=8, end=20)
        excluded_court = self.reserve(court=other_court)
        excluded_source = self.reserve(start=9, end=10, source="SYSTEM")
        excluded_date = self.reserve(day=self.day + timedelta(days=7))
        for reservation, amount, status, ref in [
            (chosen, 36000, "APPROVED", "chosen"),
            (chosen, 36000, "REJECTED", "rejected"),
            (excluded_court, 50000, "APPROVED", "other-court"),
            (excluded_source, 50000, "APPROVED", "other-source"),
            (excluded_date, 50000, "APPROVED", "other-date"),
        ]:
            Payment.objects.create(reservation=reservation, amount=amount,
                                   payment_status=status, transaction_reference=ref)
        self.client.force_login(self.user)
        response = self.client.get(reverse("reservations:admin_dashboard"), {
            "origen": "SYNTHETIC", "establecimiento": self.venue.pk, "cancha": self.court.pk,
            "fecha_inicio": self.day.isoformat(), "fecha_fin": self.day.isoformat(),
        })
        self.assertTrue(response.context["filtros_validos"])
        self.assertEqual(response.context["ocupacion"]["ocupacion"], Decimal(50))
        self.assertEqual(response.context["completadas"], 1)
        self.assertEqual(response.context["ingresos_aprobados"], Decimal(36000))
        self.assertEqual(response.context["pagos_aprobados"], 1)
        self.assertEqual(response.context["total_canchas"], 1)
        self.assertContains(response, "No representa el comportamiento real")
        self.assertContains(response, "$36.000,00")
        charts = response.context["chart_data"]
        monday = charts["occupancy_by_day"][0]
        self.assertEqual(monday["occupancy_rate"], 50)
        self.assertEqual(monday["reserved_hours"], 1)
        self.assertEqual(monday["available_hours"], 2)
        self.assertEqual(charts["reservation_status_distribution"], [
            {"status": "COMPLETED", "label": "Completada", "count": 1},
        ])
        self.assertEqual(response.context["dashboard_data"]["analysis_context"]["court_ids"], [self.court.pk])
        self.assertEqual(list(response.context["ultimas_reservas"]), [chosen])
        self.assertContains(response, 'id="dashboard-chart-data"')

    def test_court_choices_are_scoped_to_venue_and_reject_foreign_courts(self):
        other_venue = Venue.objects.create(venue_name="Otro venue", address="Calle 2")
        other_court = Court.objects.create(venue=other_venue, court_name="Otra", price_per_hour=120000)
        form = DashboardFilterForm({"establecimiento": str(self.venue.pk)})
        self.assertTrue(form.is_valid())
        self.assertEqual(list(form.fields["cancha"].queryset), [self.court])
        # El navegador dispone del catálogo para cambiar de venue sin enviar el formulario.
        self.assertEqual({option["id"] for option in form.court_options},
                         {str(self.court.pk), str(other_court.pk)})
        invalid = DashboardFilterForm({"establecimiento": str(self.venue.pk), "cancha": str(other_court.pk)})
        self.assertFalse(invalid.is_valid())
        self.assertIn("cancha", invalid.errors)
        all_venues = DashboardFilterForm({})
        self.assertEqual(all_venues.fields["cancha"].queryset.count(), 2)

    def test_default_and_future_dates_respect_bogota_timezone(self):
        # 1 de octubre UTC todavía es 30 de septiembre en Bogotá.
        with patch("django.utils.timezone.now", return_value=datetime(2026, 10, 1, 2, tzinfo=ZoneInfo("UTC"))):
            historical = DashboardFilterForm({})
            future = DashboardFilterForm({"tipo": "FUTURE"})
            self.assertTrue(historical.is_valid())
            self.assertTrue(future.is_valid())
            self.assertEqual(historical.cleaned_data["fecha_fin"], date(2026, 9, 30))
            self.assertEqual(future.cleaned_data["fecha_inicio"], date(2026, 9, 30))

    def test_hourly_splits_partial_hours_and_unions_capacity(self):
        CourtSchedule.objects.create(court=self.court, day_of_week=1,
                                     start_time=time(8, 30), end_time=time(10, 30))
        self.schedule(start=9, end=11)
        Reservation.objects.create(user=self.user, court=self.court,
                                   reservation_date=self.day, start_time=time(8, 45), end_time=time(10, 15),
                                   total_amount=120000, reservation_status="COMPLETED")
        result = self.metric()
        slots = result["occupancy_by_time_slot"]
        self.assertEqual([row["available_hours"] for row in slots], [Decimal('.5'), Decimal(1), Decimal(1)])
        self.assertEqual([row["reserved_hours"] for row in slots], [Decimal('.25'), Decimal(1), Decimal('.25')])
        self.assertEqual([row["occupancy_rate"] for row in slots], [Decimal(50), Decimal(100), Decimal(25)])
        self.assertEqual(sum(row["reserved_hours"] for row in slots), result["horas_reservadas"])
        self.assertEqual(sum(row["available_hours"] for row in slots), result["horas_disponibles"])
        self.assertEqual(result["occupancy_by_day"][0]["occupancy_rate"], Decimal(60))
        self.assertIsNone(result["occupancy_by_day"][1]["occupancy_rate"])

    def test_cancellation_denominator_and_deposits_exclude_balances_and_rejections(self):
        self.schedule()
        for hour, status in enumerate(["COMPLETED", "CONFIRMED", "CANCELLED", "EXPIRED", "PENDING_PAYMENT"], 8):
            self.reserve(start=hour, end=hour+1, status=status)
        reservation = Reservation.objects.get(reservation_status="COMPLETED")
        for amount, kind, status, ref in [
            (36000, "DEPOSIT", "APPROVED", "deposit"),
            (84000, "BALANCE", "APPROVED", "balance"),
            (36000, "DEPOSIT", "REJECTED", "rejected"),
        ]:
            Payment.objects.create(reservation=reservation, amount=amount, payment_type=kind,
                                   payment_status=status, transaction_reference=ref)
        data = dashboard_data(Court.objects.select_related("venue"), Reservation.objects.all(),
                              self.day, self.day, "HISTORICAL", "SYNTHETIC")
        self.assertEqual(data["summary"]["cancellation_rate"], Decimal(100) / 3)
        self.assertEqual(data["summary"]["approved_deposits"], Decimal(36000))
        self.assertEqual(data["approved_payments"], Decimal(120000))
        self.assertEqual(data["summary"]["reservation_value"], Decimal(120000))
        self.assertEqual(len(data["reservation_status_distribution"]), 5)

    def test_empty_data_preserves_nulls_and_synthetic_notice(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("reservations:admin_dashboard"), {
            "origen": "SYNTHETIC", "fecha_inicio": self.day.isoformat(), "fecha_fin": self.day.isoformat(),
        })
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["dashboard_data"]["summary"]["cancellation_rate"])
        self.assertEqual(response.context["chart_data"]["occupancy_by_time_slot"], [])
        self.assertEqual(response.context["chart_data"]["reservation_status_distribution"], [])
        self.assertTrue(all(row["occupancy_rate"] is None for row in response.context["chart_data"]["occupancy_by_day"]))
        self.assertContains(response, "datos sintéticos")
        self.assertContains(response, "No se ha generado un análisis inteligente")

    def test_zero_reservations_with_capacity_is_zero_not_null(self):
        self.schedule(start=8, end=10)
        result = self.metric()
        self.assertEqual(result["ocupacion"], Decimal(0))
        self.assertEqual(result["occupancy_by_day"][0]["occupancy_rate"], Decimal(0))
        self.assertEqual([row["occupancy_rate"] for row in result["occupancy_by_time_slot"]], [Decimal(0), Decimal(0)])

    def test_future_charts_share_remaining_hour_semantics(self):
        self.schedule(start=8, end=16, day=7)
        today = date(2026, 10, 4)
        self.reserve(day=today, start=11, end=13, status="CONFIRMED")
        self.reserve(day=today, start=14, end=15, status="COMPLETED")
        result = self.metric(kind="FUTURE", start=today, end=today)
        slots = result["occupancy_by_time_slot"]
        self.assertEqual([row["label"] for row in slots], ['12:00–13:00', '13:00–14:00', '14:00–15:00', '15:00–16:00'])
        self.assertEqual([row["occupancy_rate"] for row in slots], [Decimal(100), Decimal(0), Decimal(0), Decimal(0)])
        self.assertEqual(result["occupancy_by_day"][6]["occupancy_rate"], Decimal(25))
