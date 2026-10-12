"""Validación local: estructura, evidencia exacta y aviso de datos sintéticos."""

import re
import unicodedata
from decimal import Decimal

from .schemas import AIAnalysis, InputContract, InsightType

CHANGE_METRICS = {
    InsightType.OCCUPANCY_CHANGE: ("occupancy_variation_pp", "occupancy_rate"),
    InsightType.RESERVATION_CHANGE: ("reservations_variation_pct", "valid_reservations"),
}


def available_change_types(payload: InputContract):
    """Comprueba disponibilidad de comparaciones; no calcula variaciones."""
    previous = payload.comparisons.previous_period
    if previous is None:
        return set()
    return {
        kind for kind, (variation, metric) in CHANGE_METRICS.items()
        if getattr(payload.comparisons, variation) is not None
        and getattr(payload.summary, metric) is not None
        and getattr(previous, metric) is not None
        and (kind != InsightType.RESERVATION_CHANGE or previous.valid_reservations > 0)
    }

# Catálogo único: los valores son unidades internas, nunca campos del output.
METRIC_UNITS = {
    "summary.occupancy_rate": "%",
    "summary.valid_reservations": "reservations",
    "summary.reserved_hours": "h",
    "summary.available_hours": "h",
    "summary.reservation_value": "COP",
    "summary.approved_deposits": "COP",
    "summary.pending_balance": "COP",
    "summary.cancellation_rate": "%",
    "summary.average_booking_lead_hours": "h",
    **{f"reservation_status_counts.{state}": "reservations" for state in
       ("pending_payment", "confirmed", "completed", "cancelled", "expired")},
    **{f"{group}.{metric}": unit for group in
       ("occupancy_by_court", "occupancy_by_day", "occupancy_by_time_slot")
       for metric, unit in (("occupancy_rate", "%"), ("reserved_hours", "h"), ("available_hours", "h"))},
    "comparisons.previous_period.occupancy_rate": "%",
    "comparisons.previous_period.valid_reservations": "reservations",
    "comparisons.occupancy_variation_pp": "pp",
    "comparisons.reservations_variation_pct": "%",
}


class InvalidAIResponse(ValueError):
    """Respuesta estructurada que no coincide con los datos enviados."""

    def __init__(self, message, code="INVALID_AI_RESPONSE"):
        super().__init__(message)
        self.code = code


def evidence_catalog(payload: InputContract):
    """Indexa valores existentes; no calcula KPIs. Referencias globales: None.

    Canchas: str(court_id), días: day, franjas: time_slot. Los nombres de cancha
    no son claves: pueden repetirse entre establecimientos.
    """
    data = payload.model_dump(mode="json")
    catalog = {}
    for metric in METRIC_UNITS:
        parts = metric.split(".")
        if parts[0].startswith("occupancy_by_"):
            reference_field = {"occupancy_by_court": "court_id", "occupancy_by_day": "day",
                               "occupancy_by_time_slot": "time_slot"}[parts[0]]
            for row in data[parts[0]]:
                if row[parts[1]] is not None:
                    catalog[(metric, str(row[reference_field]))] = row[parts[1]]
        else:
            value = data
            for part in parts:
                value = value[part] if value is not None else None
            if value is not None:
                catalog[(metric, None)] = value
    return catalog


def validate_analysis(input_data, output_data) -> AIAnalysis:
    """Acepta JSON o dict. Revalida incluso instancias existentes de los modelos.

    Los errores de esquema usan pydantic.ValidationError. Los errores de negocio
    usan InvalidAIResponse. Ningún resultado parcial se devuelve ante un fallo.
    """
    payload = _parse(InputContract, input_data)
    output = _parse(AIAnalysis, output_data)
    catalog = evidence_catalog(payload)
    for insight in output.insights:
        for evidence in insight.evidence:
            key = (evidence.metric, evidence.reference)
            if key not in catalog:
                raise InvalidAIResponse(f"Métrica/referencia ausente o no disponible: {key}.",
                                        code="INVALID_EVIDENCE_REFERENCE")
            # Sin epsilon, redondeos ni tolerancia. 24 y 24.0 representan el mismo valor.
            if Decimal(str(evidence.value)) != Decimal(str(catalog[key])):
                raise InvalidAIResponse(f"Valor de evidencia distinto al input: {key}.",
                                        code="INVALID_EVIDENCE_VALUE")
        if insight.type in CHANGE_METRICS:
            if insight.type not in available_change_types(payload):
                raise InvalidAIResponse("Insight de cambio sin comparación disponible.",
                                        code="MISSING_CHANGE_COMPARISON")
            variation, _ = CHANGE_METRICS[insight.type]
            if not any(item.metric == f"comparisons.{variation}" for item in insight.evidence):
                raise InvalidAIResponse("Insight de cambio sin evidencia de la variación suministrada.",
                                        code="MISSING_CHANGE_EVIDENCE")
    if payload.analysis_context.data_source == "SYNTHETIC":
        if not any(_synthetic_notice(text) for text in output.limitations):
            raise InvalidAIResponse("Falta una limitación explícita de datos sintéticos de demostración.",
                                    code="SYNTHETIC_NOTICE_MISSING")
    return output


def _parse(schema, value):
    if isinstance(value, (str, bytes, bytearray)):
        return schema.model_validate_json(value)
    return schema.model_validate(value)


def _synthetic_notice(text):
    normalized = "".join(char for char in unicodedata.normalize("NFKD", text.casefold())
                         if not unicodedata.combining(char))
    # Convención explícita y acotada; no intenta juzgar semánticamente toda la prosa.
    if re.search(r"\b(?:no|sin)\s+(?:se\s+)?(?:usan|utilizan|utiliza|usaron|utilizaron)?\s*(?:datos\s+)?sintetic", normalized):
        return False
    return bool(re.search(r"\bdatos\s+sinteticos\b", normalized)
                and re.search(r"\b(?:demostracion|pruebas|validacion\s+funcional)\b", normalized))
