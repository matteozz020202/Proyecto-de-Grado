from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class BookingIntent(BaseModel):
    model_config = ConfigDict(extra='forbid')
    intent: Literal['search_availability', 'select_option', 'greeting', 'help', 'other']
    date: str | None
    time: str | None
    venue_query: str | None
    court_query: str | None
    duration_minutes: int | None = Field(ge=30, le=180)
    time_band: Literal['morning', 'afternoon', 'evening'] | None
    any_venue: bool | None
    missing_fields: list[Literal['date', 'time', 'venue']]
    clarification_question: str | None
