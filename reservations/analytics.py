"""KPIs determinísticos de ocupación a partir de horarios y reservas."""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone
from courts.models import CourtSchedule


def seconds(value):
    return value.hour * 3600 + value.minute * 60 + value.second


def union_duration(intervals):
    """No cuenta dos veces intervalos operativos superpuestos."""
    total = 0
    end = None
    for start, stop in sorted(intervals):
        if stop <= start:
            continue
        if end is None or start > end:
            total += stop - start
        elif stop > end:
            total += stop - end
        end = max(end or stop, stop)
    return total


def occupancy(courts, reservations, start_date, end_date, analysis_type):
    status = {"HISTORICAL": "COMPLETED", "FUTURE": "CONFIRMED"}[analysis_type]
    courts = list(courts)
    court_map = {court.pk: court for court in courts}
    now = timezone.localtime()
    today, now_seconds = now.date(), seconds(now.time())
    schedules = defaultdict(list)
    for court_id, day, start, end in CourtSchedule.objects.filter(
        court_id__in=court_map, is_active=True,
    ).values_list("court_id", "day_of_week", "start_time", "end_time"):
        schedules[(court_id, day)].append((seconds(start), seconds(end)))
    capacity = defaultdict(int)
    current = start_date
    while current <= end_date:
        for court_id in court_map:
            court = court_map[court_id]
            if analysis_type == "FUTURE" and (not court.is_active or not court.venue.is_active):
                continue
            intervals = schedules[(court_id, current.isoweekday())]
            if analysis_type == "FUTURE" and current == today:
                intervals = [(max(start, now_seconds), end) for start, end in intervals]
            capacity[court_id] += union_duration(intervals)
        current += timedelta(days=1)

    reserved = defaultdict(int)
    count = defaultdict(int)
    for court_id, reservation_date, start, end in reservations.filter(
        reservation_date__range=(start_date, end_date),
        court_id__in=court_map, reservation_status=status,
    ).values_list("court_id", "reservation_date", "start_time", "end_time"):
        start_seconds, end_seconds = seconds(start), seconds(end)
        if analysis_type == "FUTURE" and reservation_date == today:
            start_seconds = max(start_seconds, now_seconds)
        if end_seconds <= start_seconds:
            continue
        reserved[court_id] += end_seconds - start_seconds
        count[court_id] += 1

    def metric(court_ids):
        available_seconds = sum(capacity[pk] for pk in court_ids)
        reserved_seconds = sum(reserved[pk] for pk in court_ids)
        return {
            "horas_disponibles": Decimal(available_seconds) / Decimal(3600),
            "horas_reservadas": Decimal(reserved_seconds) / Decimal(3600),
            "reservas_validas": sum(count[pk] for pk in court_ids),
            "ocupacion": (Decimal(reserved_seconds) * 100 / available_seconds)
                         if available_seconds else None,
        }

    total = metric(court_map)
    rows = []
    for court in courts:
        rows.append({"cancha": court, **metric([court.pk])})
    return {
        **total, "por_cancha": rows, "estado_ocupacion": status,
        "capacidad_inconsistente": any(
            row["horas_reservadas"] > row["horas_disponibles"] for row in rows
        ),
    }
