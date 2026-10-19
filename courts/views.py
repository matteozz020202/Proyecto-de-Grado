from datetime import date

from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.db.models import Count, Min, Q

from reservations.services import calculate_reservation_values, get_availability

from .models import Venue, Court


def establecimientos(request):
    venues = Venue.objects.filter(
        is_active=True
    ).annotate(
        active_court_count=Count("courts", filter=Q(courts__is_active=True)),
        starting_price=Min("courts__price_per_hour", filter=Q(courts__is_active=True, courts__price_per_hour__gte=0)),
    ).order_by("venue_name", "venue_id")

    return render(
        request,
        "courts/establecimientos.html",
        {
            "establecimientos": venues
        }
    )


def canchas_establecimiento(
    request,
    venue_id
):
    venue = get_object_or_404(
        Venue,
        venue_id=venue_id,
        is_active=True
    )

    courts = Court.objects.filter(
        venue=venue,
        is_active=True
    ).order_by(
        "court_name", "court_id"
    )

    return render(
        request,
        "courts/canchas.html",
        {
            "establecimiento": venue,
            "canchas": courts
        }
    )


def disponibilidad_cancha(
    request,
    cancha_id
):
    court = get_object_or_404(
        Court.objects.select_related(
            "venue"
        ),
        court_id=cancha_id,
        is_active=True,
        venue__is_active=True
    )

    selected_date = None
    slots = None
    error = None

    today = timezone.localdate()

    date_parameter = request.GET.get(
        "fecha"
    )

    if date_parameter:
        try:
            selected_date = date.fromisoformat(
                date_parameter
            )

            if selected_date < today:
                error = (
                    "No puedes consultar disponibilidad "
                    "para una fecha anterior a hoy."
                )
            else:
                slots = get_availability(
                    court,
                    selected_date
                )

        except ValueError:
            error = (
                "La fecha seleccionada no es válida."
            )

    if slots:
        for slot in slots:
            slot["values"] = calculate_reservation_values(court, selected_date, slot["start_time"], slot["end_time"])
            slot["one_hour"] = slot["values"]["duration_hours"] == 1

    return render(
        request,
        "courts/disponibilidad.html",
        {
            "cancha": court,
            "fecha_seleccionada": selected_date,
            "slots": slots,
            "error": error,
            "hoy": today,
        }
    )
