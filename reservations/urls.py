from django.urls import include, path
from django.contrib import admin


from . import views

app_name = "reservations"

urlpatterns = [
    path("admin/usuarios/buscar/", views.admin_buscar_usuarios, name="admin_buscar_usuarios"),
    path("confirmada/<int:reserva_id>/", views.reserva_confirmada, name="reserva_confirmada"),
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
    path(
        "admin/dashboard/",
        views.admin_dashboard,
        name="admin_dashboard"
    ),
    path("admin/dashboard/analisis/", views.admin_dashboard_analysis, name="admin_dashboard_analysis"),
    path(
    "admin/reservas/<int:reserva_id>/",
    views.admin_detalle_reserva,
    name="admin_detalle_reserva"
    ),
]
