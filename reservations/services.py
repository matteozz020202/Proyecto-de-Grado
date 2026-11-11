from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from courts.models import Court, CourtSchedule
from reservations.models import Reservation, Payment, WompiTransaction


BLOCKING_RESERVATION_STATUSES = [
    "PENDING_PAYMENT",
    "CONFIRMED",
    "COMPLETED",
]

HOLD_MINUTES = 15

MIN_BOOKING_ADVANCE_HOURS = 1

def get_reservation_datetime(reservation_date, start_time):
    tz = timezone.get_current_timezone()
    return timezone.make_aware(
        datetime.combine(reservation_date, start_time),
        tz
    )

def validate_minimum_booking_advance(reservation_date, start_time):
    reservation_datetime = get_reservation_datetime(
        reservation_date,
        start_time
    )
    minimum_datetime = (
        timezone.localtime(timezone.now())
        + timedelta(hours=MIN_BOOKING_ADVANCE_HOURS)
    )

    if reservation_datetime < minimum_datetime:
        raise ValidationError(
            "La reserva debe realizarse con mínimo "
            "1 hora de anticipación."
        )



def expire_pending_reservations():
    """
    Expira reservas pendientes cuyo bloqueo temporal
    terminó y que no tienen un pago Wompi pendiente.

    Cada reserva se comprueba dentro de una
    transacción con bloqueo de fila.

    Los pagos Wompi pendientes deberán resolverse
    posteriormente mediante conciliación.
    """

    now = timezone.now()

    candidate_ids = list(
        Reservation.objects.filter(
            reservation_status="PENDING_PAYMENT",
            hold_expires_at__isnull=False,
            hold_expires_at__lte=now,
        ).values_list("pk", flat=True)
    )

    expired_count = 0

    for reservation_id in candidate_ids:

        with transaction.atomic():

            reservation = (
                Reservation.objects
                .select_for_update()
                .get(pk=reservation_id)
            )

            # Revalidar después de obtener el bloqueo.
            if reservation.reservation_status != "PENDING_PAYMENT":
                continue

            if (
                reservation.hold_expires_at is None
                or reservation.hold_expires_at > timezone.now()
            ):
                continue

            # Comprobar intentos pendientes mientras
            # mantenemos bloqueada la reserva.
            has_pending_wompi_payment = (
                Payment.objects.filter(
                    reservation=reservation,
                    provider="WOMPI",
                    payment_status="PENDING",
                ).exists()
            )

            if has_pending_wompi_payment:
                            continue

            # Un Payment puede tener varias transacciones.
            # Aunque el estado general sea DECLINED,
            # otra transaccion puede seguir PENDING.
            has_pending_wompi_transaction = (
                WompiTransaction.objects.filter(
                    payment__reservation=reservation,
                    payment__provider="WOMPI",
                    status="PENDING",
                ).exists()
            )

            if has_pending_wompi_transaction:
                continue

            # No liberar automáticamente reservas
            # con excepciones financieras sin resolver.
            requires_financial_review = (
                Payment.objects.filter(
                    reservation=reservation,
                    provider="WOMPI",
                    requires_reconciliation=True,
                ).exists()
            )

            if requires_financial_review:
                continue

            # Nunca liberar automaticamente una reserva
            # si existe evidencia de un abono aprobado.
            has_approved_wompi_payment = (
                Payment.objects.filter(
                    reservation=reservation,
                    provider="WOMPI",
                    payment_status="APPROVED",
                ).exists()
            )

            if has_approved_wompi_payment:
                continue

            # Proteger tambien el historial individual.
            # Payment puede conservar un estado antiguo
            # o inconsistente respecto a WompiTransaction.
            has_approved_wompi_transaction = (
                WompiTransaction.objects.filter(
                    payment__reservation=reservation,
                    payment__provider="WOMPI",
                    status="APPROVED",
                ).exists()
            )

            if has_approved_wompi_transaction:
                continue

            reservation.reservation_status = "EXPIRED"


            reservation.save(
                update_fields=["reservation_status"]
            )

            expired_count += 1

    return expired_count




