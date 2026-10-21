from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse
from courts.models import Venue


class AdminProfileTests(TestCase):
    def setUp(self):
        U=get_user_model()
        self.admin=U.objects.create_user(username='admin_demo',password='Test!93Existing',is_staff=True)
        self.normal=U.objects.create_user(username='normal')
        Venue.objects.create(venue_name='Venue sin relación administrativa')

    def test_admin_has_admin_navigation_without_invented_venue_assignment(self):
        self.client.force_login(self.admin)
        response=self.client.get(reverse('users:profile'))
        self.assertContains(response,'>Dashboard</a>')
        self.assertContains(response,reverse('reservations:admin_dashboard')+'#reservas-administrativas')
        self.assertContains(response,'href="/perfil/" aria-current="page"')
        self.assertNotContains(response,'Mis reservas')
        self.assertContains(response,'value="Administrador" readonly')
        self.assertContains(response,'>AD</span>')
        self.assertContains(response,'La información de establecimientos asignados no está disponible')
        self.assertNotContains(response,'Venue sin relación administrativa')

    def test_group_admin_uses_same_navigation_and_user_keeps_personal_navigation(self):
        self.client.force_login(self.normal)
        response=self.client.get(reverse('users:profile'))
        self.assertContains(response,'Mis reservas')
        self.assertNotContains(response,'>Dashboard</a>')
        self.assertNotContains(response,'id="account-role"')
        group,_=Group.objects.get_or_create(name='Administrador');self.normal.groups.add(group)
        response=self.client.get(reverse('users:profile'))
        self.assertContains(response,'>Dashboard</a>')
        self.assertNotContains(response,'Mis reservas')

    def test_admin_profile_update_preserves_role_and_username(self):
        self.client.force_login(self.admin)
        self.assertRedirects(self.client.post(reverse('users:profile'),{'first_name':'Admin','last_name':'Demo','email':'admin@example.test','is_staff':'','username':'changed','role':'Usuario'}),reverse('users:profile'))
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.first_name,'Admin')
        self.assertEqual(self.admin.username,'admin_demo')
        self.assertTrue(self.admin.is_staff)
        self.assertTrue(self.admin.check_password('Test!93Existing'))
        response=self.client.get(reverse('users:password_change'))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'href="/perfil/" aria-current="page"')
        self.assertNotContains(response,'Mis reservas')
