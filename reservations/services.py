from datetime import datetime, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from uuid import uuid4
from courts.models import Horario
from reservations.models import Reserva, Pago


ESTADOS_QUE_BLOQUEAN = [
    "PENDING_PAYMENT",
    "CONFIRMED",
    "COMPLETED",
]

HOLD_MINUTES = 15

def expirar_reservas_pendientes():

    """
    Marca como EXPIRED las reservas PENDING_PAYMENT
    cuyo bloqueo temporal ya venció.
    """

    ahora = timezone.now()

    cantidad = Reserva.objects.filter(
        estado="PENDING_PAYMENT",
        hold_expira_en__isnull=False,
        hold_expira_en__lte=ahora
    ).update(
        estado="EXPIRED"
    )

    return cantidad

def obtener_disponibilidad(cancha, fecha, duracion_minutos=None):
    """
    Retorna los horarios disponibles de una cancha para una fecha determinada.

    Por defecto genera bloques de 60 minutos.
    """
    # Expira las reservas pendientes de pago que ya no tienen bloqueo temporal
    expirar_reservas_pendientes()

    dia_semana = fecha.isoweekday()

    horarios = Horario.objects.filter(
        cancha=cancha,
        dia_semana=dia_semana,
        activo=True
    ).order_by("hora_inicio")

    if not horarios.exists():
        return []

    reservas = Reserva.objects.filter(
        cancha=cancha,
        fecha=fecha,
        estado__in=ESTADOS_QUE_BLOQUEAN
    )

    slots_disponibles = []

    for horario in horarios:

        slot_minutos = (
            duracion_minutos
            if duracion_minutos is not None
            else horario.duracion_slot_minutos
        )

        inicio_actual = datetime.combine(
            fecha,
            horario.hora_inicio
        )

        fin_horario = datetime.combine(
            fecha,
            horario.hora_fin
        )

        while inicio_actual + timedelta(minutes=slot_minutos) <= fin_horario:
            fin_actual = inicio_actual + timedelta(
                minutes=slot_minutos
            )

            existe_conflicto = reservas.filter(
                hora_inicio__lt=fin_actual.time(),
                hora_fin__gt=inicio_actual.time()
            ).exists()

            if not existe_conflicto:
                slots_disponibles.append({
                    "hora_inicio": inicio_actual.time(),
                    "hora_fin": fin_actual.time(),
                })

            inicio_actual = fin_actual

    return slots_disponibles


def calcular_valores_reserva(
    cancha,
    fecha,
    hora_inicio,
    hora_fin
):
    """
    Calcula el valor total, abono requerido y saldo
    para una reserva.
    """

    if hora_inicio >= hora_fin:
        raise ValidationError(
            "La hora de inicio debe ser anterior a la hora de finalización."
        )

    inicio_dt = datetime.combine(
        fecha,
        hora_inicio
    )

    fin_dt = datetime.combine(
        fecha,
        hora_fin
    )

    duracion_segundos = Decimal(
        str((fin_dt - inicio_dt).total_seconds())
    )

    duracion_horas = (
        duracion_segundos / Decimal("3600")
    )

    valor_total = (
        cancha.precio_hora * duracion_horas
    ).quantize(Decimal("0.01"))

    porcentaje_abono = (
        cancha.venue.porcentaje_abono
    )

    abono_requerido = (
        valor_total
        * porcentaje_abono
        / Decimal("100")
    ).quantize(Decimal("0.01"))

    saldo_pendiente = (
        valor_total - abono_requerido
    ).quantize(Decimal("0.01"))

    return {
        "duracion_horas": duracion_horas,
        "valor_total": valor_total,
        "porcentaje_abono": porcentaje_abono,
        "abono_requerido": abono_requerido,
        "saldo_pendiente": saldo_pendiente,
    }


def calcular_valores_reserva(
    cancha,
    fecha,
    hora_inicio,
    hora_fin
):
    """
    Calcula el valor total, abono requerido y saldo pendiente
    de una reserva.
    """

    if hora_inicio >= hora_fin:
        raise ValidationError(
            "La hora de inicio debe ser anterior a la hora de finalización."
        )

    inicio_dt = datetime.combine(
        fecha,
        hora_inicio
    )

    fin_dt = datetime.combine(
        fecha,
        hora_fin
    )

    duracion_segundos = Decimal(
        str((fin_dt - inicio_dt).total_seconds())
    )

    duracion_horas = (
        duracion_segundos / Decimal("3600")
    )

    valor_total = (
        cancha.precio_hora * duracion_horas
    ).quantize(Decimal("0.01"))

    porcentaje_abono = (
        cancha.venue.porcentaje_abono
    )

    abono_requerido = (
        valor_total
        * porcentaje_abono
        / Decimal("100")
    ).quantize(Decimal("0.01"))

    saldo_pendiente = (
        valor_total - abono_requerido
    ).quantize(Decimal("0.01"))

    return {
        "duracion_horas": duracion_horas,
        "valor_total": valor_total,
        "porcentaje_abono": porcentaje_abono,
        "abono_requerido": abono_requerido,
        "saldo_pendiente": saldo_pendiente,
    }


