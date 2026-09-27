from datetime import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from courts.models import Cancha

from .models import Reserva
from .services import (
    calcular_valores_reserva,
    crear_reserva_pendiente,
    expirar_reservas_pendientes,
    obtener_disponibilidad,
    procesar_pago_simulado,
    cancelar_reserva as cancelar_reserva_servicio,
)


@login_required(login_url="users:login")
def mis_reservas(request):
    expirar_reservas_pendientes()

    reservas = (
        Reserva.objects
        .filter(usuario=request.user)
        .select_related(
            "cancha",
            "cancha__venue"
        )
        .prefetch_related("pagos")
        .order_by("-fecha", "-hora_inicio")
    )

    return render(
        request,
        "reservations/mis_reservas.html",
        {
            "reservas": reservas
        }
    )


@login_required(login_url="users:login")
def resumen_reserva(request, cancha_id):
    cancha = get_object_or_404(
        Cancha.objects.select_related("venue"),
        id=cancha_id,
        activa=True
    )

    fecha_texto = (
        request.POST.get("fecha")
        or request.GET.get("fecha")
    )

    inicio_texto = (
        request.POST.get("inicio")
        or request.GET.get("inicio")
    )

    fin_texto = (
        request.POST.get("fin")
        or request.GET.get("fin")
    )

    # Si falta algún dato, regresar a disponibilidad
    if not fecha_texto or not inicio_texto or not fin_texto:
        messages.error(
            request,
            "Debes seleccionar una fecha y un horario."
        )

        return redirect(
            "courts:disponibilidad_cancha",
            cancha_id=cancha.id
        )

    try:
        fecha = datetime.strptime(
            fecha_texto,
            "%Y-%m-%d"
        ).date()

        hora_inicio = datetime.strptime(
            inicio_texto,
            "%H:%M"
        ).time()

        hora_fin = datetime.strptime(
            fin_texto,
            "%H:%M"
        ).time()

    except ValueError:
        messages.error(
            request,
            "La fecha o el horario seleccionado no son válidos."
        )

        return redirect(
            "courts:disponibilidad_cancha",
            cancha_id=cancha.id
        )

    # No permitir fechas anteriores
    if fecha < timezone.localdate():
        messages.error(
            request,
            "No puedes reservar una fecha anterior a hoy."
        )

        return redirect(
            "courts:disponibilidad_cancha",
            cancha_id=cancha.id
        )

    # Revalidar disponibilidad
    slots = obtener_disponibilidad(
        cancha,
        fecha
    )

    horario_disponible = any(
        slot["hora_inicio"] == hora_inicio
        and slot["hora_fin"] == hora_fin
        for slot in slots
    )

    if not horario_disponible:
        messages.error(
            request,
            "Ese horario ya no está disponible. Selecciona otro."
        )

        url = reverse(
            "courts:disponibilidad_cancha",
            kwargs={"cancha_id": cancha.id}
        )

        return redirect(
            f"{url}?fecha={fecha.isoformat()}"
        )

    # Calcular valores para mostrarlos en el resumen
    valores = calcular_valores_reserva(
        cancha,
        fecha,
        hora_inicio,
        hora_fin
    )

    # Si el usuario confirmó la reserva
    if request.method == "POST":
        try:
            reserva = crear_reserva_pendiente(
                usuario=request.user,
                cancha=cancha,
                fecha=fecha,
                hora_inicio=hora_inicio,
                hora_fin=hora_fin
            )

        except ValidationError as error:
            messages.error(
                request,
                error.messages[0]
            )

            url = reverse(
                "courts:disponibilidad_cancha",
                kwargs={"cancha_id": cancha.id}
            )

            return redirect(
                f"{url}?fecha={fecha.isoformat()}"
            )

        messages.success(
            request,
            "Reserva creada. Tienes 15 minutos para realizar el abono."
        )

        return redirect(
            "reservations:pagar_reserva",
            reserva_id=reserva.id
        )

    return render(
        request,
        "reservations/resumen_reserva.html",
        {
            "cancha": cancha,
            "fecha": fecha,
            "hora_inicio": hora_inicio,
            "hora_fin": hora_fin,
            "valores": valores,
        }
    )


@login_required(login_url="users:login")
def pagar_reserva(request, reserva_id):
    expirar_reservas_pendientes()

    reserva = get_object_or_404(
        Reserva.objects.select_related(
            "cancha",
            "cancha__venue"
        ),
        id=reserva_id,
        usuario=request.user
    )

    reserva.refresh_from_db()

    if reserva.estado == "EXPIRED":
        messages.error(
            request,
            "El tiempo para realizar el abono expiró."
        )

        return redirect(
            "reservations:mis_reservas"
        )

    if reserva.estado == "CONFIRMED":
        messages.info(
            request,
            "Esta reserva ya está confirmada."
        )

        return redirect(
            "reservations:mis_reservas"
        )

    if reserva.estado != "PENDING_PAYMENT":
        messages.error(
            request,
            "Esta reserva no se encuentra pendiente de pago."
        )

        return redirect(
            "reservations:mis_reservas"
        )

    if request.method == "POST":
        resultado = request.POST.get("resultado")

        try:
            pago = procesar_pago_simulado(
                reserva,
                resultado
            )

        except ValidationError as error:
            messages.error(
                request,
                error.messages[0]
            )

            return redirect(
                "reservations:mis_reservas"
            )

        if pago.estado == "APPROVED":
            messages.success(
                request,
                "Abono aprobado. Tu reserva fue confirmada."
            )

            return redirect(
                "reservations:mis_reservas"
            )

        messages.error(
            request,
            "El pago fue rechazado. Puedes intentar nuevamente mientras el tiempo de reserva siga vigente."
        )

        return redirect(
            "reservations:pagar_reserva",
            reserva_id=reserva.id
        )

    tiempo_restante = max(
        0,
        int(
            (
                reserva.hold_expira_en
                - timezone.now()
            ).total_seconds()
        )
    )
    return render(
        request,
        "reservations/pagar_reserva.html",
        {
            "reserva": reserva,
            "tiempo_restante": tiempo_restante,
        }
    )

@login_required(login_url="users:login")
@require_POST
def cancelar_reserva_view(request, reserva_id):

    reserva = get_object_or_404(
        Reserva,
        id=reserva_id,
        usuario=request.user
    )

    try:
        cancelar_reserva_servicio(reserva)

    except ValidationError as error:
        messages.error(
            request,
            error.messages[0]
        )

    else:
        messages.success(
            request,
            "La reserva fue cancelada correctamente. "
            "El horario volvió a estar disponible."
        )

    return redirect(
        "reservations:mis_reservas"
    )