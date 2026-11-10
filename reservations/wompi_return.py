
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .models import Reservation
from .wompi_client import WompiAPIError
from .wompi_return_verification import (
    claim_return_verification_attempt,
    verify_wompi_return_transaction,
)


@never_cache
@login_required(login_url="users:login")
@require_GET
def wompi_payment_return(request, reserva_id):
    """
    Muestra el estado local y, cuando Wompi devuelve un ID,
    consulta el resultado desde el backend antes de procesarlo.
    """

    reservation = get_object_or_404(
        Reservation.objects.select_related(
            "court",
            "court__venue",
        ).prefetch_related("payments"),
        pk=reserva_id,
        user=request.user,
    )

    transaction_id = request.GET.get("id", "").strip()
    verification_message = ""

    if (
        transaction_id
        and reservation.reservation_status != "CONFIRMED"
    ):
        if claim_return_verification_attempt(
            request.user.pk,
            reservation.pk,
        ):
            try:
                verify_wompi_return_transaction(
                    reservation,
                    transaction_id,
                )
            except (ValidationError, ValueError):
                verification_message = (
                    "No pudimos asociar esa transacción a tu reserva. "
                    "El pago no fue aplicado."
                )
            except WompiAPIError:
                verification_message = (
                    "Wompi no está disponible temporalmente. "
                    "Conservamos la reserva pendiente de verificación."
                )
            else:
                reservation.refresh_from_db()
        else:
            verification_message = (
                "Se alcanzó el límite temporal de consultas. "
                "Espera un minuto antes de volver a verificar."
            )

    status = reservation.reservation_status
    wompi_payments = list(
        reservation.payments.filter(
            provider="WOMPI",
            payment_type="DEPOSIT",
        ).order_by("-created_at")
    )
    requires_review = any(
        payment.requires_reconciliation
        for payment in wompi_payments
    )
    latest_payment_status = (
        wompi_payments[0].payment_status
        if wompi_payments
        else ""
    )

    if status == "CONFIRMED":
        result = "CONFIRMED"

    elif requires_review:
        result = "REVIEW"

    elif status == "PENDING_PAYMENT" and latest_payment_status in {
        "DECLINED",
        "VOIDED",
        "ERROR",
    }:
        result = "REJECTED"

    elif status == "PENDING_PAYMENT":
        result = "PENDING"

    elif status == "EXPIRED":
        result = "EXPIRED"

    else:
        result = "NOT_PAYABLE"

    return render(
        request,
        "reservations/wompi_payment_return.html",
        {
            "reserva": reservation,
            "resultado": result,
            "verification_message": verification_message,
            "transaction_id": transaction_id,
        },
    )
