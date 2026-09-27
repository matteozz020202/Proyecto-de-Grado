from datetime import date

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from reservations.services import get_availability

from .models import Venue, Court


@login_required
def establecimientos(request):
    venues = Venue.objects.filter(
        is_active=True
    ).order_by(
        "venue_name"
    )

    return render(
        request,
        "courts/establecimientos.html",
        {
            "establecimientos": venues
        }
    )


@login_required
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
        "court_name"
    )

    return render(
        request,
        "courts/canchas.html",
        {
            "establecimiento": venue,
            "canchas": courts
        }
    )


@login_required
def disponibilidad_cancha(
    request,
    cancha_id
):
    court = get_object_or_404(
        Court.objects.select_related(
            "venue"
        ),
        court_id=cancha_id,
        is_active=True
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