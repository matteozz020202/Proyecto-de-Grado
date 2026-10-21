from datetime import datetime, time, timedelta
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from courts.models import Venue, Court, CourtSchedule
from .models import Payment, Reservation

from .services import (
    cancel_reservation,
    create_pending_reservation,
    expire_pending_reservations,
    get_availability,
    process_simulated_payment,
)


class ReservationFlowTests(TestCase):

    def setUp(self):
        # Usuario de prueba
        self.user = User.objects.create_user(
            username="usuario_test",
            password="Test12345!"
        )

        # Establecimiento
        self.venue = Venue.objects.create(
            venue_name="Complejo Test",
            city="Barranquilla",
            address="Calle 1 # 1-1",
            deposit_percentage=Decimal("30.00"),
            is_active=True
        )

        # Cancha
        self.court = Court.objects.create(
            venue=self.venue,
            court_name="Cancha Test",
            price_per_hour=Decimal("120000.00"),
            is_active=True,
            description="Cancha para pruebas"
        )

        # Fecha futura
        self.reservation_date = (
            timezone.localdate()
            + timedelta(days=7)
        )

        # Horario correspondiente al día elegido
        CourtSchedule.objects.create(
            court=self.court,
            day_of_week=self.reservation_date.isoweekday(),
            start_time=time(8, 0),
            end_time=time(22, 0),
            slot_duration_minutes=60,
            is_active=True
        )

    def create_reservation(self):
        return create_pending_reservation(
            user=self.user,
            court=self.court,
            reservation_date=self.reservation_date,
            start_time=time(10, 0),
            end_time=time(11, 0)
        )

    def test_create_pending_payment_reservation(self):
        reservation = self.create_reservation()

        self.assertEqual(
            reservation.reservation_status,
            "PENDING_PAYMENT"
        )

        self.assertEqual(
            reservation.total_amount,
            Decimal("120000.00")
        )

        self.assertEqual(
            reservation.deposit_required,
            Decimal("36000.00")
        )

        self.assertEqual(
            reservation.remaining_amount,
            Decimal("84000.00")
        )

        self.assertIsNotNone(
            reservation.hold_expires_at
        )

    def test_duplicate_reservation_is_rejected(self):
        self.create_reservation()

        with self.assertRaises(ValidationError):
            create_pending_reservation(
                user=self.user,
                court=self.court,
                reservation_date=self.reservation_date,
                start_time=time(10, 0),
                end_time=time(11, 0)
            )

    def test_partial_overlap_is_rejected(self):
        self.create_reservation()

        with self.assertRaises(ValidationError):
            create_pending_reservation(
                user=self.user,
                court=self.court,
                reservation_date=self.reservation_date,
                start_time=time(10, 30),
                end_time=time(11, 30)
            )

    def test_consecutive_time_slot_is_allowed(self):
        self.create_reservation()

        second_reservation = create_pending_reservation(
            user=self.user,
            court=self.court,
            reservation_date=self.reservation_date,
            start_time=time(11, 0),
            end_time=time(12, 0)
        )

        self.assertEqual(
            second_reservation.reservation_status,
            "PENDING_PAYMENT"
        )

    def test_rejected_payment_does_not_confirm(self):
        reservation = self.create_reservation()

        payment = process_simulated_payment(
            reservation,
            "REJECTED"
        )

        reservation.refresh_from_db()

        self.assertEqual(
            payment.payment_status,
            "REJECTED"
        )

        self.assertEqual(
            reservation.reservation_status,
            "PENDING_PAYMENT"
        )

        self.assertEqual(
            reservation.payments.count(),
            1
        )

    def test_approved_payment_confirms_reservation(self):
        reservation = self.create_reservation()

        payment = process_simulated_payment(
            reservation,
            "APPROVED"
        )

        reservation.refresh_from_db()

        self.assertEqual(
            payment.payment_status,
            "APPROVED"
        )

        self.assertEqual(
            reservation.reservation_status,
            "CONFIRMED"
        )

        self.assertIsNone(
            reservation.hold_expires_at
        )

    def test_rejected_then_approved_retry(self):
        reservation = self.create_reservation()

        payment_1 = process_simulated_payment(
            reservation,
            "REJECTED"
        )

        reservation.refresh_from_db()

        payment_2 = process_simulated_payment(
            reservation,
            "APPROVED"
        )

        reservation.refresh_from_db()

        self.assertEqual(
            payment_1.payment_status,
            "REJECTED"
        )

        self.assertEqual(
            payment_2.payment_status,
            "APPROVED"
        )

        self.assertEqual(
            reservation.reservation_status,
            "CONFIRMED"
        )

        self.assertEqual(
            reservation.payments.count(),
            2
        )

    def test_expired_reservation_releases_time_slot(self):
        reservation = self.create_reservation()

        reservation.hold_expires_at = (
            timezone.now()
            - timedelta(minutes=1)
        )

        reservation.save()

        count = expire_pending_reservations()

        reservation.refresh_from_db()

        self.assertGreaterEqual(
            count,
            1
        )

        self.assertEqual(
            reservation.reservation_status,
            "EXPIRED"
        )

        slots = get_availability(
            self.court,
            self.reservation_date
        )

        time_slot_available = any(
            slot["start_time"] == time(10, 0)
            and slot["end_time"] == time(11, 0)
            for slot in slots
        )

        self.assertTrue(
            time_slot_available
        )

    def test_cancelled_reservation_releases_time_slot(self):
        reservation = self.create_reservation()

        process_simulated_payment(
            reservation,
            "APPROVED"
        )

        reservation.refresh_from_db()

        self.assertEqual(
            reservation.reservation_status,
            "CONFIRMED"
        )

        cancel_reservation(
            reservation
        )

        reservation.refresh_from_db()

        self.assertEqual(
            reservation.reservation_status,
            "CANCELLED"
        )

        self.assertIsNotNone(
            reservation.cancelled_at
        )

        slots = get_availability(
            self.court,
            self.reservation_date
        )

        time_slot_available = any(
            slot["start_time"] == time(10, 0)
            and slot["end_time"] == time(11, 0)
            for slot in slots
        )

        self.assertTrue(
            time_slot_available
        )

    def test_confirmed_reservation_cannot_be_paid_twice(self):
        reservation = self.create_reservation()

        process_simulated_payment(
            reservation,
            "APPROVED"
        )

        reservation.refresh_from_db()

        with self.assertRaises(ValidationError):
            process_simulated_payment(
                reservation,
                "APPROVED"
            )

    def test_conflict_when_new_reservation_starts_before_existing(self):
        self.create_reservation()

        with self.assertRaises(ValidationError):
            create_pending_reservation(
                user=self.user,
                court=self.court,
                reservation_date=self.reservation_date,
                start_time=time(9, 30),
                end_time=time(10, 30)
            )

    def test_conflict_when_new_reservation_wraps_existing(self):
        self.create_reservation()

        with self.assertRaises(ValidationError):
            create_pending_reservation(
                user=self.user,
                court=self.court,
                reservation_date=self.reservation_date,
                start_time=time(9, 30),
                end_time=time(11, 30)
            )

    def test_time_slot_immediately_before_is_allowed(self):
        self.create_reservation()

        previous_reservation = create_pending_reservation(
            user=self.user,
            court=self.court,
            reservation_date=self.reservation_date,
            start_time=time(9, 0),
            end_time=time(10, 0)
        )

        self.assertEqual(
            previous_reservation.reservation_status,
            "PENDING_PAYMENT"
        )

    def test_same_time_on_different_court_is_allowed(self):
        second_court = Court.objects.create(
            venue=self.venue,
            court_name="Cancha Test 2",
            price_per_hour=Decimal("120000.00"),
            is_active=True,
            description="Segunda cancha para pruebas"
        )

        CourtSchedule.objects.create(
            court=second_court,
            day_of_week=self.reservation_date.isoweekday(),
            start_time=time(8, 0),
            end_time=time(22, 0),
            slot_duration_minutes=60,
            is_active=True
        )

        self.create_reservation()

        second_reservation = create_pending_reservation(
            user=self.user,
            court=second_court,
            reservation_date=self.reservation_date,
            start_time=time(10, 0),
            end_time=time(11, 0)
        )

        self.assertEqual(
            second_reservation.reservation_status,
            "PENDING_PAYMENT"
        )

    def test_booking_30_minutes_ahead_is_rejected(self):
        fixed_now = timezone.make_aware(
            datetime.combine(
                self.reservation_date,
                time(18, 0)
            ),
            timezone.get_current_timezone()
        )

        with patch(
            "reservations.services.timezone.now",
            return_value=fixed_now
        ):
            with self.assertRaises(ValidationError):
                create_pending_reservation(
                    user=self.user,
                    court=self.court,
                    reservation_date=self.reservation_date,
                    start_time=time(18, 30),
                    end_time=time(19, 30)
                )

    def test_booking_59_minutes_ahead_is_rejected(self):
        fixed_now = timezone.make_aware(
            datetime.combine(
                self.reservation_date,
                time(18, 0)
            ),
            timezone.get_current_timezone()
        )

        with patch(
            "reservations.services.timezone.now",
            return_value=fixed_now
        ):
            with self.assertRaises(ValidationError):
                create_pending_reservation(
                    user=self.user,
                    court=self.court,
                    reservation_date=self.reservation_date,
                    start_time=time(18, 59),
                    end_time=time(19, 59)
                )

    def test_booking_exactly_one_hour_ahead_is_allowed(self):
        fixed_now = timezone.make_aware(
            datetime.combine(
                self.reservation_date,
                time(18, 0)
            ),
            timezone.get_current_timezone()
        )

        with patch(
            "reservations.services.timezone.now",
            return_value=fixed_now
        ):
            reservation = create_pending_reservation(
                user=self.user,
                court=self.court,
                reservation_date=self.reservation_date,
                start_time=time(19, 0),
                end_time=time(20, 0)
            )

        self.assertEqual(
            reservation.reservation_status,
            "PENDING_PAYMENT"
        )

    def test_booking_two_hours_ahead_is_allowed(self):
        fixed_now = timezone.make_aware(
            datetime.combine(
                self.reservation_date,
                time(18, 0)
            ),
            timezone.get_current_timezone()
        )

        with patch(
            "reservations.services.timezone.now",
            return_value=fixed_now
        ):
            reservation = create_pending_reservation(
                user=self.user,
                court=self.court,
                reservation_date=self.reservation_date,
                start_time=time(20, 0),
                end_time=time(21, 0)
            )

        self.assertEqual(
            reservation.reservation_status,
            "PENDING_PAYMENT"
        )


