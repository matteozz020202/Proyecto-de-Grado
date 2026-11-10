
from datetime import time, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from courts.models import Court, CourtSchedule, Venue

from .models import Reservation, WompiTransaction
from .services import (
    create_pending_reservation,
    create_wompi_payment_attempt,
)
from .wompi_expiration_reconciliation import (
    reconcile_expired_reservation,
)


class WompiExpirationReconciliationTests(TestCase):

    def setUp(self):
        user = get_user_model().objects.create_user(
            username="expiration_reconciliation_user"
        )

        venue = Venue.objects.create(
            venue_name="Arena Reconciliation Expiration",
            deposit_percentage=30,
        )

        court = Court.objects.create(
            venue=venue,
            court_name="Cancha Reconciliation",
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

    def test_missing_transaction_id_is_not_assumed_declined(self):
        result = reconcile_expired_reservation(
            self.reservation.pk
        )

        self.reservation.refresh_from_db()

        self.assertEqual(result["result"], "CHECKED")
        self.assertEqual(
            result["checks"][0]["result"],
            "AWAITING_TRANSACTION_ID",
        )
        self.assertEqual(
            self.reservation.reservation_status,
            "PENDING_PAYMENT",
        )

    @patch(
        "reservations.wompi_expiration_reconciliation."
        "reconcile_wompi_transaction"
    )
    def test_pending_history_is_checked(
        self,
        mock_reconcile,
    ):
        transaction_id = "TX-EXPIRATION-PENDING-001"

        WompiTransaction.objects.create(
            payment=self.payment,
            provider_transaction_id=transaction_id,
            status="PENDING",
            amount_in_cents=3900000,
            currency="COP",
        )

        mock_reconcile.return_value = {
            "result": "STILL_PENDING",
            "transaction_status": "PENDING",
        }

        result = reconcile_expired_reservation(
            self.reservation.pk
        )

        mock_reconcile.assert_called_once_with(
            transaction_id
        )

        self.assertEqual(
            result["checks"][0]["result"],
            "STILL_PENDING",
        )

        self.reservation.refresh_from_db()

        self.assertEqual(
            self.reservation.reservation_status,
            "PENDING_PAYMENT",
        )

    @patch(
        "reservations.wompi_expiration_reconciliation."
        "reconcile_wompi_transaction"
    )
    def test_declined_payment_with_pending_history_is_checked(
        self,
        mock_reconcile,
    ):
        self.payment.payment_status = "DECLINED"
        self.payment.save(
            update_fields=["payment_status"]
        )

        WompiTransaction.objects.create(
            payment=self.payment,
            provider_transaction_id="TX-OLD-DECLINED",
            status="DECLINED",
            amount_in_cents=3900000,
            currency="COP",
        )

        WompiTransaction.objects.create(
            payment=self.payment,
            provider_transaction_id="TX-NEW-PENDING",
            status="PENDING",
            amount_in_cents=3900000,
            currency="COP",
        )

        mock_reconcile.return_value = {
            "result": "STILL_PENDING",
            "transaction_status": "PENDING",
        }

        result = reconcile_expired_reservation(
            self.reservation.pk
        )

        mock_reconcile.assert_called_once_with(
            "TX-NEW-PENDING"
        )

        self.assertEqual(len(result["checks"]), 1)

    @patch(
        "reservations.wompi_expiration_reconciliation."
        "reconcile_wompi_payment"
    )
    def test_nonexpired_reservation_is_not_checked(
        self,
        mock_reconcile,
    ):
        Reservation.objects.filter(
            pk=self.reservation.pk
        ).update(
            hold_expires_at=(
                timezone.now() + timedelta(minutes=10)
            )
        )

        result = reconcile_expired_reservation(
            self.reservation.pk
        )

        self.assertEqual(
            result["result"],
            "NOT_ELIGIBLE",
        )

        mock_reconcile.assert_not_called()
