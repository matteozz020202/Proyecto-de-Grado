from django.contrib import admin

from .access import courts_for_user, venues_for_user
from .models import Court, CourtSchedule, Venue


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
        "manager",
        "city",
        "address",
        "deposit_percentage",
        "is_active",
    )

    list_filter = (
        "is_active",
        "city",
        "manager",
    )

    search_fields = (
        "venue_name",
        "address",
        "city",
        "manager__username",
    )

    ordering = (
        "venue_name",
    )

    inlines = [
        CourtInline
    ]

    def get_queryset(self, request):
        queryset = super().get_queryset(request)

        if request.user.is_superuser:
            return queryset

        return queryset.filter(
            manager=request.user
        )

    def get_readonly_fields(self, request, obj=None):
        if request.user.is_superuser:
            return ()

        return (
            "manager",
        )

    def save_model(
        self,
        request,
        obj,
        form,
        change
    ):
        if not request.user.is_superuser:
            obj.manager = request.user

        super().save_model(
            request,
            obj,
            form,
            change
        )

    def has_view_permission(
        self,
        request,
        obj=None
    ):
        allowed = super().has_view_permission(
            request,
            obj
        )

        if not allowed:
            return False

        if (
            obj is not None
            and not request.user.is_superuser
        ):
            return obj.manager_id == request.user.id

        return True

    def has_change_permission(
        self,
        request,
        obj=None
    ):
        allowed = super().has_change_permission(
            request,
            obj
        )

        if not allowed:
            return False

        if (
            obj is not None
            and not request.user.is_superuser
        ):
            return obj.manager_id == request.user.id

        return True

    def has_delete_permission(
        self,
        request,
        obj=None
    ):
        allowed = super().has_delete_permission(
            request,
            obj
        )

        if not allowed:
            return False

        if (
            obj is not None
            and not request.user.is_superuser
        ):
            return obj.manager_id == request.user.id

        return True


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

    def get_queryset(self, request):
        queryset = super().get_queryset(request)

        if request.user.is_superuser:
            return queryset

        return queryset.filter(
            venue__manager=request.user
        )

    def formfield_for_foreignkey(
        self,
        db_field,
        request,
        **kwargs
    ):
        if (
            db_field.name == "venue"
            and not request.user.is_superuser
        ):
            kwargs["queryset"] = venues_for_user(
                request.user
            )

        return super().formfield_for_foreignkey(
            db_field,
            request,
            **kwargs
        )

    def has_view_permission(
        self,
        request,
        obj=None
    ):
        allowed = super().has_view_permission(
            request,
            obj
        )

        if not allowed:
            return False

        if (
            obj is not None
            and not request.user.is_superuser
        ):
            return (
                obj.venue.manager_id
                == request.user.id
            )

        return True

    def has_change_permission(
        self,
        request,
        obj=None
    ):
        allowed = super().has_change_permission(
            request,
            obj
        )

        if not allowed:
            return False

        if (
            obj is not None
            and not request.user.is_superuser
        ):
            return (
                obj.venue.manager_id
                == request.user.id
            )

        return True

    def has_delete_permission(
        self,
        request,
        obj=None
    ):
        allowed = super().has_delete_permission(
            request,
            obj
        )

        if not allowed:
            return False

        if (
            obj is not None
            and not request.user.is_superuser
        ):
            return (
                obj.venue.manager_id
                == request.user.id
            )

        return True


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

    def get_queryset(self, request):
        queryset = super().get_queryset(request)

        if request.user.is_superuser:
            return queryset

        return queryset.filter(
            court__venue__manager=request.user
        )

    def formfield_for_foreignkey(
        self,
        db_field,
        request,
        **kwargs
    ):
        if (
            db_field.name == "court"
            and not request.user.is_superuser
        ):
            kwargs["queryset"] = courts_for_user(
                request.user
            )

        return super().formfield_for_foreignkey(
            db_field,
            request,
            **kwargs
        )

    def has_view_permission(
        self,
        request,
        obj=None
    ):
        allowed = super().has_view_permission(
            request,
            obj
        )

        if not allowed:
            return False

        if (
            obj is not None
            and not request.user.is_superuser
        ):
            return (
                obj.court.venue.manager_id
                == request.user.id
            )

        return True

    def has_change_permission(
        self,
        request,
        obj=None
    ):
        allowed = super().has_change_permission(
            request,
            obj
        )

        if not allowed:
            return False

        if (
            obj is not None
            and not request.user.is_superuser
        ):
            return (
                obj.court.venue.manager_id
                == request.user.id
            )

        return True

    def has_delete_permission(
        self,
        request,
        obj=None
    ):
        allowed = super().has_delete_permission(
            request,
            obj
        )

        if not allowed:
            return False

        if (
            obj is not None
            and not request.user.is_superuser
        ):
            return (
                obj.court.venue.manager_id
                == request.user.id
            )

        return True