class AdminDashboardTests(TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 30, 12, 0, tzinfo=ZoneInfo("America/Bogota"))
        clock = patch("django.utils.timezone.now", return_value=self.now)
        clock.start()
        self.addCleanup(clock.stop)
        self.user = User.objects.create_user(username="cliente")
        self.admin = User.objects.create_user(username="admin", is_staff=True)
        self.venue = Venue.objects.create(
            venue_name="Test",
            address="Calle 1",
            manager=self.admin
        )
        self.court = Court.objects.create(
            venue=self.venue, court_name="Cancha", price_per_hour=120000
        )
        self.url = reverse("reservations:admin_dashboard")
        self.client.force_login(self.admin)

    def reservation(self, hour=13, days=0, status="CONFIRMED", source="SYSTEM", **kwargs):
        return Reservation.objects.create(
            user=self.user, court=self.court,
            reservation_date=self.now.date() + timedelta(days=days),
            start_time=time(hour), end_time=time(hour + 1),
            total_amount=120000, deposit_required=36000, remaining_amount=84000,
            reservation_status=status, data_source=source, **kwargs,
        )

    def test_access_requires_login_and_admin_role(self):
        self.client.logout()
        self.assertRedirects(self.client.get(self.url),
                             reverse("users:login") + "?next=" + self.url)
        self.client.force_login(self.user)
        self.assertRedirects(self.client.get(self.url), reverse("users:home"))
        group = Group.objects.create(name="Administrador")
        self.user.groups.add(group)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.user.groups.clear()
        self.user.is_superuser = True
        self.user.save()
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_dashboard_no_longer_contains_reservation_table(self):
        self.reservation(hour=10)
        response=self.client.get(self.url,{"tipo":"FUTURE","fecha_inicio":self.now.date().isoformat(),"fecha_fin":(self.now.date()+timedelta(days=1)).isoformat()})
        self.assertEqual(response.status_code,200)
        self.assertNotContains(response,'id="reservas-administrativas"')

    def test_source_filter_applies_to_counts_and_payments(self):
        system = self.reservation()
        synthetic = self.reservation(hour=14, source="SYNTHETIC")
        for reservation, amount, status, ref in [
            (system, 36000, "APPROVED", "system"),
            (system, 9000, "REJECTED", "rejected"),
            (synthetic, 72000, "APPROVED", "synthetic"),
        ]:
            Payment.objects.create(reservation=reservation, amount=amount,
                                   payment_status=status, transaction_reference=ref)
        for source,count,income in [(None,1,36000),("SYNTHETIC",1,72000),("ALL",2,108000),("invalid",1,36000)]:
            with self.subTest(source=source):
                response = self.client.get(self.url, {} if source is None else {"origen": source})
                self.assertEqual(response.context["confirmadas"], count)
                self.assertEqual(response.context["reservas_hoy"], count)
                self.assertEqual(response.context["ingresos_aprobados"], Decimal(income))
                self.assertEqual(response.context["pagos_aprobados"], count)

    def test_expired_holds_are_not_counted_as_pending(self):
        expired = self.reservation(status="PENDING_PAYMENT",
                                   hold_expires_at=self.now - timedelta(minutes=1))
        self.reservation(hour=14, status="PENDING_PAYMENT",
                         hold_expires_at=self.now + timedelta(minutes=15))
        response = self.client.get(self.url)
        expired.refresh_from_db()
        self.assertEqual(expired.reservation_status, "EXPIRED")
        self.assertEqual(response.context["pendientes_pago"], 1)
        self.assertEqual(response.context["reservas_hoy"], 1)

    def test_empty_dashboard_and_navigation(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["ingresos_aprobados"], 0)
        self.assertContains(response, "reservas del período")
        home = self.client.get(reverse("users:home"))
        self.assertContains(home, self.url)

    def test_reservations_page_is_not_limited_to_eight(self):
        reservations=[self.reservation(hour=hour) for hour in range(13,23)]
        response=self.client.get(reverse("reservations:admin_reservas"))
        page=response.context["pagina_reservas"]
        self.assertEqual(response.status_code,200)
        self.assertEqual(page.paginator.count,10)
        self.assertEqual(list(page),list(reversed(reservations)))

