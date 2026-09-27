from django.contrib import admin
from .models import Reserva, Pago


@admin.register(Reserva)
class ReservaAdmin(admin.ModelAdmin):
    list_display = (
        "usuario",
        "cancha",
        "fecha",
        "hora_inicio",
        "hora_fin",
        "precio",
        "estado",
    )

    list_filter = (
        "estado",
        "fecha",
        "cancha",
    )

    search_fields = (
        "usuario__username",
        "cancha__nombre",
    )

    ordering = (
        "-fecha",
        "hora_inicio",
    )

    @admin.register(Pago)
    class PagoAdmin(admin.ModelAdmin):
        list_display = (
            "id",
            "reserva",
            "monto",
            "tipo",
            "estado",
            "referencia",
            "fecha_creacion",
        )

        list_filter = (
            "estado",
            "tipo",
            "fecha_creacion",
        )

        search_fields = (
            "referencia",
            "reserva__usuario__username",
        )