from django.core.exceptions import ValidationError

from .models import Payment
from .payment_processing import (
    process_verified_wompi_transaction,
)
from .wompi_client import get_wompi_transaction
from .wompi import validate_wompi_transaction


def verify_and_process_wompi_payment(
    payment_id,
    transaction_id,
):
    """
    Consulta Wompi Sandbox y procesa el resultado.

    Nunca confia en el estado informado directamente
    por el navegador o por un webhook.

    La actualizacion de la base de datos se realiza
    dentro de process_verified_wompi_transaction().
    """

    if (
        not isinstance(payment_id, int)
        or isinstance(payment_id, bool)
        or payment_id <= 0
    ):
        raise ValidationError(
            "El identificador del pago no es valido."
        )

    if not isinstance(transaction_id, str) or not transaction_id:
        raise ValidationError(
            "El identificador de la transaccion es obligatorio."
        )

    payment = Payment.objects.select_related(
        "reservation"
    ).get(pk=payment_id)

    if payment.provider != "WOMPI":
        raise ValidationError(
            "El pago no pertenece a Wompi."
        )

    if (
        payment.provider_transaction_id
        and payment.provider_transaction_id != transaction_id
    ):
        raise ValidationError(
            "El identificador no coincide con el pago."
        )

    # Consulta autenticada mediante la llave privada.
    # Los errores de conexion se propagan al llamador.
    transaction_data = get_wompi_transaction(
        transaction_id
    )

    # Validacion antes de intentar actualizar registros.
    validate_wompi_transaction(
        payment,
        transaction_data,
    )

    # El procesador vuelve a validar con los registros
    # bloqueados dentro de una transaccion atomica.
    return process_verified_wompi_transaction(
        payment.pk,
        transaction_data,
    )
