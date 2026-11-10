
from datetime import time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from courts.models import Court, CourtSchedule, Venue
from .models import Payment
from .services import (
    create_pending_reservation,
    create_wompi_payment_attempt,
)


class WompiPaymentAttemptTests(TestCase):

    def setUp(self):
        User = get_user_model()

        self.user = User.objects.create_user(
            username="wompi_payer"
        )

        self.venue = Venue.objects.create(
            venue_name="Arena Wompi",
            deposit_percentage=30,
        )

        self.court = Court.objects.create(
            venue=self.venue,
            court_name="Cancha Wompi",
            price_per_hour=130000,
        )

        self.day = (
            timezone.localdate()
            + timedelta(days=7)
        )

        CourtSchedule.objects.create(
            court=self.court,
            day_of_week=self.day.isoweekday(),
            start_time=time(8),
            end_time=time(22),
        )

        self.reservation = create_pending_reservation(
            user=self.user,
            court=self.court,
            reservation_date=self.day,
            start_time=time(18),
            end_time=time(19),
        )

    def test_creates_pending_payment(self):
        payment = create_wompi_payment_attempt(
            self.reservation
        )

        self.assertEqual(payment.provider, "WOMPI")
        self.assertEqual(payment.payment_type, "DEPOSIT")
        self.assertEqual(payment.payment_status, "PENDING")
        self.assertEqual(payment.currency, "COP")
        self.assertEqual(payment.amount, Decimal("39000.00"))

        self.assertTrue(
            payment.transaction_reference.startswith(
                f"CL-{self.reservation.pk}-"
            )
        )

        self.assertIsNone(payment.provider_transaction_id)

        self.reservation.refresh_from_db()

        self.assertEqual(
            self.reservation.reservation_status,
            "PENDING_PAYMENT",
        )

    def test_reuses_existing_pending_attempt(self):
        first = create_wompi_payment_attempt(
            self.reservation
        )

        second = create_wompi_payment_attempt(
            self.reservation
        )

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(
            Payment.objects.filter(
                reservation=self.reservation,
                provider="WOMPI",
            ).count(),
            1,
        )

    def test_rejected_attempt_allows_new_attempt(self):
        first = create_wompi_payment_attempt(
            self.reservation
        )

        first.payment_status = "REJECTED"
        first.save(update_fields=["payment_status"])

        second = create_wompi_payment_attempt(
            self.reservation
        )

        self.assertNotEqual(first.pk, second.pk)

        self.assertNotEqual(
            first.transaction_reference,
            second.transaction_reference,
        )

        self.assertEqual(
            Payment.objects.filter(
                reservation=self.reservation,
                provider="WOMPI",
            ).count(),
            2,
        )

    def test_confirmed_reservation_cannot_pay_again(self):
        self.reservation.reservation_status = "CONFIRMED"
        self.reservation.hold_expires_at = None

        self.reservation.save(
            update_fields=[
                "reservation_status",
                "hold_expires_at",
            ]
        )

        with self.assertRaises(ValidationError):
            create_wompi_payment_attempt(
                self.reservation
            )

        self.assertFalse(Payment.objects.exists())

    def test_expired_hold_cannot_start_payment(self):
        self.reservation.hold_expires_at = (
            timezone.now() - timedelta(minutes=1)
        )

        self.reservation.save(
            update_fields=["hold_expires_at"]
        )

        with self.assertRaises(ValidationError):
            create_wompi_payment_attempt(
                self.reservation
            )

        self.assertFalse(Payment.objects.exists())

    def test_zero_deposit_cannot_start_payment(self):
        self.reservation.deposit_required = Decimal("0.00")
        self.reservation.save(
            update_fields=["deposit_required"]
        )

        with self.assertRaises(ValidationError):
            create_wompi_payment_attempt(
                self.reservation
            )

        self.assertFalse(Payment.objects.exists())
