from datetime import time, timedelta
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from .models import Court, CourtSchedule, Venue
from reservations.services import calculate_reservation_values, create_pending_reservation
from django.contrib.auth import get_user_model


class AvailabilityPresentationTests(TestCase):
    def setUp(self):
        self.venue = Venue.objects.create(venue_name="Arena",city="Barranquilla",deposit_percentage=30)
        self.court = Court.objects.create(venue=self.venue,court_name="Cancha",price_per_hour=130000)
        self.day = timezone.localdate()+timedelta(days=7)
        self.schedule = CourtSchedule.objects.create(court=self.court,day_of_week=self.day.isoweekday(),start_time=time(8),end_time=time(12),slot_duration_minutes=60)
        self.url = reverse("courts:disponibilidad_cancha",args=[self.court.pk])

    def test_public_initial_state_and_navbar(self):
        response = self.client.get(self.url)
        self.assertContains(response,"Encuentra tu horario")
        self.assertContains(response,"Imagen no disponible")
        self.assertContains(response,"Establecimientos")
        self.assertContains(response,"Iniciar sesión")
        self.assertNotContains(response,">Inicio</a>")
        self.assertNotContains(response,">Registrarse</a>")
        self.assertNotContains(response,'class="time-slot"')

    def test_slot_values_reuse_service_and_preserve_booking_url(self):
        response = self.client.get(self.url,{"fecha":self.day.isoformat()})
        slot = response.context["slots"][0]
        self.assertEqual(slot["values"],calculate_reservation_values(self.court,self.day,slot["start_time"],slot["end_time"]))
        self.assertTrue(slot["one_hour"])
        self.assertContains(response,'data-total="$130.000"')
        self.assertContains(response,'data-deposit="$39.000"')
        self.assertContains(response,'inicio=08:00&amp;fin=09:00')
        self.assertContains(response,'class="booking-summary" hidden')

    def test_variable_duration_and_conflicts_remain_backend_driven(self):
        self.schedule.slot_duration_minutes=90
        self.schedule.save()
        response=self.client.get(self.url,{"fecha":self.day.isoformat()})
        slot=response.context["slots"][0]
        self.assertFalse(slot["one_hour"])
        self.assertContains(response,'data-total="$195.000"')
        self.assertContains(response,'data-deposit="$58.500"')
        user=get_user_model().objects.create_user(username="taken")
        create_pending_reservation(user=user,court=self.court,reservation_date=self.day,start_time=time(8),end_time=time(9,30))
        response=self.client.get(self.url,{"fecha":self.day.isoformat()})
        self.assertNotContains(response,'data-range="08:00 – 09:30"')
        self.assertContains(response,'data-range="09:30 – 11:00"')

    def test_invalid_past_and_empty_dates(self):
        for value in ['invalid',(timezone.localdate()-timedelta(days=1)).isoformat()]:
            response=self.client.get(self.url,{"fecha":value})
            self.assertIsNotNone(response.context["error"])
            self.assertNotContains(response,'class="time-slot"')
        self.schedule.is_active=False
        self.schedule.save()
        self.assertContains(self.client.get(self.url,{"fecha":self.day.isoformat()}),"No hay horarios disponibles para esta fecha.")
