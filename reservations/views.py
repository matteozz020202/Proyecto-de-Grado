from datetime import date, datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from courts.models import Court
from users.decorators import admin_required

from .models import Reservation
from .services import (
    calculate_reservation_values,
    cancel_reservation,
    create_pending_reservation,
    expire_pending_reservations,
    get_availability,
    process_simulated_payment,
)


@login_required(login_url="users:login")
def mis_reservas(request):
    expire_pending_reservations()

    reservations = (
        Reservation.objects
        .filter(
            user=request.user
        )
        .select_related(
            "court",
            "court__venue"
        )
        .prefetch_related(
            "payments"
        )
        .order_by(
            "-reservation_date",
            "-start_time"
        )
    )

    return render(
        request,
        "reservations/mis_reservas.html",
        {
            "reservas": reservations
        }
    )


@login_required(login_url="users:login")
def resumen_reserva(
    request,
    cancha_id
):
    court = get_object_or_404(
        Court.objects.select_related(
            "venue"
        ),
        court_id=cancha_id,
        is_active=True
    )

    date_text = (
        request.POST.get("fecha")
        or request.GET.get("fecha")
    )

    start_text = (
        request.POST.get("inicio")
        or request.GET.get("inicio")
    )

    end_text = (
        request.POST.get("fin")
        or request.GET.get("fin")
    )

    # Si falta algún dato,
    # regresar a disponibilidad.
    if (
        not date_text
        or not start_text
        or not end_text
    ):
        messages.error(
            request,
            "Debes seleccionar una fecha y un horario."
        )

        return redirect(
            "courts:disponibilidad_cancha",
            cancha_id=court.court_id
        )

    try:
        reservation_date = datetime.strptime(
            date_text,
            "%Y-%m-%d"
        ).date()

        start_time = datetime.strptime(
            start_text,
            "%H:%M"
        ).time()

        end_time = datetime.strptime(
            end_text,
            "%H:%M"
        ).time()

    except ValueError:
        messages.error(
            request,
            "La fecha o el horario seleccionado "
            "no son válidos."
        )

        return redirect(
            "courts:disponibilidad_cancha",
            cancha_id=court.court_id
        )

    # No permitir fechas anteriores.
    if (
        reservation_date
        < timezone.localdate()
    ):
        messages.error(
            request,
            "No puedes reservar una fecha "
            "anterior a hoy."
        )

        return redirect(
            "courts:disponibilidad_cancha",
            cancha_id=court.court_id
        )

    # Revalidar disponibilidad.
    slots = get_availability(
        court,
        reservation_date
    )

    slot_available = any(
        slot["start_time"] == start_time
        and slot["end_time"] == end_time
        for slot in slots
    )

    if not slot_available:
        messages.error(
            request,
            "Ese horario ya no está disponible. "
            "Selecciona otro."
        )

        url = reverse(
            "courts:disponibilidad_cancha",
            kwargs={
                "cancha_id": court.court_id
            }
        )

        return redirect(
            f"{url}?fecha="
            f"{reservation_date.isoformat()}"
        )

    # Calcular valores para el resumen.
    values = calculate_reservation_values(
        court,
        reservation_date,
        start_time,
        end_time
    )

    # Crear reserva.
    if request.method == "POST":
        try:
            reservation = create_pending_reservation(
                user=request.user,
                court=court,
                reservation_date=reservation_date,
                start_time=start_time,
                end_time=end_time
            )

        except ValidationError as error:
            messages.error(
                request,
                error.messages[0]
            )

            url = reverse(
                "courts:disponibilidad_cancha",
                kwargs={
                    "cancha_id": court.court_id
                }
            )

            return redirect(
                f"{url}?fecha="
                f"{reservation_date.isoformat()}"
            )

        messages.success(
            request,
            "Reserva creada. Tienes 15 minutos "
            "para realizar el abono."
        )

        return redirect(
            "reservations:pagar_reserva",
            reserva_id=reservation.reservation_id
        )

    return render(
        request,
        "reservations/resumen_reserva.html",
        {
            "cancha": court,
            "fecha": reservation_date,
            "hora_inicio": start_time,
            "hora_fin": end_time,
            "valores": values,
        }
    )


