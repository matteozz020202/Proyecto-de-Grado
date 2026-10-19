from datetime import date, datetime

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
from django.utils.dateparse import parse_date

from courts.models import Court, Venue
from courts.access import courts_for_user
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
    create_pending_reservation,
    expire_pending_reservations,
    get_availability,
    process_simulated_payment,
    complete_reservation,
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
        courts_for_user(request.user)
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

    client_type = request.POST.get(
    "tipo_cliente",
    "REGISTERED"
    )

    guest_name = request.POST.get(
        "guest_name",
        ""
    ).strip()

    guest_phone = request.POST.get(
        "guest_phone",
        ""
    ).strip()

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
            selected_court,
            selected_date,
            selected_start,
            selected_end,
        ]):
            messages.error(
                request,
                "Debes completar la cancha, fecha y horario."
            )

        elif client_type not in [
            "REGISTERED",
            "GUEST",
        ]:
            messages.error(
                request,
                "El tipo de cliente seleccionado no es válido."
            )

        elif (
            client_type == "REGISTERED"
            and not selected_user
        ):
            messages.error(
                request,
                "Debes seleccionar un usuario registrado."
            )

        elif (
            client_type == "GUEST"
            and not guest_name
        ):
            messages.error(
                request,
                "Debes indicar el nombre del cliente sin cuenta."
            )

        else:

            try:

                # -------------------------
                # Usuario
                # -------------------------

                if client_type == "REGISTERED":
                    user = User.objects.get(
                        pk=selected_user,
                        is_active=True,
                    )

                    reservation_guest_name = ""
                    reservation_guest_phone = ""

                else:
                    user = None
                    reservation_guest_name = guest_name
                    reservation_guest_phone = guest_phone

                # -------------------------
                # Cancha
                # -------------------------

                court = (
                    courts_for_user(request.user)
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
                    guest_name=reservation_guest_name,
                    guest_phone=reservation_guest_phone,
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

                return redirect("reservations:admin_reservas")

    return render(
        request,
        "reservations/admin_crear_reserva.html",
        {
            "usuarios": users,
            "canchas": courts,

            "usuario_seleccionado": selected_user,
            "tipo_cliente": client_type,
            "guest_name": guest_name,
            "guest_phone": guest_phone,
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
    form = DashboardFilterForm(
        request.GET,
        user=request.user
    )
    if not form.is_valid():
        return render(request, "reservations/admin_dashboard.html", {
            "hoy": today, "form": form, "filtros_validos": False,
        })
    expire_pending_reservations()
    filters = form.cleaned_data
    data_source = filters["origen"]
    start_date, end_date = filters["fecha_inicio"], filters["fecha_fin"]
    courts, source_reservations = filtered_scope(
        filters,
        request.user
    )
    reservations = source_reservations.filter(reservation_date__range=(start_date, end_date))

    analytics = dashboard_data(courts, reservations, start_date, end_date, filters["tipo"], data_source)
    status_counts = analytics["status_counts"]




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
    form = DashboardFilterForm(
        request.POST,
        user=request.user
    )
    error = None
    status = 200
    context = {}
    if request.POST.get("origen") not in dict(Reservation.DATA_SOURCES) and request.POST.get("origen") != "ALL":
        error, status = "Selecciona un origen válido y vuelve a aplicar los filtros.", 400
    elif not form.is_valid():
        error, status = "Revisa el establecimiento, la cancha y las fechas; vuelve a aplicar los filtros.", 400
    else:
        filters = form.cleaned_data
        courts, reservations = filtered_scope(
            filters,
            request.user
        )
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

@login_required(login_url="users:login")
@admin_required
def admin_reservas(request):
    allowed_courts = courts_for_user(
        request.user
    )

    reservations = (
        Reservation.objects
        .select_related(
            "user",
            "court",
            "court__venue"
        )
        .filter(
            court__in=allowed_courts
        )
        .order_by(
            "-reservation_date",
            "-start_time"
        )
    )

    selected_court = request.GET.get(
        "cancha",
        ""
    )

    selected_status = request.GET.get(
        "estado",
        ""
    )

    start_date_raw = request.GET.get(
        "fecha_inicio",
        ""
    )

    end_date_raw = request.GET.get(
        "fecha_fin",
        ""
    )

    if selected_court:
        reservations = reservations.filter(
            court_id=selected_court
        )

    allowed_statuses = {
        "PENDING_PAYMENT",
        "CONFIRMED",
        "COMPLETED",
        "CANCELLED",
        "EXPIRED",
    }

    if selected_status in allowed_statuses:
        reservations = reservations.filter(
            reservation_status=selected_status
        )

    start_date = parse_date(
        start_date_raw
    )

    end_date = parse_date(
        end_date_raw
    )

    if start_date:
        reservations = reservations.filter(
            reservation_date__gte=start_date
        )

    if end_date:
        reservations = reservations.filter(
            reservation_date__lte=end_date
        )

    paginator = Paginator(
        reservations,
        25
    )

    reservation_page = paginator.get_page(
        request.GET.get("page")
    )

    params = request.GET.copy()

    if "page" in params:
        params.pop("page")

    context = {
        "pagina_reservas": reservation_page,
        "courts": allowed_courts.order_by(
            "venue__venue_name",
            "court_name"
        ),
        "selected_court": selected_court,
        "selected_status": selected_status,
        "fecha_inicio": start_date_raw,
        "fecha_fin": end_date_raw,
        "querystring": params.urlencode(),
    }

    return render(
        request,
        "reservations/admin_reservas.html",
        context
    )

@admin_required
def admin_detalle_reserva(request, reserva_id):
    allowed_courts = courts_for_user(
        request.user
    )

    reservation = get_object_or_404(
        Reservation.objects
        .select_related(
            "user",
            "court",
            "court__venue"
        )
        .prefetch_related(
            "payments"
        )
        .filter(
            court__in=allowed_courts
        ),
        reservation_id=reserva_id
    )

    if request.method=="POST":
        action=request.POST.get("action")
        try:
            if action=="complete":
                complete_reservation(reservation); success="La reserva fue marcada como completada."
            elif action=="cancel":
                cancel_reservation(reservation); success="La reserva fue cancelada correctamente."
            else:
                raise ValidationError("La acción seleccionada no es válida.")
        except ValidationError as error:
            messages.error(request,error.messages[0])
        else:
            messages.success(request,success)
        return redirect("reservations:admin_detalle_reserva",reserva_id=reservation.reservation_id)

    return render(
        request,
        "reservations/admin_detalle_reserva.html",
        {
            "reserva": reservation
        }
    )