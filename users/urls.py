from django.urls import path
from . import views
from django.contrib.auth.views import PasswordChangeView, PasswordChangeDoneView
from django.urls import reverse_lazy

app_name = "users"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("registro/", views.register_view, name="register"),
    path("perfil/", views.profile_view, name="profile"),
    path("perfil/password/", PasswordChangeView.as_view(template_name="users/account_form.html", success_url=reverse_lazy("users:password_change_done"), extra_context={"title": "Cambiar contraseña"}), name="password_change"),
    path("perfil/password/listo/", PasswordChangeDoneView.as_view(template_name="users/password_done.html"), name="password_change_done"),
    path("", views.home_view, name="home"),
]
