from datetime import time, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from courts.models import Venue, Court, CourtSchedule

from .services import (
    cancel_reservation,
    create_pending_reservation,
    expire_pending_reservations,
    get_availability,
    process_simulated_payment,
)


class ReservationFlowTests(TestCase):

    def setUp(self):
        # Usuario de prueba
        self.user = User.objects.create_user(
            username="usuario_test",
            password="Test12345!"
        )

        # Establecimiento
        self.venue = Venue.objects.create(
            venue_name="Complejo Test",
            city="Barranquilla",
            address="Calle 1 # 1-1",
            deposit_percentage=Decimal("30.00"),
            is_active=True
        )

        # Cancha
        self.court = Court.objects.create(
            venue=self.venue,
            court_name="Cancha Test",
            price_per_hour=Decimal("120000.00"),
            is_active=True,
            description="Cancha para pruebas"
        )

        # Fecha futura
        self.reservation_date = (
            timezone.localdate()
            + timedelta(days=7)
        )

        # Horario correspondiente al día elegido
        CourtSchedule.objects.create(
            court=self.court,
            day_of_week=self.reservation_date.isoweekday(),
            start_time=time(8, 0),
            end_time=time(22, 0),
            slot_duration_minutes=60,
            is_active=True
        )

    def create_reservation(self):
        return create_pending_reservation(
            user=self.user,
            court=self.court,
            reservation_date=self.reservation_date,
            start_time=time(10, 0),
            end_time=time(11, 0)
        )

    def test_create_pending_payment_reservation(self):
        reservation = self.create_reservation()

        self.assertEqual(
            reservation.reservation_status,
            "PENDING_PAYMENT"
        )

        self.assertEqual(
            reservation.total_amount,
            Decimal("120000.00")
        )

        self.assertEqual(
            reservation.deposit_required,
            Decimal("36000.00")
        )

        self.assertEqual(
            reservation.remaining_amount,
            Decimal("84000.00")
        )

        self.assertIsNotNone(
            reservation.hold_expires_at
        )

    def test_duplicate_reservation_is_rejected(self):
        self.create_reservation()

        with self.assertRaises(ValidationError):
            create_pending_reservation(
                user=self.user,
                court=self.court,
                reservation_date=self.reservation_date,
                start_time=time(10, 0),
                end_time=time(11, 0)
            )

    def test_partial_overlap_is_rejected(self):
        self.create_reservation()

        with self.assertRaises(ValidationError):
            create_pending_reservation(
                user=self.user,
                court=self.court,
                reservation_date=self.reservation_date,
                start_time=time(10, 30),
                end_time=time(11, 30)
            )

    def test_consecutive_time_slot_is_allowed(self):
        self.create_reservation()

        second_reservation = create_pending_reservation(
            user=self.user,
            court=self.court,
            reservation_date=self.reservation_date,
            start_time=time(11, 0),
            end_time=time(12, 0)
        )

        self.assertEqual(
            second_reservation.reservation_status,
            "PENDING_PAYMENT"
        )

    def test_rejected_payment_does_not_confirm(self):
        reservation = self.create_reservation()

        payment = process_simulated_payment(
            reservation,
            "REJECTED"
        )

        reservation.refresh_from_db()

        self.assertEqual(
            payment.payment_status,
            "REJECTED"
        )

        self.assertEqual(
            reservation.reservation_status,
            "PENDING_PAYMENT"
        )

        self.assertEqual(
            reservation.payments.count(),
            1
        )

    def test_approved_payment_confirms_reservation(self):
        reservation = self.create_reservation()

        payment = process_simulated_payment(
            reservation,
            "APPROVED"
        )

        reservation.refresh_from_db()

        self.assertEqual(
            payment.payment_status,
            "APPROVED"
        )

        self.assertEqual(
            reservation.reservation_status,
            "CONFIRMED"
        )

        self.assertIsNone(
            reservation.hold_expires_at
        )

    def test_rejected_then_approved_retry(self):
        reservation = self.create_reservation()

        payment_1 = process_simulated_payment(
            reservation,
            "REJECTED"
        )

        reservation.refresh_from_db()

        payment_2 = process_simulated_payment(
            reservation,
            "APPROVED"
        )

        reservation.refresh_from_db()

        self.assertEqual(
            payment_1.payment_status,
            "REJECTED"
        )

        self.assertEqual(
            payment_2.payment_status,
            "APPROVED"
        )

        self.assertEqual(
            reservation.reservation_status,
            "CONFIRMED"
        )

        self.assertEqual(
            reservation.payments.count(),
            2
        )

    def test_expired_reservation_releases_time_slot(self):
        reservation = self.create_reservation()

        reservation.hold_expires_at = (
            timezone.now()
            - timedelta(minutes=1)
        )

        reservation.save()

        count = expire_pending_reservations()

        reservation.refresh_from_db()

        self.assertGreaterEqual(
            count,
            1
        )

        self.assertEqual(
            reservation.reservation_status,
            "EXPIRED"
        )

        slots = get_availability(
            self.court,
            self.reservation_date
        )

        time_slot_available = any(
            slot["start_time"] == time(10, 0)
            and slot["end_time"] == time(11, 0)
            for slot in slots
        )

        self.assertTrue(
            time_slot_available
        )

    def test_cancelled_reservation_releases_time_slot(self):
        reservation = self.create_reservation()

        process_simulated_payment(
            reservation,
            "APPROVED"
        )

        reservation.refresh_from_db()

        self.assertEqual(
            reservation.reservation_status,
            "CONFIRMED"
        )

        cancel_reservation(
            reservation
        )

        reservation.refresh_from_db()

        self.assertEqual(
            reservation.reservation_status,
            "CANCELLED"
        )

        self.assertIsNotNone(
            reservation.cancelled_at
        )

        slots = get_availability(
            self.court,
            self.reservation_date
        )

        time_slot_available = any(
            slot["start_time"] == time(10, 0)
            and slot["end_time"] == time(11, 0)
            for slot in slots
        )

        self.assertTrue(
            time_slot_available
        )

    def test_confirmed_reservation_cannot_be_paid_twice(self):
        reservation = self.create_reservation()

        process_simulated_payment(
            reservation,
            "APPROVED"
        )

        reservation.refresh_from_db()

        with self.assertRaises(ValidationError):
            process_simulated_payment(
                reservation,
                "APPROVED"
            )

    def test_conflict_when_new_reservation_starts_before_existing(self):
        self.create_reservation()

        with self.assertRaises(ValidationError):
            create_pending_reservation(
                user=self.user,
                court=self.court,
                reservation_date=self.reservation_date,
                start_time=time(9, 30),
                end_time=time(10, 30)
            )

    def test_conflict_when_new_reservation_wraps_existing(self):
        self.create_reservation()

        with self.assertRaises(ValidationError):
            create_pending_reservation(
                user=self.user,
                court=self.court,
                reservation_date=self.reservation_date,
                start_time=time(9, 30),
                end_time=time(11, 30)
            )

    def test_time_slot_immediately_before_is_allowed(self):
        self.create_reservation()

        previous_reservation = create_pending_reservation(
            user=self.user,
            court=self.court,
            reservation_date=self.reservation_date,
            start_time=time(9, 0),
            end_time=time(10, 0)
        )

        self.assertEqual(
            previous_reservation.reservation_status,
            "PENDING_PAYMENT"
        )

    def test_same_time_on_different_court_is_allowed(self):
        second_court = Court.objects.create(
            venue=self.venue,
            court_name="Cancha Test 2",
            price_per_hour=Decimal("120000.00"),
            is_active=True,
            description="Segunda cancha para pruebas"
        )

        CourtSchedule.objects.create(
            court=second_court,
            day_of_week=self.reservation_date.isoweekday(),
            start_time=time(8, 0),
            end_time=time(22, 0),
            slot_duration_minutes=60,
            is_active=True
        )

        self.create_reservation()

        second_reservation = create_pending_reservation(
            user=self.user,
            court=second_court,
            reservation_date=self.reservation_date,
            start_time=time(10, 0),
            end_time=time(11, 0)
        )

        self.assertEqual(
            second_reservation.reservation_status,
            "PENDING_PAYMENT"
        )