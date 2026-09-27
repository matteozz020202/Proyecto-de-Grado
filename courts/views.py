from datetime import date

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from reservations.services import obtener_disponibilidad

from .models import Venue, Cancha


@login_required
def establecimientos(request):
    establecimientos = Venue.objects.filter(
        activo=True
    ).order_by("nombre")

    return render(
        request,
        "courts/establecimientos.html",
        {
            "establecimientos": establecimientos
        }
    )


@login_required
def canchas_establecimiento(request, venue_id):
    establecimiento = get_object_or_404(
        Venue,
        id=venue_id,
        activo=True
    )

    canchas = Cancha.objects.filter(
        venue=establecimiento,
        activa=True
    ).order_by("nombre")

    return render(
        request,
        "courts/canchas.html",
        {
            "establecimiento": establecimiento,
            "canchas": canchas
        }
    )

@login_required
def disponibilidad_cancha(request, cancha_id):
    cancha = get_object_or_404(
        Cancha.objects.select_related("venue"),
        id=cancha_id,
        activa=True
    )

    fecha_seleccionada = None
    slots = None
    error = None

    hoy = timezone.localdate()

    fecha_parametro = request.GET.get("fecha")

    if fecha_parametro:
        try:
            fecha_seleccionada = date.fromisoformat(
                fecha_parametro
            )

            if fecha_seleccionada < hoy:
                error = (
                    "No puedes consultar disponibilidad "
                    "para una fecha anterior a hoy."
                )
            else:
                slots = obtener_disponibilidad(
                    cancha,
                    fecha_seleccionada
                )

        except ValueError:
            error = "La fecha seleccionada no es válida."

    return render(
        request,
        "courts/disponibilidad.html",
        {
            "cancha": cancha,
            "fecha_seleccionada": fecha_seleccionada,
            "slots": slots,
            "error": error,
            "hoy": hoy,
        }
    )