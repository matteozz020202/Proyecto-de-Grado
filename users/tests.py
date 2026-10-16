from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from courts.models import Court, Venue
from .views import court_image_url


class HomeTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="jugador", password="test")
        self.client.force_login(self.user)
        self.venue = Venue.objects.create(venue_name="Complejo Norte", address="Calle 10")

    def court(self, **kwargs):
        return Court.objects.create(venue=self.venue, court_name="Cancha Norte", price_per_hour=150000, **kwargs)

    def test_index_is_public(self):
        self.client.logout()
        self.assertContains(self.client.get(reverse("users:home")), "Iniciar sesión")

    def test_real_court_price_and_reservation_link(self):
        court = self.court()
        response = self.client.get(reverse("users:home"))
        self.assertContains(response, "Cancha Norte")
        self.assertContains(response, "$150.000,00")
        self.assertContains(response, reverse("courts:disponibilidad_cancha", args=[court.pk]))
        self.assertContains(response, "users/images/Fallback-image.jpg")
        self.assertNotContains(response, "Disponible ahora")

    def test_featured_excludes_inactive_venue_court_and_invalid_names(self):
        self.court(is_active=False)
        Court.objects.create(venue=self.venue, court_name=" ", price_per_hour=10)
        inactive = Venue.objects.create(venue_name="Cerrado", is_active=False)
        Court.objects.create(venue=inactive, court_name="Otra", price_per_hour=10)
        expected = self.court()
        self.court()
        self.assertEqual(self.client.get("/").context["featured_court"], expected)

    def test_empty_state(self):
        response = self.client.get("/")
        self.assertContains(response, "Aún no hay canchas activas")
        self.assertContains(response, reverse("courts:establecimientos"))

    def test_missing_image_uses_fallback(self):
        court = self.court(image="courts/missing.jpg")
        with patch.object(court.image.storage, "exists", return_value=False):
            self.assertIsNone(court_image_url(court))
        with patch.object(court.image.storage, "exists", return_value=True):
            self.assertEqual(court_image_url(court), "/media/courts/missing.jpg")

    def test_group_admin_navigation_and_escaped_names(self):
        self.user.groups.add(Group.objects.create(name="Administrador"))
        self.venue.venue_name = "<script>alert(1)</script>"
        self.venue.save()
        self.court()
        response = self.client.get("/")
        self.assertContains(response, reverse("reservations:admin_dashboard"))
        self.assertContains(response, "&lt;script&gt;alert(1)&lt;/script&gt;")
        self.assertNotContains(response, "<script>alert(1)</script>")

    def test_logout_still_requires_post(self):
        self.assertRedirects(self.client.get(reverse("users:logout")), reverse("users:home"))
        self.assertRedirects(self.client.post(reverse("users:logout")), reverse("users:login"))
