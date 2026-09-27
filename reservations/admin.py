from django.contrib import admin
from .models import Reservation, Payment


@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display = (
        "reservation_id",
        "user",
        "court",
        "reservation_date",
        "start_time",
        "end_time",
        "total_amount",
        "deposit_required",
        "remaining_amount",
        "reservation_status",
        "data_source",
    )

    list_filter = (
        "reservation_status",
        "reservation_date",
        "court",
        "data_source",
    )

    search_fields = (
        "user__username",
        "court__court_name",
        "court__venue__venue_name",
    )

    ordering = (
        "-reservation_date",
        "start_time",
    )

    readonly_fields = (
        "created_at",
    )


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "payment_id",
        "reservation",
        "amount",
        "payment_type",
        "payment_status",
        "provider",
        "transaction_reference",
        "created_at",
        "approved_at",
    )

    list_filter = (
        "payment_status",
        "payment_type",
        "provider",
        "created_at",
    )

    search_fields = (
        "transaction_reference",
        "reservation__user__username",
        "reservation__court__court_name",
    )

    ordering = (
        "-created_at",
    )

    readonly_fields = (
        "created_at",
    )