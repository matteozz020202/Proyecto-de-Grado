
from django.core.exceptions import ValidationError

from .models import Payment
from .payment_processing import (
    process_verified_wompi_transaction,
)
from .wompi_client import get_wompi_transaction


def process_wompi_transaction_notification(transaction_id):
    """
    Procesa una transaccion identificada por Wompi.

    Primero consulta la API autenticada de Sandbox.
    Luego identifica el Payment mediante la referencia
    del comercio y delega el procesamiento seguro.

    Esta funcion no es una vista HTTP y no debe
    exponerse directamente como endpoint publico.
    """

    # Obtener datos directamente de Wompi.
    # Nunca confiar en una referencia recibida
    # solamente desde el navegador.
    transaction_data = get_wompi_transaction(
        transaction_id
    )

    reference = transaction_data.get("reference")

    if not isinstance(reference, str) or not reference:
        raise ValidationError(
            "La transaccion no contiene una referencia valida."
        )

    try:
        payment = Payment.objects.get(
            transaction_reference=reference
        )
    except Payment.DoesNotExist as exc:
        raise ValidationError(
            "No existe un pago asociado a esta referencia."
        ) from exc

    if (
        payment.provider != "WOMPI"
        or payment.payment_type != "DEPOSIT"
    ):
        raise ValidationError(
            "El pago asociado no corresponde "
            "a un abono de Wompi."
        )

    # El procesador comprueba de nuevo, dentro
    # de una transaccion atomica, la referencia,
    # importe, moneda, estado e identificador.
    return process_verified_wompi_transaction(
        payment.pk,
        transaction_data,
    )
