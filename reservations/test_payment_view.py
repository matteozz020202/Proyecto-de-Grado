from datetime import time, timedelta
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from courts.models import Court, CourtSchedule, Venue
from .models import Payment
from .services import create_pending_reservation


class SimulatedPaymentViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="payer")
        self.client.force_login(self.user)
        venue = Venue.objects.create(venue_name="Test", deposit_percentage=30)
        self.court = Court.objects.create(venue=venue, court_name="Test court", price_per_hour=120000)
        day = timezone.localdate() + timedelta(days=7)
        CourtSchedule.objects.create(court=self.court, day_of_week=day.isoweekday(), start_time=time(8), end_time=time(22))
        self.reservation = create_pending_reservation(user=self.user,court=self.court,reservation_date=day,start_time=time(10),end_time=time(11))
        self.url = reverse("reservations:pagar_reserva", args=[self.reservation.pk])

    def test_approved_payment_confirms_and_displays_my_reservations(self):
        response = self.client.post(self.url, {"resultado":"APPROVED"}, follow=True)
        self.assertContains(response, "Abono aprobado.")
        self.reservation.refresh_from_db()
        self.assertEqual(self.reservation.reservation_status, "CONFIRMED")
        payment = Payment.objects.get(reservation=self.reservation)
        self.assertEqual(payment.payment_status,"APPROVED")
        self.assertEqual(payment.amount,36000)
        self.assertEqual(response.redirect_chain,[(reverse("reservations:mis_reservas"),302)])
        self.client.post(self.url, {"resultado":"APPROVED"})
        self.assertEqual(Payment.objects.filter(reservation=self.reservation).count(),1)

    def test_rejected_payment_can_be_retried(self):
        response = self.client.post(self.url, {"resultado":"REJECTED"}, follow=True)
        self.assertEqual(response.status_code,200)
        self.assertContains(response, "El pago fue rechazado.")
        self.reservation.refresh_from_db()
        self.assertEqual(self.reservation.reservation_status,"PENDING_PAYMENT")
        self.assertEqual(Payment.objects.get(reservation=self.reservation).payment_status,"REJECTED")
        self.client.post(self.url,{"resultado":"APPROVED"})
        self.reservation.refresh_from_db()
        self.assertEqual(self.reservation.reservation_status,"CONFIRMED")

    def test_invalid_result_creates_no_payment(self):
        self.assertRedirects(self.client.post(self.url,{"resultado":"INVALID"}),reverse("reservations:mis_reservas"))
        self.assertFalse(Payment.objects.exists())