class AdminManualReservationTests(TestCase):
    def setUp(self):
        self.admin=User.objects.create_user(username="admin_manual",password="Test12345!",is_staff=True)
        self.client_user=User.objects.create_user(username="cliente_manual",password="Test12345!")
        self.venue=Venue.objects.create(venue_name="Complejo Manual",address="Calle 1",manager=self.admin,deposit_percentage=Decimal("30.00"),is_active=True)
        self.court=Court.objects.create(venue=self.venue,court_name="Cancha Manual",price_per_hour=Decimal("120000.00"),is_active=True)
        self.date=timezone.localdate()+timedelta(days=7)
        CourtSchedule.objects.create(court=self.court,day_of_week=self.date.isoweekday(),start_time=time(8),end_time=time(22),slot_duration_minutes=60,is_active=True)
        self.url=reverse("reservations:admin_crear_reserva")
        self.client.force_login(self.admin)

    def data(self,**kwargs):
        data={"tipo_cliente":"REGISTERED","usuario":str(self.client_user.pk),"cancha":str(self.court.pk),"fecha":self.date.isoformat(),"hora_inicio":"10:00","hora_fin":"11:00"}
        data.update(kwargs)
        return data

    def test_registered_client_creates_confirmed_reservation_without_fake_payment(self):
        response=self.client.post(self.url,self.data())
        reservation=Reservation.objects.get()
        self.assertRedirects(response,reverse("reservations:admin_reservas"))
        self.assertEqual(reservation.user,self.client_user)
        self.assertEqual(reservation.reservation_status,"CONFIRMED")
        self.assertIsNone(reservation.hold_expires_at)
        self.assertEqual(reservation.payments.count(),0)

    def test_guest_client_creates_confirmed_reservation(self):
        response=self.client.post(self.url,self.data(tipo_cliente="GUEST",usuario="",guest_name="Juan Pérez",guest_phone="3001234567"))
        reservation=Reservation.objects.get()
        self.assertRedirects(response,reverse("reservations:admin_reservas"))
        self.assertIsNone(reservation.user)
        self.assertEqual(reservation.guest_name,"Juan Pérez")
        self.assertEqual(reservation.guest_phone,"3001234567")
        self.assertEqual(reservation.reservation_status,"CONFIRMED")
        self.assertEqual(reservation.payments.count(),0)

    def test_overlapping_manual_reservation_is_rejected(self):
        self.client.post(self.url,self.data())
        response=self.client.post(self.url,self.data(usuario=str(self.client_user.pk)))
        self.assertEqual(response.status_code,200)
        self.assertEqual(Reservation.objects.count(),1)

    def test_admin_cannot_create_reservation_on_foreign_court(self):
        other=User.objects.create_user(username="other_admin",is_staff=True)
        venue=Venue.objects.create(venue_name="Complejo Ajeno",address="Calle 2",manager=other,deposit_percentage=Decimal("30.00"),is_active=True)
        court=Court.objects.create(venue=venue,court_name="Cancha Ajena",price_per_hour=Decimal("100000.00"),is_active=True)
        CourtSchedule.objects.create(court=court,day_of_week=self.date.isoweekday(),start_time=time(8),end_time=time(22),slot_duration_minutes=60,is_active=True)
        response=self.client.post(self.url,self.data(cancha=str(court.pk)))
        self.assertEqual(response.status_code,200)
        self.assertFalse(Reservation.objects.filter(court=court).exists())

