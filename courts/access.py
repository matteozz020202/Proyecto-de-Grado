from .models import Court, Venue


def venues_for_user(user):
    queryset = Venue.objects.all()

    if not user.is_authenticated:
        return queryset.none()

    if user.is_superuser:
        return queryset

    return queryset.filter(
        manager=user
    )


def courts_for_user(user):
    queryset = Court.objects.select_related(
        "venue"
    )

    if not user.is_authenticated:
        return queryset.none()

    if user.is_superuser:
        return queryset

    return queryset.filter(
        venue__manager=user
    )