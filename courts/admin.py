from django.contrib import admin

from .models import Venue, Court, CourtSchedule


class CourtInline(admin.TabularInline):
    model = Court
    extra = 0

    fields = (
        "court_name",
        "price_per_hour",
        "is_active",
    )

    show_change_link = True


@admin.register(Venue)
class VenueAdmin(admin.ModelAdmin):
    list_display = (
        "venue_id",
        "venue_name",
        "city",
        "address",
        "deposit_percentage",
        "is_active",
    )

    list_filter = (
        "is_active",
        "city",
    )

    search_fields = (
        "venue_name",
        "address",
        "city",
    )

    ordering = (
        "venue_name",
    )

    inlines = [
        CourtInline
    ]


@admin.register(Court)
class CourtAdmin(admin.ModelAdmin):
    list_display = (
        "court_id",
        "court_name",
        "venue",
        "price_per_hour",
        "is_active",
    )

    list_filter = (
        "venue",
        "is_active",
    )

    search_fields = (
        "court_name",
        "venue__venue_name",
    )

    ordering = (
        "venue__venue_name",
        "court_name",
    )


@admin.register(CourtSchedule)
class CourtScheduleAdmin(admin.ModelAdmin):
    list_display = (
        "schedule_id",
        "court",
        "day_of_week",
        "start_time",
        "end_time",
        "slot_duration_minutes",
        "is_active",
    )

    list_filter = (
        "day_of_week",
        "is_active",
        "court",
    )

    search_fields = (
        "court__court_name",
        "court__venue__venue_name",
    )

    ordering = (
        "court",
        "day_of_week",
        "start_time",
    )