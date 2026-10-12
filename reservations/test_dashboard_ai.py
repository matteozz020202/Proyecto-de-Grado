"""KPIs y análisis manual: alcance, privacidad, autorización, CSRF y fallback."""

from datetime import date, datetime, time, timedelta
import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth.models import Group, User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from courts.models import Court, CourtSchedule, Venue
from .ai.adapters import AnalysisContextError, build_analysis_input
from .ai.schemas import AIAnalysis
from .analytics import dashboard_data
from .dashboard_scope import filtered_scope
from .forms import DashboardFilterForm
from .models import Payment, Reservation
from .test_ai import example_output


@override_settings(OPENAI_API_KEY="credential-for-offline-tests", OPENAI_MODEL="configured-test-model")
class DashboardAITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="staff", is_staff=True, email="private@example.test")
        self.venue = Venue.objects.create(venue_name="Arena", address="Calle 1")
        self.court = Court.objects.create(venue=self.venue, court_name="Cancha A", price_per_hour=120000)
        self.day = date(2026, 1, 5)
        self.clock = patch("django.utils.timezone.now", return_value=datetime(2026, 10, 4, 12, tzinfo=ZoneInfo("America/Bogota")))
        self.clock.start()
        self.addCleanup(self.clock.stop)
        CourtSchedule.objects.create(court=self.court, day_of_week=1, start_time=time(8), end_time=time(10))
        self.reservation = self.reserve()
        self.params = {"origen": "SYNTHETIC", "establecimiento": str(self.venue.pk), "cancha": str(self.court.pk),
                       "fecha_inicio": self.day.isoformat(), "fecha_fin": self.day.isoformat(), "tipo": "HISTORICAL"}
        self.url = reverse("reservations:admin_dashboard_analysis")
        self.dashboard = reverse("reservations:admin_dashboard")
        self.client.force_login(self.user)
        self.factory_patch = patch("reservations.ai.services.OpenAI")
        self.factory = self.factory_patch.start()
        self.addCleanup(self.factory_patch.stop)
        self.api = self.factory.return_value.__enter__.return_value
        self.api.responses.parse.return_value = self.response(example_output())
        self.sleep_patch = patch("reservations.ai.services.time.sleep")
        self.sleep_patch.start()
        self.addCleanup(self.sleep_patch.stop)

    def reserve(self, status="COMPLETED", source="SYNTHETIC", day=None, court=None, start=8, end=9):
        return Reservation.objects.create(user=self.user, court=court or self.court,
            reservation_date=day or self.day, start_time=time(start), end_time=time(end),
            total_amount=120000, deposit_required=36000, remaining_amount=84000,
            reservation_status=status, data_source=source)

    @staticmethod
    def response(output):
        return SimpleNamespace(status="completed", output=[], output_parsed=AIAnalysis.model_validate(output))

    def data(self, params=None):
        form = DashboardFilterForm(params or self.params)
        self.assertTrue(form.is_valid(), form.errors)
        filters = form.cleaned_data
        courts, reservations = filtered_scope(filters)
        data = dashboard_data(courts, reservations, filters["fecha_inicio"], filters["fecha_fin"],
                              filters["tipo"], filters["origen"])
        return filters, data, courts, reservations

    def payload(self, params=None):
        return build_analysis_input(*self.data(params))

    def test_dashboard_get_never_calls_api_and_keeps_filters(self):
        response = self.client.get(self.dashboard, self.params)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-state="IDLE"')
        self.assertContains(response, 'name="cancha" value="' + str(self.court.pk) + '"')
        self.assertContains(response, 'name="fecha_inicio" value="2026-01-05"')
        self.assertContains(response, "Completadas del análisis histórico")
        self.assertNotContains(response, "credential-for-offline-tests")
        self.factory.assert_not_called()

    def test_post_generates_with_exact_filtered_kpis_and_no_personal_data(self):
        other = Venue.objects.create(venue_name="Otra", address="Otra")
        other_court = Court.objects.create(venue=other, court_name="Otra", price_per_hour=120000)
        self.reserve(court=other_court)
        self.reserve(source="SYSTEM", start=9, end=10)
        self.reserve(status="CONFIRMED", start=10, end=11)
        response = self.client.post(self.url, self.params)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["state"], "SUCCESS")
        self.assertIn("Limitaciones", response.json()["html"])
        self.assertIn("datos sintéticos", response.json()["html"])
        request = self.api.responses.parse.call_args.kwargs
        sent = json.loads(request["input"][-1]["content"])
        self.assertEqual(sent["summary"]["valid_reservations"], 1)
        self.assertEqual(sent["summary"]["occupancy_rate"], 50)
        self.assertEqual(sent["analysis_context"]["court_id"], self.court.pk)
        self.assertEqual(sent["analysis_context"]["data_source"], "SYNTHETIC")
        self.assertNotIn(self.user.email, request["input"][-1]["content"])
        for field in ("email", "user_id", "transaction_reference", "password", "reservation_id"):
            self.assertNotIn(field, request["input"][-1]["content"])

    def test_empty_insights_render_successful_empty_state(self):
        self.api.responses.parse.return_value = self.response(example_output(False))
        response = self.client.post(self.url, self.params)
        self.assertEqual(response.json()["state"], "SUCCESS")
        self.assertIn("No se identificaron hallazgos", response.json()["html"])

    def test_contract_uses_dashboard_precision_before_generation(self):
        CourtSchedule.objects.filter(court=self.court).update(end_time=time(11))
        output = example_output()
        output["insights"][0]["evidence"][0]["value"] = 33.33
        self.api.responses.parse.return_value = self.response(output)
        self.assertEqual(self.payload().summary.occupancy_rate, 33.33)
        self.assertEqual(self.client.post(self.url, self.params).status_code, 200)

    def test_invalid_analysis_is_not_rendered_and_dashboard_still_works(self):
        output = example_output()
        output["insights"][0]["evidence"][0]["value"] = 31
        output["insights"][0]["finding"] = "UNVALIDATED_FINDING"
        self.api.responses.parse.return_value = self.response(output)
        response = self.client.post(self.url, self.params)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["state"], "ERROR")
        self.assertNotIn("UNVALIDATED_FINDING", response.json()["html"])
        self.assertEqual(self.api.responses.parse.call_count, 2)
        self.assertContains(self.client.get(self.dashboard, self.params), "Resumen del período")

    def test_missing_synthetic_notice_is_rejected(self):
        output = example_output(False)
        output["limitations"] = []
        self.api.responses.parse.return_value = self.response(output)
        self.assertEqual(self.client.post(self.url, self.params).status_code, 503)

    def test_model_text_is_escaped_in_html(self):
        output = example_output()
        output["insights"][0]["finding"] = '<script>alert("x")</script>'
        self.api.responses.parse.return_value = self.response(output)
        html = self.client.post(self.url, self.params).json()["html"]
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_invalid_filters_and_foreign_court_prevent_api_calls(self):
        other = Venue.objects.create(venue_name="Otro", address="Otra")
        for update in ({"fecha_inicio": "not-a-date"}, {"establecimiento": str(other.pk)},
                       {"origen": "UNSUPPORTED"}, {"fecha_fin": "2027-01-01"}):
            response = self.client.post(self.url, {**self.params, **update})
            self.assertEqual(response.status_code, 400, update)
        self.factory.assert_not_called()

    def test_all_origins_prevent_api_calls_and_disable_button(self):
        params = {**self.params, "origen": "ALL"}
        response = self.client.post(self.url, params)
        self.assertEqual(response.status_code, 400)
        self.assertIn("origen específico", response.json()["html"])
        page = self.client.get(self.dashboard, params)
        self.assertFalse(page.context["analysis_enabled"])
        self.factory.assert_not_called()

    def test_missing_configuration_keeps_dashboard_usable(self):
        with override_settings(OPENAI_API_KEY=""):
            page = self.client.get(self.dashboard, self.params)
            self.assertFalse(page.context["analysis_enabled"])
            self.assertEqual(self.client.post(self.url, self.params).status_code, 503)
        self.factory.assert_not_called()

    def test_permissions_and_http_method(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.client.logout()
        self.assertEqual(self.client.post(self.url, self.params).status_code, 302)
        normal = User.objects.create_user(username="normal")
        self.client.force_login(normal)
        self.assertEqual(self.client.post(self.url, self.params).status_code, 302)
        self.factory.assert_not_called()
        normal.groups.add(Group.objects.create(name="Administrador"))
        self.assertEqual(self.client.post(self.url, self.params).status_code, 200)

    def test_post_requires_csrf(self):
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.user)
        self.assertEqual(browser.post(self.url, self.params).status_code, 403)
        self.factory.assert_not_called()
        browser.get(self.dashboard, self.params)
        token = browser.cookies["csrftoken"].value
        self.assertEqual(browser.post(self.url, {**self.params, "csrfmiddlewaretoken": token}).status_code, 200)

    def test_pending_balance_is_clamped_per_reservation_not_globally(self):
        second = self.reserve(start=9, end=10)
        Payment.objects.create(reservation=self.reservation, amount=150000, payment_status="APPROVED",
                               transaction_reference="overpayment")
        Payment.objects.create(reservation=second, amount=36000, payment_status="REJECTED",
                               transaction_reference="rejected")
        summary = self.data()[1]["summary"]
        self.assertEqual(summary["pending_balance"], Decimal(120000))
        self.assertEqual(summary["reservation_value"], Decimal(240000))

    def test_future_summary_and_financial_metrics_exclude_completed(self):
        future = date(2026, 10, 5)
        self.reserve(status="CONFIRMED", day=future)
        self.reserve(day=future, start=9, end=10)
        params = {**self.params, "tipo": "FUTURE", "fecha_inicio": future.isoformat(), "fecha_fin": future.isoformat()}
        payload = self.payload(params)
        self.assertEqual(payload.summary.valid_reservations, 1)
        self.assertEqual(payload.summary.reservation_value, 120000)
        self.assertEqual(payload.summary.occupancy_rate, 50)
        self.assertIsNone(payload.comparisons.previous_period)

    def test_future_today_excludes_confirmed_that_have_finished(self):
        today = date(2026, 10, 4)
        CourtSchedule.objects.create(court=self.court, day_of_week=7, start_time=time(8), end_time=time(20))
        self.reserve(status="CONFIRMED", day=today, start=8, end=9)
        self.reserve(status="CONFIRMED", day=today, start=13, end=14)
        params = {**self.params, "tipo": "FUTURE", "fecha_inicio": today.isoformat(), "fecha_fin": today.isoformat()}
        self.assertEqual(self.payload(params).summary.valid_reservations, 1)

    def test_source_mapping_and_nulls_are_preserved(self):
        for local, contract in (("SYSTEM", "PLATFORM"), ("HISTORICAL_REAL", "HISTORICAL"), ("SYNTHETIC", "SYNTHETIC")):
            payload = self.payload({**self.params, "origen": local})
            self.assertEqual(payload.analysis_context.data_source, contract)
            self.assertIsNone(payload.summary.average_booking_lead_hours)
            self.assertIsNone(payload.comparisons.reservations_variation_pct)
        CourtSchedule.objects.all().delete()
        self.reservation.delete()
        payload = self.payload()
        self.assertIsNone(payload.summary.occupancy_rate)
        self.assertEqual(payload.extremes.highest_occupancy_days, [])

    def test_ties_keep_all_extremes_and_reference_formats(self):
        tomorrow = self.day + timedelta(days=1)
        CourtSchedule.objects.create(court=self.court, day_of_week=2, start_time=time(8), end_time=time(10))
        self.reserve(day=tomorrow)
        payload = self.payload({**self.params, "fecha_fin": tomorrow.isoformat()})
        self.assertEqual([row.reference for row in payload.extremes.highest_occupancy_days], ["Monday", "Tuesday"])
        self.assertTrue(all("–" not in row.time_slot for row in payload.occupancy_by_time_slot))

    def test_previous_period_uses_same_source_and_court_and_equal_duration(self):
        previous_day = self.day - timedelta(days=1)
        CourtSchedule.objects.create(court=self.court, day_of_week=7, start_time=time(8), end_time=time(10))
        self.reserve(day=previous_day)
        self.reserve(day=previous_day, source="SYSTEM", start=9, end=10)
        payload = self.payload()
        self.assertEqual(payload.comparisons.previous_period.start_date, previous_day.isoformat())
        self.assertEqual(payload.comparisons.previous_period.valid_reservations, 1)
        self.assertEqual(payload.comparisons.occupancy_variation_pp, 0)
        self.assertEqual(payload.comparisons.reservations_variation_pct, 0)

    def test_lead_time_uses_actual_booking_date_and_negative_values_stay_null(self):
        created = datetime(2026, 1, 4, 8, tzinfo=ZoneInfo("America/Bogota"))
        Reservation.objects.filter(pk=self.reservation.pk).update(created_at=created)
        self.assertEqual(self.payload().summary.average_booking_lead_hours, 24)
        Reservation.objects.filter(pk=self.reservation.pk).update(created_at=created + timedelta(days=2))
        self.assertIsNone(self.payload().summary.average_booking_lead_hours)

    def test_inconsistent_capacity_does_not_send_invalid_kpis(self):
        CourtSchedule.objects.all().delete()
        with self.assertRaises(AnalysisContextError):
            self.payload()
        self.assertEqual(self.client.post(self.url, self.params).status_code, 400)
        page = self.client.get(self.dashboard, self.params)
        self.assertFalse(page.context["analysis_enabled"])
        self.factory.assert_not_called()
