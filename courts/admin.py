from django.contrib import admin
from .models import Venue, Cancha, Horario


class CanchaInline(admin.TabularInline):
    model = Cancha
    extra = 0

    fields = (
        "nombre",
        "precio_hora",
        "activa",
    )

    show_change_link = True


@admin.register(Venue)
class VenueAdmin(admin.ModelAdmin):
    list_display = (
        "nombre",
        "direccion",
        "ciudad",
        "activo",
    )

    list_filter = (
        "activo",
        "ciudad",
    )

    search_fields = (
        "nombre",
        "direccion",
        "ciudad",
    )

    inlines = [
        CanchaInline
    ]


@admin.register(Cancha)
class CanchaAdmin(admin.ModelAdmin):
    list_display = (
        "nombre",
        "venue",
        "precio_hora",
        "activa",
    )

    list_filter = (
        "venue",
        "activa",
    )

    search_fields = (
        "nombre",
        "venue__nombre",
    )


@admin.register(Horario)
class HorarioAdmin(admin.ModelAdmin):
    list_display = (
        "cancha",
        "dia_semana",
        "hora_inicio",
        "hora_fin",
        "activo",
    )

    list_filter = (
        "dia_semana",
        "activo",
        "cancha",
    )