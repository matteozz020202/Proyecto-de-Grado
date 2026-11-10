
from datetime import time, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from courts.models import Court, CourtSchedule, Venue

from .models import Payment, Reservation


FAKE_WOMPI_KEYS = {
    "WOMPI_PUBLIC_KEY": "pub_test_EXAMPLE",
    "WOMPI_INTEGRITY_SECRET": "test_integrity_EXAMPLE",
}


@override_settings(WOMPI_CHECKOUT_ENABLED=True)
@patch.dict("os.environ", FAKE_WOMPI_KEYS)
class WompiPublicBookingFlowTests(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="wompi_public_booking_user",
            password="TestPassword123!",
        )

        venue = Venue.objects.create(
            venue_name="Arena Public Booking Test",
            deposit_percentage=30,
        )

        self.court = Court.objects.create(
            venue=venue,
            court_name="Cancha Public Booking Test",
            price_per_hour=130000,
        )

        self.day = timezone.localdate() + timedelta(days=7)

        CourtSchedule.objects.create(
            court=self.court,
            day_of_week=self.day.isoweekday(),
            start_time=time(8),
            end_time=time(22),
        )

        self.url = reverse(
            "reservations:resumen_reserva",
            kwargs={
                "cancha_id": self.court.pk,
            },
        )

        self.data = {
            "fecha": self.day.isoformat(),
            "inicio": "18:00",
            "fin": "19:00",
        }

        self.client.force_login(self.user)

    def test_get_only_displays_review(self):
        response = self.client.get(
            self.url,
            self.data,
        )

        self.assertEqual(response.status_code, 200)

        self.assertEqual(
            Reservation.objects.count(),
            0,
        )

        self.assertEqual(
            Payment.objects.count(),
            0,
        )

    def test_post_creates_pending_reservation_and_payment(self):
        response = self.client.post(
            self.url,
            self.data,
        )

        self.assertEqual(response.status_code, 302)

        self.assertEqual(
            Reservation.objects.count(),
            1,
        )

        reservation = Reservation.objects.get()

        self.assertEqual(
            reservation.user,
            self.user,
        )

        self.assertEqual(
            reservation.reservation_status,
            "PENDING_PAYMENT",
        )

        self.assertIsNotNone(
            reservation.hold_expires_at,
        )

        self.assertEqual(
            Payment.objects.filter(
                reservation=reservation,
            ).count(),
            1,
        )

        payment = Payment.objects.get(
            reservation=reservation,
        )

        self.assertEqual(payment.provider, "WOMPI")

        self.assertEqual(
            payment.payment_type,
            "DEPOSIT",
        )

        self.assertEqual(
            payment.payment_status,
            "PENDING",
        )

        self.assertEqual(
            payment.amount,
            reservation.deposit_required,
        )

        self.assertEqual(
            response.url,
            reverse(
                "reservations:pagar_reserva",
                kwargs={
                    "reserva_id": reservation.pk,
                },
            ),
        )

    def test_user_reaches_wompi_checkout(self):
        response = self.client.post(
            self.url,
            self.data,
            follow=True,
        )

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
            'name="expiration-time"',
        )

        reservation = Reservation.objects.get()

        payment = Payment.objects.get(
            reservation=reservation,
        )

        self.assertContains(
            response,
            payment.transaction_reference,
        )

        self.assertEqual(
            reservation.reservation_status,
            "PENDING_PAYMENT",
        )

        self.assertEqual(
            payment.payment_status,
            "PENDING",
        )

        # Mostrar el checkout NO equivale
        # a recibir una aprobacion.
        self.assertFalse(
            Payment.objects.filter(
                payment_status="APPROVED",
            ).exists()
        )

    def test_same_slot_cannot_be_reserved_twice(self):
        first_response = self.client.post(
            self.url,
            self.data,
        )

        self.assertEqual(
            first_response.status_code,
            302,
        )

        second_response = self.client.post(
            self.url,
            self.data,
        )

        self.assertEqual(
            second_response.status_code,
            302,
        )

        self.assertEqual(
            Reservation.objects.count(),
            1,
        )

        self.assertEqual(
            Payment.objects.count(),
            1,
        )
