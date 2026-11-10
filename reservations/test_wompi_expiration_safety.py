
from datetime import time, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from courts.models import Court, CourtSchedule, Venue

from .models import Payment, WompiTransaction
from .services import (
    create_pending_reservation,
    create_wompi_payment_attempt,
    expire_pending_reservations,
)


class WompiExpirationSafetyTests(TestCase):

    def setUp(self):
        user = get_user_model().objects.create_user(
            username="expiration_safety_user"
        )

        venue = Venue.objects.create(
            venue_name="Arena Expiration Safety",
            deposit_percentage=30,
        )

        court = Court.objects.create(
            venue=venue,
            court_name="Cancha Expiration Safety",
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

        # Simular un vencimiento ya confirmado
        # en la base de datos.
        type(self.reservation).objects.filter(
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

    def test_pending_transaction_prevents_expiration(self):
        # El resultado general corresponde al
        # primer intento rechazado.
        self.payment.payment_status = "DECLINED"
        self.payment.save(
            update_fields=["payment_status"]
        )

        self.add_transaction("TX-DECLINED-001", "DECLINED")
        self.add_transaction("TX-PENDING-002", "PENDING")

        count = expire_pending_reservations()

        self.reservation.refresh_from_db()

        self.assertEqual(count, 0)
        self.assertEqual(
            self.reservation.reservation_status,
            "PENDING_PAYMENT",
        )

    def test_financial_review_prevents_expiration(self):
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

        self.add_transaction("TX-LATE-001", "APPROVED")

        count = expire_pending_reservations()

        self.reservation.refresh_from_db()

        self.assertEqual(count, 0)
        self.assertEqual(
            self.reservation.reservation_status,
            "PENDING_PAYMENT",
        )

    def test_declined_without_pending_transactions_expires(self):
        self.payment.payment_status = "DECLINED"
        self.payment.save(
            update_fields=["payment_status"]
        )

        self.add_transaction("TX-DECLINED-ONLY", "DECLINED")

        count = expire_pending_reservations()

        self.reservation.refresh_from_db()

        self.assertEqual(count, 1)
        self.assertEqual(
            self.reservation.reservation_status,
            "EXPIRED",
        )


    def test_approved_payment_never_expires(self):
        """
        Una reserva con un Payment aprobado
        no puede liberarse automaticamente.
        """

        self.payment.payment_status = "APPROVED"
        self.payment.save(
            update_fields=["payment_status"]
        )

        count = expire_pending_reservations()

        self.reservation.refresh_from_db()

        self.assertEqual(count, 0)
        self.assertEqual(
            self.reservation.reservation_status,
            "PENDING_PAYMENT",
        )

    def test_approved_transaction_never_expires(self):
        """
        Una aprobacion individual debe proteger
        la reserva, incluso si Payment conserva
        un estado general diferente.
        """

        self.payment.payment_status = "DECLINED"
        self.payment.save(
            update_fields=["payment_status"]
        )

        self.add_transaction(
            "TX-APPROVED-PROTECTION",
            "APPROVED",
        )

        count = expire_pending_reservations()

        self.reservation.refresh_from_db()

        self.assertEqual(count, 0)
        self.assertEqual(
            self.reservation.reservation_status,
            "PENDING_PAYMENT",
        )