def get_availability(
    court,
    reservation_date,
    duration_minutes=None
):
    """
    Returns the available time slots for a court
    on a specific date.
    """

    # Expire old temporary reservations first.
    expire_pending_reservations()

    day_of_week = reservation_date.isoweekday()

    schedules = CourtSchedule.objects.filter(
        court=court,
        day_of_week=day_of_week,
        is_active=True
    ).order_by(
        "start_time"
    )

    if not schedules.exists():
        return []

    reservations = Reservation.objects.filter(
        court=court,
        reservation_date=reservation_date,
        reservation_status__in=BLOCKING_RESERVATION_STATUSES
    )

    available_slots = []

    minimum_datetime = (
        timezone.localtime(timezone.now())
        + timedelta(hours=MIN_BOOKING_ADVANCE_HOURS)
    )

    for schedule in schedules:

        slot_minutes = (
            duration_minutes
            if duration_minutes is not None
            else schedule.slot_duration_minutes
        )

        current_start = datetime.combine(
            reservation_date,
            schedule.start_time
        )

        schedule_end = datetime.combine(
            reservation_date,
            schedule.end_time
        )

        while (
            current_start
            + timedelta(minutes=slot_minutes)
            <= schedule_end
        ):
            current_end = (
                current_start
                + timedelta(minutes=slot_minutes)
            )

            slot_datetime = get_reservation_datetime(
                reservation_date,
                current_start.time()
            )

            if slot_datetime < minimum_datetime:
                current_start = current_end
                continue
            conflict_exists = reservations.filter(
                start_time__lt=current_end.time(),
                end_time__gt=current_start.time()
            ).exists()

            if not conflict_exists:
                available_slots.append({
                    "start_time": current_start.time(),
                    "end_time": current_end.time(),
                })

            current_start = current_end

    return available_slots


def calculate_reservation_values(
    court,
    reservation_date,
    start_time,
    end_time
):
    """
    Calculates reservation duration, total amount,
    required deposit and remaining amount.
    """

    if start_time >= end_time:
        raise ValidationError(
            "La hora de inicio debe ser anterior "
            "a la hora de finalización."
        )

    start_datetime = datetime.combine(
        reservation_date,
        start_time
    )

    end_datetime = datetime.combine(
        reservation_date,
        end_time
    )

    duration_seconds = Decimal(
        str(
            (
                end_datetime
                - start_datetime
            ).total_seconds()
        )
    )

    duration_hours = (
        duration_seconds
        / Decimal("3600")
    )

    total_amount = (
        court.price_per_hour
        * duration_hours
    ).quantize(
        Decimal("0.01")
    )

    deposit_percentage = (
        court.venue.deposit_percentage
    )

    deposit_required = (
        total_amount
        * deposit_percentage
        / Decimal("100")
    ).quantize(
        Decimal("0.01")
    )

    remaining_amount = (
        total_amount
        - deposit_required
    ).quantize(
        Decimal("0.01")
    )

    return {
        "duration_hours": duration_hours,
        "total_amount": total_amount,
        "deposit_percentage": deposit_percentage,
        "deposit_required": deposit_required,
        "remaining_amount": remaining_amount,
    }


@transaction.atomic
def create_pending_reservation(
    user,
    court,
    reservation_date,
    start_time,
    end_time,
    guest_name="",
    guest_phone="",
):
    """
    Creates a temporary reservation in
    PENDING_PAYMENT status.

    Calculates:
    - Total reservation amount.
    - Required deposit.
    - Remaining amount.
    - Hold expiration time.
    """

    # Bloquear la cancha durante la creación de la reserva.
    # Esto evita que dos solicitudes concurrentes creen
    # reservas para el mismo horario.
    #
    # El bloqueo permanece hasta finalizar la transacción.
    court = (
        Court.objects
        .select_related("venue")
        .select_for_update()
        .get(pk=court.pk)
    )


    # Expire reservations whose hold already ended.
    expire_pending_reservations()

    validate_minimum_booking_advance(
        reservation_date,
        start_time
    )

    if start_time >= end_time:
        raise ValidationError(
            "La hora de inicio debe ser anterior "
            "a la hora de finalización."
        )

    # Dataset convention:
    # 1 = Monday ... 7 = Sunday.
    day_of_week = reservation_date.isoweekday()

    schedule = CourtSchedule.objects.filter(
        court=court,
        day_of_week=day_of_week,
        is_active=True,
        start_time__lte=start_time,
        end_time__gte=end_time
    ).first()

    if schedule is None:
        raise ValidationError(
            "El horario seleccionado está fuera "
            "del horario operativo de la cancha."
        )

    # Reservation overlap rule:
    #
    # existing.start < new.end
    # AND
    # existing.end > new.start
    conflict_exists = Reservation.objects.filter(
        court=court,
        reservation_date=reservation_date,
        start_time__lt=end_time,
        end_time__gt=start_time,
        reservation_status__in=BLOCKING_RESERVATION_STATUSES
    ).exists()

    if conflict_exists:
        raise ValidationError(
            "La cancha ya está reservada "
            "o temporalmente bloqueada "
            "en este horario."
        )

    values = calculate_reservation_values(
        court,
        reservation_date,
        start_time,
        end_time
    )

    reservation = Reservation(
        court=court,
        user=user,
        guest_name=guest_name,
        guest_phone=guest_phone,
        reservation_date=reservation_date,
        start_time=start_time,
        end_time=end_time,
        total_amount=values["total_amount"],
        deposit_required=values["deposit_required"],
        remaining_amount=values["remaining_amount"],
        reservation_status="PENDING_PAYMENT",
        hold_expires_at=(
            timezone.now()
            + timedelta(
                minutes=HOLD_MINUTES
            )
        ),
        cancelled_at=None,
        data_source="SYSTEM"
    )

    reservation.full_clean()
    reservation.save()

    return reservation

