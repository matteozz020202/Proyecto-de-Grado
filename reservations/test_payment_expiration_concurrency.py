
from concurrent.futures import (
    ThreadPoolExecutor,
)
from datetime import time, timedelta
from threading import Event
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.db import (
    connection,
    connections,
    close_old_connections,
    transaction,
)
from django.test import TransactionTestCase
from django.utils import timezone

from courts.models import Court, CourtSchedule, Venue
from .models import Reservation, Payment
from .services import (
    create_pending_reservation,
    create_wompi_payment_attempt,
    expire_pending_reservations,
)


@skipUnless(
    connection.vendor == "postgresql",
    "Esta prueba requiere PostgreSQL.",
)
class PaymentExpirationConcurrencyTests(TransactionTestCase):

    def setUp(self):
        User = get_user_model()

        self.user = User.objects.create_user(
            username="expiration_concurrent_user"
        )

        venue = Venue.objects.create(
            venue_name="Arena Concurrente",
            deposit_percentage=30,
        )

        court = Court.objects.create(
            venue=venue,
            court_name="Cancha Concurrente",
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
            user=self.user,
            court=court,
            reservation_date=day,
            start_time=time(18),
            end_time=time(19),
        )

    def test_expiration_waits_for_pending_payment_creation(self):
        payment_created = Event()
        release_transaction = Event()
        expiration_started = Event()

        reservation_id = self.reservation.pk

        def create_payment_and_hold_lock():
            close_old_connections()

            try:
                with transaction.atomic():
                    reservation = (
                        Reservation.objects
                        .select_for_update()
                        .get(pk=reservation_id)
                    )

                    payment = create_wompi_payment_attempt(
                        reservation
                    )

                    # Simular que el tiempo de retencion
                    # vence mientras la primera transaccion
                    # mantiene bloqueada la reserva.
                    reservation.hold_expires_at = (
                        timezone.now()
                        - timedelta(minutes=1)
                    )

                    reservation.save(
                        update_fields=["hold_expires_at"]
                    )

                    payment_created.set()

                    if not release_transaction.wait(timeout=10):
                        raise TimeoutError(
                            "No se libero la transaccion."
                        )

                    return payment.pk

            finally:
                connections.close_all()

        def expire_from_another_connection():
            close_old_connections()

            try:
                expiration_started.set()
                return expire_pending_reservations()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            payment_future = executor.submit(
                create_payment_and_hold_lock
            )

            try:
                self.assertTrue(
                    payment_created.wait(timeout=10),
                    "No se creo el intento de pago.",
                )

                expiration_future = executor.submit(
                    expire_from_another_connection
                )

                self.assertTrue(
                    expiration_started.wait(timeout=10),
                    "No se inicio la expiracion.",
                )

                # La expiracion puede finalizar sin esperar
                # si no encuentra reservas vencidas
                # confirmadas en PostgreSQL.
                #
                # El resultado final se verificara
                # despues de finalizar ambas transacciones.

            finally:
                release_transaction.set()

            payment_id = payment_future.result(timeout=10)
            expired_count = expiration_future.result(timeout=10)

        self.reservation.refresh_from_db()

        payment = Payment.objects.get(pk=payment_id)

        self.assertEqual(expired_count, 0)

        self.assertEqual(
            self.reservation.reservation_status,
            "PENDING_PAYMENT",
        )

        self.assertEqual(
            payment.payment_status,
            "PENDING",
        )

        self.assertEqual(payment.provider, "WOMPI")

        self.assertEqual(
            Payment.objects.filter(
                reservation=self.reservation,
                provider="WOMPI",
                payment_status="PENDING",
            ).count(),
            1,
        )