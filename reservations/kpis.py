from datetime import timedelta
from decimal import Decimal

from courts.models import Court, CourtSchedule
from reservations.models import Reservation

# Estados que representan reservas efectivamente realizadas
# para métricas operativas como ocupación, horas e ingresos.
KPI_RESERVATION_STATUSES = (
    "CONFIRMED",
    "COMPLETED",
)


def get_reservations_queryset(
    start_date=None,
    end_date=None,
    court_id=None,
    venue_id=None,
):
    """
    Query base de reservas para reportes y KPIs.

    Permite filtrar por:
    - fecha inicial
    - fecha final
    - cancha
    - establecimiento
    """

    reservations = (
        Reservation.objects
        .select_related(
            "court",
            "court__venue",
            "user",
        )
        .all()
    )

    if start_date:
        reservations = reservations.filter(
            reservation_date__gte=start_date
        )

    if end_date:
        reservations = reservations.filter(
            reservation_date__lte=end_date
        )

    if court_id:
        reservations = reservations.filter(
            court_id=court_id
        )

    if venue_id:
        reservations = reservations.filter(
            court__venue_id=venue_id
        )

    return reservations


def get_effective_reservations_queryset(
    start_date=None,
    end_date=None,
    court_id=None,
    venue_id=None,
):
    """
    Reservas válidas para KPIs operativos.

    Incluye:
    - CONFIRMED
    - COMPLETED

    Excluye pendientes, expiradas y canceladas.
    """

    return get_reservations_queryset(
        start_date=start_date,
        end_date=end_date,
        court_id=court_id,
        venue_id=venue_id,
    ).filter(
        reservation_status__in=KPI_RESERVATION_STATUSES
    )


def get_cancelled_reservations_queryset(
    start_date=None,
    end_date=None,
    court_id=None,
    venue_id=None,
):
    """
    Reservas canceladas utilizadas para
    indicadores de cancelación.
    """

    return get_reservations_queryset(
        start_date=start_date,
        end_date=end_date,
        court_id=court_id,
        venue_id=venue_id,
    ).filter(
        reservation_status="CANCELLED"
    )


def get_court_occupancy(
    start_date,
    end_date,
    court_id=None,
    venue_id=None,
):
    """
    Calcula la ocupación por cancha dentro de un rango de fechas.

    Ocupación =
    horas reservadas efectivas / horas disponibles * 100
    """

    courts = Court.objects.filter(
        is_active=True
    ).select_related(
        "venue"
    )

    if court_id:
        courts = courts.filter(
            court_id=court_id
        )

    if venue_id:
        courts = courts.filter(
            venue_id=venue_id
        )

    results = []

    for court in courts:

        available_minutes = 0

        current_date = start_date

        while current_date <= end_date:

            day_of_week = current_date.isoweekday()

            schedules = CourtSchedule.objects.filter(
                court=court,
                day_of_week=day_of_week,
                is_active=True
            )

            for schedule in schedules:

                start_minutes = (
                    schedule.start_time.hour * 60
                    + schedule.start_time.minute
                )

                end_minutes = (
                    schedule.end_time.hour * 60
                    + schedule.end_time.minute
                )

                available_minutes += (
                    end_minutes - start_minutes
                )

            current_date += timedelta(days=1)

        reservations = get_effective_reservations_queryset(
            start_date=start_date,
            end_date=end_date,
            court_id=court.court_id,
        )

        reserved_minutes = 0

        for reservation in reservations:

            start_minutes = (
                reservation.start_time.hour * 60
                + reservation.start_time.minute
            )

            end_minutes = (
                reservation.end_time.hour * 60
                + reservation.end_time.minute
            )

            reserved_minutes += (
                end_minutes - start_minutes
            )

        available_hours = (
            Decimal(available_minutes)
            / Decimal("60")
        )

        reserved_hours = (
            Decimal(reserved_minutes)
            / Decimal("60")
        )

        if available_minutes > 0:
            occupancy_percentage = (
                Decimal(reserved_minutes)
                / Decimal(available_minutes)
                * Decimal("100")
            )
        else:
            occupancy_percentage = Decimal("0")

        results.append({
            "court_id": court.court_id,
            "court_name": court.court_name,
            "venue_id": court.venue.venue_id,
            "venue_name": court.venue.venue_name,
            "available_hours": available_hours.quantize(
                Decimal("0.01")
            ),
            "reserved_hours": reserved_hours.quantize(
                Decimal("0.01")
            ),
            "occupancy_percentage": occupancy_percentage.quantize(
                Decimal("0.01")
            ),
        })

    return results


def get_summary_kpis(
    start_date,
    end_date,
    court_id=None,
    venue_id=None,
):
    """
    Retorna los KPIs generales de reservas efectivas
    dentro de un rango de fechas.

    Incluye únicamente:
    - CONFIRMED
    - COMPLETED
    """

    reservations = get_effective_reservations_queryset(
        start_date=start_date,
        end_date=end_date,
        court_id=court_id,
        venue_id=venue_id,
    )

    total_reservations = reservations.count()

    reserved_minutes = 0
    total_value = Decimal("0.00")

    for reservation in reservations:

        start_minutes = (
            reservation.start_time.hour * 60
            + reservation.start_time.minute
        )

        end_minutes = (
            reservation.end_time.hour * 60
            + reservation.end_time.minute
        )

        reserved_minutes += (
            end_minutes - start_minutes
        )

        total_value += reservation.total_amount

    reserved_hours = (
        Decimal(reserved_minutes)
        / Decimal("60")
    )

    return {
        "total_reservations": total_reservations,

        "reserved_hours": reserved_hours.quantize(
            Decimal("0.01")
        ),

        "total_value": total_value.quantize(
            Decimal("0.01")
        ),
    }


def get_cancellation_kpis(
    start_date,
    end_date,
    court_id=None,
    venue_id=None,
):
    """
    Calcula indicadores de cancelación dentro
    de un rango de fechas.

    Retorna:
    - total de reservas
    - reservas canceladas
    - tasa de cancelación
    """

    reservations = get_reservations_queryset(
        start_date=start_date,
        end_date=end_date,
        court_id=court_id,
        venue_id=venue_id,
    )

    cancelled_reservations = (
        get_cancelled_reservations_queryset(
            start_date=start_date,
            end_date=end_date,
            court_id=court_id,
            venue_id=venue_id,
        )
    )

    total_reservations = reservations.count()

    total_cancelled = cancelled_reservations.count()

    if total_reservations > 0:
        cancellation_rate = (
            Decimal(total_cancelled)
            / Decimal(total_reservations)
            * Decimal("100")
        )
    else:
        cancellation_rate = Decimal("0.00")

    return {
        "total_reservations": total_reservations,

        "cancelled_reservations": total_cancelled,

        "cancellation_rate": cancellation_rate.quantize(
            Decimal("0.01")
        ),
    }