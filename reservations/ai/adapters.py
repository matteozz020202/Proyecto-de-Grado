"""Adaptación de KPIs ya calculados: nunca envía filas de reservas ni pagos."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from reservations.analytics import dashboard_data, ratio
from .schemas import InputContract

SOURCES = {"SYNTHETIC": "SYNTHETIC", "SYSTEM": "PLATFORM", "HISTORICAL_REAL": "HISTORICAL"}
DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


class AnalysisContextError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def number(value):
    # Misma precisión de presentación del dashboard. El modelo debe copiarla, no redondearla.
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)) if isinstance(value, Decimal) else value


def all_extremes(rows, field, highest):
    candidates = [row for row in rows if row["occupancy_rate"] is not None]
    if not candidates:
        return []
    target = (max if highest else min)(row["occupancy_rate"] for row in candidates)
    return [{"reference": row[field], "value": target}
            for row in candidates if row["occupancy_rate"] == target]


def build_analysis_input(filters, analytics, courts, reservations):
    """reservations conserva origen/canchas, sin fecha: permite calcular período previo."""
    if filters["origen"] not in SOURCES:
        raise AnalysisContextError("SELECT_SINGLE_SOURCE")
    if analytics["occupancy"]["capacidad_inconsistente"]:
        raise AnalysisContextError("INCONSISTENT_CAPACITY")
    summary = analytics["summary"]
    venue, court = filters["establecimiento"], filters["cancha"]
    if court and not venue:
        venue = court.venue
    day_rows = [{"day": day, **{key: number(row[key]) for key in
                ("reserved_hours", "available_hours", "occupancy_rate")}}
                for day, row in zip(DAYS, analytics["occupancy"]["occupancy_by_day"])]
    slots = [{"time_slot": row["label"].replace("–", "-"),
              **{key: number(row[key]) for key in ("reserved_hours", "available_hours", "occupancy_rate")}}
             for row in analytics["occupancy"]["occupancy_by_time_slot"]]
    comparisons = {"previous_period": None, "occupancy_variation_pp": None, "reservations_variation_pct": None}
    if filters["tipo"] == "HISTORICAL":
        try:
            previous_end = filters["fecha_inicio"] - timedelta(days=1)
            previous_start = previous_end - (filters["fecha_fin"] - filters["fecha_inicio"])
        except OverflowError:
            pass
        else:
            previous = dashboard_data(courts, reservations, previous_start, previous_end,
                                      "HISTORICAL", filters["origen"])
            if not previous["occupancy"]["capacidad_inconsistente"]:
                past = previous["summary"]
                comparisons["previous_period"] = {
                    "start_date": previous_start.isoformat(), "end_date": previous_end.isoformat(),
                    "occupancy_rate": number(past["occupancy_rate"]),
                    "valid_reservations": past["valid_reservations"],
                }
                if summary["occupancy_rate"] is not None and past["occupancy_rate"] is not None:
                    comparisons["occupancy_variation_pp"] = number(summary["occupancy_rate"] - past["occupancy_rate"])
                comparisons["reservations_variation_pct"] = number(ratio(
                    summary["valid_reservations"] - past["valid_reservations"], past["valid_reservations"],
                ))
    return InputContract.model_validate({
        "contract_version": "1.0",
        "analysis_context": {
            "venue_id": venue.pk if venue else None, "venue_name": venue.venue_name if venue else None,
            "court_id": court.pk if court else None, "court_name": court.court_name if court else None,
            "start_date": filters["fecha_inicio"].isoformat(), "end_date": filters["fecha_fin"].isoformat(),
            "analysis_type": filters["tipo"], "data_source": SOURCES[filters["origen"]],
            "currency": "COP", "response_language": "es",
        },
        "summary": {key: number(summary[key]) for key in (
            "occupancy_rate", "valid_reservations", "reserved_hours", "available_hours", "reservation_value",
            "approved_deposits", "pending_balance", "cancellation_rate", "average_booking_lead_hours",
        )},
        "reservation_status_counts": {status.lower(): analytics["status_counts"].get(status, 0)
                                      for status in ("PENDING_PAYMENT", "CONFIRMED", "COMPLETED", "CANCELLED", "EXPIRED")},
        "occupancy_by_court": [{"court_id": row["cancha"].pk, "court_name": row["cancha"].court_name,
                                "reserved_hours": number(row["horas_reservadas"]),
                                "available_hours": number(row["horas_disponibles"]),
                                "occupancy_rate": number(row["ocupacion"])}
                               for row in analytics["occupancy"]["por_cancha"]],
        "occupancy_by_day": day_rows, "occupancy_by_time_slot": slots, "comparisons": comparisons,
        "extremes": {
            "highest_occupancy_days": all_extremes(day_rows, "day", True),
            "lowest_occupancy_days": all_extremes(day_rows, "day", False),
            "highest_occupancy_time_slots": all_extremes(slots, "time_slot", True),
            "lowest_occupancy_time_slots": all_extremes(slots, "time_slot", False),
        },
    })
