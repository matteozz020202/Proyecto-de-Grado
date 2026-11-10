from django.core.cache import cache
from django.core.exceptions import ValidationError

from .models import Payment
from .payment_processing import process_verified_wompi_transaction
from .wompi_client import get_wompi_transaction


RETURN_CHECK_LIMIT = 5
RETURN_CHECK_WINDOW_SECONDS = 60


def claim_return_verification_attempt(user_id, reservation_id):
    """Limita consultas iniciadas desde la URL de retorno."""
    cache_key = (
        f"wompi-return-check:{user_id}:{reservation_id}"
    )

    if cache.add(
        cache_key,
        1,
        timeout=RETURN_CHECK_WINDOW_SECONDS,
    ):
        return True

    try:
        attempts = cache.incr(cache_key)
    except ValueError:
        cache.set(
            cache_key,
            1,
            timeout=RETURN_CHECK_WINDOW_SECONDS,
        )
        return True

    return attempts <= RETURN_CHECK_LIMIT


def verify_wompi_return_transaction(reservation, transaction_id):
    """
    Consulta Wompi y procesa el resultado solo si la referencia
    autenticada pertenece a un pago de la reserva indicada.

    No confía en estados recibidos por query string.
    """
    transaction_data = get_wompi_transaction(transaction_id)
    reference = transaction_data.get("reference")

    if not isinstance(reference, str) or not reference:
        raise ValidationError(
            "No fue posible asociar la transacción a esta reserva."
        )

    try:
        payment = Payment.objects.get(
            reservation=reservation,
            provider="WOMPI",
            payment_type="DEPOSIT",
            transaction_reference=reference,
        )
    except Payment.DoesNotExist as exc:
        raise ValidationError(
            "No fue posible asociar la transacción a esta reserva."
        ) from exc

    return process_verified_wompi_transaction(
        payment.pk,
        transaction_data,
    )
