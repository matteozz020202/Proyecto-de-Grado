from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse
from users.forms import RegistrationForm


class AuthFormTests(TestCase):
    def data(self, **changes):
        return {"username": "new_player", "full_name": "Ana Pérez", "email": "ANA@example.test", "password1": "UniquePass!394xy", "password2": "UniquePass!394xy", **changes}

    def test_signup_hashes_password_and_preserves_next(self):
        target = reverse("users:profile")
        response = self.client.post(reverse("users:register"), self.data(next=target))
        self.assertRedirects(response, target)
        user = get_user_model().objects.get(username="new_player")
        self.assertEqual(user.first_name, "Ana Pérez")
        self.assertEqual(user.email, "ana@example.test")
        self.assertNotEqual(user.password, self.data()["password1"])
        self.assertTrue(user.check_password(self.data()["password1"]))
        self.assertTrue(self.client.session.get("_auth_user_id"))

    def test_signup_rejects_external_next(self):
        self.assertRedirects(self.client.post(reverse("users:register"), self.data(next="https://evil.test")), reverse("courts:establecimientos"))

    def test_required_name_email_and_password_validation(self):
        for changes, field in [({"full_name":" "}, "full_name"), ({"email":""}, "email"), ({"email":"bad"}, "email"), ({"password2":"different"}, "password2"), ({"password1":"12345678", "password2":"12345678"}, "password2")]:
            form = RegistrationForm(self.data(**changes))
            self.assertFalse(form.is_valid())
            self.assertIn(field, form.errors)

    def test_duplicate_email_case_insensitive(self):
        get_user_model().objects.create_user(username="existing", email="ana@EXAMPLE.test")
        response = self.client.post(reverse("users:register"), self.data())
        self.assertEqual(response.status_code, 200)
        self.assertIn("email", response.context["form"].errors)
        self.assertFalse(get_user_model().objects.filter(username="new_player").exists())
        self.assertNotContains(response, 'value="UniquePass!394xy"')

    def test_invalid_login_retains_username_not_password_and_next(self):
        target = reverse("users:profile")
        response = self.client.post(reverse("users:login"), {"username":"missing", "password":"secret-value", "next":target})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Usuario o contraseña incorrectos.")
        self.assertContains(response, 'value="missing"')
        self.assertNotContains(response, "secret-value")
        self.assertEqual(response.context["next"], target)
        self.assertContains(response, "/registro/?next=")
        signup = self.client.post(reverse("users:register"), self.data(password2="wrong", next=target))
        self.assertEqual(signup.context["next"], target)
        self.assertContains(signup, "/login/?next=")

    def test_csrf_is_required(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post(reverse("users:login"), {"username":"a", "password":"b"}).status_code,403)
        self.assertEqual(client.post(reverse("users:register"), self.data()).status_code,403)
