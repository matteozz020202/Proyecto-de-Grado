from datetime import timezone as dt_timezone
import os

from django.core.exceptions import (
    ImproperlyConfigured,
    ValidationError,
)
from django.utils import timezone

from .wompi import (
    amount_to_cents,
    generate_integrity_signature,
)


WOMPI_CHECKOUT_URL = "https://checkout.wompi.co/p/"


def build_wompi_checkout_data(payment):
    """
    Prepara los parametros del Web Checkout Sandbox.

    No crea transacciones.
    No modifica Payment ni Reservation.
    No realiza conexiones HTTP.

    Solo admite abonos pendientes de reservas
    que todavia tienen un hold vigente.
    """

    reservation = payment.reservation

    if payment.pk is None:
        raise ValidationError(
            "El intento de pago debe estar registrado."
        )

    if (
        payment.provider != "WOMPI"
        or payment.payment_type != "DEPOSIT"
        or payment.payment_status != "PENDING"
    ):
        raise ValidationError(
            "El intento no esta disponible para checkout."
        )

    if (
        reservation.reservation_status != "PENDING_PAYMENT"
        or reservation.hold_expires_at is None
        or reservation.hold_expires_at <= timezone.now()
    ):
        raise ValidationError(
            "La reserva ya no esta disponible para pago."
        )

    if payment.currency != "COP":
        raise ValidationError(
            "La moneda del pago no es valida."
        )

    if payment.amount != reservation.deposit_required:
        raise ValidationError(
            "El abono no coincide con la reserva."
        )

    if not payment.transaction_reference:
        raise ValidationError(
            "La referencia del pago es obligatoria."
        )

    public_key = os.environ.get(
        "WOMPI_PUBLIC_KEY", ""
    ).strip()

    integrity_secret = os.environ.get(
        "WOMPI_INTEGRITY_SECRET", ""
    ).strip()

    if (
        not public_key.startswith("pub_test_")
        or len(public_key) <= len("pub_test_")
        or not integrity_secret.startswith("test_integrity_")
        or len(integrity_secret) <= len("test_integrity_")
    ):
        raise ImproperlyConfigured(
            "Credenciales del checkout Sandbox "
            "no configuradas correctamente."
        )

    amount_in_cents = amount_to_cents(
        payment.amount
    )


    # Convertir el vencimiento de la reserva a UTC.
    # Wompi espera milisegundos y una Z final.
    hold_expires_at = reservation.hold_expires_at

    if timezone.is_naive(hold_expires_at):
        raise ValidationError(
            "El vencimiento de la reserva "
            "debe incluir zona horaria."
        )

    expiration_utc = hold_expires_at.astimezone(
        dt_timezone.utc
    )

    expiration_time = (
        expiration_utc.strftime("%Y-%m-%dT%H:%M:%S")
        + f".{expiration_utc.microsecond // 1000:03d}Z"
    )

    signature = generate_integrity_signature(
        payment.transaction_reference,
        amount_in_cents,
        integrity_secret,
        expiration_time=expiration_time,
    )


    return {
        "checkout_url": WOMPI_CHECKOUT_URL,
        "public-key": public_key,
        "currency": "COP",
        "amount-in-cents": amount_in_cents,
        "reference": payment.transaction_reference,
        "signature:integrity": signature,
        "expiration-time": expiration_time,
    }
