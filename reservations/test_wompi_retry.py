from datetime import time, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from courts.models import Court, CourtSchedule, Venue

from .models import Payment, WompiTransaction
from .services import create_pending_reservation, create_wompi_payment_attempt


@override_settings(WOMPI_CHECKOUT_ENABLED=True)
class WompiRetryPaymentTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="retry_owner",
            password="TestPassword123!",
        )
        self.other_user = User.objects.create_user(
            username="retry_other",
            password="TestPassword123!",
        )
        venue = Venue.objects.create(
            venue_name="Arena Retry",
            deposit_percentage=30,
        )
        court = Court.objects.create(
            venue=venue,
            court_name="Cancha Retry",
            price_per_hour=100000,
        )
        day = timezone.localdate() + timedelta(days=5)
        CourtSchedule.objects.create(
            court=court,
            day_of_week=day.isoweekday(),
            start_time=time(8),
            end_time=time(22),
        )
        self.reservation = create_pending_reservation(
            user=self.user,
            court=court,
            reservation_date=day,
            start_time=time(15),
            end_time=time(16),
        )
        self.payment = create_wompi_payment_attempt(self.reservation)
        self.url = reverse(
            "reservations:reintentar_pago_wompi",
            kwargs={"reserva_id": self.reservation.pk},
        )
        self.client.force_login(self.user)

    def mark_declined(self):
        transaction_id = "TX-DECLINED-RETRY-001"
        self.payment.payment_status = "DECLINED"
        self.payment.provider_transaction_id = transaction_id
        self.payment.save(
            update_fields=["payment_status", "provider_transaction_id"]
        )
        WompiTransaction.objects.create(
            payment=self.payment,
            provider_transaction_id=transaction_id,
            status="DECLINED",
            amount_in_cents=int(self.payment.amount * 100),
            currency="COP",
        )

    def test_verified_decline_shows_retry_button(self):
        self.mark_declined()

        response = self.client.get(reverse("reservations:mis_reservas"))

        self.assertContains(response, "Intentar pagar nuevamente")
        self.assertNotContains(response, "Continuar pago con Wompi")

    def test_retry_creates_new_pending_attempt_with_unique_reference(self):
        self.mark_declined()
        previous_reference = self.payment.transaction_reference

        response = self.client.post(self.url)

        self.assertRedirects(
            response,
            reverse(
                "reservations:pagar_reserva",
                kwargs={"reserva_id": self.reservation.pk},
            ),
            fetch_redirect_response=False,
        )
        payments = Payment.objects.filter(
            reservation=self.reservation,
            provider="WOMPI",
        ).order_by("created_at", "pk")
        self.assertEqual(payments.count(), 2)
        retry = payments.last()
        self.assertEqual(retry.payment_status, "PENDING")
        self.assertNotEqual(retry.transaction_reference, previous_reference)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.payment_status, "DECLINED")

    def test_repeated_post_reuses_pending_retry(self):
        self.mark_declined()

        self.client.post(self.url)
        self.client.post(self.url)

        self.assertEqual(
            Payment.objects.filter(
                reservation=self.reservation,
                provider="WOMPI",
            ).count(),
            2,
        )

    def test_other_user_cannot_retry(self):
        self.mark_declined()
        self.client.force_login(self.other_user)

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            Payment.objects.filter(reservation=self.reservation).count(),
            1,
        )

    def test_retry_requires_post(self):
        self.mark_declined()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 405)
        self.assertEqual(
            Payment.objects.filter(reservation=self.reservation).count(),
            1,
        )

    def test_unverified_decline_cannot_retry(self):
        self.payment.payment_status = "DECLINED"
        self.payment.save(update_fields=["payment_status"])

        response = self.client.post(self.url)

        self.assertRedirects(
            response,
            reverse("reservations:mis_reservas"),
            fetch_redirect_response=False,
        )
        self.assertEqual(
            Payment.objects.filter(reservation=self.reservation).count(),
            1,
        )

    def test_pending_provider_transaction_blocks_retry(self):
        WompiTransaction.objects.create(
            payment=self.payment,
            provider_transaction_id="TX-STILL-PENDING-RETRY-001",
            status="PENDING",
            amount_in_cents=int(self.payment.amount * 100),
            currency="COP",
        )

        response = self.client.post(self.url)

        self.assertRedirects(
            response,
            reverse("reservations:mis_reservas"),
            fetch_redirect_response=False,
        )
        self.assertEqual(
            Payment.objects.filter(reservation=self.reservation).count(),
            1,
        )

    def test_expired_hold_blocks_retry(self):
        self.mark_declined()
        self.reservation.hold_expires_at = timezone.now() - timedelta(seconds=1)
        self.reservation.save(update_fields=["hold_expires_at"])

        response = self.client.post(self.url)

        self.assertRedirects(
            response,
            reverse("reservations:mis_reservas"),
            fetch_redirect_response=False,
        )
        self.assertEqual(
            Payment.objects.filter(reservation=self.reservation).count(),
            1,
        )
