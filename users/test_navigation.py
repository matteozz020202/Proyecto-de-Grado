from datetime import time, timedelta
from urllib.parse import parse_qs, urlsplit
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from courts.models import Court, CourtSchedule, Venue
from reservations.models import Reservation


class NavigationTests(TestCase):
    def setUp(self):
        U = get_user_model()
        self.user = U.objects.create_user(username="normal", password="test")
        self.admin = U.objects.create_user(username="admin", password="test", is_staff=True)
        self.other = U.objects.create_user(username="other", password="test")
        self.venue = Venue.objects.create(venue_name="Venue", address="Calle")
        self.court = Court.objects.create(venue=self.venue, court_name="Court", price_per_hour=100)

    def login(self, username="normal", next_url=None):
        data = {"username": username, "password": "test"}
        if next_url is not None: data["next"] = next_url
        return self.client.post(reverse("users:login"), data)

    def test_role_landings(self):
        self.assertRedirects(self.login(), reverse("courts:establecimientos"))
        self.client.logout()
        self.assertRedirects(self.login("admin"), reverse("reservations:admin_dashboard"), fetch_redirect_response=False)
        self.client.logout()
        self.user.groups.add(Group.objects.create(name="Administrador"))
        self.assertRedirects(self.login(), reverse("reservations:admin_dashboard"), fetch_redirect_response=False)

    def test_selected_slot_survives_login_and_reaches_summary(self):
        day = timezone.localdate() + timedelta(days=1)
        CourtSchedule.objects.create(court=self.court, day_of_week=day.isoweekday(), start_time=time(19), end_time=time(21))
        target = reverse("reservations:resumen_reserva", args=[self.court.pk])+f"?fecha={day.isoformat()}&inicio=19:00&fin=20:00"
        redirect = self.client.get(target)
        login_page = self.client.get(redirect.url)
        self.assertEqual(login_page.context["next"], target)
        self.assertRedirects(self.login(next_url=target), target)
        self.assertEqual(Reservation.objects.count(), 0)

    def test_safe_next_preserves_slot_and_rejects_unsafe_destinations(self):
        target = reverse("reservations:resumen_reserva", args=[self.court.pk])+"?fecha=2030-01-01&inicio=19:00&fin=20:00"
        self.assertEqual(self.login(next_url=target).url, target)
        for target in ["https://evil.test", "//evil.test", "/missing/", reverse("reservations:admin_dashboard"), reverse("users:logout"), "/admin/", reverse("reservations:admin_dashboard_analysis")]:
            self.client.logout()
            self.assertEqual(self.login(next_url=target).url, reverse("courts:establecimientos"))

    def test_public_browsing_and_protected_booking(self):
        for url in ["/", reverse("courts:establecimientos"), reverse("courts:canchas_establecimiento", args=[self.venue.pk]), reverse("courts:disponibilidad_cancha", args=[self.court.pk])]:
            self.assertEqual(self.client.get(url).status_code, 200)
        target = reverse("reservations:resumen_reserva", args=[self.court.pk])+"?fecha=2030-01-01&inicio=19:00&fin=20:00"
        response = self.client.get(target)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(parse_qs(urlsplit(response.url).query)["next"], [target])
        for name in ["users:profile", "reservations:mis_reservas"]:
            self.assertEqual(self.client.get(reverse(name)).status_code, 302)

    def test_profile_only_changes_allowed_fields(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("users:profile"), {"first_name":"Ana", "last_name":"Pérez", "email":"ana@example.test", "is_staff":"True", "is_superuser":"True", "is_active":"False", "username":"changed", "password":"hacked"})
        self.assertRedirects(response, reverse("users:profile"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Ana")
        self.assertEqual(self.user.username, "normal")
        self.assertFalse(self.user.is_staff or self.user.is_superuser)
        self.assertTrue(self.user.is_active)
        self.assertTrue(self.user.check_password("test"))
        self.client.post(reverse("users:profile"), {"email":"invalid"})
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "ana@example.test")

    def test_registration_cannot_assign_admin(self):
        response = self.client.post(reverse("users:register"), {"username":"new", "full_name":"Ana Pérez", "email":"ana@example.test", "password1":"UniquePass!394xy", "password2":"UniquePass!394xy", "is_staff":"True", "role":"Administrador"})
        self.assertRedirects(response, reverse("courts:establecimientos"))
        user = get_user_model().objects.get(username="new")
        self.assertFalse(user.is_staff or user.is_superuser)
        self.assertTrue(user.groups.filter(name="Usuario").exists())
        self.assertFalse(user.groups.filter(name="Administrador").exists())

    def test_password_change_keeps_session(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("users:password_change"), {"old_password":"test", "new_password1":"UniquePass!394xy", "new_password2":"UniquePass!394xy"})
        self.assertRedirects(response, reverse("users:password_change_done"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("UniquePass!394xy"))
        self.assertEqual(self.client.get(reverse("users:profile")).status_code, 200)

    def test_own_reservations_and_other_users_payment_are_private(self):
        for offset, user in enumerate([self.user, self.other], 1):
            Reservation.objects.create(user=user,court=self.court,reservation_date=timezone.localdate()+timedelta(days=offset),start_time=time(19),end_time=time(20),total_amount=100,reservation_status="CONFIRMED")
        self.client.force_login(self.user)
        response = self.client.get(reverse("reservations:mis_reservas"))
        self.assertEqual([r.user_id for r in response.context["reservas"]], [self.user.pk])
        self.assertContains(response, "Próxima")
        other = Reservation.objects.get(user=self.other)
        self.assertEqual(self.client.get(reverse("reservations:pagar_reserva",args=[other.pk])).status_code,404)
        self.assertEqual(self.client.post(reverse("reservations:cancelar_reserva",args=[other.pk])).status_code,404)
        self.client.logout()
        self.assertEqual(self.login(next_url=reverse("reservations:pagar_reserva",args=[other.pk])).url, reverse("courts:establecimientos"))

    def test_admin_routes_block_user(self):
        self.client.force_login(self.user)
        for name in ["reservations:admin_dashboard", "reservations:admin_crear_reserva"]:
            self.assertRedirects(self.client.get(reverse(name)), reverse("users:home"))
        self.assertRedirects(self.client.post(reverse("reservations:admin_dashboard_analysis")), reverse("users:home"))
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("reservations:admin_dashboard")+"?fecha_inicio=invalid").status_code,200)
        self.assertEqual(self.client.get(reverse("reservations:admin_crear_reserva")).status_code,200)
