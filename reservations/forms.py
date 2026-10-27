from datetime import timedelta
from calendar import monthrange

from django import forms
from django.utils import timezone

from courts.access import courts_for_user, venues_for_user
from courts.models import Court, Venue
from .models import Reservation


class DashboardFilterForm(forms.Form):
    periodo = forms.ChoiceField(label="Período", choices=[("day", "Día"), ("month", "Mes")])
    fecha = forms.DateField(label="Fecha", required=False, input_formats=["%Y-%m-%d"],
                            widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}))
    mes = forms.DateField(label="Mes", required=False, input_formats=["%Y-%m"],
                          widget=forms.DateInput(format="%Y-%m", attrs={"type": "month"}))

    origen = forms.ChoiceField(
        label="Origen",
        choices=Reservation.DATA_SOURCES + [
            ("ALL", "Todos los orígenes")
        ],
    )

    establecimiento = forms.ModelChoiceField(
        label="Establecimiento",
        queryset=Venue.objects.none(),
        required=False,
        empty_label="Todos los establecimientos",
    )

    cancha = forms.ModelChoiceField(
        label="Cancha",
        queryset=Court.objects.none(),
        required=False,
        empty_label="Todas las canchas",
        error_messages={
            "invalid_choice":
                "Selecciona una cancha del establecimiento elegido."
        },
    )

    fecha_inicio = forms.DateField(
        label="Desde",
        input_formats=["%Y-%m-%d"],
        widget=forms.DateInput(
            format="%Y-%m-%d",
            attrs={"type": "date"}
        ),
    )

    fecha_fin = forms.DateField(
        label="Hasta",
        input_formats=["%Y-%m-%d"],
        widget=forms.DateInput(
            format="%Y-%m-%d",
            attrs={"type": "date"}
        ),
    )

    tipo = forms.ChoiceField(
        label="Análisis",
        choices=[
            ("HISTORICAL", "Histórico · completadas"),
            ("FUTURE", "Programado · confirmadas"),
        ],
    )

    def __init__(
        self,
        params=None,
        *args,
        user=None,
        **kwargs
    ):
        params = params or {}

        today = timezone.localdate()
        analysis_type = params.get(
            "tipo",
            "HISTORICAL"
        )

        future = analysis_type == "FUTURE"

        data = {
            "origen": "SYSTEM",
            "establecimiento": "",
            "cancha": "",
            "fecha_inicio":
                today.isoformat()
                if future
                else today.replace(
                    month=1,
                    day=1
                ).isoformat(),
            "fecha_fin":
                (
                    today + timedelta(days=29)
                ).isoformat()
                if future
                else today.isoformat(),
            "tipo": analysis_type,
        }

        data.update({
            key: params[key]
            for key in data
            if key in params
        })

        # Las URLs antiguas y el contrato de análisis siguen aceptando rangos.
        self.period_mode = params.get("periodo", "day") if "periodo" in params or not any(
            key in params for key in ("fecha_inicio", "fecha_fin")
        ) else None
        data.update({"periodo": self.period_mode or "day",
                     "fecha": params.get("fecha", data["fecha_inicio"] if self.period_mode is None else today.isoformat()),
                     "mes": params.get("mes", today.strftime("%Y-%m"))})
        if self.period_mode in ("day", "month"):
            field = "fecha" if self.period_mode == "day" else "mes"
            try:
                selected = self.base_fields[field].clean(data[field])
            except forms.ValidationError:
                selected = None  # El campo visible mostrará el error al validar.
            if selected:
                start = selected if field == "fecha" else selected.replace(day=1)
                end = start if field == "fecha" else start.replace(day=monthrange(start.year, start.month)[1])
                data.update(fecha_inicio=start.isoformat(), fecha_fin=end.isoformat())

        if data["origen"] not in dict(
            self.base_fields["origen"].choices
        ):
            data["origen"] = "SYSTEM"

        super().__init__(
            data,
            *args,
            **kwargs
        )

        if user is None:
            allowed_venues = Venue.objects.none()
            allowed_courts = (
                Court.objects
                .select_related("venue")
                .none()
            )
        else:
            allowed_venues = venues_for_user(user)
            allowed_courts = courts_for_user(user)

        self.fields[
            "establecimiento"
        ].queryset = allowed_venues

        self.fields[
            "cancha"
        ].queryset = allowed_courts

        self.court_options = [
            {
                "id": str(court.pk),
                "venue": str(
                    court.venue_id
                ),
                "label": str(court),
            }
            for court in allowed_courts
        ]

        if data["establecimiento"]:
            try:
                venue_id = int(
                    data["establecimiento"]
                )
            except (
                TypeError,
                ValueError
            ):
                self.fields[
                    "cancha"
                ].queryset = (
                    allowed_courts.none()
                )
            else:
                self.fields[
                    "cancha"
                ].queryset = (
                    allowed_courts.filter(
                        venue_id=venue_id
                    )
                )

        for field in self.fields.values():
            if isinstance(
                field.widget,
                forms.Select
            ):
                field.widget.attrs[
                    "class"
                ] = "form-select"
            else:
                field.widget.attrs[
                    "class"
                ] = "form-control"

    def clean(self):
        data = super().clean()
        if self.period_mode in ("day", "month"):
            field = "fecha" if self.period_mode == "day" else "mes"
            if not data.get(field) and field not in self.errors:
                self.add_error(field, "Selecciona una fecha." if field == "fecha" else "Selecciona un mes.")
        # Mantener exactamente el contrato de filtros consumido por KPIs e IA.
        for field in ("periodo", "fecha", "mes"):
            data.pop(field, None)

        venue = data.get(
            "establecimiento"
        )

        court = data.get(
            "cancha"
        )

        if (
            venue
            and court
            and court.venue_id != venue.pk
        ):
            self.add_error(
                "cancha",
                "La cancha no pertenece al "
                "establecimiento seleccionado."
            )

        start = data.get(
            "fecha_inicio"
        )

        end = data.get(
            "fecha_fin"
        )

        if start and end:
            if start > end:
                self.add_error(
                    "fecha_fin",
                    "La fecha final debe ser "
                    "igual o posterior a la inicial."
                )

            elif (
                end - start
            ).days >= 366:
                self.add_error(
                    "fecha_fin",
                    "Selecciona un período "
                    "de máximo 366 días."
                )

            today = timezone.localdate()

            if (
                data.get("tipo")
                == "HISTORICAL"
                and end > today
                and not (self.period_mode == "month" and start <= today <= end)
            ):
                self.add_error(
                    "fecha_fin",
                    "El análisis histórico "
                    "no admite fechas "
                    "posteriores a hoy."
                )

            elif (
                data.get("tipo")
                == "FUTURE"
                and start < today
                and not (self.period_mode == "month" and start <= today <= end)
            ):
                self.add_error(
                    "fecha_inicio",
                    "La ocupación programada "
                    "requiere fechas desde hoy."
                )

        return data