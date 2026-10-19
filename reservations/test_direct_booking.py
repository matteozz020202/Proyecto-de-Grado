from datetime import time,timedelta
from django.contrib.auth import get_user_model
from django.test import TestCase,Client
from django.urls import reverse
from django.utils import timezone
from courts.models import Court,CourtSchedule,Venue
from .models import Reservation,Payment
from .services import create_pending_reservation,expire_pending_reservations


class DirectBookingTests(TestCase):
    def setUp(self):
        U=get_user_model()
        self.user=U.objects.create_user(username='booker')
        self.other=U.objects.create_user(username='other')
        self.client.force_login(self.user)
        self.venue=Venue.objects.create(venue_name='Arena',deposit_percentage=30)
        self.court=Court.objects.create(venue=self.venue,court_name='Cancha',price_per_hour=130000)
        self.day=timezone.localdate()+timedelta(days=7)
        CourtSchedule.objects.create(court=self.court,day_of_week=self.day.isoweekday(),start_time=time(8),end_time=time(22))
        self.url=reverse('reservations:resumen_reserva',args=[self.court.pk])
        self.data={'fecha':self.day.isoformat(),'inicio':'18:00','fin':'19:00'}

    def test_review_get_does_not_create_reservation(self):
        response=self.client.get(self.url,self.data)
        self.assertContains(response,'Revisa tu reserva')
        self.assertContains(response,'Confirmar y reservar')
        self.assertContains(response,'$130.000')
        self.assertNotContains(response,'Saldo pendiente')
        self.assertNotContains(response,'15 minutos')
        self.assertFalse(Reservation.objects.exists())

    def test_post_confirms_without_payment_and_refresh_is_safe(self):
        response=self.client.post(self.url,self.data)
        reservation=Reservation.objects.get()
        self.assertEqual(reservation.user,self.user)
        self.assertEqual(reservation.reservation_status,'CONFIRMED')
        self.assertIsNone(reservation.hold_expires_at)
        self.assertEqual(reservation.total_amount,130000)
        self.assertEqual(reservation.deposit_required,0)
        self.assertEqual(reservation.remaining_amount,130000)
        self.assertFalse(Payment.objects.exists())
        target=reverse('reservations:reserva_confirmada',args=[reservation.pk])
        self.assertRedirects(response,target)
        self.assertContains(self.client.get(target),'¡Reserva confirmada!')
        self.assertContains(self.client.get(target),'pagos y abonos')
        self.client.get(target)
        self.client.post(self.url,self.data)
        self.assertEqual(Reservation.objects.count(),1)
        expire_pending_reservations()
        reservation.refresh_from_db()
        self.assertEqual(reservation.reservation_status,'CONFIRMED')
        mine=self.client.get(reverse('reservations:mis_reservas'))
        self.assertContains(mine,f'Reserva #{reservation.pk}')
        self.assertNotContains(mine,'reintentar abono')

    def test_conflict_cannot_create_second_reservation(self):
        create_pending_reservation(user=self.other,court=self.court,reservation_date=self.day,start_time=time(18),end_time=time(19))
        response=self.client.post(self.url,self.data)
        self.assertEqual(response.status_code,302)
        self.assertIn('disponibilidad',response.url)
        self.assertEqual(Reservation.objects.count(),1)

    def test_confirmation_is_private_and_only_for_confirmed_reservation(self):
        self.client.post(self.url,self.data)
        reservation=Reservation.objects.get()
        url=reverse('reservations:reserva_confirmada',args=[reservation.pk])
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code,404)
        self.client.force_login(self.user)
        reservation.reservation_status='CANCELLED';reservation.save()
        self.assertEqual(self.client.get(url).status_code,404)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code,302)

    def test_advance_rule_invalid_dates_and_csrf_remain_protected(self):
        for changes in [{'fecha':(timezone.localdate()-timedelta(days=1)).isoformat()},{'inicio':'25:00'},{'inicio':'18:00','fin':'17:00'}]:
            self.assertEqual(self.client.post(self.url,{**self.data,**changes}).status_code,302)
        self.assertFalse(Reservation.objects.exists())
        client=Client(enforce_csrf_checks=True);client.force_login(self.user)
        self.assertEqual(client.post(self.url,self.data).status_code,403)