@transaction.atomic
def create_confirmed_reservation(user,court,reservation_date,start_time,end_time,guest_name="",guest_phone="",*,apply_deposit=False):
    guest_name=(guest_name or "").strip()
    guest_phone=(guest_phone or "").strip()

    if user is None and not guest_name:
        raise ValidationError("Debes seleccionar un usuario registrado o indicar el nombre del cliente sin cuenta.")

    if user is not None:
        guest_name=""
        guest_phone=""

    court=Court.objects.select_for_update().get(pk=court.pk)
    reservation=create_pending_reservation(
        user=user,court=court,reservation_date=reservation_date,
        start_time=start_time,end_time=end_time,
        guest_name=guest_name,guest_phone=guest_phone
    )

    reservation.reservation_status="CONFIRMED"
    reservation.hold_expires_at=None

    if not apply_deposit:
        reservation.deposit_required=0
        reservation.remaining_amount=reservation.total_amount

    reservation.save(update_fields=[
        "reservation_status","hold_expires_at",
        "deposit_required","remaining_amount"
    ])
    return reservation


def create_admin_reservation(user,court,reservation_date,start_time,end_time,guest_name="",guest_phone=""):
    start_datetime = datetime.combine(reservation_date, start_time)
    end_datetime = datetime.combine(reservation_date, end_time)

    if end_datetime - start_datetime != timedelta(hours=1):
        raise ValidationError(
            "La reserva manual debe durar exactamente una hora."
        )

    return create_confirmed_reservation(
        user,court,reservation_date,start_time,end_time,
        guest_name=guest_name,guest_phone=guest_phone,
        apply_deposit=True
    )


@transaction.atomic
def process_simulated_payment(
    reservation,
    result
):
    """
    Registers a simulated deposit attempt.

    result must be:
    - APPROVED
    - REJECTED
    """

    result = result.upper()

    if result not in [
        "APPROVED",
        "REJECTED"
    ]:
        raise ValidationError(
            "El resultado del pago debe ser "
            "APPROVED o REJECTED."
        )

    # Release expired holds first.
    expire_pending_reservations()

    reservation = (
        Reservation.objects
        .select_for_update()
        .get(
            pk=reservation.pk
        )
    )

    if (
        reservation.reservation_status
        == "EXPIRED"
    ):
        raise ValidationError(
            "La reserva expiró y ya no puede "
            "recibir pagos."
        )

    if (
        reservation.reservation_status
        != "PENDING_PAYMENT"
    ):
        raise ValidationError(
            "Solo las reservas pendientes de pago "
            "pueden recibir un abono."
        )

    if (
        reservation.hold_expires_at
        and reservation.hold_expires_at
        <= timezone.now()
    ):
        reservation.reservation_status = "EXPIRED"

        reservation.save(
            update_fields=[
                "reservation_status"
            ]
        )

        raise ValidationError(
            "El tiempo disponible para realizar "
            "el abono expiró."
        )

    transaction_reference = (
        f"SIM-{uuid4().hex.upper()}"
    )

    payment = Payment.objects.create(
        reservation=reservation,
        amount=reservation.deposit_required,
        payment_type="DEPOSIT",
        payment_status=result,
        provider="SIMULATED",
        transaction_reference=transaction_reference,
        approved_at=(
            timezone.now()
            if result == "APPROVED"
            else None
        )
    )

    if result == "APPROVED":
        reservation.reservation_status = (
            "CONFIRMED"
        )

        reservation.hold_expires_at = None

        reservation.save(
            update_fields=[
                "reservation_status",
                "hold_expires_at",
            ]
        )

    return payment


@transaction.atomic
def cancel_reservation(
    reservation
):
    """
    Cancels a confirmed reservation and
    releases its time slot.
    """

    reservation = (
        Reservation.objects
        .select_for_update()
        .get(
            pk=reservation.pk
        )
    )

    if (
        reservation.reservation_status
        != "CONFIRMED"
    ):
        raise ValidationError(
            "Solo las reservas confirmadas "
            "pueden cancelarse."
        )

    reservation.reservation_status = (
        "CANCELLED"
    )

    reservation.cancelled_at = (
        timezone.now()
    )

    reservation.hold_expires_at = None

    reservation.save(
        update_fields=[
            "reservation_status",
            "cancelled_at",
            "hold_expires_at",
        ]
    )

    return reservation

