
from datetime import time, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from courts.models import Court, CourtSchedule, Venue

from .services import (
    create_pending_reservation,
    create_wompi_payment_attempt,
)
from .wompi_client import WompiAPIError
from .wompi_reconciliation import (
    reconcile_wompi_payment,
    reconcile_wompi_transaction,
)
from .models import WompiTransaction


class WompiReconciliationTests(TestCase):

    def setUp(self):
        user = get_user_model().objects.create_user(
            username="reconciliation_user"
        )

        venue = Venue.objects.create(
            venue_name="Arena Reconciliation",
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

        self.transaction_id = "TX-RECONCILIATION-001"

        self.transaction_data = {
            "id": self.transaction_id,
            "reference": self.payment.transaction_reference,
            "amount_in_cents": 3900000,
            "currency": "COP",
            "status": "APPROVED",
        }

    def assign_transaction_id(self):
        self.payment.provider_transaction_id = (
            self.transaction_id
        )
        self.payment.save(
            update_fields=["provider_transaction_id"]
        )

    @patch(
        "reservations.wompi_verification.get_wompi_transaction"
    )
    def test_missing_transaction_id(
        self,
        mock_get,
    ):
        result = reconcile_wompi_payment(
            self.payment.pk
        )

        self.assertEqual(
            result["result"],
            "AWAITING_TRANSACTION_ID",
        )
        mock_get.assert_not_called()

    @patch(
        "reservations.wompi_verification.get_wompi_transaction"
    )
    def test_pending_transaction(
        self,
        mock_get,
    ):
        self.assign_transaction_id()

        mock_get.return_value = {
            **self.transaction_data,
            "status": "PENDING",
        }

        result = reconcile_wompi_payment(
            self.payment.pk
        )

        self.assertEqual(
            result["result"],
            "STILL_PENDING",
        )

        self.payment.refresh_from_db()

        self.assertEqual(
            self.payment.payment_status,
            "PENDING",
        )

    @patch(
        "reservations.wompi_verification.get_wompi_transaction"
    )
    def test_approved_transaction(
        self,
        mock_get,
    ):
        self.assign_transaction_id()
        mock_get.return_value = self.transaction_data

        result = reconcile_wompi_payment(
            self.payment.pk
        )

        self.reservation.refresh_from_db()

        self.assertEqual(
            result["result"],
            "PROCESSED",
        )
        self.assertEqual(
            result["payment_status"],
            "APPROVED",
        )
        self.assertEqual(
            self.reservation.reservation_status,
            "CONFIRMED",
        )

    @patch(
        "reservations.wompi_verification.get_wompi_transaction"
    )
    def test_declined_transaction(
        self,
        mock_get,
    ):
        self.assign_transaction_id()

        mock_get.return_value = {
            **self.transaction_data,
            "status": "DECLINED",
        }

        result = reconcile_wompi_payment(
            self.payment.pk
        )

        self.reservation.refresh_from_db()

        self.assertEqual(
            result["payment_status"],
            "DECLINED",
        )
        self.assertEqual(
            self.reservation.reservation_status,
            "PENDING_PAYMENT",
        )

    @patch(
        "reservations.wompi_verification.get_wompi_transaction"
    )
    def test_provider_error_preserves_payment(
        self,
        mock_get,
    ):
        self.assign_transaction_id()

        mock_get.side_effect = WompiAPIError(
            "Proveedor no disponible."
        )

        result = reconcile_wompi_payment(
            self.payment.pk
        )

        self.payment.refresh_from_db()

        self.assertEqual(
            result["result"],
            "PROVIDER_UNAVAILABLE",
        )
        self.assertEqual(
            self.payment.payment_status,
            "PENDING",
        )

    @patch(
        "reservations.wompi_verification.get_wompi_transaction"
    )
    def test_late_approval_requires_review(
        self,
        mock_get,
    ):
        self.assign_transaction_id()

        self.reservation.hold_expires_at = (
            timezone.now() - timedelta(minutes=1)
        )
        self.reservation.save(
            update_fields=["hold_expires_at"]
        )

        mock_get.return_value = self.transaction_data

        result = reconcile_wompi_payment(
            self.payment.pk
        )

        self.payment.refresh_from_db()
        self.reservation.refresh_from_db()

        self.assertEqual(
            result["result"],
            "REQUIRES_REVIEW",
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


    @patch(
        "reservations.wompi_notification_processing."
        "get_wompi_transaction"
    )
    def test_reconcile_pending_transaction_to_approved(
        self,
        mock_get,
    ):
        """
        Una transaccion pendiente pasa a aprobada
        durante la conciliacion.
        """

        pending_data = {
            **self.transaction_data,
            "status": "PENDING",
        }

        approved_data = {
            **self.transaction_data,
            "status": "APPROVED",
        }

        mock_get.side_effect = [
            pending_data,
            approved_data,
        ]

        from .wompi_notification_processing import (
            process_wompi_transaction_notification,
        )

        process_wompi_transaction_notification(
            self.transaction_id
        )

        result = reconcile_wompi_transaction(
            self.transaction_id
        )

        self.reservation.refresh_from_db()

        record = WompiTransaction.objects.get(
            provider_transaction_id=self.transaction_id
        )

        self.assertEqual(result["result"], "PROCESSED")
        self.assertEqual(record.status, "APPROVED")
        self.assertEqual(
            self.reservation.reservation_status,
            "CONFIRMED",
        )
        self.assertEqual(mock_get.call_count, 2)

    @patch(
        "reservations.wompi_notification_processing."
        "get_wompi_transaction"
    )
    def test_reconcile_second_transaction_after_decline(
        self,
        mock_get,
    ):
        """
        Una primera transaccion rechazada no
        impide conciliar otra transaccion pendiente.
        """

        first_id = "TX-RECON-DECLINED-001"
        second_id = "TX-RECON-PENDING-002"

        declined_data = {
            **self.transaction_data,
            "id": first_id,
            "status": "DECLINED",
        }

        pending_data = {
            **self.transaction_data,
            "id": second_id,
            "status": "PENDING",
        }

        approved_data = {
            **self.transaction_data,
            "id": second_id,
            "status": "APPROVED",
        }

        mock_get.side_effect = [
            declined_data,
            pending_data,
            approved_data,
        ]

        from .wompi_notification_processing import (
            process_wompi_transaction_notification,
        )

        process_wompi_transaction_notification(first_id)
        process_wompi_transaction_notification(second_id)

        result = reconcile_wompi_transaction(second_id)

        self.payment.refresh_from_db()
        self.reservation.refresh_from_db()

        self.assertEqual(result["result"], "PROCESSED")
        self.assertEqual(
            self.payment.payment_status,
            "APPROVED",
        )
        self.assertEqual(
            self.reservation.reservation_status,
            "CONFIRMED",
        )

        self.assertEqual(
            WompiTransaction.objects.filter(
                payment=self.payment,
                status="DECLINED",
            ).count(),
            1,
        )

        self.assertEqual(
            WompiTransaction.objects.filter(
                payment=self.payment,
                status="APPROVED",
            ).count(),
            1,
        )


    @patch(
        "reservations.wompi_notification_processing."
        "get_wompi_transaction"
    )
    def test_reconciliation_rejects_wrong_amount_without_changes(
        self,
        mock_get,
    ):
        from django.core.exceptions import ValidationError
        from .wompi_notification_processing import (
            process_wompi_transaction_notification,
        )

        pending_data = {
            **self.transaction_data,
            "status": "PENDING",
        }

        invalid_data = {
            **self.transaction_data,
            "status": "APPROVED",
            "amount_in_cents": 100,
        }

        mock_get.side_effect = [
            pending_data,
            invalid_data,
        ]

        process_wompi_transaction_notification(
            self.transaction_id
        )

        with self.assertRaises(ValidationError):
            reconcile_wompi_transaction(
                self.transaction_id
            )

        self.payment.refresh_from_db()
        self.reservation.refresh_from_db()

        wompi_transaction = WompiTransaction.objects.get(
            provider_transaction_id=self.transaction_id
        )

        self.assertEqual(
            wompi_transaction.status,
            "PENDING",
        )
        self.assertEqual(
            self.payment.payment_status,
            "PENDING",
        )
        self.assertEqual(
            self.reservation.reservation_status,
            "PENDING_PAYMENT",
        )


    @patch(
        "reservations.wompi_verification."
        "get_wompi_transaction"
    )
    def test_legacy_pending_payment_creates_transaction_history(
        self,
        mock_get,
    ):
        """
        Un pago antiguo con identificador en Payment,
        pero sin WompiTransaction, debe poder
        conciliarse y conservar su historial.
        """

        # Simular un pago creado antes de incorporar
        # el modelo WompiTransaction.
        self.payment.provider_transaction_id = (
            self.transaction_id
        )
        self.payment.save(
            update_fields=["provider_transaction_id"]
        )

        self.assertFalse(
            WompiTransaction.objects.filter(
                provider_transaction_id=self.transaction_id
            ).exists()
        )

        mock_get.return_value = self.transaction_data

        result = reconcile_wompi_payment(
            self.payment.pk
        )

        self.payment.refresh_from_db()
        self.reservation.refresh_from_db()

        record = WompiTransaction.objects.get(
            provider_transaction_id=self.transaction_id
        )

        self.assertEqual(result["result"], "PROCESSED")
        self.assertEqual(record.payment_id, self.payment.pk)
        self.assertEqual(record.status, "APPROVED")

        self.assertEqual(
            self.payment.payment_status,
            "APPROVED",
        )

        self.assertEqual(
            self.reservation.reservation_status,
            "CONFIRMED",
        )

        mock_get.assert_called_once_with(
            self.transaction_id
        )
