
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Payment, Reservation, WompiTransaction
from .wompi import validate_wompi_transaction


FINAL_PAYMENT_STATUSES = {
    "APPROVED",
    "DECLINED",
    "VOIDED",
    "ERROR",
}


@transaction.atomic
def process_verified_wompi_transaction(
    payment_id,
    transaction_data,
):
    """
    Procesa datos previamente verificados con Wompi.

    IMPORTANTE:
    Esta funcion NO autentica los datos recibidos.
    El llamador debe obtenerlos de una fuente
    autentica y verificable de Wompi.

    Payment representa el abono global.
    WompiTransaction conserva cada transaccion.
    """

    payment_lookup = Payment.objects.get(
        pk=payment_id
    )

    # Mantener siempre el mismo orden de bloqueos.
    reservation = (
        Reservation.objects
        .select_for_update()
        .get(pk=payment_lookup.reservation_id)
    )

    payment = (
        Payment.objects
        .select_for_update()
        .get(
            pk=payment_id,
            reservation=reservation,
        )
    )

    validated = validate_wompi_transaction(
        payment,
        transaction_data,
        allow_multiple_transactions=True,
    )

    transaction_id = validated["transaction_id"]
    new_status = validated["status"]

    # Compatibilidad con identificadores guardados
    # anteriormente en Payment.
    if (
        Payment.objects
        .filter(provider_transaction_id=transaction_id)
        .exclude(pk=payment.pk)
        .exists()
    ):
        raise ValidationError(
            "La transaccion pertenece a otro pago."
        )

    # Una transaccion de Wompi solo puede pertenecer
    # a un Payment.
    existing_transaction = (
        WompiTransaction.objects
        .filter(
            provider_transaction_id=transaction_id
        )
        .first()
    )

    if (
        existing_transaction is not None
        and existing_transaction.payment_id != payment.pk
    ):
        raise ValidationError(
            "La transaccion pertenece a otro pago."
        )

    if existing_transaction is not None:
        if (
            existing_transaction.amount_in_cents
            != validated["amount_in_cents"]
            or existing_transaction.currency
            != validated["currency"]
        ):
            raise ValidationError(
                "Los datos registrados de la "
                "transaccion no coinciden."
            )

        previous_transaction_status = (
            existing_transaction.status
        )

        # Los resultados definitivos son inmutables.
        if (
            previous_transaction_status
            in FINAL_PAYMENT_STATUSES
        ):
            if previous_transaction_status != new_status:
                raise ValidationError(
                    "La transaccion ya tiene un "
                    "resultado definitivo."
                )

            # Evento duplicado: no volver a contabilizar.
            return payment

        # Permitir PENDING -> estado definitivo.
        if previous_transaction_status != "PENDING":
            raise ValidationError(
                "El estado de la transaccion "
                "no es valido."
            )

        existing_transaction.status = new_status

        update_transaction_fields = [
            "status",
            "updated_at",
        ]

        if new_status == "APPROVED":
            existing_transaction.approved_at = timezone.now()
            update_transaction_fields.append("approved_at")

        existing_transaction.save(
            update_fields=update_transaction_fields
        )

        wompi_transaction = existing_transaction

    else:
        wompi_transaction = WompiTransaction.objects.create(
            payment=payment,
            provider_transaction_id=transaction_id,
            status=new_status,
            amount_in_cents=validated["amount_in_cents"],
            currency=validated["currency"],
            approved_at=(
                timezone.now()
                if new_status == "APPROVED"
                else None
            ),
        )

    # Si ya existia otra transaccion aprobada,
    # la nueva aprobacion requiere conciliacion.
    another_approved_transaction = (
        WompiTransaction.objects.filter(
            payment=payment,
            status="APPROVED",
        )
        .exclude(pk=wompi_transaction.pk)
        .exists()
    )

    # Mantener compatibilidad con otros pagos
    # aprobados asociados a la reserva.
    another_approved_payment = (
        Payment.objects.filter(
            reservation=reservation,
            provider="WOMPI",
            payment_type="DEPOSIT",
            payment_status="APPROVED",
        )
        .exclude(pk=payment.pk)
        .exists()
    )

    # Un evento PENDING no puede degradar un abono
    # ya aprobado o rechazado.
    if new_status == "PENDING":
        if (
            payment.payment_status == "PENDING"
            and not payment.provider_transaction_id
        ):
            payment.provider_transaction_id = transaction_id
            payment.save(
                update_fields=[
                    "provider_transaction_id",
                    "updated_at",
                ]
            )

        return payment

    # Los rechazos no pueden deshacer aprobaciones.
    if new_status != "APPROVED":
        if payment.payment_status != "APPROVED":
            payment.payment_status = new_status

            # Identificador de compatibilidad.
            # El historial completo se guarda arriba.
            if not payment.provider_transaction_id:
                payment.provider_transaction_id = transaction_id

            payment.save(
                update_fields=[
                    "provider_transaction_id",
                    "payment_status",
                    "updated_at",
                ]
            )

        return payment

    # En este punto hay una aprobacion verificada.
    if another_approved_transaction or another_approved_payment:
        payment.requires_reconciliation = True
        payment.reconciliation_reason = "DUPLICATE_APPROVAL"

    elif reservation.reservation_status != "PENDING_PAYMENT":
        payment.requires_reconciliation = True
        payment.reconciliation_reason = "RESERVATION_NOT_PAYABLE"

    elif (
        reservation.hold_expires_at is None
        or reservation.hold_expires_at <= timezone.now()
    ):
        payment.requires_reconciliation = True
        payment.reconciliation_reason = "LATE_APPROVAL"

    else:
        reservation.reservation_status = "CONFIRMED"
        reservation.hold_expires_at = None

        reservation.save(
            update_fields=[
                "reservation_status",
                "hold_expires_at",
            ]
        )

    # El estado agregado no debe perder
    # una aprobacion anterior.
    payment.payment_status = "APPROVED"

    # Si hay una aprobacion, el identificador
    # representativo sera el de esa aprobacion.
    # Las demas transacciones siguen en el historial.
    if not another_approved_transaction:
        payment.provider_transaction_id = transaction_id

    if payment.approved_at is None:
        payment.approved_at = timezone.now()

    payment.save(
        update_fields=[
            "payment_status",
            "provider_transaction_id",
            "approved_at",
            "requires_reconciliation",
            "reconciliation_reason",
            "updated_at",
        ]
    )

    return payment
