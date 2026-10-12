"""Input/Output Contract v1.0. No calcula ni completa KPIs."""

from datetime import date
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StringConstraints, model_validator

Number = StrictInt | StrictFloat
NonNegative = Annotated[Number, Field(ge=0)]
Percentage = Annotated[Number, Field(ge=0, le=100)]
Count = Annotated[StrictInt, Field(ge=0)]
Identifier = Annotated[StrictInt, Field(gt=0)]
Text = Annotated[str, StringConstraints(strict=True, min_length=1, pattern=r"\S")]
Day = Literal["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True,
                              revalidate_instances="always")


class InsightType(StrEnum):
    HIGH_OCCUPANCY = "HIGH_OCCUPANCY"
    LOW_OCCUPANCY = "LOW_OCCUPANCY"
    OCCUPANCY_CHANGE = "OCCUPANCY_CHANGE"
    RESERVATION_CHANGE = "RESERVATION_CHANGE"
    CANCELLATION = "CANCELLATION"
    COURT_PERFORMANCE = "COURT_PERFORMANCE"
    TIME_SLOT_PATTERN = "TIME_SLOT_PATTERN"
    DAY_PATTERN = "DAY_PATTERN"
    FINANCIAL = "FINANCIAL"
    GENERAL = "GENERAL"


class InsightPriority(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class AnalysisContext(ContractModel):
    venue_id: Identifier | None
    venue_name: Text | None
    court_id: Identifier | None
    court_name: Text | None
    start_date: Text
    end_date: Text
    analysis_type: Literal["HISTORICAL", "FUTURE"]
    data_source: Literal["SYNTHETIC", "PLATFORM", "HISTORICAL"]
    currency: Literal["COP"]
    response_language: Literal["es"]

    @model_validator(mode="after")
    def valid_dates(self):
        start, end = date.fromisoformat(self.start_date), date.fromisoformat(self.end_date)
        if start.isoformat() != self.start_date or end.isoformat() != self.end_date or start > end:
            raise ValueError("Se requieren fechas ISO YYYY-MM-DD en orden cronológico.")
        return self


class Summary(ContractModel):
    occupancy_rate: Percentage | None
    valid_reservations: Count | None
    reserved_hours: NonNegative | None
    available_hours: NonNegative | None
    reservation_value: NonNegative | None
    approved_deposits: NonNegative | None
    pending_balance: NonNegative | None
    cancellation_rate: Percentage | None
    average_booking_lead_hours: NonNegative | None


class ReservationStatusCounts(ContractModel):
    pending_payment: Count
    confirmed: Count
    completed: Count
    cancelled: Count
    expired: Count


class OccupancyRow(ContractModel):
    reserved_hours: NonNegative | None
    available_hours: NonNegative | None
    occupancy_rate: Percentage | None


class CourtOccupancy(OccupancyRow):
    court_id: Identifier
    court_name: Text


class DayOccupancy(OccupancyRow):
    day: Day


class TimeSlotOccupancy(OccupancyRow):
    time_slot: Text


class PreviousPeriod(ContractModel):
    start_date: Text
    end_date: Text
    occupancy_rate: Percentage | None
    valid_reservations: Count | None

    @model_validator(mode="after")
    def valid_dates(self):
        start, end = date.fromisoformat(self.start_date), date.fromisoformat(self.end_date)
        if start.isoformat() != self.start_date or end.isoformat() != self.end_date or start > end:
            raise ValueError("El período anterior requiere fechas ISO en orden cronológico.")
        return self


class Comparisons(ContractModel):
    previous_period: PreviousPeriod | None
    occupancy_variation_pp: Number | None
    reservations_variation_pct: Number | None


class Extreme(ContractModel):
    reference: Text
    value: Percentage


class Extremes(ContractModel):
    highest_occupancy_days: list[Extreme]
    lowest_occupancy_days: list[Extreme]
    highest_occupancy_time_slots: list[Extreme]
    lowest_occupancy_time_slots: list[Extreme]


class InputContract(ContractModel):
    contract_version: Literal["1.0"]
    analysis_context: AnalysisContext
    summary: Summary
    reservation_status_counts: ReservationStatusCounts
    occupancy_by_court: list[CourtOccupancy]
    occupancy_by_day: list[DayOccupancy]
    occupancy_by_time_slot: list[TimeSlotOccupancy]
    comparisons: Comparisons
    extremes: Extremes

    @model_validator(mode="after")
    def unique_breakdown_references(self):
        for rows, field in ((self.occupancy_by_court, "court_id"),
                            (self.occupancy_by_day, "day"),
                            (self.occupancy_by_time_slot, "time_slot")):
            references = [getattr(row, field) for row in rows]
            if len(set(references)) != len(references):
                raise ValueError(f"Referencia duplicada: {field}.")
        return self


class Evidence(ContractModel):
    metric: Text
    reference: Text | None
    value: Number


class Insight(ContractModel):
    # JSON strings are accepted explicitly; unrelated strict types stay strict.
    type: Annotated[InsightType, Field(strict=False)]
    priority: Annotated[InsightPriority, Field(strict=False)]
    finding: Text
    evidence: Annotated[list[Evidence], Field(min_length=1)]
    recommendation: Text
    justification: Text


class AIAnalysis(ContractModel):
    contract_version: Literal["1.0"]
    analysis_summary: Text
    insights: Annotated[list[Insight], Field(max_length=5)]
    limitations: list[Text]


OutputContract = AIAnalysis
