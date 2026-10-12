from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from .models import Court, Venue


class PublicCatalogTests(TestCase):
    def setUp(self):
        self.venue = Venue.objects.create(venue_name="Arena Norte", address="Calle 10")
        self.empty = Venue.objects.create(venue_name="Sin canchas", address="Calle 11")
        Venue.objects.create(venue_name="Cerrado", is_active=False)
        Court.objects.create(venue=self.venue, court_name="A", price_per_hour=150000)
        Court.objects.create(venue=self.venue, court_name="B", price_per_hour=120000)
        Court.objects.create(venue=self.venue, court_name="Cerrada", price_per_hour=1, is_active=False)

    def test_public_catalog_has_real_active_counts_and_prices(self):
        response = self.client.get(reverse("courts:establecimientos"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Cerrado")
        self.assertContains(response, "2 canchas activas")
        self.assertContains(response, "$120.000")
        self.assertContains(response, "Sin tarifa disponible")
        self.assertContains(response, reverse("courts:canchas_establecimiento", args=[self.venue.pk]))
        self.assertContains(response, "Iniciar sesión")
        self.assertNotContains(response, "Mis reservas")

    def test_same_catalog_for_user_and_admin_with_contextual_navigation(self):
        U = get_user_model()
        for staff in [False, True]:
            user = U.objects.create_user(username=f"user-{staff}", is_staff=staff)
            self.client.force_login(user)
            response = self.client.get(reverse("courts:establecimientos"))
            self.assertEqual(response.status_code, 200)
            self.assertEqual([v.pk for v in response.context["establecimientos"]], [self.venue.pk, self.empty.pk])
            self.assertContains(response, "Dashboard" if staff else "Mis reservas")
            self.assertContains(response, "Cerrar sesión")
            self.assertNotContains(response, "Registrarse")

    def test_empty_state(self):
        Venue.objects.update(is_active=False)
        response = self.client.get(reverse("courts:establecimientos"))
        self.assertContains(response, "Aún no hay establecimientos activos")
        self.assertNotContains(response, "Ver canchas")

    def test_names_are_escaped(self):
        self.venue.venue_name = "<script>alert(1)</script>"
        self.venue.save()
        self.assertNotContains(self.client.get(reverse("courts:establecimientos")), "<script>alert(1)</script>")


class VenueDetailTests(TestCase):
    def setUp(self):
        self.venue = Venue.objects.create(venue_name="Arena Norte", address="Calle 10", city="Barranquilla")
        self.other = Venue.objects.create(venue_name="Otro establecimiento")
        self.court = Court.objects.create(venue=self.venue, court_name="Cancha Norte", price_per_hour=120000, description="Descripción real de la cancha")
        Court.objects.create(venue=self.venue, court_name="Cancha inactiva", price_per_hour=100, is_active=False)
        Court.objects.create(venue=self.other, court_name="Cancha ajena", price_per_hour=200)
        self.url = reverse("courts:canchas_establecimiento", args=[self.venue.pk])

    def test_public_detail_shows_only_active_courts_of_current_venue(self):
        with self.assertNumQueries(2):
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Arena Norte")
        self.assertContains(response, "Calle 10")
        self.assertContains(response, "Barranquilla")
        self.assertContains(response, "Descripción real de la cancha")
        self.assertContains(response, "$120.000")
        self.assertNotContains(response, "Cancha ajena")
        self.assertNotContains(response, "Cancha inactiva")
        self.assertContains(response, reverse("courts:disponibilidad_cancha", args=[self.court.pk]))
        self.assertContains(response, "users/images/Fallback-image.jpg")
        self.assertNotContains(response, "Parqueadero")
        self.assertNotContains(response, "Fútbol 5")
        self.assertEqual(self.client.get(reverse("courts:disponibilidad_cancha", args=[self.court.pk])).status_code, 200)

    def test_all_roles_use_same_public_detail(self):
        U = get_user_model()
        for staff in [False, True]:
            user = U.objects.create_user(username=f"detail-{staff}", is_staff=staff)
            self.client.force_login(user)
            response = self.client.get(self.url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(list(response.context["canchas"]), [self.court])
            self.assertContains(response, "Dashboard" if staff else "Mis reservas")

    def test_empty_inactive_and_missing_venue(self):
        self.court.is_active = False
        self.court.save()
        self.assertContains(self.client.get(self.url), "Este establecimiento no tiene canchas disponibles actualmente.")
        self.assertNotContains(self.client.get(self.url), "Ver disponibilidad")
        self.venue.is_active = False
        self.venue.save()
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.client.get(reverse("courts:canchas_establecimiento", args=[9999])).status_code,404)

    def test_real_image_urls_and_escaped_description(self):
        self.venue.image = "venues/actual.jpg"
        self.venue.save()
        self.court.image = "courts/actual.jpg"
        self.court.description = "<script>alert(1)</script>"
        self.court.save()
        response = self.client.get(self.url)
        self.assertContains(response, "/media/venues/actual.jpg")
        self.assertContains(response, "/media/courts/actual.jpg")
        self.assertNotContains(response, "<script>alert(1)</script>")
