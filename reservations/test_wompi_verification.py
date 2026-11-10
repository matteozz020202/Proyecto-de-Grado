
from datetime import time, timedelta
from unittest.mock import patch

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
from .wompi_client import WompiAPIError
from .wompi_verification import (
    verify_and_process_wompi_payment,
)


class WompiVerificationTests(TestCase):

    def setUp(self):
        user = get_user_model().objects.create_user(
            username="verification_user"
        )

        venue = Venue.objects.create(
            venue_name="Arena Verification",
            deposit_percentage=30,
        )

        court = Court.objects.create(
            venue=venue,
            court_name="Cancha Verification",
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

        self.transaction_id = "TX-SANDBOX-VERIFY-001"

        self.transaction_data = {
            "id": self.transaction_id,
            "reference": self.payment.transaction_reference,
            "amount_in_cents": 3900000,
            "currency": "COP",
            "status": "APPROVED",
        }

    @patch(
        "reservations.wompi_verification.get_wompi_transaction"
    )
    def test_verified_approval_confirms_reservation(
        self,
        mock_get,
    ):
        mock_get.return_value = self.transaction_data

        result = verify_and_process_wompi_payment(
            self.payment.pk,
            self.transaction_id,
        )

        self.reservation.refresh_from_db()

        self.assertEqual(result.payment_status, "APPROVED")
        self.assertEqual(
            self.reservation.reservation_status,
            "CONFIRMED",
        )

        mock_get.assert_called_once_with(
            self.transaction_id
        )

    @patch(
        "reservations.wompi_verification.get_wompi_transaction"
    )
    def test_verified_decline_does_not_confirm(
        self,
        mock_get,
    ):
        mock_get.return_value = {
            **self.transaction_data,
            "status": "DECLINED",
        }

        verify_and_process_wompi_payment(
            self.payment.pk,
            self.transaction_id,
        )

        self.reservation.refresh_from_db()
        self.payment.refresh_from_db()

        self.assertEqual(
            self.payment.payment_status,
            "DECLINED",
        )
        self.assertEqual(
            self.reservation.reservation_status,
            "PENDING_PAYMENT",
        )

    @patch(
        "reservations.wompi_verification.get_wompi_transaction"
    )
    def test_wrong_amount_is_rejected(self, mock_get):
        mock_get.return_value = {
            **self.transaction_data,
            "amount_in_cents": 100,
        }

        with self.assertRaises(ValidationError):
            verify_and_process_wompi_payment(
                self.payment.pk,
                self.transaction_id,
            )

        self.payment.refresh_from_db()

        self.assertEqual(
            self.payment.payment_status,
            "PENDING",
        )

    @patch(
        "reservations.wompi_verification.get_wompi_transaction"
    )
    def test_wrong_reference_is_rejected(self, mock_get):
        mock_get.return_value = {
            **self.transaction_data,
            "reference": "OTHER-REFERENCE",
        }

        with self.assertRaises(ValidationError):
            verify_and_process_wompi_payment(
                self.payment.pk,
                self.transaction_id,
            )

        self.assertEqual(
            Payment.objects.get(pk=self.payment.pk).payment_status,
            "PENDING",
        )

    @patch(
        "reservations.wompi_verification.get_wompi_transaction"
    )
    def test_api_failure_does_not_modify_payment(
        self,
        mock_get,
    ):
        mock_get.side_effect = WompiAPIError(
            "No fue posible comunicarse con Wompi."
        )

        with self.assertRaises(WompiAPIError):
            verify_and_process_wompi_payment(
                self.payment.pk,
                self.transaction_id,
            )

        self.payment.refresh_from_db()
        self.reservation.refresh_from_db()

        self.assertEqual(self.payment.payment_status, "PENDING")
        self.assertEqual(
            self.reservation.reservation_status,
            "PENDING_PAYMENT",
        )

    @patch(
        "reservations.wompi_verification.get_wompi_transaction"
    )
    def test_duplicate_approved_result_is_idempotent(
        self,
        mock_get,
    ):
        mock_get.return_value = self.transaction_data

        first = verify_and_process_wompi_payment(
            self.payment.pk,
            self.transaction_id,
        )

        second = verify_and_process_wompi_payment(
            self.payment.pk,
            self.transaction_id,
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
        "reservations.wompi_verification.get_wompi_transaction"
    )
    def test_non_wompi_payment_is_rejected(self, mock_get):
        self.payment.provider = "SIMULATED"
        self.payment.save(update_fields=["provider"])

        with self.assertRaises(ValidationError):
            verify_and_process_wompi_payment(
                self.payment.pk,
                self.transaction_id,
            )

        mock_get.assert_not_called()

    @patch(
        "reservations.wompi_verification.get_wompi_transaction"
    )
    def test_existing_transaction_id_mismatch(
        self,
        mock_get,
    ):
        self.payment.provider_transaction_id = "TX-OTHER"
        self.payment.save(
            update_fields=["provider_transaction_id"]
        )

        with self.assertRaises(ValidationError):
            verify_and_process_wompi_payment(
                self.payment.pk,
                self.transaction_id,
            )

        mock_get.assert_not_called()