class AdminCompleteReservationTests(TestCase):
    def setUp(self):
        self.admin=User.objects.create_user(username="admin_complete",is_staff=True)
        self.user=User.objects.create_user(username="cliente_complete")
        self.venue=Venue.objects.create(venue_name="Complejo Complete",address="Calle 1",manager=self.admin)
        self.court=Court.objects.create(venue=self.venue,court_name="Cancha Complete",price_per_hour=Decimal("120000.00"))
        self.client.force_login(self.admin)

    def reservation(self,status="CONFIRMED",court=None):
        return Reservation.objects.create(user=self.user,court=court or self.court,reservation_date=timezone.localdate()+timedelta(days=1),start_time=time(10),end_time=time(11),total_amount=120000,deposit_required=36000,remaining_amount=84000,reservation_status=status)

    def test_confirmed_reservation_can_be_completed(self):
        reservation=self.reservation()
        response=self.client.post(reverse("reservations:admin_detalle_reserva",args=[reservation.pk]),{"action":"complete"})
        reservation.refresh_from_db()
        self.assertRedirects(response,reverse("reservations:admin_detalle_reserva",args=[reservation.pk]))
        self.assertEqual(reservation.reservation_status,"COMPLETED")

    def test_non_confirmed_reservation_cannot_be_completed(self):
        reservation=self.reservation("CANCELLED")
        self.client.post(reverse("reservations:admin_detalle_reserva",args=[reservation.pk]),{"action":"complete"})
        reservation.refresh_from_db()
        self.assertEqual(reservation.reservation_status,"CANCELLED")

    def test_admin_cannot_complete_foreign_reservation(self):
        other=User.objects.create_user(username="other_complete",is_staff=True)
        venue=Venue.objects.create(venue_name="Complejo Ajeno",address="Calle 2",manager=other)
        court=Court.objects.create(venue=venue,court_name="Cancha Ajena",price_per_hour=Decimal("100000.00"))
        reservation=self.reservation(court=court)
        response=self.client.post(reverse("reservations:admin_detalle_reserva",args=[reservation.pk]),{"action":"complete"})
        reservation.refresh_from_db()
        self.assertEqual(response.status_code,404)
        self.assertEqual(reservation.reservation_status,"CONFIRMED")

