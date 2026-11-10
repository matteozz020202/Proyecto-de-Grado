
from datetime import time, timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from .models import Payment
from courts.models import Court, CourtSchedule, Venue

from .services import (
    create_pending_reservation,
    create_wompi_payment_attempt,
)
from .payment_processing import (
    process_verified_wompi_transaction,
)


class WompiProcessingTests(TestCase):

    def setUp(self):
        user = get_user_model().objects.create_user(
            username="processing_user"
        )

        venue = Venue.objects.create(
            venue_name="Arena Processing",
            deposit_percentage=30,
        )

        court = Court.objects.create(
            venue=venue,
            court_name="Cancha Processing",
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
            user=user,
            court=court,
            reservation_date=day,
            start_time=time(18),
            end_time=time(19),
        )

        self.payment = create_wompi_payment_attempt(
            self.reservation
        )

        self.data = {
            "id": "TX-SANDBOX-001",
            "reference": self.payment.transaction_reference,
            "amount_in_cents": 3900000,
            "currency": "COP",
            "status": "APPROVED",
        }

    def process(self):
        return process_verified_wompi_transaction(
            self.payment.pk,
            self.data,
        )

    def test_approved_payment_confirms_reservation(self):
        self.process()

        self.payment.refresh_from_db()
        self.reservation.refresh_from_db()

        self.assertEqual(
            self.payment.payment_status,
            "APPROVED",
        )

        self.assertEqual(
            self.reservation.reservation_status,
            "CONFIRMED",
        )

        self.assertIsNone(
            self.reservation.hold_expires_at
        )

        self.assertIsNotNone(
            self.payment.approved_at
        )

    def test_duplicate_approved_event_is_idempotent(self):
        self.process()
        approved_at = self.payment.__class__.objects.get(
            pk=self.payment.pk
        ).approved_at

        self.process()

        self.payment.refresh_from_db()

        self.assertEqual(
            self.payment.approved_at,
            approved_at,
        )

    def test_declined_payment_does_not_confirm(self):
        self.data["status"] = "DECLINED"
        self.process()

        self.reservation.refresh_from_db()

        self.assertEqual(
            self.reservation.reservation_status,
            "PENDING_PAYMENT",
        )

    def test_approved_payment_cannot_become_declined(self):
        self.process()
        self.data["status"] = "DECLINED"

        with self.assertRaises(ValidationError):
            self.process()

        self.payment.refresh_from_db()

        self.assertEqual(
            self.payment.payment_status,
            "APPROVED",
        )

    def test_wrong_amount_does_not_change_database(self):
        self.data["amount_in_cents"] = 100

        with self.assertRaises(ValidationError):
            self.process()

        self.payment.refresh_from_db()

        self.assertEqual(
            self.payment.payment_status,
            "PENDING",
        )

    def test_approved_after_hold_expiration(self):
        self.reservation.hold_expires_at = (
            timezone.now() - timedelta(minutes=1)
        )

        self.reservation.save(
            update_fields=["hold_expires_at"]
        )

        self.process()

        self.payment.refresh_from_db()
        self.reservation.refresh_from_db()

        self.assertEqual(
            self.payment.payment_status,
            "APPROVED",
        )

        self.assertEqual(
            self.reservation.reservation_status,
            "PENDING_PAYMENT",
        )

    def test_voided_payment_does_not_confirm(self):
        self.data["status"] = "VOIDED"

        self.process()

        self.payment.refresh_from_db()
        self.reservation.refresh_from_db()

        self.assertEqual(
            self.payment.payment_status,
            "VOIDED",
        )
        self.assertEqual(
            self.reservation.reservation_status,
            "PENDING_PAYMENT",
        )

    def test_error_payment_does_not_confirm(self):
        self.data["status"] = "ERROR"

        self.process()

        self.payment.refresh_from_db()
        self.reservation.refresh_from_db()

        self.assertEqual(
            self.payment.payment_status,
            "ERROR",
        )
        self.assertEqual(
            self.reservation.reservation_status,
            "PENDING_PAYMENT",
        )

    def test_pending_event_is_idempotent(self):
        self.data["status"] = "PENDING"

        self.process()
        self.process()

        self.payment.refresh_from_db()
        self.reservation.refresh_from_db()

        self.assertEqual(
            self.payment.payment_status,
            "PENDING",
        )
        self.assertEqual(
            self.payment.provider_transaction_id,
            "TX-SANDBOX-001",
        )
        self.assertEqual(
            self.reservation.reservation_status,
            "PENDING_PAYMENT",
        )

    def test_same_transaction_cannot_change_final_status(self):
        self.data["status"] = "DECLINED"
        self.process()

        self.data["status"] = "APPROVED"

        with self.assertRaises(ValidationError):
            self.process()

        self.payment.refresh_from_db()
        self.reservation.refresh_from_db()

        self.assertEqual(
            self.payment.payment_status,
            "DECLINED",
        )
        self.assertEqual(
            self.reservation.reservation_status,
            "PENDING_PAYMENT",
        )

    def test_duplicate_final_event_preserves_approved_at(self):
        self.process()

        self.payment.refresh_from_db()
        first_approved_at = self.payment.approved_at

        self.process()

        self.payment.refresh_from_db()

        self.assertEqual(
            self.payment.payment_status,
            "APPROVED",
        )
        self.assertEqual(
            self.payment.approved_at,
            first_approved_at,
        )

    def test_late_approval_requires_reconciliation(self):
        self.reservation.hold_expires_at = (
            timezone.now() - timedelta(minutes=1)
        )
        self.reservation.save(
            update_fields=["hold_expires_at"]
        )

        self.process()

        self.payment.refresh_from_db()
        self.reservation.refresh_from_db()

        self.assertEqual(
            self.payment.payment_status,
            "APPROVED",
        )
        self.assertTrue(
            self.payment.requires_reconciliation
        )
        self.assertEqual(
            self.payment.reconciliation_reason,
            "LATE_APPROVAL",
        )
        self.assertEqual(
            self.reservation.reservation_status,
            "PENDING_PAYMENT",
        )

    def test_approved_payment_on_cancelled_reservation(self):
        self.reservation.reservation_status = "CANCELLED"
        self.reservation.save(
            update_fields=["reservation_status"]
        )

        self.process()

        self.payment.refresh_from_db()
        self.reservation.refresh_from_db()

        self.assertTrue(
            self.payment.requires_reconciliation
        )
        self.assertEqual(
            self.payment.reconciliation_reason,
            "RESERVATION_NOT_PAYABLE",
        )
        self.assertEqual(
            self.reservation.reservation_status,
            "CANCELLED",
        )

    def test_duplicate_approval_requires_reconciliation(self):
        # Primera transaccion aprobada.
        self.process()

        second_payment = Payment.objects.create(
            reservation=self.reservation,
            amount=self.payment.amount,
            payment_type="DEPOSIT",
            payment_status="PENDING",
            provider="WOMPI",
            transaction_reference="CL-DUPLICATE-TEST",
            currency="COP",
        )

        second_data = {
            "id": "TX-SANDBOX-002",
            "reference": second_payment.transaction_reference,
            "amount_in_cents": 3900000,
            "currency": "COP",
            "status": "APPROVED",
        }

        process_verified_wompi_transaction(
            second_payment.pk,
            second_data,
        )

        second_payment.refresh_from_db()
        self.reservation.refresh_from_db()

        self.assertEqual(
            second_payment.payment_status,
            "APPROVED",
        )
        self.assertTrue(
            second_payment.requires_reconciliation
        )
        self.assertEqual(
            second_payment.reconciliation_reason,
            "DUPLICATE_APPROVAL",
        )
        self.assertEqual(
            self.reservation.reservation_status,
            "CONFIRMED",
        )

    def test_normal_approval_does_not_require_reconciliation(self):
        self.process()

        self.payment.refresh_from_db()

        self.assertFalse(
            self.payment.requires_reconciliation
        )
        self.assertEqual(
            self.payment.reconciliation_reason,
            "",
        )
