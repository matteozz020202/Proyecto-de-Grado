from decimal import Decimal
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse
from .models import Court,Venue

User=get_user_model()


class AdminCourtManagementTests(TestCase):
    def setUp(self):
        group=Group.objects.create(name="Administrador")

        self.admin1=User.objects.create_user(username="admin1",password="123456")
        self.admin2=User.objects.create_user(username="admin2",password="123456")
        self.superuser=User.objects.create_superuser(username="superadmin",password="123456")

        self.admin1.groups.add(group)
        self.admin2.groups.add(group)

        self.venue1=Venue.objects.create(
            venue_name="Establecimiento Admin 1",
            city="Barranquilla",
            address="Calle 1",
            manager=self.admin1
        )

        self.venue2=Venue.objects.create(
            venue_name="Establecimiento Admin 2",
            city="Barranquilla",
            address="Calle 2",
            manager=self.admin2
        )

        self.court1=Court.objects.create(
            venue=self.venue1,
            court_name="Cancha Admin 1",
            price_per_hour=Decimal("50000"),
            description="Cancha del primer administrador"
        )

        self.court2=Court.objects.create(
            venue=self.venue2,
            court_name="Cancha Admin 2",
            price_per_hour=Decimal("60000"),
            description="Cancha del segundo administrador"
        )

    def test_admin_solo_ve_sus_establecimientos(self):
        self.client.force_login(self.admin1)
        response=self.client.get(reverse("courts:admin_canchas"))

        self.assertEqual(response.status_code,200)
        self.assertContains(response,self.venue1.venue_name)
        self.assertNotContains(response,self.venue2.venue_name)

    def test_admin_puede_editar_su_establecimiento(self):
        self.client.force_login(self.admin1)

        response=self.client.post(
            reverse("courts:admin_editar_establecimiento",args=[self.venue1.pk]),
            {
                "venue_name":"Establecimiento actualizado",
                "city":"Barranquilla",
                "address":"Carrera 50"
            }
        )

        self.assertRedirects(response,reverse("courts:admin_canchas"))
        self.venue1.refresh_from_db()
        self.assertEqual(self.venue1.venue_name,"Establecimiento actualizado")
        self.assertEqual(self.venue1.address,"Carrera 50")

    def test_admin_no_puede_editar_establecimiento_ajeno(self):
        self.client.force_login(self.admin1)

        response=self.client.get(
            reverse("courts:admin_editar_establecimiento",args=[self.venue2.pk])
        )

        self.assertEqual(response.status_code,404)

    def test_admin_puede_editar_su_cancha(self):
        self.client.force_login(self.admin1)

        response=self.client.post(
            reverse("courts:admin_editar_cancha",args=[self.court1.pk]),
            {
                "court_name":"Cancha actualizada",
                "price_per_hour":"75000",
                "description":"Nueva descripción"
            }
        )

        self.assertRedirects(response,reverse("courts:admin_canchas"))
        self.court1.refresh_from_db()
        self.assertEqual(self.court1.court_name,"Cancha actualizada")
        self.assertEqual(self.court1.price_per_hour,Decimal("75000"))

    def test_admin_no_puede_editar_cancha_ajena(self):
        self.client.force_login(self.admin1)

        response=self.client.get(
            reverse("courts:admin_editar_cancha",args=[self.court2.pk])
        )

        self.assertEqual(response.status_code,404)

    def test_superusuario_puede_editar_cualquier_establecimiento(self):
        self.client.force_login(self.superuser)

        response=self.client.get(
            reverse("courts:admin_editar_establecimiento",args=[self.venue2.pk])
        )

        self.assertEqual(response.status_code,200)

    def test_superusuario_puede_editar_cualquier_cancha(self):
        self.client.force_login(self.superuser)

        response=self.client.get(
            reverse("courts:admin_editar_cancha",args=[self.court2.pk])
        )

        self.assertEqual(response.status_code,200)