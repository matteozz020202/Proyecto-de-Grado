
from concurrent.futures import ThreadPoolExecutor
from datetime import time, timedelta
from threading import Barrier
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import (
    connection,
    close_old_connections,
)
from django.test import TransactionTestCase
from django.utils import timezone

from courts.models import Court, CourtSchedule, Venue
from .models import Reservation
from .services import create_pending_reservation


@skipUnless(
    connection.vendor == "postgresql",
    "Esta prueba requiere PostgreSQL.",
)
class PaymentConcurrencyTests(TransactionTestCase):

    def setUp(self):
        User = get_user_model()

        self.user1 = User.objects.create_user(
            username="concurrent_user_1"
        )

        self.user2 = User.objects.create_user(
            username="concurrent_user_2"
        )

        self.venue = Venue.objects.create(
            venue_name="Arena Concurrente",
            deposit_percentage=30,
        )

        self.court = Court.objects.create(
            venue=self.venue,
            court_name="Cancha Concurrente",
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

    def test_two_users_cannot_reserve_same_slot(self):

        barrier = Barrier(2)

        def attempt_reservation(user_id):
            close_old_connections()

            try:
                barrier.wait(timeout=10)

                user = get_user_model().objects.get(
                    pk=user_id
                )

                court = Court.objects.get(
                    pk=self.court.pk
                )

                reservation = create_pending_reservation(
                    user=user,
                    court=court,
                    reservation_date=self.day,
                    start_time=time(18),
                    end_time=time(19),
                )

                return (
                    "CREATED",
                    reservation.pk,
                )

            except ValidationError:
                return ("CONFLICT", None)

            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as executor:

            future1 = executor.submit(
                attempt_reservation,
                self.user1.pk,
            )

            future2 = executor.submit(
                attempt_reservation,
                self.user2.pk,
            )

            results = [
                future1.result(),
                future2.result(),
            ]

        created = [
            result
            for result in results
            if result[0] == "CREATED"
        ]

        conflicts = [
            result
            for result in results
            if result[0] == "CONFLICT"
        ]

        self.assertEqual(len(created), 1)
        self.assertEqual(len(conflicts), 1)

        reservations = Reservation.objects.filter(
            court=self.court,
            reservation_date=self.day,
            start_time=time(18),
            end_time=time(19),
        )

        self.assertEqual(
            reservations.count(),
            1,
        )

        self.assertEqual(
            reservations.first().reservation_status,
            "PENDING_PAYMENT",
        )
