
from datetime import time, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from courts.models import Court, CourtSchedule, Venue

from .models import Payment, Reservation, WompiTransaction
from .services import (
    create_pending_reservation,
    create_wompi_payment_attempt,
)


TEST_WOMPI_KEYS = {
    "WOMPI_PUBLIC_KEY": "pub_test_EXAMPLE",
    "WOMPI_INTEGRITY_SECRET": "test_integrity_EXAMPLE",
}


@override_settings(WOMPI_CHECKOUT_ENABLED=True)
@patch.dict("os.environ", TEST_WOMPI_KEYS)
class WompiCheckoutViewTests(TestCase):

    def setUp(self):
        User = get_user_model()

        self.user = User.objects.create_user(
            username="checkout_owner",
            password="TestPassword123!",
        )

        self.other_user = User.objects.create_user(
            username="checkout_other_user",
            password="TestPassword123!",
        )

        venue = Venue.objects.create(
            venue_name="Arena Checkout Test",
            deposit_percentage=30,
        )

        court = Court.objects.create(
            venue=venue,
            court_name="Cancha Checkout Test",
            price_per_hour=130000,
        )

        reservation_day = (
            timezone.localdate() + timedelta(days=7)
        )

        CourtSchedule.objects.create(
            court=court,
            day_of_week=reservation_day.isoweekday(),
            start_time=time(8),
            end_time=time(22),
        )

        self.reservation = create_pending_reservation(
            user=self.user,
            court=court,
            reservation_date=reservation_day,
            start_time=time(18),
            end_time=time(19),
        )

        self.payment = create_wompi_payment_attempt(
            self.reservation
        )

        self.url = reverse(
            "reservations:pagar_reserva",
            kwargs={
                "reserva_id": self.reservation.pk,
            },
        )

        self.client.force_login(self.user)

    def test_owner_can_view_wompi_checkout(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)

        self.assertTemplateUsed(
            response,
            "reservations/pagar_reserva.html",
        )

        self.assertContains(
            response,
            "Pagar abono con Wompi Sandbox",
        )

        self.assertContains(
            response,
            'name="public-key"',
        )

        self.assertContains(
            response,
            'name="amount-in-cents"',
        )

        self.assertContains(
            response,
            'name="signature:integrity"',
        )

        self.assertContains(
            response,
            'name="expiration-time"',
        )

        self.assertContains(
            response,
            self.payment.transaction_reference,
        )

        self.assertNotContains(
            response,
            "Simular pago aprobado",
        )

        self.assertNotContains(
            response,
            "Simular pago rechazado",
        )

        self.assertEqual(
            Payment.objects.filter(
                reservation=self.reservation
            ).count(),
            1,
        )

    def test_other_user_cannot_view_checkout(self):
        self.client.force_login(self.other_user)

        response = self.client.get(self.url)

        self.assertEqual(
            response.status_code,
            404,
        )

    def test_expired_hold_cannot_open_checkout(self):
        Reservation.objects.filter(
            pk=self.reservation.pk
        ).update(
            hold_expires_at=(
                timezone.now() - timedelta(minutes=1)
            )
        )

        response = self.client.get(self.url)

        self.assertEqual(
            response.status_code,
            302,
        )

        self.assertEqual(
            response.url,
            reverse("reservations:mis_reservas"),
        )

        self.assertNotEqual(
            response.status_code,
            200,
        )

    def test_simulated_approval_post_is_blocked(self):
        response = self.client.post(
            self.url,
            {
                "resultado": "APPROVED",
            },
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.assertEqual(
            response.url,
            reverse("reservations:mis_reservas"),
        )

        self.reservation.refresh_from_db()
        self.payment.refresh_from_db()

        self.assertEqual(
            self.reservation.reservation_status,
            "PENDING_PAYMENT",
        )

        self.assertEqual(
            self.payment.payment_status,
            "PENDING",
        )

        self.assertFalse(
            Payment.objects.filter(
                reservation=self.reservation,
                payment_status="APPROVED",
            ).exists()
        )

    def test_checkout_requires_existing_wompi_payment(self):
        self.payment.delete()

        response = self.client.get(self.url)

        self.assertEqual(
            response.status_code,
            302,
        )

        self.assertEqual(
            response.url,
            reverse("reservations:mis_reservas"),
        )

        self.reservation.refresh_from_db()

        self.assertEqual(
            self.reservation.reservation_status,
            "PENDING_PAYMENT",
        )

        self.assertFalse(
            Payment.objects.filter(
                reservation=self.reservation
            ).exists()
        )



    @override_settings(
        WOMPI_PUBLIC_BASE_URL="https://cancha-lista.ngrok-free.app"
    )
    def test_checkout_has_correct_redirect_url(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)

        expected_url = (
            "https://cancha-lista.ngrok-free.app"
            + reverse(
                "reservations:wompi_payment_return",
                kwargs={
                    "reserva_id": self.reservation.pk,
                },
            )
        )

        checkout = response.context["checkout"]

        self.assertEqual(
            checkout["redirect_url"],
            expected_url,
        )

        self.assertContains(
            response,
            'name="redirect-url"',
        )

    @override_settings(
        WOMPI_PUBLIC_BASE_URL="",
        LOCAL_TUNNEL_URL="",
    )
    def test_checkout_omits_redirect_without_public_https_origin(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["checkout"]["redirect_url"], "")
        self.assertNotContains(response, 'name="redirect-url"')


    def test_redirect_url_does_not_change_payment_status(self):
        response = self.client.get(self.url)

        self.assertEqual(
            response.status_code,
            200,
        )

        self.payment.refresh_from_db()
        self.reservation.refresh_from_db()

        self.assertEqual(
            self.payment.payment_status,
            "PENDING",
        )

        self.assertEqual(
            self.reservation.reservation_status,
            "PENDING_PAYMENT",
        )

        self.assertFalse(
            Payment.objects.filter(
                reservation=self.reservation,
                payment_status="APPROVED",
            ).exists()
        )

    def test_my_reservations_allows_safe_checkout_resume(self):
        response = self.client.get(
            reverse("reservations:mis_reservas")
        )

        self.assertContains(response, "Continuar pago con Wompi")
        self.assertContains(response, "Consultar estado del pago")
        self.assertContains(response, "Tiempo restante para pagar")
        self.assertContains(response, 'class="payment-countdown"')

    def test_my_reservations_blocks_resume_for_known_pending_transaction(self):
        WompiTransaction.objects.create(
            payment=self.payment,
            provider_transaction_id="TX-PENDING-NAVIGATION-001",
            status="PENDING",
            amount_in_cents=int(self.payment.amount * 100),
            currency="COP",
        )

        response = self.client.get(
            reverse("reservations:mis_reservas")
        )

        self.assertNotContains(response, "Continuar pago con Wompi")
        self.assertContains(response, "Consultar estado del pago")
