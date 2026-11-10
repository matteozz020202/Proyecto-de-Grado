import hmac
import re
import hashlib
from django.core.exceptions import ValidationError
from decimal import Decimal, InvalidOperation


def amount_to_cents(amount):
    """
    Convierte un valor monetario COP a centavos.

    No permite valores negativos, cero ni fracciones
    menores que un centavo.
    """
    if isinstance(amount, (bool, float)):
        raise ValueError("El monto debe ser un Decimal válido.")

    try:
        value = Decimal(str(amount))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("El monto no es válido.")

    if not value.is_finite() or value <= 0:
        raise ValueError("El monto debe ser mayor que cero.")

    cents = value * Decimal("100")

    if cents != cents.to_integral_value():
        raise ValueError(
            "El monto tiene más de dos decimales."
        )

    return int(cents)

def generate_integrity_signature(
    reference,
    amount_in_cents,
    integrity_secret,
    expiration_time=None,
):
    """
    Genera la firma SHA-256 de Wompi Sandbox.

    Si se utiliza expiration_time, el orden es:
    referencia + monto + COP + vencimiento + secreto.

    Sin expiration_time conserva compatibilidad
    con las firmas anteriores.
    """

    if not isinstance(reference, str) or not reference:
        raise ValueError("La referencia es obligatoria.")

    if (
        isinstance(amount_in_cents, bool)
        or not isinstance(amount_in_cents, int)
        or amount_in_cents <= 0
    ):
        raise ValueError(
            "El monto en centavos no es valido."
        )

    if (
        not isinstance(integrity_secret, str)
        or not integrity_secret.startswith("test_integrity_")
    ):
        raise ValueError(
            "Se requiere un secreto de integridad Sandbox."
        )

    if expiration_time is not None:
        if (
            not isinstance(expiration_time, str)
            or not re.fullmatch(
                r"\d{4}-\d{2}-\d{2}T"
                r"\d{2}:\d{2}:\d{2}\.\d{3}Z",
                expiration_time,
            )
        ):
            raise ValueError(
                "El vencimiento debe tener formato "
                "ISO 8601 UTC con milisegundos."
            )

    payload = (
        f"{reference}"
        f"{amount_in_cents}"
        "COP"
        f"{expiration_time or ''}"
        f"{integrity_secret}"
    )

    return hashlib.sha256(
        payload.encode("utf-8")
    ).hexdigest()


def verify_wompi_event(event, events_secret):
    """
    Verifica la firma de un evento de Wompi Sandbox.

    Devuelve True si el evento tiene una firma válida.
    No actualiza pagos ni reservas.
    """

    if (
        not isinstance(events_secret, str)
        or not events_secret.startswith("test_events_")
    ):
        raise ValueError(
            "Se requiere un secreto de eventos Sandbox."
        )

    if not isinstance(event, dict):
        return False

    if event.get("environment") != "test":
        return False

    if event.get("event") != "transaction.updated":
        return False

    signature = event.get("signature")
    data = event.get("data")
    timestamp = event.get("timestamp")

    if not isinstance(signature, dict):
        return False

    if not isinstance(data, dict):
        return False

    if isinstance(timestamp, bool) or not isinstance(
        timestamp, int
    ):
        return False

    properties = signature.get("properties")
    received_checksum = signature.get("checksum")

    if not isinstance(properties, list) or not properties:
        return False

    if not isinstance(received_checksum, str):
        return False

    if not re.fullmatch(
        r"[0-9a-fA-F]{64}",
        received_checksum,
    ):
        return False

    values = []

    for property_path in properties:
        if not isinstance(property_path, str):
            return False

        current = data

        for part in property_path.split("."):
            if (
                not part
                or not isinstance(current, dict)
                or part not in current
            ):
                return False

            current = current[part]

        if (
            isinstance(current, bool)
            or not isinstance(current, (str, int))
        ):
            return False

        values.append(str(current))

    payload = (
        "".join(values)
        + str(timestamp)
        + events_secret
    )

    expected_checksum = hashlib.sha256(
        payload.encode("utf-8")
    ).hexdigest()

    return hmac.compare_digest(
        expected_checksum,
        received_checksum.lower(),
    )


def validate_wompi_transaction(
    payment,
    transaction_data,
    *,
    allow_multiple_transactions=False,
):
    """
    Valida una transacción obtenida de Wompi
    contra un intento de pago registrado.

    Esta función NO verifica la procedencia de los
    datos. Debe recibir información previamente
    verificada con el proveedor.

    No modifica la base de datos.
    """
    if payment.provider != "WOMPI":
        raise ValidationError(
            "El intento no pertenece a Wompi."
        )

    if payment.payment_type != "DEPOSIT":
        raise ValidationError(
            "El intento no corresponde a un abono."
        )

    if not isinstance(transaction_data, dict):
        raise ValidationError(
            "Los datos de la transacción no son válidos."
        )

    reference = transaction_data.get("reference")
    transaction_id = transaction_data.get("id")
    amount = transaction_data.get("amount_in_cents")
    currency = transaction_data.get("currency")
    status = transaction_data.get("status")

    if (
        not isinstance(reference, str)
        or reference != payment.transaction_reference
    ):
        raise ValidationError(
            "La referencia de Wompi no coincide."
        )


    if not isinstance(transaction_id, str) or not transaction_id:
        raise ValidationError(
            "El identificador de Wompi no es válido."
        )

    if (
        not allow_multiple_transactions
        and payment.provider_transaction_id
        and payment.provider_transaction_id != transaction_id
    ):
        raise ValidationError(
            "La transacción no coincide con el intento."
        )


    expected_amount = amount_to_cents(payment.amount)

    if (
        isinstance(amount, bool)
        or not isinstance(amount, int)
        or amount != expected_amount
    ):
        raise ValidationError(
            "El importe de Wompi no coincide con el abono."
        )

    if currency != "COP" or payment.currency != "COP":
        raise ValidationError(
            "La moneda de la transacción no es válida."
        )

    allowed_statuses = {
        "PENDING",
        "APPROVED",
        "DECLINED",
        "VOIDED",
        "ERROR",
    }

    if status not in allowed_statuses:
        raise ValidationError(
            "El estado de Wompi no es reconocido."
        )

    return {
        "transaction_id": transaction_id,
        "status": status,
        "amount_in_cents": amount,
        "currency": currency,
        "reference": reference,
    }
