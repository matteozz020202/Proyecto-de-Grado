from django.urls import path
from . import views

app_name="courts"

urlpatterns=[
    path("",views.establecimientos,name="establecimientos"),
    path("<int:venue_id>/canchas/",views.canchas_establecimiento,name="canchas_establecimiento"),
    path("cancha/<int:cancha_id>/disponibilidad/",views.disponibilidad_cancha,name="disponibilidad_cancha"),

    path("admin/canchas/",views.admin_canchas,name="admin_canchas"),
    path("admin/establecimiento/<int:venue_id>/editar/",views.admin_editar_establecimiento,name="admin_editar_establecimiento"),
    path("admin/cancha/<int:cancha_id>/editar/",views.admin_editar_cancha,name="admin_editar_cancha"),
]