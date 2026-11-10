
from django.core.exceptions import ValidationError

from .models import Payment
from .wompi_client import WompiAPIError
from .wompi_verification import (
    verify_and_process_wompi_payment,
)
from .models import WompiTransaction
from .wompi_notification_processing import (
    process_wompi_transaction_notification,
)

def reconcile_wompi_payment(payment_id):
    """
    Consulta y concilia un intento de pago Wompi.

    No modifica reservas directamente.
    No presupone que un pago sin ID fue rechazado.
    No elimina intentos pendientes.
    """

    payment = Payment.objects.get(pk=payment_id)

    if payment.provider != "WOMPI":
        raise ValidationError(
            "El pago no pertenece a Wompi."
        )

    if payment.payment_status != "PENDING":
        return {
            "result": "ALREADY_PROCESSED",
            "payment_status": payment.payment_status,
        }

    if not payment.provider_transaction_id:
        return {
            "result": "AWAITING_TRANSACTION_ID",
            "payment_status": "PENDING",
        }

    try:
        updated_payment = verify_and_process_wompi_payment(
            payment.pk,
            payment.provider_transaction_id,
        )
    except WompiAPIError:
        return {
            "result": "PROVIDER_UNAVAILABLE",
            "payment_status": "PENDING",
        }

    if updated_payment.payment_status == "PENDING":
        return {
            "result": "STILL_PENDING",
            "payment_status": "PENDING",
        }

    if updated_payment.requires_reconciliation:
        return {
            "result": "REQUIRES_REVIEW",
            "payment_status": updated_payment.payment_status,
        }

    return {
        "result": "PROCESSED",
        "payment_status": updated_payment.payment_status,
    }


def reconcile_wompi_transaction(transaction_id):
    """
    Concilia una transaccion individual de Wompi.

    Solo trabaja con identificadores que ya existen
    en nuestro historial.

    Consulta Wompi mediante el servicio autenticado
    de procesamiento de notificaciones.

    No elimina registros ni libera reservas.
    """

    if not isinstance(transaction_id, str) or not transaction_id:
        raise ValidationError(
            "El identificador de transaccion no es valido."
        )

    try:
        wompi_transaction = (
            WompiTransaction.objects
            .select_related("payment")
            .get(provider_transaction_id=transaction_id)
        )
    except WompiTransaction.DoesNotExist as exc:
        raise ValidationError(
            "La transaccion no esta registrada."
        ) from exc

    if wompi_transaction.payment.provider != "WOMPI":
        raise ValidationError(
            "El pago no pertenece a Wompi."
        )

    if wompi_transaction.status != "PENDING":
        return {
            "result": "ALREADY_PROCESSED",
            "transaction_status": wompi_transaction.status,
        }

    try:
        payment = process_wompi_transaction_notification(
            transaction_id
        )
    except WompiAPIError:
        return {
            "result": "PROVIDER_UNAVAILABLE",
            "transaction_status": "PENDING",
        }

    wompi_transaction.refresh_from_db()
    payment.refresh_from_db()

    if wompi_transaction.status == "PENDING":
        return {
            "result": "STILL_PENDING",
            "transaction_status": "PENDING",
        }

    if payment.requires_reconciliation:
        return {
            "result": "REQUIRES_REVIEW",
            "transaction_status": wompi_transaction.status,
        }

    return {
        "result": "PROCESSED",
        "transaction_status": wompi_transaction.status,
    }
