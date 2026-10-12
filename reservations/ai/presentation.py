"""Etiquetas y unidades de UI, fuera del contrato devuelto por el modelo."""

from .validators import METRIC_UNITS

LABELS = {
    "occupancy_rate": "Ocupación", "valid_reservations": "Reservas válidas",
    "reserved_hours": "Horas reservadas", "available_hours": "Horas disponibles",
    "reservation_value": "Valor de reservas", "approved_deposits": "Abonos aprobados",
    "pending_balance": "Saldo pendiente", "cancellation_rate": "Tasa de cancelación",
    "average_booking_lead_hours": "Anticipación promedio", "pending_payment": "Pendientes de pago",
    "confirmed": "Confirmadas", "completed": "Completadas", "cancelled": "Canceladas",
    "expired": "Expiradas", "occupancy_variation_pp": "Variación de ocupación",
    "reservations_variation_pct": "Variación de reservas",
}
DAYS_ES = dict(zip(("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"),
                   ("Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo")))
TYPES_ES = {
    "HIGH_OCCUPANCY": "Ocupación alta", "LOW_OCCUPANCY": "Ocupación baja",
    "OCCUPANCY_CHANGE": "Cambio de ocupación", "RESERVATION_CHANGE": "Cambio de reservas",
    "CANCELLATION": "Cancelaciones", "COURT_PERFORMANCE": "Desempeño de cancha",
    "TIME_SLOT_PATTERN": "Franjas horarias", "DAY_PATTERN": "Días de la semana",
    "FINANCIAL": "Finanzas", "GENERAL": "Observación general",
}


def analysis_for_display(result, payload):
    output = result.model_dump(mode="json")
    court_names = {str(row.court_id): row.court_name for row in payload.occupancy_by_court}
    for insight in output["insights"]:
        insight["type_label"] = TYPES_ES[insight["type"]]
        insight["priority_label"] = {"HIGH": "Alta", "MEDIUM": "Media", "LOW": "Baja"}[insight["priority"]]
        insight["priority_color"] = {"HIGH": "danger", "MEDIUM": "warning", "LOW": "secondary"}[insight["priority"]]
        for evidence in insight["evidence"]:
            metric = evidence["metric"]
            evidence["label"] = LABELS[metric.split(".")[-1]]
            if metric.startswith("comparisons.previous_period."):
                evidence["label"] += " del período anterior"
            ref = evidence["reference"]
            evidence["reference_label"] = (court_names[ref] if metric.startswith("occupancy_by_court.")
                                           else DAYS_ES.get(ref, ref))
            unit = METRIC_UNITS[metric]
            evidence["unit_label"] = {"reservations": "reservas", "pp": "p.p."}.get(unit, unit)
    return output
