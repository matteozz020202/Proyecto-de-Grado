from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from courts.models import CourtSchedule
from reservations.models import Reservation, Payment


BLOCKING_RESERVATION_STATUSES = [
    "PENDING_PAYMENT",
    "CONFIRMED",
    "COMPLETED",
]

HOLD_MINUTES = 15


def expire_pending_reservations():
    """
    Marks as EXPIRED all PENDING_PAYMENT reservations
    whose temporary hold has expired.
    """

    now = timezone.now()

    count = Reservation.objects.filter(
        reservation_status="PENDING_PAYMENT",
        hold_expires_at__isnull=False,
        hold_expires_at__lte=now
    ).update(
        reservation_status="EXPIRED"
    )

    return count


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
    end_time
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

    # Expire reservations whose hold already ended.
    expire_pending_reservations()

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
def create_admin_reservation(
    user,
    court,
    reservation_date,
    start_time,
    end_time,
):
    """
    Creates a reservation manually from the
    administrative panel.

    The existing reservation creation service is reused
    so schedule and overlap validations remain centralized.

    Administrative reservations are confirmed immediately
    and do not use the 15-minute payment hold.
    """

    reservation = create_pending_reservation(
        user=user,
        court=court,
        reservation_date=reservation_date,
        start_time=start_time,
        end_time=end_time,
    )

    reservation.reservation_status = "CONFIRMED"
    reservation.hold_expires_at = None

    reservation.save(
        update_fields=[
            "reservation_status",
            "hold_expires_at",
        ]
    )

    return reservation


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