"""Alcance compartido por KPIs visibles y solicitud manual de análisis."""

from courts.models import Court
from .models import Reservation


def filtered_scope(filters):
    courts = Court.objects.select_related("venue").all()
    if filters["establecimiento"]:
        courts = courts.filter(venue=filters["establecimiento"])
    if filters["cancha"]:
        courts = courts.filter(pk=filters["cancha"].pk)
    reservations = Reservation.objects.filter(court__in=courts)
    if filters["origen"] != "ALL":
        reservations = reservations.filter(data_source=filters["origen"])
    return courts, reservations
