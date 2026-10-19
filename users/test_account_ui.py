from datetime import time,timedelta
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from courts.models import Court,Venue
from reservations.models import Reservation
from .templatetags.account_display import initials


class AccountPresentationTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_user(username='luisa',first_name='Luisa',last_name='Gallego',email='luisa@example.test')
        self.client.force_login(self.user)

    def test_profile_has_existing_fields_initials_and_active_nav(self):
        response=self.client.get(reverse('users:profile'))
        self.assertContains(response,'LG')
        self.assertContains(response,'Cuenta activa')
        self.assertContains(response,'value="luisa" readonly')
        self.assertContains(response,'value="luisa@example.test"')
        self.assertContains(response,reverse('users:password_change'))
        self.assertContains(response,'href="/perfil/" aria-current="page"')
        self.assertNotContains(response,'>Inicio</a>\n')
        self.user.first_name='Luisa Gallego';self.user.last_name=''
        self.assertEqual(initials(self.user),'LG')
        self.user.first_name=''
        self.assertEqual(initials(self.user),'LU')

    def test_all_statuses_render_and_cancel_only_for_confirmed(self):
        venue=Venue.objects.create(venue_name='Arena')
        court=Court.objects.create(venue=venue,court_name='Cancha',price_per_hour=130000)
        for offset,status in enumerate(['CONFIRMED','COMPLETED','CANCELLED','EXPIRED']):
            Reservation.objects.create(user=self.user,court=court,reservation_date=timezone.localdate()+timedelta(days=offset+1),start_time=time(18),end_time=time(19),total_amount=130000,reservation_status=status)
        response=self.client.get(reverse('reservations:mis_reservas'))
        for label in ['Confirmada','Completada','Cancelada','Expirada','Próxima','Historial']:
            self.assertContains(response,label)
        self.assertContains(response,'Cancelar reserva</button>',count=1)
        self.assertContains(response,'$130.000',count=4)
        self.assertContains(response,'Imagen no disponible',count=4)
        self.assertContains(response,'href="/reservas/mis-reservas/" aria-current="page"')

    def test_empty_state_has_catalog_link(self):
        response=self.client.get(reverse('reservations:mis_reservas'))
        self.assertContains(response,'Aún no tienes reservas.')
        self.assertContains(response,'Explorar establecimientos')