class AdminCancelReservationTests(TestCase):
    def setUp(self):
        self.admin=User.objects.create_user(username="admin_cancel",is_staff=True)
        self.user=User.objects.create_user(username="cliente_cancel")
        self.venue=Venue.objects.create(venue_name="Complejo Cancel",address="Calle 1",manager=self.admin)
        self.court=Court.objects.create(venue=self.venue,court_name="Cancha Cancel",price_per_hour=Decimal("120000.00"))
        self.client.force_login(self.admin)

    def reservation(self,status="CONFIRMED",court=None):
        return Reservation.objects.create(user=self.user,court=court or self.court,reservation_date=timezone.localdate()+timedelta(days=1),start_time=time(10),end_time=time(11),total_amount=120000,deposit_required=36000,remaining_amount=84000,reservation_status=status,hold_expires_at=timezone.now()+timedelta(minutes=15))

    def test_confirmed_reservation_can_be_cancelled(self):
        reservation=self.reservation()
        response=self.client.post(reverse("reservations:admin_detalle_reserva",args=[reservation.pk]),{"action":"cancel"})
        reservation.refresh_from_db()
        self.assertRedirects(response,reverse("reservations:admin_detalle_reserva",args=[reservation.pk]))
        self.assertEqual(reservation.reservation_status,"CANCELLED")
        self.assertIsNotNone(reservation.cancelled_at)
        self.assertIsNone(reservation.hold_expires_at)

    def test_non_confirmed_reservation_cannot_be_cancelled(self):
        reservation=self.reservation("COMPLETED")
        self.client.post(reverse("reservations:admin_detalle_reserva",args=[reservation.pk]),{"action":"cancel"})
        reservation.refresh_from_db()
        self.assertEqual(reservation.reservation_status,"COMPLETED")

    def test_admin_cannot_cancel_foreign_reservation(self):
        other=User.objects.create_user(username="other_cancel",is_staff=True)
        venue=Venue.objects.create(venue_name="Complejo Ajeno Cancel",address="Calle 2",manager=other)
        court=Court.objects.create(venue=venue,court_name="Cancha Ajena",price_per_hour=Decimal("100000.00"))
        reservation=self.reservation(court=court)
        response=self.client.post(reverse("reservations:admin_detalle_reserva",args=[reservation.pk]),{"action":"cancel"})
        reservation.refresh_from_db()
        self.assertEqual(response.status_code,404)
        self.assertEqual(reservation.reservation_status,"CONFIRMED")

    def test_confirmed_detail_shows_safe_action_buttons(self):
        reservation=self.reservation()
        response=self.client.get(reverse("reservations:admin_detalle_reserva",args=[reservation.pk]))
        self.assertContains(response,"Marcar como completada")
        self.assertContains(response,"Cancelar reserva")
        self.assertContains(response,"return confirm(")

    def test_non_confirmed_detail_hides_action_buttons(self):
        reservation=self.reservation("COMPLETED")
        response=self.client.get(reverse("reservations:admin_detalle_reserva",args=[reservation.pk]))
        self.assertNotContains(response,"Marcar como completada")
        self.assertNotContains(response,"Cancelar reserva")