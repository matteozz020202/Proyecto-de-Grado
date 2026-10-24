from datetime import time,timedelta
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from courts.models import Venue,Court,CourtSchedule
from .models import Reservation


class AdminManualTests(TestCase):
    def setUp(self):
        U=get_user_model()
        self.admin=U.objects.create_user(username='operator',is_staff=True)
        self.user=U.objects.create_user(username='lui2016',first_name='Luisa',last_name='Gallego',email='lui@example.test')
        self.inactive=U.objects.create_user(username='luisa_inactive',is_active=False)
        self.client.force_login(self.admin)
        self.search=reverse('reservations:admin_buscar_usuarios')
        self.url=reverse('reservations:admin_crear_reserva')
        venue=Venue.objects.create(venue_name='Arena',manager=self.admin)
        self.court=Court.objects.create(venue=venue,court_name='Cancha',price_per_hour=130000)
        self.day=timezone.localdate()+timedelta(days=7)
        CourtSchedule.objects.create(court=self.court,day_of_week=self.day.isoweekday(),start_time=time(8),end_time=time(22))
        self.data={"tipo_cliente":"REGISTERED",'usuario':str(self.user.pk),'cancha':str(self.court.pk),'fecha':self.day.isoformat(),'hora_inicio':'18:00','hora_fin':'19:00'}

    def test_search_matches_fields_case_insensitively_and_returns_only_public_profile_fields(self):
        for query in ['LUI201','luISA','GALLEGO','EXAMPLE.test']:
            response=self.client.get(self.search,{'q':query})
            self.assertEqual(response.status_code,200)
            self.assertIn('no-store',response.headers['Cache-Control'])
            self.assertEqual(response.json()['results'],[{'id':self.user.pk,'username':'lui2016','name':'Luisa Gallego','email':'lui@example.test'}])
        self.assertEqual(self.client.get(self.search,{'q':'l'}).json(),{'results':[]})
        self.assertEqual(self.client.get(self.search,{'q':'luisa_inactive'}).json(),{'results':[]})

    def test_search_is_limited_and_admin_only(self):
        U=get_user_model()
        for n in range(12):U.objects.create_user(username=f'match{n:02}')
        self.assertEqual(len(self.client.get(self.search,{'q':'match'}).json()['results']),10)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(self.search,{'q':'luisa'}).status_code,302)
        self.client.logout()
        self.assertEqual(self.client.get(self.search,{'q':'luisa'}).status_code,302)
        group,_=Group.objects.get_or_create(name='Administrador');self.user.groups.add(group)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(self.search,{'q':'luisa'}).status_code,200)

    def test_creation_uses_selected_user_and_remains_confirmed(self):
        response=self.client.post(self.url,self.data)
        self.assertRedirects(response,reverse('reservations:admin_reservas'))
        reservation=Reservation.objects.get()
        self.assertEqual(reservation.user,self.user)
        self.assertEqual(reservation.reservation_status,'CONFIRMED')
        self.assertIsNone(reservation.hold_expires_at)
        self.client.post(self.url,self.data)
        self.assertEqual(Reservation.objects.count(),1)

    def test_invalid_identity_and_missing_fields_are_rejected(self):
        for identity in ['', 'texto libre',str(self.inactive.pk),'9'*100,'999999']:
            response=self.client.post(self.url,{**self.data,'usuario':identity})
            self.assertEqual(response.status_code,200)
        self.assertFalse(Reservation.objects.exists())

    def test_error_preserves_selection_and_business_rules(self):
        for changes in [{'hora_inicio':'22:00','hora_fin':'23:00'},{'hora_inicio':'19:00','hora_fin':'18:00'},{'fecha':(timezone.localdate()-timedelta(days=1)).isoformat()}]:
            response=self.client.post(self.url,{**self.data,**changes})
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.context['usuario_objeto'],self.user)
            self.assertContains(response,'lui2016')
        self.assertFalse(Reservation.objects.exists())
