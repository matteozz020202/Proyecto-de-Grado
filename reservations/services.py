from datetime import datetime, timedelta

from courts.models import Horario
from reservations.models import Reserva


ESTADOS_QUE_BLOQUEAN = [
    "PENDING_PAYMENT",
    "CONFIRMED",
    "COMPLETED",
]


def obtener_disponibilidad(cancha, fecha, duracion_minutos=None):
    """
    Retorna los horarios disponibles de una cancha para una fecha determinada.

    Por defecto genera bloques de 60 minutos.
    """

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