@transaction.atomic
def complete_reservation(reservation):
    reservation=Reservation.objects.select_for_update().get(pk=reservation.pk)
    if reservation.reservation_status!="CONFIRMED":
        raise ValidationError("Solo las reservas confirmadas pueden marcarse como completadas.")
    reservation.reservation_status="COMPLETED"
    reservation.save(update_fields=["reservation_status"])
    return reservation


@transaction.atomic
def create_wompi_payment_attempt(reservation):
    """
    Registra o reutiliza un intento pendiente
    de pago del abono mediante Wompi Sandbox.

    No realiza solicitudes a Wompi.
    No aprueba pagos ni confirma reservas.
    """

    reservation = (
        Reservation.objects
        .select_for_update()
        .get(pk=reservation.pk)
    )

    if reservation.reservation_status != "PENDING_PAYMENT":
        raise ValidationError(
            "La reserva no está pendiente de pago."
        )

    if (
        reservation.hold_expires_at is None
        or reservation.hold_expires_at <= timezone.now()
    ):
        raise ValidationError(
            "El tiempo de la reserva ha vencido."
        )

    if reservation.deposit_required <= 0:
        raise ValidationError(
            "El abono debe ser mayor que cero."
        )

    # Evitar crear varios intentos pendientes
    # para la misma reserva.
    existing_payment = (
        Payment.objects
        .filter(
            reservation=reservation,
            provider="WOMPI",
            payment_type="DEPOSIT",
            payment_status="PENDING",
        )
        .order_by("-created_at", "-pk")
        .first()
    )

    if existing_payment is not None:
        return existing_payment

    reference = f"CL-{reservation.pk}-{uuid4().hex}"

    payment = Payment.objects.create(
        reservation=reservation,
        amount=reservation.deposit_required,
        payment_type="DEPOSIT",
        payment_status="PENDING",
        provider="WOMPI",
        transaction_reference=reference,
        currency="COP",
    )

    return payment

@transaction.atomic
def create_wompi_retry_attempt(reservation):
    """Crea un nuevo intento solo tras un rechazo Wompi verificado."""

    reservation = (
        Reservation.objects.select_for_update().get(pk=reservation.pk)
    )

    if reservation.reservation_status != "PENDING_PAYMENT":
        raise ValidationError("La reserva no esta pendiente de pago.")

    if (
        reservation.hold_expires_at is None
        or reservation.hold_expires_at <= timezone.now()
    ):
        raise ValidationError("El tiempo de la reserva ha vencido.")

    payments = list(
        Payment.objects.select_for_update()
        .filter(
            reservation=reservation,
            provider="WOMPI",
            payment_type="DEPOSIT",
        )
        .order_by("created_at", "pk")
    )
    transactions = list(
        WompiTransaction.objects.select_for_update().filter(
            payment__in=payments
        )
    )

    if any(payment.requires_reconciliation for payment in payments):
        raise ValidationError(
            "El pago requiere revision antes de reintentarlo."
        )

    if any(payment.payment_status == "APPROVED" for payment in payments):
        raise ValidationError("La reserva ya tiene un pago aprobado.")

    if any(
        wompi_transaction.status in {"PENDING", "APPROVED"}
        for wompi_transaction in transactions
    ):
        raise ValidationError(
            "Existe una transaccion que todavia no permite reintentar."
        )

    pending_payments = [
        payment
        for payment in payments
        if payment.payment_status == "PENDING"
    ]
    if pending_payments:
        pending = pending_payments[-1]
        if (
            pending.provider_transaction_id
            or any(
                wompi_transaction.payment_id == pending.pk
                for wompi_transaction in transactions
            )
        ):
            raise ValidationError(
                "El intento pendiente requiere verificacion."
            )
        return pending

    verified_decline = any(
        payment.payment_status == "DECLINED"
        and any(
            wompi_transaction.payment_id == payment.pk
            and wompi_transaction.status == "DECLINED"
            for wompi_transaction in transactions
        )
        for payment in payments
    )
    if not verified_decline:
        raise ValidationError(
            "No existe un rechazo verificado que permita reintentar."
        )

    return Payment.objects.create(
        reservation=reservation,
        amount=reservation.deposit_required,
        payment_type="DEPOSIT",
        payment_status="PENDING",
        provider="WOMPI",
        transaction_reference=f"CL-{reservation.pk}-{uuid4().hex}",
        currency="COP",
    )
