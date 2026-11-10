
from django.utils import timezone

from .models import Payment, Reservation, WompiTransaction


def classify_expired_reservation(reservation_id):
    """
    Clasifica una reserva vencida segun su
    situacion financiera.

    No modifica datos ni consulta Wompi.
    """

    reservation = Reservation.objects.get(pk=reservation_id)

    if (
        reservation.reservation_status != "PENDING_PAYMENT"
        or reservation.hold_expires_at is None
        or reservation.hold_expires_at > timezone.now()
    ):
        return "NOT_ELIGIBLE"

    payments = Payment.objects.filter(
        reservation=reservation,
        provider="WOMPI",
    )

    if payments.filter(
        requires_reconciliation=True,
    ).exists():
        return "FINANCIAL_REVIEW"

    if payments.filter(
        payment_status="APPROVED",
    ).exists():
        return "FINANCIAL_REVIEW"

    transactions = WompiTransaction.objects.filter(
        payment__reservation=reservation,
        payment__provider="WOMPI",
    )

    if transactions.filter(status="APPROVED").exists():
        return "FINANCIAL_REVIEW"

    if transactions.filter(status="PENDING").exists():
        return "NEEDS_RECONCILIATION"

    if payments.filter(payment_status="PENDING").exists():
        return "NEEDS_RECONCILIATION"

    return "CAN_EXPIRE"
