
from datetime import time, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from courts.models import Court, CourtSchedule, Venue

from .models import Payment, WompiTransaction
from .services import (
    create_pending_reservation,
    create_wompi_payment_attempt,
)
from .wompi_notification_processing import (
    process_wompi_transaction_notification,
)


class WompiNotificationProcessingTests(TestCase):

    def setUp(self):
        user = get_user_model().objects.create_user(
            username="notification_user"
        )

        venue = Venue.objects.create(
            venue_name="Arena Notification",
            deposit_percentage=30,
        )

        court = Court.objects.create(
            venue=venue,
            court_name="Cancha Notification",
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

        self.transaction_id = "TX-NOTIFICATION-001"

        self.transaction_data = {
            "id": self.transaction_id,
            "reference": self.payment.transaction_reference,
            "amount_in_cents": 3900000,
            "currency": "COP",
            "status": "APPROVED",
        }

    @patch(
        "reservations.wompi_notification_processing."
        "get_wompi_transaction"
    )
    def test_approved_transaction_confirms_reservation(
        self,
        mock_get,
    ):
        mock_get.return_value = self.transaction_data

        payment = process_wompi_transaction_notification(
            self.transaction_id
        )

        self.reservation.refresh_from_db()

        self.assertEqual(payment.payment_status, "APPROVED")
        self.assertEqual(
            payment.provider_transaction_id,
            self.transaction_id,
        )
        self.assertEqual(
            self.reservation.reservation_status,
            "CONFIRMED",
        )

        mock_get.assert_called_once_with(
            self.transaction_id
        )

    @patch(
        "reservations.wompi_notification_processing."
        "get_wompi_transaction"
    )
    def test_pending_transaction_does_not_confirm(
        self,
        mock_get,
    ):
        mock_get.return_value = {
            **self.transaction_data,
            "status": "PENDING",
        }

        payment = process_wompi_transaction_notification(
            self.transaction_id
        )

        self.reservation.refresh_from_db()

        self.assertEqual(payment.payment_status, "PENDING")
        self.assertEqual(
            self.reservation.reservation_status,
            "PENDING_PAYMENT",
        )

    @patch(
        "reservations.wompi_notification_processing."
        "get_wompi_transaction"
    )
    def test_unknown_reference_is_rejected(
        self,
        mock_get,
    ):
        mock_get.return_value = {
            **self.transaction_data,
            "reference": "UNKNOWN-REFERENCE",
        }

        with self.assertRaises(ValidationError):
            process_wompi_transaction_notification(
                self.transaction_id
            )

        self.payment.refresh_from_db()

        self.assertEqual(
            self.payment.payment_status,
            "PENDING",
        )

    @patch(
        "reservations.wompi_notification_processing."
        "get_wompi_transaction"
    )
    def test_wrong_amount_is_rejected(
        self,
        mock_get,
    ):
        mock_get.return_value = {
            **self.transaction_data,
            "amount_in_cents": 100,
        }

        with self.assertRaises(ValidationError):
            process_wompi_transaction_notification(
                self.transaction_id
            )

        self.payment.refresh_from_db()

        self.assertEqual(
            self.payment.payment_status,
            "PENDING",
        )

    @patch(
        "reservations.wompi_notification_processing."
        "get_wompi_transaction"
    )
    def test_duplicate_notification_is_idempotent(
        self,
        mock_get,
    ):
        mock_get.return_value = self.transaction_data

        first = process_wompi_transaction_notification(
            self.transaction_id
        )

        second = process_wompi_transaction_notification(
            self.transaction_id
        )

        self.assertEqual(first.pk, second.pk)

        self.assertEqual(
            Payment.objects.filter(
                reservation=self.reservation,
                payment_status="APPROVED",
            ).count(),
            1,
        )

    @patch(
        "reservations.wompi_notification_processing."
        "get_wompi_transaction"
    )
    def test_non_wompi_payment_is_rejected(
        self,
        mock_get,
    ):
        self.payment.provider = "SIMULATED"
        self.payment.save(update_fields=["provider"])

        mock_get.return_value = self.transaction_data

        with self.assertRaises(ValidationError):
            process_wompi_transaction_notification(
                self.transaction_id
            )

        self.payment.refresh_from_db()

        self.assertEqual(
            self.payment.payment_status,
            "PENDING",
        )


    @patch(
        "reservations.wompi_notification_processing."
        "get_wompi_transaction"
    )
    def test_retry_approved_after_declined_same_reference(
        self,
        mock_get,
    ):
        """
        Wompi puede generar dos transacciones
        diferentes bajo la misma referencia.

        Un rechazo inicial no debe impedir
        registrar una aprobacion posterior.
        """

        first_transaction = {
            **self.transaction_data,
            "id": "TX-RETRY-DECLINED-001",
            "status": "DECLINED",
        }

        second_transaction = {
            **self.transaction_data,
            "id": "TX-RETRY-APPROVED-002",
            "status": "APPROVED",
        }

        mock_get.side_effect = [
            first_transaction,
            second_transaction,
        ]

        # Primer intento: rechazado.
        first_payment = (
            process_wompi_transaction_notification(
                first_transaction["id"]
            )
        )

        self.assertEqual(
            first_payment.payment_status,
            "DECLINED",
        )

        self.reservation.refresh_from_db()

        self.assertEqual(
            self.reservation.reservation_status,
            "PENDING_PAYMENT",
        )

        # Segundo intento: aprobado,
        # conservando la referencia comercial.
        second_payment = (
            process_wompi_transaction_notification(
                second_transaction["id"]
            )
        )

        self.assertEqual(
            second_payment.payment_status,
            "APPROVED",
        )

        self.reservation.refresh_from_db()

        self.assertEqual(
            self.reservation.reservation_status,
            "CONFIRMED",
        )

        self.assertEqual(
            Payment.objects.filter(
                reservation=self.reservation,
                payment_status="APPROVED",
            ).count(),
            1,
        )

        self.assertEqual(mock_get.call_count, 2)


    @patch(
        "reservations.wompi_notification_processing."
        "get_wompi_transaction"
    )
    def test_approved_transaction_is_recorded_in_history(
        self,
        mock_get,
    ):
        mock_get.return_value = self.transaction_data

        process_wompi_transaction_notification(
            self.transaction_id
        )

        record = WompiTransaction.objects.get(
            provider_transaction_id=self.transaction_id
        )

        self.assertEqual(record.payment_id, self.payment.pk)
        self.assertEqual(record.status, "APPROVED")
        self.assertEqual(record.amount_in_cents, 3900000)
        self.assertEqual(record.currency, "COP")
        self.assertIsNotNone(record.approved_at)

    @patch(
        "reservations.wompi_notification_processing."
        "get_wompi_transaction"
    )
    def test_duplicate_event_does_not_duplicate_history(
        self,
        mock_get,
    ):
        mock_get.return_value = self.transaction_data

        process_wompi_transaction_notification(
            self.transaction_id
        )

        process_wompi_transaction_notification(
            self.transaction_id
        )

        self.assertEqual(
            WompiTransaction.objects.filter(
                payment=self.payment,
                provider_transaction_id=self.transaction_id,
            ).count(),
            1,
        )


    @patch(
        "reservations.wompi_notification_processing."
        "get_wompi_transaction"
    )
    def test_second_approval_requires_reconciliation(
        self,
        mock_get,
    ):
        """
        Dos transacciones aprobadas para un
        mismo abono deben conservarse.

        La segunda aprobacion requiere revision.
        """

        first_transaction = {
            **self.transaction_data,
            "id": "TX-DOUBLE-APPROVED-001",
            "status": "APPROVED",
        }

        second_transaction = {
            **self.transaction_data,
            "id": "TX-DOUBLE-APPROVED-002",
            "status": "APPROVED",
        }

        mock_get.side_effect = [
            first_transaction,
            second_transaction,
        ]

        process_wompi_transaction_notification(
            first_transaction["id"]
        )

        self.reservation.refresh_from_db()

        self.assertEqual(
            self.reservation.reservation_status,
            "CONFIRMED",
        )

        process_wompi_transaction_notification(
            second_transaction["id"]
        )

        self.payment.refresh_from_db()
        self.reservation.refresh_from_db()

        self.assertEqual(
            WompiTransaction.objects.filter(
                payment=self.payment,
                status="APPROVED",
            ).count(),
            2,
        )

        self.assertEqual(
            self.payment.payment_status,
            "APPROVED",
        )

        self.assertTrue(
            self.payment.requires_reconciliation
        )

        self.assertEqual(
            self.payment.reconciliation_reason,
            "DUPLICATE_APPROVAL",
        )

        self.assertEqual(
            self.reservation.reservation_status,
            "CONFIRMED",
        )

    @patch(
        "reservations.wompi_notification_processing."
        "get_wompi_transaction"
    )
    def test_decline_after_approval_keeps_reservation_confirmed(
        self,
        mock_get,
    ):
        """
        Una transaccion rechazada posteriormente
        no puede deshacer una aprobacion anterior.
        """

        approved_transaction = {
            **self.transaction_data,
            "id": "TX-FIRST-APPROVED-001",
            "status": "APPROVED",
        }

        declined_transaction = {
            **self.transaction_data,
            "id": "TX-LATER-DECLINED-002",
            "status": "DECLINED",
        }

        mock_get.side_effect = [
            approved_transaction,
            declined_transaction,
        ]

        process_wompi_transaction_notification(
            approved_transaction["id"]
        )

        process_wompi_transaction_notification(
            declined_transaction["id"]
        )

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

        self.assertEqual(
            WompiTransaction.objects.filter(
                payment=self.payment,
                status="APPROVED",
            ).count(),
            1,
        )

        self.assertEqual(
            WompiTransaction.objects.filter(
                payment=self.payment,
                status="DECLINED",
            ).count(),
            1,
        )


    @patch(
        "reservations.wompi_notification_processing."
        "get_wompi_transaction"
    )
    def test_pending_transaction_becomes_approved(
        self,
        mock_get,
    ):
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

        # Primera notificacion: pendiente.
        process_wompi_transaction_notification(
            self.transaction_id
        )

        self.reservation.refresh_from_db()

        self.assertEqual(
            self.reservation.reservation_status,
            "PENDING_PAYMENT",
        )

        # Segunda notificacion: aprobada.
        process_wompi_transaction_notification(
            self.transaction_id
        )

        self.payment.refresh_from_db()
        self.reservation.refresh_from_db()

        wompi_transaction = WompiTransaction.objects.get(
            provider_transaction_id=self.transaction_id
        )

        self.assertEqual(
            wompi_transaction.status,
            "APPROVED",
        )

        self.assertIsNotNone(
            wompi_transaction.approved_at
        )

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
                provider_transaction_id=self.transaction_id,
            ).count(),
            1,
        )
