from datetime import time, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from courts.models import Venue, Cancha, Horario

from .models import Reserva, Pago
from .services import (
    cancelar_reserva,
    crear_reserva_pendiente,
    expirar_reservas_pendientes,
    obtener_disponibilidad,
    procesar_pago_simulado,
)


class ReservaFlowTests(TestCase):

    def setUp(self):
        # Usuario de prueba
        self.usuario = User.objects.create_user(
            username="usuario_test",
            password="Test12345!"
        )

        # Establecimiento
        self.venue = Venue.objects.create(
            nombre="Complejo Test",
            direccion="Calle 1 # 1-1",
            ciudad="Barranquilla",
            porcentaje_abono=Decimal("30.00"),
            activo=True
        )

        # Cancha
        self.cancha = Cancha.objects.create(
            venue=self.venue,
            nombre="Cancha Test",
            descripcion="Cancha para pruebas",
            precio_hora=Decimal("120000.00"),
            activa=True
        )

        # Fecha futura
        self.fecha = timezone.localdate() + timedelta(days=7)

        # Horario correspondiente al día elegido
        Horario.objects.create(
            cancha=self.cancha,
            dia_semana=self.fecha.isoweekday(),
            hora_inicio=time(8, 0),
            hora_fin=time(22, 0),
            duracion_slot_minutos=60,
            activo=True
        )

    def crear_reserva(self):
        return crear_reserva_pendiente(
            usuario=self.usuario,
            cancha=self.cancha,
            fecha=self.fecha,
            hora_inicio=time(10, 0),
            hora_fin=time(11, 0)
        )

    def test_crear_reserva_pending_payment(self):
        reserva = self.crear_reserva()

        self.assertEqual(
            reserva.estado,
            "PENDING_PAYMENT"
        )

        self.assertEqual(
            reserva.precio,
            Decimal("120000.00")
        )

        self.assertEqual(
            reserva.abono_requerido,
            Decimal("36000.00")
        )

        self.assertEqual(
            reserva.saldo_pendiente,
            Decimal("84000.00")
        )

        self.assertIsNotNone(
            reserva.hold_expira_en
        )

    def test_no_permite_doble_reserva(self):
        self.crear_reserva()

        with self.assertRaises(ValidationError):
            crear_reserva_pendiente(
                usuario=self.usuario,
                cancha=self.cancha,
                fecha=self.fecha,
                hora_inicio=time(10, 0),
                hora_fin=time(11, 0)
            )

    def test_detecta_solapamiento_parcial(self):
        self.crear_reserva()

        with self.assertRaises(ValidationError):
            crear_reserva_pendiente(
                usuario=self.usuario,
                cancha=self.cancha,
                fecha=self.fecha,
                hora_inicio=time(10, 30),
                hora_fin=time(11, 30)
            )

    def test_permite_horarios_consecutivos(self):
        self.crear_reserva()

        segunda = crear_reserva_pendiente(
            usuario=self.usuario,
            cancha=self.cancha,
            fecha=self.fecha,
            hora_inicio=time(11, 0),
            hora_fin=time(12, 0)
        )

        self.assertEqual(
            segunda.estado,
            "PENDING_PAYMENT"
        )

    def test_pago_rejected_no_confirma(self):
        reserva = self.crear_reserva()

        pago = procesar_pago_simulado(
            reserva,
            "REJECTED"
        )

        reserva.refresh_from_db()

        self.assertEqual(
            pago.estado,
            "REJECTED"
        )

        self.assertEqual(
            reserva.estado,
            "PENDING_PAYMENT"
        )

        self.assertEqual(
            reserva.pagos.count(),
            1
        )

    def test_pago_approved_confirma_reserva(self):
        reserva = self.crear_reserva()

        pago = procesar_pago_simulado(
            reserva,
            "APPROVED"
        )

        reserva.refresh_from_db()

        self.assertEqual(
            pago.estado,
            "APPROVED"
        )

        self.assertEqual(
            reserva.estado,
            "CONFIRMED"
        )

        self.assertIsNone(
            reserva.hold_expira_en
        )

    def test_rejected_y_reintento_approved(self):
        reserva = self.crear_reserva()

        pago1 = procesar_pago_simulado(
            reserva,
            "REJECTED"
        )

        reserva.refresh_from_db()

        pago2 = procesar_pago_simulado(
            reserva,
            "APPROVED"
        )

        reserva.refresh_from_db()

        self.assertEqual(
            pago1.estado,
            "REJECTED"
        )

        self.assertEqual(
            pago2.estado,
            "APPROVED"
        )

        self.assertEqual(
            reserva.estado,
            "CONFIRMED"
        )

        self.assertEqual(
            reserva.pagos.count(),
            2
        )

    def test_reserva_expirada_libera_horario(self):
        reserva = self.crear_reserva()

        reserva.hold_expira_en = (
            timezone.now()
            - timedelta(minutes=1)
        )

        reserva.save()

        cantidad = expirar_reservas_pendientes()

        reserva.refresh_from_db()

        self.assertGreaterEqual(
            cantidad,
            1
        )

        self.assertEqual(
            reserva.estado,
            "EXPIRED"
        )

        slots = obtener_disponibilidad(
            self.cancha,
            self.fecha
        )

        horario_disponible = any(
            slot["hora_inicio"] == time(10, 0)
            and slot["hora_fin"] == time(11, 0)
            for slot in slots
        )

        self.assertTrue(
            horario_disponible
        )

    def test_cancelar_reserva_libera_horario(self):
        reserva = self.crear_reserva()

        procesar_pago_simulado(
            reserva,
            "APPROVED"
        )

        reserva.refresh_from_db()

        self.assertEqual(
            reserva.estado,
            "CONFIRMED"
        )

        cancelar_reserva(
            reserva
        )

        reserva.refresh_from_db()

        self.assertEqual(
            reserva.estado,
            "CANCELLED"
        )

        self.assertIsNotNone(
            reserva.fecha_cancelacion
        )

        slots = obtener_disponibilidad(
            self.cancha,
            self.fecha
        )

        horario_disponible = any(
            slot["hora_inicio"] == time(10, 0)
            and slot["hora_fin"] == time(11, 0)
            for slot in slots
        )

        self.assertTrue(
            horario_disponible
        )

    def test_no_permite_pagar_reserva_confirmada_dos_veces(self):
        reserva = self.crear_reserva()

        procesar_pago_simulado(
            reserva,
            "APPROVED"
        )

        reserva.refresh_from_db()

        with self.assertRaises(ValidationError):
            procesar_pago_simulado(
                reserva,
                "APPROVED"
            )

    def test_conflicto_cuando_nueva_empieza_antes(self):
        self.crear_reserva()

        with self.assertRaises(ValidationError):
            crear_reserva_pendiente(
                usuario=self.usuario,
                cancha=self.cancha,
                fecha=self.fecha,
                hora_inicio=time(9, 30),
                hora_fin=time(10, 30)
            )


    def test_conflicto_cuando_nueva_envuelve_existente(self):
        self.crear_reserva()

        with self.assertRaises(ValidationError):
            crear_reserva_pendiente(
                usuario=self.usuario,
                cancha=self.cancha,
                fecha=self.fecha,
                hora_inicio=time(9, 30),
                hora_fin=time(11, 30)
            )


    def test_permite_horario_justo_antes(self):
        self.crear_reserva()

        reserva_anterior = crear_reserva_pendiente(
            usuario=self.usuario,
            cancha=self.cancha,
            fecha=self.fecha,
            hora_inicio=time(9, 0),
            hora_fin=time(10, 0)
        )

        self.assertEqual(
            reserva_anterior.estado,
            "PENDING_PAYMENT"
        )


    def test_misma_hora_en_otra_cancha_es_permitida(self):
        otra_cancha = Cancha.objects.create(
            venue=self.venue,
            nombre="Cancha Test 2",
            descripcion="Segunda cancha para pruebas",
            precio_hora=Decimal("120000.00"),
            activa=True
        )

        Horario.objects.create(
            cancha=otra_cancha,
            dia_semana=self.fecha.isoweekday(),
            hora_inicio=time(8, 0),
            hora_fin=time(22, 0),
            duracion_slot_minutos=60,
            activo=True
        )

        self.crear_reserva()

        segunda_reserva = crear_reserva_pendiente(
            usuario=self.usuario,
            cancha=otra_cancha,
            fecha=self.fecha,
            hora_inicio=time(10, 0),
            hora_fin=time(11, 0)
        )

        self.assertEqual(
            segunda_reserva.estado,
            "PENDING_PAYMENT"
        )