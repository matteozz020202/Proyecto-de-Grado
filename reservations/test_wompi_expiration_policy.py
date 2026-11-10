
from datetime import time, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from courts.models import Court, CourtSchedule, Venue

from .models import Reservation, WompiTransaction
from .services import (
    create_pending_reservation,
    create_wompi_payment_attempt,
)
from .wompi_expiration_policy import (
    classify_expired_reservation,
)


class WompiExpirationPolicyTests(TestCase):

    def setUp(self):
        user = get_user_model().objects.create_user(
            username="expiration_policy_user"
        )

        venue = Venue.objects.create(
            venue_name="Arena Expiration Policy",
            deposit_percentage=30,
        )

        court = Court.objects.create(
            venue=venue,
            court_name="Cancha Expiration Policy",
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

        Reservation.objects.filter(
            pk=self.reservation.pk
        ).update(
            hold_expires_at=(
                timezone.now() - timedelta(minutes=1)
            )
        )

    def add_transaction(self, transaction_id, status):
        return WompiTransaction.objects.create(
            payment=self.payment,
            provider_transaction_id=transaction_id,
            status=status,
            amount_in_cents=3900000,
            currency="COP",
        )

    def test_pending_payment_needs_reconciliation(self):
        result = classify_expired_reservation(
            self.reservation.pk
        )

        self.assertEqual(result, "NEEDS_RECONCILIATION")

    def test_pending_transaction_needs_reconciliation(self):
        self.payment.payment_status = "DECLINED"
        self.payment.save(update_fields=["payment_status"])

        self.add_transaction("TX-POLICY-PENDING", "PENDING")

        result = classify_expired_reservation(
            self.reservation.pk
        )

        self.assertEqual(result, "NEEDS_RECONCILIATION")

    def test_approved_transaction_requires_review(self):
        self.payment.payment_status = "DECLINED"
        self.payment.save(update_fields=["payment_status"])

        self.add_transaction("TX-POLICY-APPROVED", "APPROVED")

        result = classify_expired_reservation(
            self.reservation.pk
        )

        self.assertEqual(result, "FINANCIAL_REVIEW")

    def test_declined_payment_can_expire(self):
        self.payment.payment_status = "DECLINED"
        self.payment.save(update_fields=["payment_status"])

        self.add_transaction("TX-POLICY-DECLINED", "DECLINED")

        result = classify_expired_reservation(
            self.reservation.pk
        )

        self.assertEqual(result, "CAN_EXPIRE")

    def test_financial_exception_requires_review(self):
        self.payment.payment_status = "APPROVED"
        self.payment.requires_reconciliation = True
        self.payment.reconciliation_reason = "LATE_APPROVAL"

        self.payment.save(
            update_fields=[
                "payment_status",
                "requires_reconciliation",
                "reconciliation_reason",
            ]
        )

        result = classify_expired_reservation(
            self.reservation.pk
        )

        self.assertEqual(result, "FINANCIAL_REVIEW")

    def test_nonexpired_reservation_is_not_eligible(self):
        Reservation.objects.filter(
            pk=self.reservation.pk
        ).update(
            hold_expires_at=(
                timezone.now() + timedelta(minutes=10)
            )
        )

        result = classify_expired_reservation(
            self.reservation.pk
        )

        self.assertEqual(result, "NOT_ELIGIBLE")
