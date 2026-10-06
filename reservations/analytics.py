"""KPIs determinísticos de ocupación a partir de horarios y reservas."""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone
from courts.models import CourtSchedule
from .models import Payment, Reservation


def seconds(value):
    return value.hour * 3600 + value.minute * 60 + value.second


def merged_intervals(intervals):
    """No cuenta dos veces intervalos operativos superpuestos."""
    merged = []
    for start, stop in sorted(intervals):
        if stop <= start:
            continue
        if not merged or start > merged[-1][1]:
            merged.append([start, stop])
        else:
            merged[-1][1] = max(merged[-1][1], stop)
    return merged


def union_duration(intervals):
    return sum(end - start for start, end in merged_intervals(intervals))


def add_hourly(buckets, start, end):
    for hour in range(start // 3600, (end + 3599) // 3600):
        buckets[hour] += max(0, min(end, (hour + 1) * 3600) - max(start, hour * 3600))


def ratio(reserved, available):
    return Decimal(reserved) * 100 / available if available else None


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
    capacity_day, capacity_hour = defaultdict(int), defaultdict(int)
    current = start_date
    while current <= end_date:
        for court_id in court_map:
            court = court_map[court_id]
            if analysis_type == "FUTURE" and (not court.is_active or not court.venue.is_active):
                continue
            intervals = schedules[(court_id, current.isoweekday())]
            if analysis_type == "FUTURE" and current == today:
                intervals = [(max(start, now_seconds), end) for start, end in intervals]
            for start, end in merged_intervals(intervals):
                capacity[court_id] += end - start
                capacity_day[current.isoweekday()] += end - start
                add_hourly(capacity_hour, start, end)
        current += timedelta(days=1)

    reserved = defaultdict(int)
    count = defaultdict(int)
    reserved_day, reserved_hour = defaultdict(int), defaultdict(int)
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
        reserved_day[reservation_date.isoweekday()] += end_seconds - start_seconds
        add_hourly(reserved_hour, start_seconds, end_seconds)
        count[court_id] += 1

    def metric(court_ids):
        available_seconds = sum(capacity[pk] for pk in court_ids)
        reserved_seconds = sum(reserved[pk] for pk in court_ids)
        return {
            "horas_disponibles": Decimal(available_seconds) / Decimal(3600),
            "horas_reservadas": Decimal(reserved_seconds) / Decimal(3600),
            "reservas_validas": sum(count[pk] for pk in court_ids),
            "ocupacion": ratio(reserved_seconds, available_seconds),
        }

    total = metric(court_map)
    rows = []
    for court in courts:
        rows.append({"cancha": court, **metric([court.pk])})
    def breakdown(label, reserved, available):
        return {"label": label, "reserved_hours": Decimal(reserved) / 3600,
                "available_hours": Decimal(available) / 3600,
                "occupancy_rate": ratio(reserved, available)}

    by_day = [breakdown(label, reserved_day[day], capacity_day[day])
              for day, label in enumerate(["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"], 1)]
    by_hour = [breakdown(f"{hour:02d}:00–{hour+1:02d}:00", reserved_hour[hour], capacity_hour[hour])
               for hour in range(24) if capacity_hour[hour]]
    return {
        **total, "por_cancha": rows, "estado_ocupacion": status,
        "occupancy_by_day": by_day, "occupancy_by_time_slot": by_hour,
        "capacidad_inconsistente": any(
            row["horas_reservadas"] > row["horas_disponibles"] for row in rows
        ) or any(row["reserved_hours"] > row["available_hours"] for row in by_day + by_hour),
    }


def dashboard_data(courts, reservations, start_date, end_date, analysis_type, source):
    """Un solo alcance para KPIs, gráficas y el futuro contrato de análisis GPT."""
    metrics = occupancy(courts, reservations, start_date, end_date, analysis_type)
    counts = dict(reservations.order_by().values_list("reservation_status").annotate(total=Count("pk")))
    formalized = sum(counts.get(status, 0) for status in ("CONFIRMED", "COMPLETED", "CANCELLED"))
    payments = Payment.objects.filter(payment_status="APPROVED", reservation__in=reservations)
    deposits = payments.filter(payment_type="DEPOSIT")
    valid = reservations.filter(reservation_status=metrics["estado_ocupacion"])
    # En el programado de hoy, la reserva es válida si aún tiene horas pendientes.
    if analysis_type == "FUTURE":
        now = timezone.localtime()
        valid = valid.filter(Q(reservation_date__gt=now.date()) |
                             Q(reservation_date=now.date(), end_time__gt=now.time()))
    distribution = [{"status": status, "label": label, "count": counts[status]}
                    for status, label in Reservation.RESERVATION_STATUSES if counts.get(status)]
    summary = {
        "occupancy_rate": metrics["ocupacion"], "valid_reservations": metrics["reservas_validas"],
        "reserved_hours": metrics["horas_reservadas"], "available_hours": metrics["horas_disponibles"],
        "reservation_value": valid.aggregate(total=Sum("total_amount"))["total"] or Decimal(0),
        "approved_deposits": deposits.aggregate(total=Sum("amount"))["total"] or Decimal(0),
        "cancellation_rate": ratio(counts.get("CANCELLED", 0), formalized),
    }
    def chart_rows(rows):
        return [{key: float(value) if isinstance(value, Decimal) else value
                 for key, value in row.items()} for row in rows]

    return {
        "summary": summary, "occupancy": metrics, "status_counts": counts,
        "reservation_status_distribution": distribution,
        "approved_payments": payments.aggregate(total=Sum("amount"))["total"] or Decimal(0),
        "approved_payment_count": payments.count(),
        "analysis_context": {
            "venue_ids": sorted({court.venue_id for court in courts}),
            "court_ids": sorted(court.pk for court in courts),
            "start_date": start_date.isoformat(), "end_date": end_date.isoformat(),
            "analysis_type": analysis_type, "data_source": source,
        },
        "chart_data": {
            "occupancy_by_day": chart_rows(metrics["occupancy_by_day"]),
            "occupancy_by_time_slot": chart_rows(metrics["occupancy_by_time_slot"]),
            "reservation_status_distribution": distribution,
        },
    }
