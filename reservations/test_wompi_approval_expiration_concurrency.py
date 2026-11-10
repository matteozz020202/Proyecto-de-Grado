
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

from courts.models import (
    Court,
    CourtSchedule,
    Venue,
)

from .models import Payment, Reservation, WompiTransaction
from .payment_processing import (
    process_verified_wompi_transaction,
)
from .services import (
    create_pending_reservation,
    create_wompi_payment_attempt,
    expire_pending_reservations,
)


@skipUnless(
    connection.vendor == "postgresql",
    "Esta prueba requiere PostgreSQL.",
)
class WompiApprovalExpirationConcurrencyTests(
    TransactionTestCase
):

    def setUp(self):
        user = get_user_model().objects.create_user(
            username="wompi_expiration_race_user"
        )

        venue = Venue.objects.create(
            venue_name="Arena Approval Expiration",
            deposit_percentage=30,
        )

        court = Court.objects.create(
            venue=venue,
            court_name="Cancha Approval Expiration",
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

        # El vencimiento debe existir en PostgreSQL
        # antes de lanzar ambos procesos.
        Reservation.objects.filter(
            pk=self.reservation.pk
        ).update(
            hold_expires_at=(
                timezone.now() - timedelta(minutes=1)
            )
        )

    def test_late_approval_and_expiration_are_safe(
        self,
    ):
        """
        Una aprobacion posterior al vencimiento
        no debe confirmar automaticamente la reserva.

        Tampoco debe perderse el registro del dinero
        recibido, aunque la expiracion se ejecute
        simultaneamente.
        """

        payment_id = self.payment.pk

        transaction_id = "TX-APPROVAL-EXPIRATION-001"

        transaction_data = {
            "id": transaction_id,
            "reference": self.payment.transaction_reference,
            "amount_in_cents": 3900000,
            "currency": "COP",
            "status": "APPROVED",
        }

        barrier = Barrier(3, timeout=15)

        def run_approval():
            close_old_connections()

            try:
                barrier.wait()

                return process_verified_wompi_transaction(
                    payment_id,
                    transaction_data,
                ).pk

            finally:
                connections.close_all()

        def run_expiration():
            close_old_connections()

            try:
                barrier.wait()
                return expire_pending_reservations()

            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            approval_future = executor.submit(run_approval)
            expiration_future = executor.submit(run_expiration)

            barrier.wait()

            approved_payment_id = approval_future.result(
                timeout=20
            )

            expired_count = expiration_future.result(
                timeout=20
            )

        payment = Payment.objects.get(pk=payment_id)

        reservation = Reservation.objects.get(
            pk=self.reservation.pk
        )

        wompi_transaction = WompiTransaction.objects.get(
            provider_transaction_id=transaction_id
        )

        self.assertEqual(
            approved_payment_id,
            payment_id,
        )

        # El Payment estaba PENDING cuando vencio.
        # La expiracion debe protegerlo.
        self.assertEqual(expired_count, 0)

        self.assertEqual(
            payment.payment_status,
            "APPROVED",
        )

        self.assertTrue(
            payment.requires_reconciliation
        )

        self.assertEqual(
            payment.reconciliation_reason,
            "LATE_APPROVAL",
        )

        self.assertEqual(
            wompi_transaction.status,
            "APPROVED",
        )

        self.assertEqual(
            reservation.reservation_status,
            "PENDING_PAYMENT",
        )

        self.assertEqual(
            WompiTransaction.objects.filter(
                payment=payment,
                status="APPROVED",
            ).count(),
            1,
        )

    def test_approval_after_reservation_expired_requires_review(
        self,
    ):
        """
        Una reserva expirada no puede confirmarse
        posteriormente por una nueva aprobacion.

        El dinero aprobado debe quedar registrado
        para conciliacion financiera.
        """

        reference = self.payment.transaction_reference

        declined_data = {
            "id": "TX-EXPIRED-DECLINED-001",
            "reference": reference,
            "amount_in_cents": 3900000,
            "currency": "COP",
            "status": "DECLINED",
        }

        approved_data = {
            **declined_data,
            "id": "TX-EXPIRED-APPROVED-002",
            "status": "APPROVED",
        }

        # 1. Primera transaccion rechazada.
        process_verified_wompi_transaction(
            self.payment.pk,
            declined_data,
        )

        self.payment.refresh_from_db()

        self.assertEqual(
            self.payment.payment_status,
            "DECLINED",
        )

        # 2. La reserva vencida se libera.
        expired_count = expire_pending_reservations()

        self.reservation.refresh_from_db()

        self.assertEqual(expired_count, 1)

        self.assertEqual(
            self.reservation.reservation_status,
            "EXPIRED",
        )

        # 3. Wompi comunica otra transaccion aprobada.
        process_verified_wompi_transaction(
            self.payment.pk,
            approved_data,
        )

        self.payment.refresh_from_db()
        self.reservation.refresh_from_db()

        # 4. La reserva NO se vuelve a confirmar.
        self.assertEqual(
            self.reservation.reservation_status,
            "EXPIRED",
        )

        # 5. La aprobacion se registra.
        self.assertEqual(
            self.payment.payment_status,
            "APPROVED",
        )

        self.assertTrue(
            self.payment.requires_reconciliation,
        )

        self.assertEqual(
            self.payment.reconciliation_reason,
            "RESERVATION_NOT_PAYABLE",
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
