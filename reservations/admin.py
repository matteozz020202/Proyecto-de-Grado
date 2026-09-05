from django.contrib import admin
from .models import Reserva


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