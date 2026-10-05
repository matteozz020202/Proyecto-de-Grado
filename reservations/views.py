from datetime import date, datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.contrib.auth import get_user_model

from django.db.models import Min, Max
from .kpis import (
    get_court_occupancy,
    get_summary_kpis,
    get_cancellation_kpis,
)

from courts.models import Court
from users.decorators import admin_required

from .models import Reservation
from .services import (
    calculate_reservation_values,
    cancel_reservation,
    create_admin_reservation,
    create_pending_reservation,
    expire_pending_reservations,
    get_availability,
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



@admin_required
def admin_crear_reserva(request):

    User = get_user_model()

    users = (
        User.objects
        .filter(is_active=True)
        .order_by("username")
    )

    courts = (
        Court.objects
        .select_related("venue")
        .filter(is_active=True)
        .order_by(
            "venue__venue_name",
            "court_name",
        )
    )

    # Mantener los datos escritos si ocurre un error.
    selected_user = request.POST.get(
        "usuario",
        ""
    )

    selected_court = request.POST.get(
        "cancha",
        ""
    )

    selected_date = request.POST.get(
        "fecha",
        ""
    )

    selected_start = request.POST.get(
        "hora_inicio",
        ""
    )

    selected_end = request.POST.get(
        "hora_fin",
        ""
    )

    if request.method == "POST":

        # ---------------------------------
        # Campos obligatorios
        # ---------------------------------

        if not all([
            selected_user,
            selected_court,
            selected_date,
            selected_start,
            selected_end,
        ]):
            messages.error(
                request,
                "Debes completar todos los campos."
            )

        else:

            try:

                # -------------------------
                # Usuario
                # -------------------------

                user = User.objects.get(
                    pk=selected_user,
                    is_active=True,
                )

                # -------------------------
                # Cancha
                # -------------------------

                court = (
                    Court.objects
                    .select_related("venue")
                    .get(
                        court_id=selected_court,
                        is_active=True,
                    )
                )

                # -------------------------
                # Fecha
                # -------------------------

                reservation_date = date.fromisoformat(
                    selected_date
                )

                # -------------------------
                # Horarios
                # -------------------------

                start_time = datetime.strptime(
                    selected_start,
                    "%H:%M",
                ).time()

                end_time = datetime.strptime(
                    selected_end,
                    "%H:%M",
                ).time()

                # -------------------------
                # No permitir pasado
                # -------------------------

                if reservation_date < timezone.localdate():
                    raise ValidationError(
                        "No puedes crear una reserva "
                        "para una fecha anterior a hoy."
                    )

                # -------------------------
                # Crear reserva
                # -------------------------

                reservation = create_admin_reservation(
                    user=user,
                    court=court,
                    reservation_date=reservation_date,
                    start_time=start_time,
                    end_time=end_time,
                )

            except User.DoesNotExist:

                messages.error(
                    request,
                    "El usuario seleccionado no existe "
                    "o se encuentra inactivo."
                )

            except Court.DoesNotExist:

                messages.error(
                    request,
                    "La cancha seleccionada no existe "
                    "o se encuentra inactiva."
                )

            except ValueError:

                messages.error(
                    request,
                    "La fecha o el horario ingresado "
                    "no es válido."
                )

            except ValidationError as error:

                messages.error(
                    request,
                    error.messages[0]
                )

            else:

                messages.success(
                    request,
                    (
                        f"Reserva #{reservation.reservation_id} "
                        "creada correctamente y confirmada."
                    )
                )

                return redirect(
                    "reservations:admin_reservas"
                )

    return render(
        request,
        "reservations/admin_crear_reserva.html",
        {
            "usuarios": users,
            "canchas": courts,

            "usuario_seleccionado": selected_user,
            "cancha_seleccionada": selected_court,
            "fecha_seleccionada": selected_date,
            "hora_inicio_seleccionada": selected_start,
            "hora_fin_seleccionada": selected_end,

            "fecha_minima": (
                timezone.localdate().isoformat()
            ),
        }
    )


@login_required(login_url="users:login")
@admin_required
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

    # Fechas ya convertidas para reutilizarlas en KPIs
    parsed_start_date = None
    parsed_end_date = None

    # ---------------------------------
    # Filtro fecha desde
    # ---------------------------------

    if start_date_filter:
        try:
            parsed_start_date = date.fromisoformat(
                start_date_filter
            )

            reservations = reservations.filter(
                reservation_date__gte=parsed_start_date
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
            parsed_end_date = date.fromisoformat(
                end_date_filter
            )

            reservations = reservations.filter(
                reservation_date__lte=parsed_end_date
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
    # Rango para KPIs
    # ---------------------------------

    kpi_base_queryset = Reservation.objects.all()

    # Si se selecciona una cancha,
    # el rango automático también se obtiene
    # a partir de esa cancha.
    if court_id:
        kpi_base_queryset = kpi_base_queryset.filter(
            court_id=court_id
        )

    bounds = kpi_base_queryset.aggregate(
        min_date=Min("reservation_date"),
        max_date=Max("reservation_date"),
    )

    today = timezone.localdate()

    kpi_start_date = (
        parsed_start_date
        or bounds["min_date"]
        or today
    )

    kpi_end_date = (
        parsed_end_date
        or bounds["max_date"]
        or today
    )

    # Evitar un rango inválido
    if kpi_start_date > kpi_end_date:
        messages.warning(
            request,
            "La fecha inicial no puede ser "
            "posterior a la fecha final."
        )

        kpi_start_date, kpi_end_date = (
            kpi_end_date,
            kpi_start_date
        )

    # ---------------------------------
    # M3-09
    # Reservas / horas / valor
    # ---------------------------------

    summary_kpis = get_summary_kpis(
        start_date=kpi_start_date,
        end_date=kpi_end_date,
        court_id=court_id or None,
    )

    # ---------------------------------
    # M3-10
    # Cancelaciones
    # ---------------------------------

    cancellation_kpis = get_cancellation_kpis(
        start_date=kpi_start_date,
        end_date=kpi_end_date,
        court_id=court_id or None,
    )

    # ---------------------------------
    # M3-08
    # Ocupación por cancha
    # ---------------------------------

    occupancy_by_court = get_court_occupancy(
        start_date=kpi_start_date,
        end_date=kpi_end_date,
        court_id=court_id or None,
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

    # ---------------------------------
    # Contexto
    # ---------------------------------

    context = {
        "pagina": page,
        "canchas": courts,
        "estados": statuses,

        "fecha_desde": start_date_filter,
        "fecha_hasta": end_date_filter,
        "cancha_seleccionada": court_id,
        "estado_seleccionado": status,

        "querystring": parameters.urlencode(),

        # KPIs
        "summary_kpis": summary_kpis,
        "cancellation_kpis": cancellation_kpis,
        "occupancy_by_court": occupancy_by_court,

        "kpi_start_date": kpi_start_date,
        "kpi_end_date": kpi_end_date,
    }

    return render(
        request,
        "reservations/admin_reservas.html",
        context
    )
