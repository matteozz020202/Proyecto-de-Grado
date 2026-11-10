
from datetime import time, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from courts.models import Court, CourtSchedule, Venue
from .models import Reservation
from .services import (
    create_pending_reservation,
    create_wompi_payment_attempt,
    expire_pending_reservations,
)


class PaymentExpirationTests(TestCase):

    def setUp(self):
        User = get_user_model()

        self.user = User.objects.create_user(
            username="expiration_payer"
        )

        venue = Venue.objects.create(
            venue_name="Arena Expiracion",
            deposit_percentage=30,
        )

        court = Court.objects.create(
            venue=venue,
            court_name="Cancha Expiracion",
            price_per_hour=130000,
        )

        day = timezone.localdate() + timedelta(days=7)

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
            start_time=time(18),
            end_time=time(19),
        )

    def expire_hold(self):
        Reservation.objects.filter(
            pk=self.reservation.pk
        ).update(
            hold_expires_at=(
                timezone.now() - timedelta(minutes=1)
            )
        )

    def test_expired_reservation_without_payment(self):
        self.expire_hold()

        count = expire_pending_reservations()

        self.reservation.refresh_from_db()

        self.assertEqual(count, 1)
        self.assertEqual(
            self.reservation.reservation_status,
            "EXPIRED",
        )

    def test_pending_wompi_payment_prevents_expiration(self):
        create_wompi_payment_attempt(self.reservation)

        self.expire_hold()

        count = expire_pending_reservations()

        self.reservation.refresh_from_db()

        self.assertEqual(count, 0)
        self.assertEqual(
            self.reservation.reservation_status,
            "PENDING_PAYMENT",
        )

    def test_rejected_payment_allows_expiration(self):
        payment = create_wompi_payment_attempt(
            self.reservation
        )

        payment.payment_status = "REJECTED"
        payment.save(update_fields=["payment_status"])

        self.expire_hold()

        count = expire_pending_reservations()

        self.reservation.refresh_from_db()

        self.assertEqual(count, 1)
        self.assertEqual(
            self.reservation.reservation_status,
            "EXPIRED",
        )

    def test_confirmed_reservation_does_not_expire(self):
        self.reservation.reservation_status = "CONFIRMED"
        self.reservation.hold_expires_at = None

        self.reservation.save(
            update_fields=[
                "reservation_status",
                "hold_expires_at",
            ]
        )

        count = expire_pending_reservations()

        self.reservation.refresh_from_db()

        self.assertEqual(count, 0)
        self.assertEqual(
            self.reservation.reservation_status,
            "CONFIRMED",
        )
