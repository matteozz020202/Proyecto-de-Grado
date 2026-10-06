from datetime import timedelta

from django import forms
from django.utils import timezone

from courts.models import Court, Venue
from .models import Reservation


class DashboardFilterForm(forms.Form):
    origen = forms.ChoiceField(
        label="Origen", choices=Reservation.DATA_SOURCES + [("ALL", "Todos los orígenes")],
    )
    establecimiento = forms.ModelChoiceField(
        label="Establecimiento", queryset=Venue.objects.all(), required=False,
        empty_label="Todos los establecimientos",
    )
    cancha = forms.ModelChoiceField(
        label="Cancha", queryset=Court.objects.select_related("venue").all(), required=False,
        empty_label="Todas las canchas",
    )
    fecha_inicio = forms.DateField(
        label="Desde", input_formats=["%Y-%m-%d"],
        widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
    )
    fecha_fin = forms.DateField(
        label="Hasta", input_formats=["%Y-%m-%d"],
        widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
    )
    tipo = forms.ChoiceField(label="Análisis", choices=[
        ("HISTORICAL", "Histórico · completadas"),
        ("FUTURE", "Programado · confirmadas"),
    ])

    def __init__(self, params, *args, **kwargs):
        today = timezone.localdate()
        analysis_type = params.get("tipo", "HISTORICAL")
        future = analysis_type == "FUTURE"
        data = {
            "origen": "SYSTEM", "establecimiento": "", "cancha": "",
            "fecha_inicio": today.isoformat() if future else today.replace(month=1, day=1).isoformat(),
            "fecha_fin": (today + timedelta(days=29)).isoformat() if future else today.isoformat(),
            "tipo": analysis_type,
        }
        data.update({key: params[key] for key in data if key in params})
        # Conserva el comportamiento seguro del selector de origen existente.
        if data["origen"] not in dict(self.base_fields["origen"].choices):
            data["origen"] = "SYSTEM"
        super().__init__(data, *args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-select" if isinstance(field.widget, forms.Select) else "form-control"

    def clean(self):
        data = super().clean()
        venue, court = data.get("establecimiento"), data.get("cancha")
        if venue and court and court.venue_id != venue.pk:
            self.add_error("cancha", "La cancha no pertenece al establecimiento seleccionado.")
        start, end = data.get("fecha_inicio"), data.get("fecha_fin")
        if start and end:
            if start > end:
                self.add_error("fecha_fin", "La fecha final debe ser igual o posterior a la inicial.")
            elif (end - start).days >= 366:
                self.add_error("fecha_fin", "Selecciona un período de máximo 366 días.")
            today = timezone.localdate()
            if data.get("tipo") == "HISTORICAL" and end > today:
                self.add_error("fecha_fin", "El análisis histórico no admite fechas posteriores a hoy.")
            elif data.get("tipo") == "FUTURE" and start < today:
                self.add_error("fecha_inicio", "La ocupación programada requiere fechas desde hoy.")
        return data
