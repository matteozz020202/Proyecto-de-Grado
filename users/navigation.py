"""Política compartida de roles y destinos de autenticación."""
from urllib.parse import urlsplit

from django.urls import Resolver404, resolve, reverse
from django.utils.http import url_has_allowed_host_and_scheme


def is_admin(user):
    return user.is_authenticated and (
        user.is_staff or user.is_superuser or user.groups.filter(name="Administrador").exists()
    )


def login_destination(request, user, next_url=""):
    if next_url and url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        try:
            match = resolve(urlsplit(next_url).path)
        except Resolver404:
            match = None
        public = {"users:home", "courts:establecimientos", "courts:canchas_establecimiento", "courts:disponibilidad_cancha"}
        personal={"users:profile","users:password_change","users:password_change_done","reservations:mis_reservas","reservations:resumen_reserva","reservations:pagar_reserva","reservations:reserva_confirmada"}
        administrative={"reservations:admin_dashboard","reservations:admin_reservas","reservations:admin_crear_reserva","reservations:admin_detalle_reserva","courts:admin_canchas","courts:admin_editar_establecimiento","courts:admin_editar_cancha"}
        if match and match.view_name in {"reservations:pagar_reserva","reservations:reserva_confirmada"}:
            from reservations.models import Reservation
            if not Reservation.objects.filter(pk=match.kwargs["reserva_id"],user=user).exists():
                match=None
        if match and (match.view_name in public | personal or (is_admin(user) and match.view_name in administrative)):
            return next_url
    return reverse("reservations:admin_dashboard" if is_admin(user) else "courts:establecimientos")
