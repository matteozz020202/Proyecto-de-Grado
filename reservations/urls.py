from django.urls import include, path
from django.contrib import admin


from . import views

app_name = "reservations"

urlpatterns = [
    path(
        "mis-reservas/",
        views.mis_reservas,
        name="mis_reservas"
    ),
    path(
        "nueva/<int:cancha_id>/",
        views.resumen_reserva,
        name="resumen_reserva"
    ),
    path(
        "pago/<int:reserva_id>/",
        views.pagar_reserva,
        name="pagar_reserva"
    ),
    path(
    "cancelar/<int:reserva_id>/",
    views.cancelar_reserva_view,
    name="cancelar_reserva"
    ),
    path(
    "admin/reservas/nueva/",
    views.admin_crear_reserva,
    name="admin_crear_reserva"
    ),
    path(
        "admin/reservas/",
        views.admin_reservas,
        name="admin_reservas"
    ),
]