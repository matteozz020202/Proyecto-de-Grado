from django.urls import path

from . import views


app_name = "courts"

urlpatterns = [
    path(
        "",
        views.establecimientos,
        name="establecimientos"
    ),

    path(
        "<int:venue_id>/canchas/",
        views.canchas_establecimiento,
        name="canchas_establecimiento"
    ),

    path(
        "cancha/<int:cancha_id>/disponibilidad/",
        views.disponibilidad_cancha,
        name="disponibilidad_cancha"
    ),
]