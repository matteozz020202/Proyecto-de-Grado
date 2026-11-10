
from concurrent.futures import ThreadPoolExecutor
from datetime import time, timedelta
from threading import Barrier
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.db import (
    connection,
    close_old_connections,
    connections,
)
from django.test import TransactionTestCase
from django.utils import timezone

from courts.models import Court, CourtSchedule, Venue

from .models import Payment, Reservation, WompiTransaction
from .payment_processing import (
    process_verified_wompi_transaction,
)
from .services import (
    create_pending_reservation,
    create_wompi_payment_attempt,
)


@skipUnless(
    connection.vendor == "postgresql",
    "Esta prueba requiere PostgreSQL.",
)
class WompiApprovalConcurrencyTests(TransactionTestCase):

    def setUp(self):
        user = get_user_model().objects.create_user(
            username="wompi_concurrent_user"
        )

        venue = Venue.objects.create(
            venue_name="Arena Wompi Concurrency",
            deposit_percentage=30,
        )

        court = Court.objects.create(
            venue=venue,
            court_name="Cancha Wompi Concurrency",
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

    def test_two_simultaneous_approvals_require_reconciliation(
        self,
    ):
        """
        Dos aprobaciones concurrentes del mismo abono
        deben conservarse sin duplicar la confirmacion.
        """

        payment_id = self.payment.pk

        reference = self.payment.transaction_reference

        first_data = {
            "id": "TX-CONCURRENT-APPROVED-001",
            "reference": reference,
            "amount_in_cents": 3900000,
            "currency": "COP",
            "status": "APPROVED",
        }

        second_data = {
            **first_data,
            "id": "TX-CONCURRENT-APPROVED-002",
        }

        # Los tres participantes se sincronizan
        # antes de iniciar el procesamiento.
        barrier = Barrier(3, timeout=15)

        def process_in_separate_connection(data):
            close_old_connections()

            try:
                barrier.wait()

                result = process_verified_wompi_transaction(
                    payment_id,
                    data,
                )

                return result.pk

            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            first_future = executor.submit(
                process_in_separate_connection,
                first_data,
            )

            second_future = executor.submit(
                process_in_separate_connection,
                second_data,
            )

            barrier.wait()

            first_payment_id = first_future.result(
                timeout=20
            )

            second_payment_id = second_future.result(
                timeout=20
            )

        self.assertEqual(
            first_payment_id,
            payment_id,
        )

        self.assertEqual(
            second_payment_id,
            payment_id,
        )

        reservation = Reservation.objects.get(
            pk=self.reservation.pk
        )

        payment = Payment.objects.get(
            pk=payment_id
        )

        self.assertEqual(
            reservation.reservation_status,
            "CONFIRMED",
        )

        self.assertIsNone(
            reservation.hold_expires_at
        )

        self.assertEqual(
            payment.payment_status,
            "APPROVED",
        )

        self.assertTrue(
            payment.requires_reconciliation
        )

        self.assertEqual(
            payment.reconciliation_reason,
            "DUPLICATE_APPROVAL",
        )

        self.assertEqual(
            Payment.objects.filter(
                reservation=reservation,
                provider="WOMPI",
                payment_type="DEPOSIT",
                payment_status="APPROVED",
            ).count(),
            1,
        )

        self.assertEqual(
            WompiTransaction.objects.filter(
                payment=payment,
                status="APPROVED",
            ).count(),
            2,
        )

        self.assertEqual(
            set(
                WompiTransaction.objects.filter(
                    payment=payment,
                ).values_list(
                    "provider_transaction_id",
                    flat=True,
                )
            ),
            {
                "TX-CONCURRENT-APPROVED-001",
                "TX-CONCURRENT-APPROVED-002",
            },
        )