@login_required(login_url="users:login")
def pagar_reserva(
    request,
    reserva_id
):
    expire_pending_reservations()

    reservation = get_object_or_404(
        Reservation.objects.select_related(
            "court",
            "court__venue"
        ),
        reservation_id=reserva_id,
        user=request.user
    )

    reservation.refresh_from_db()

    if (
        reservation.reservation_status
        == "EXPIRED"
    ):
        messages.error(
            request,
            "El tiempo para realizar el abono expiró."
        )

        return redirect(
            "reservations:mis_reservas"
        )

    if (
        reservation.reservation_status
        == "CONFIRMED"
    ):
        messages.info(
            request,
            "Esta reserva ya está confirmada."
        )

        return redirect(
            "reservations:mis_reservas"
        )

    if (
        reservation.reservation_status
        != "PENDING_PAYMENT"
    ):
        messages.error(
            request,
            "Esta reserva no se encuentra "
            "pendiente de pago."
        )

        return redirect(
            "reservations:mis_reservas"
        )

    if request.method == "POST":
        result = request.POST.get(
            "resultado",
            ""
        )

        try:
            payment = process_simulated_payment(
                reservation,
                result
            )

        except ValidationError as error:
            messages.error(
                request,
                error.messages[0]
            )

            return redirect(
                "reservations:mis_reservas"
            )

        if (
            payment.payment_status
            == "APPROVED"
        ):
            messages.success(
                request,
                "Abono aprobado. "
                "Tu reserva fue confirmada."
            )

            return redirect(
                "reservations:mis_reservas"
            )

        messages.error(
            request,
            "El pago fue rechazado. "
            "Puedes intentar nuevamente mientras "
            "el tiempo de reserva siga vigente."
        )

        return redirect(
            "reservations:pagar_reserva",
            reserva_id=reservation.reservation_id
        )

    remaining_time = max(
        0,
        int(
            (
                reservation.hold_expires_at
                - timezone.now()
            ).total_seconds()
        )
    )

    return render(
        request,
        "reservations/pagar_reserva.html",
        {
            "reserva": reservation,
            "tiempo_restante": remaining_time,
        }
    )


@login_required(login_url="users:login")
@require_POST
def cancelar_reserva_view(
    request,
    reserva_id
):
    reservation = get_object_or_404(
        Reservation,
        reservation_id=reserva_id,
        user=request.user
    )

    try:
        cancel_reservation(
            reservation
        )

    except ValidationError as error:
        messages.error(
            request,
            error.messages[0]
        )

    else:
        messages.success(
            request,
            "La reserva fue cancelada "
            "correctamente. "
            "El horario volvió a estar disponible."
        )

    return redirect(
        "reservations:mis_reservas"
    )


@login_required(login_url="users:login")
@admin_required
def admin_reservas(request):
    reservations = (
        Reservation.objects
        .select_related(
            "user",
            "court",
            "court__venue"
        )
        .order_by(
            "-reservation_date",
            "-start_time"
        )
    )

    # ---------------------------------
    # Parámetros de filtros
    # ---------------------------------

    start_date_filter = request.GET.get(
        "fecha_desde",
        ""
    )

    end_date_filter = request.GET.get(
        "fecha_hasta",
        ""
    )

    court_id = request.GET.get(
        "cancha",
        ""
    )

    status = request.GET.get(
        "estado",
        ""
    )

    # ---------------------------------
    # Filtro fecha desde
    # ---------------------------------

    if start_date_filter:
        try:
            start_date = date.fromisoformat(
                start_date_filter
            )

            reservations = reservations.filter(
                reservation_date__gte=start_date
            )

        except ValueError:
            messages.warning(
                request,
                "La fecha inicial no es válida."
            )

    # ---------------------------------
    # Filtro fecha hasta
    # ---------------------------------

    if end_date_filter:
        try:
            end_date = date.fromisoformat(
                end_date_filter
            )

            reservations = reservations.filter(
                reservation_date__lte=end_date
            )

        except ValueError:
            messages.warning(
                request,
                "La fecha final no es válida."
            )

    # ---------------------------------
    # Filtro cancha
    # ---------------------------------

    if court_id:
        reservations = reservations.filter(
            court_id=court_id
        )

    # ---------------------------------
    # Filtro estado
    # ---------------------------------

    valid_statuses = [
        value
        for value, label
        in Reservation._meta
        .get_field(
            "reservation_status"
        )
        .choices
    ]

    if (
        status
        and status in valid_statuses
    ):
        reservations = reservations.filter(
            reservation_status=status
        )

    # ---------------------------------
    # Catálogos para filtros
    # ---------------------------------

    courts = (
        Court.objects
        .select_related(
            "venue"
        )
        .filter(
            is_active=True
        )
        .order_by(
            "venue__venue_name",
            "court_name"
        )
    )

    statuses = (
        Reservation._meta
        .get_field(
            "reservation_status"
        )
        .choices
    )

    # ---------------------------------
    # Paginación
    # ---------------------------------

    paginator = Paginator(
        reservations,
        25
    )

    page = paginator.get_page(
        request.GET.get("page")
    )

    parameters = request.GET.copy()

    if "page" in parameters:
        parameters.pop("page")

    context = {
        "pagina": page,
        "canchas": courts,
        "estados": statuses,

        "fecha_desde": start_date_filter,
        "fecha_hasta": end_date_filter,
        "cancha_seleccionada": court_id,
        "estado_seleccionado": status,

        "querystring": parameters.urlencode(),
    }

    return render(
        request,
        "reservations/admin_reservas.html",
        context
    )