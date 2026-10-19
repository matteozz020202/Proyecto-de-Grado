from datetime import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.contrib.auth import get_user_model
from pydantic import ValidationError as ContractValidationError

from courts.models import Court, Venue
from users.decorators import admin_required

from .models import Reservation
from .analytics import dashboard_data
from .forms import DashboardFilterForm
from .dashboard_scope import filtered_scope
from .ai.adapters import AnalysisContextError, build_analysis_input
from .ai.presentation import analysis_for_display
from .ai.services import AIAnalysisError, AIAnalysisService
from .services import (
    calculate_reservation_values,
    cancel_reservation,
    create_admin_reservation,
    create_confirmed_reservation,
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

    now = timezone.localtime()
    for reservation in reservations:
        reservation.is_upcoming = (
            reservation.reservation_status in {"PENDING_PAYMENT", "CONFIRMED"}
            and (reservation.reservation_date, reservation.end_time) > (now.date(), now.time().replace(tzinfo=None))
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
            reservation = create_confirmed_reservation(
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
            "Tu reserva fue confirmada correctamente."
        )

        return redirect(
            "reservations:reserva_confirmada",
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
def reserva_confirmada(request, reserva_id):
    reservation = get_object_or_404(
        Reservation.objects.select_related("court", "court__venue"),
        pk=reserva_id, user=request.user, reservation_status="CONFIRMED",
    )
    return render(request, "reservations/reserva_confirmada.html", {"reserva": reservation})


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
                    "reservations:admin_dashboard"
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
def admin_dashboard(request):
    now = timezone.localtime()
    today = now.date()
    form = DashboardFilterForm(request.GET)
    if not form.is_valid():
        return render(request, "reservations/admin_dashboard.html", {
            "hoy": today, "form": form, "filtros_validos": False,
        })
    expire_pending_reservations()
    filters = form.cleaned_data
    data_source = filters["origen"]
    start_date, end_date = filters["fecha_inicio"], filters["fecha_fin"]
    courts, source_reservations = filtered_scope(filters)
    reservations = source_reservations.filter(reservation_date__range=(start_date, end_date))

    analytics = dashboard_data(courts, reservations, start_date, end_date, filters["tipo"], data_source)
    status_counts = analytics["status_counts"]

    table_reservations = reservations.select_related("user", "court", "court__venue").order_by("-reservation_date", "-start_time", "-pk")
    paginator = Paginator(table_reservations, 25)
    reservation_page = paginator.get_page(request.GET.get("page"))
    params = request.GET.copy()
    if "page" in params:
        params.pop("page")


    context = {
        "hoy": today,
        "form": form,
        "filtros_validos": True,
        "fecha_inicio": start_date,
        "fecha_fin": end_date,
        "tipo_analisis": filters["tipo"],
        "ocupacion": analytics["occupancy"],
        "dashboard_data": analytics,
        "analysis_filters": {key: (value.pk if key in ("cancha", "establecimiento") and value
                                    else "" if value is None else value.isoformat()
                                    if key in ("fecha_inicio", "fecha_fin") else value)
                             for key, value in filters.items()},
        "analysis_enabled": data_source != "ALL" and not analytics["occupancy"]["capacidad_inconsistente"]
                            and bool(settings.OPENAI_API_KEY and settings.OPENAI_MODEL),
        "analysis_block_reason": (
            "Selecciona un origen específico para generar el análisis." if data_source == "ALL" else
            "Revisa la capacidad y las reservas antes de generar el análisis."
            if analytics["occupancy"]["capacidad_inconsistente"] else
            "El análisis inteligente todavía no está configurado." if not (settings.OPENAI_API_KEY and settings.OPENAI_MODEL) else ""
        ),
        "chart_data": analytics["chart_data"],
        "datos_sinteticos": data_source == "SYNTHETIC" or reservations.filter(data_source="SYNTHETIC").exists(),
        "origen": data_source,
        "origenes": Reservation.DATA_SOURCES,
        "pagina_reservas": reservation_page,
        "querystring": params.urlencode(),
        "total_establecimientos": Venue.objects.filter(
            pk__in=courts.values("venue_id"), is_active=True,
        ).count(),
        "total_canchas": courts.filter(
            is_active=True
        ).count(),
        "reservas_hoy": reservations.filter(
            reservation_date=today
        ).exclude(
            reservation_status__in=[
                "CANCELLED",
                "EXPIRED",
            ]
        ).count(),
        "pendientes_pago": status_counts.get(
            "PENDING_PAYMENT",
            0
        ),
        "confirmadas": status_counts.get(
            "CONFIRMED",
            0
        ),
        "completadas": status_counts.get(
            "COMPLETED",
            0
        ),
        "canceladas": status_counts.get(
            "CANCELLED",
            0
        ),
        "ingresos_aprobados": analytics["approved_payments"],
        "pagos_aprobados": analytics["approved_payment_count"],
    }

    return render(
        request,
        "reservations/admin_dashboard.html",
        context
    )


@login_required(login_url="users:login")
@admin_required
@require_POST
def admin_dashboard_analysis(request):
    form = DashboardFilterForm(request.POST)
    error = None
    status = 200
    context = {}
    if request.POST.get("origen") not in dict(Reservation.DATA_SOURCES) and request.POST.get("origen") != "ALL":
        error, status = "Selecciona un origen válido y vuelve a aplicar los filtros.", 400
    elif not form.is_valid():
        error, status = "Revisa el establecimiento, la cancha y las fechas; vuelve a aplicar los filtros.", 400
    else:
        filters = form.cleaned_data
        courts, reservations = filtered_scope(filters)
        try:
            analytics = dashboard_data(courts, reservations, filters["fecha_inicio"], filters["fecha_fin"],
                                       filters["tipo"], filters["origen"])
            payload = build_analysis_input(filters, analytics, courts, reservations)
            result = AIAnalysisService().generate(payload)
        except AnalysisContextError as exc:
            error = {"SELECT_SINGLE_SOURCE": "Selecciona un origen específico; el análisis no mezcla fuentes.",
                     "INCONSISTENT_CAPACITY": "Revisa las reservas y los horarios: la ocupación supera la capacidad."}[exc.code]
            status = 400
        except AIAnalysisError as exc:
            error = {
                "CONFIGURATION_ERROR": "El análisis inteligente todavía no está configurado.",
                "TIMEOUT": "El análisis tardó demasiado. Puedes intentarlo nuevamente.",
                "INPUT_TOO_LARGE": "El período contiene demasiada información. Reduce las fechas o selecciona una cancha.",
                "RATE_LIMIT": "El análisis no está disponible por ahora. Inténtalo más tarde.",
            }.get(exc.code, "No se pudo generar un análisis validado. Puedes intentarlo nuevamente; los indicadores siguen disponibles.")
            status = 503
        except (ValidationError, ContractValidationError):
            error, status = "Revisa los datos del contexto antes de solicitar el análisis.", 400
        else:
            context = {"analysis": analysis_for_display(result, payload), "analysis_generated_at": timezone.localtime()}
    if error:
        context = {"analysis_error": error}
    html = render_to_string("reservations/dashboard_insights_result.html", context, request=request)
    return JsonResponse({"state": "ERROR" if error else "SUCCESS", "html": html}, status=status)

@admin_required
def admin_detalle_reserva(request, reserva_id):
    reservation = get_object_or_404(
        Reservation.objects
        .select_related("user", "court", "court__venue")
        .prefetch_related("payments"),
        reservation_id=reserva_id
    )

    return render(
        request,
        "reservations/admin_detalle_reserva.html",
        {"reserva": reservation}
    )