@transaction.atomic
def crear_reserva_pendiente(
    usuario,
    cancha,
    fecha,
    hora_inicio,
    hora_fin
):
    """
    Crea una reserva temporal en estado PENDING_PAYMENT.

    Calcula:
    - Valor total de la reserva.
    - Abono requerido.
    - Saldo pendiente.
    - Fecha de expiración del hold.
    """

    # Expira las reservas pendientes de pago que ya no tienen bloqueo temporal
    expirar_reservas_pendientes()

    # Validar que la hora de inicio sea anterior a la hora de finalización
    if hora_inicio >= hora_fin:
        raise ValidationError(
            "La hora de inicio debe ser anterior a la hora de finalización."
        )

    # Día de semana compatible con el dataset: 1=Lunes ... 7=Domingo
    dia_semana = fecha.isoweekday()

    horario = Horario.objects.filter(
        cancha=cancha,
        dia_semana=dia_semana,
        activo=True,
        hora_inicio__lte=hora_inicio,
        hora_fin__gte=hora_fin
    ).first()

    if horario is None:
        raise ValidationError(
            "El horario seleccionado está fuera del horario operativo de la cancha."
        )

    # Detectar cualquier superposición
    conflicto = Reserva.objects.filter(
        cancha=cancha,
        fecha=fecha,
        hora_inicio__lt=hora_fin,
        hora_fin__gt=hora_inicio,
        estado__in=ESTADOS_QUE_BLOQUEAN
    ).exists()

    if conflicto:
        raise ValidationError(
            "La cancha ya está reservada o temporalmente bloqueada en este horario."
        )

    valores = calcular_valores_reserva(
        cancha,
        fecha,
        hora_inicio,
        hora_fin
    )

    valor_total = valores["valor_total"]
    abono_requerido = valores["abono_requerido"]
    saldo_pendiente = valores["saldo_pendiente"]

    reserva = Reserva(
        usuario=usuario,
        cancha=cancha,
        fecha=fecha,
        hora_inicio=hora_inicio,
        hora_fin=hora_fin,
        precio=valor_total,
        abono_requerido=abono_requerido,
        saldo_pendiente=saldo_pendiente,
        estado="PENDING_PAYMENT",
        hold_expira_en=timezone.now() + timedelta(
            minutes=HOLD_MINUTES
        ),
        origen_datos="SYSTEM"
    )

    reserva.full_clean()
    reserva.save()

    return reserva



@transaction.atomic
def procesar_pago_simulado(reserva, resultado):
    """
    Registra un intento de abono simulado.

    resultado debe ser:
    - APPROVED
    - REJECTED
    """

    resultado = resultado.upper()

    if resultado not in ["APPROVED", "REJECTED"]:
        raise ValidationError(
            "El resultado del pago debe ser APPROVED o REJECTED."
        )

    # Primero liberar reservas cuyo hold ya venció
    expirar_reservas_pendientes()

    # Bloquear la reserva durante esta operación
    reserva = (
        Reserva.objects
        .select_for_update()
        .get(pk=reserva.pk)
    )

    if reserva.estado == "EXPIRED":
        raise ValidationError(
            "La reserva expiró y ya no puede recibir pagos."
        )

    if reserva.estado != "PENDING_PAYMENT":
        raise ValidationError(
            "Solo las reservas pendientes de pago pueden recibir un abono."
        )

    if (
        reserva.hold_expira_en
        and reserva.hold_expira_en <= timezone.now()
    ):
        reserva.estado = "EXPIRED"
        reserva.save(update_fields=["estado"])

        raise ValidationError(
            "El tiempo disponible para realizar el abono expiró."
        )

    referencia = f"SIM-{uuid4().hex.upper()}"

    pago = Pago.objects.create(
        reserva=reserva,
        monto=reserva.abono_requerido,
        tipo="DEPOSIT",
        estado=resultado,
        proveedor="SIMULATED",
        referencia=referencia,
        fecha_aprobacion=(
            timezone.now()
            if resultado == "APPROVED"
            else None
        )
    )

    if resultado == "APPROVED":
        reserva.estado = "CONFIRMED"
        reserva.hold_expira_en = None
        reserva.save(
            update_fields=[
                "estado",
                "hold_expira_en",
            ]
        )

    return pago


@transaction.atomic
def cancelar_reserva(reserva):
    """
    Cancela una reserva confirmada y libera su franja horaria.
    """

    reserva = (
        Reserva.objects
        .select_for_update()
        .get(pk=reserva.pk)
    )

    if reserva.estado != "CONFIRMED":
        raise ValidationError(
            "Solo las reservas confirmadas pueden cancelarse."
        )

    reserva.estado = "CANCELLED"
    reserva.fecha_cancelacion = timezone.now()
    reserva.hold_expira_en = None

    reserva.save(
        update_fields=[
            "estado",
            "fecha_cancelacion",
            "hold_expira_en",
        ]
    )

    return reserva 