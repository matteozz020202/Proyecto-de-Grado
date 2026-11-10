
from django.utils import timezone

from .models import Payment, Reservation, WompiTransaction
from .wompi_reconciliation import (
    reconcile_wompi_payment,
    reconcile_wompi_transaction,
)


def reconcile_expired_reservation(reservation_id):
    """
    Revisa los pagos Wompi de una reserva
    cuyo tiempo de retencion ya termino.

    No expira, cancela ni libera reservas.
    No considera un fallo de red como rechazo.
    """

    reservation = Reservation.objects.get(
        pk=reservation_id
    )

    if (
        reservation.reservation_status != "PENDING_PAYMENT"
        or reservation.hold_expires_at is None
        or reservation.hold_expires_at > timezone.now()
    ):
        return {
            "result": "NOT_ELIGIBLE",
            "checks": [],
        }

    payments = list(
        Payment.objects.filter(
            reservation=reservation,
            provider="WOMPI",
        )
    )

    checks = []

    for payment in payments:
        # Revisar todas las transacciones pendientes
        # conocidas, no solamente el ID representativo
        # almacenado en Payment.
        pending_transaction_ids = list(
            WompiTransaction.objects.filter(
                payment=payment,
                status="PENDING",
            ).values_list(
                "provider_transaction_id",
                flat=True,
            )
        )

        if pending_transaction_ids:
            for transaction_id in pending_transaction_ids:
                result = reconcile_wompi_transaction(
                    transaction_id
                )

                checks.append({
                    "payment_id": payment.pk,
                    "transaction_id": transaction_id,
                    "result": result["result"],
                })

        elif payment.payment_status == "PENDING":
            # Compatibilidad con pagos anteriores
            # que todavia no tienen historial individual.
            result = reconcile_wompi_payment(
                payment.pk
            )

            checks.append({
                "payment_id": payment.pk,
                "transaction_id": (
                    payment.provider_transaction_id
                ),
                "result": result["result"],
            })

    reservation.refresh_from_db()

    return {
        "result": "CHECKED",
        "reservation_status": reservation.reservation_status,
        "checks": checks,
    }
