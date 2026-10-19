import re
from django.contrib.auth import get_user_model
from django.test import Client, TestCase


class AuthCSRFTests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.user = get_user_model().objects.create_user(username="csrf_existing",password="Test!93Existing")

    def token(self, path):
        response = self.client.get(path)
        tokens = re.findall(r'name="csrfmiddlewaretoken" value="([^"]+)"', response.content.decode())
        self.assertEqual(len(tokens),1)
        self.assertRegex(response.content.decode(),r'<form[^>]*method="post"[^>]*>\s*<input[^>]*name="csrfmiddlewaretoken"')
        self.assertIn('no-store',response.headers['Cache-Control'])
        return tokens[0]

    def registration(self):
        return {'username':'csrf_new','full_name':'Prueba CSRF','email':'csrf-new@example.test','password1':'UniquePass!394xy','password2':'UniquePass!394xy'}

    def test_repeated_switch_then_registration_is_accepted(self):
        for path in ['/login/','/registro/','/login/','/registro/']:
            token = self.token(path)
        response = self.client.post('/registro/',{**self.registration(),'csrfmiddlewaretoken':token})
        self.assertEqual(response.status_code,302)
        self.assertTrue(get_user_model().objects.filter(username='csrf_new').exists())
        self.assertTrue(self.client.session.get('_auth_user_id'))

    def test_login_post_is_accepted_with_valid_token(self):
        token=self.token('/login/')
        response=self.client.post('/login/',{'username':self.user.username,'password':'Test!93Existing','csrfmiddlewaretoken':token})
        self.assertEqual(response.status_code,302)
        self.assertTrue(self.client.session.get('_auth_user_id'))

    def test_missing_and_wrong_tokens_remain_forbidden(self):
        for path in ['/login/','/registro/']:
            self.token(path)
            self.assertEqual(self.client.post(path,{}).status_code,403)
            self.assertEqual(self.client.post(path,{'csrfmiddlewaretoken':'A'*64}).status_code,403)
        self.assertFalse(get_user_model().objects.filter(username='csrf_new').exists())

    def test_stale_token_after_login_logout_is_rejected_and_fresh_page_works(self):
        old=self.token('/registro/')
        self.client.post('/login/',{'username':self.user.username,'password':'Test!93Existing','csrfmiddlewaretoken':old})
        self.client.post('/logout/',{'csrfmiddlewaretoken':self.client.cookies['csrftoken'].value})
        self.assertEqual(self.client.post('/registro/',{**self.registration(),'csrfmiddlewaretoken':old}).status_code,403)
        current=self.token('/registro/')
        self.assertEqual(self.client.post('/registro/',{**self.registration(),'csrfmiddlewaretoken':current}).status_code,302)
