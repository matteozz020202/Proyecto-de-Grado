from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect
from .navigation import is_admin, login_destination
from .forms import LoginForm, ProfileForm, RegistrationForm
from django.contrib.auth.models import Group
from django.db import transaction
from courts.models import Court


def featured_court():
    """Destacado visual determinístico, sin recomendaciones ni disponibilidad implícita."""
    candidates = Court.objects.select_related("venue").filter(
        is_active=True, venue__is_active=True, price_per_hour__gte=0,
    ).order_by("court_id")
    return next((court for court in candidates
                 if court.court_name.strip() and court.venue.venue_name.strip()), None)


def court_image_url(court):
    if court is None or not court.image:
        return None
    try:
        url = court.image.url
        if url.startswith("/") and not url.startswith("//") and court.image.storage.exists(court.image.name):
            return url
    except (OSError, ValueError):
        pass
    return None


def login_view(request):
    next_url = request.POST.get("next", request.GET.get("next", ""))
    if request.user.is_authenticated:
        return redirect(login_destination(request, request.user, next_url))

    form = LoginForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        user = authenticate(
            request,
            username=form.cleaned_data["username"],
            password=form.cleaned_data["password"]
        )

        if user is not None:
            login(request, user)
            return redirect(login_destination(request, user, next_url))

        form.add_error(None, "Usuario o contraseña incorrectos.")

    return render(request, "users/login.html", {"next": next_url, "form": form})


def home_view(request):
    rol = "Sin rol"

    if is_admin(request.user):
        rol = "Administrador"
    elif request.user.is_authenticated and request.user.groups.filter(name="Usuario").exists():
        rol = "Usuario"

    court = featured_court()
    return render(
        request,
        "users/home.html",
        {
            "rol": rol,
            "featured_court": court,
            "featured_image_url": court_image_url(court),
        }
    )


@login_required(login_url="users:login")
def logout_view(request):
    if request.method == "POST":
        logout(request)
        return redirect("users:login")

    return redirect("users:home")


@login_required
def profile_view(request):
    form = ProfileForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Perfil actualizado.")
        return redirect("users:profile")
    return render(request, "users/account_form.html", {"form": form, "title": "Mi perfil", "profile": True})


def register_view(request):
    if request.user.is_authenticated:
        return redirect(login_destination(request, request.user))
    form = RegistrationForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            user = form.save()
            group, _ = Group.objects.get_or_create(name="Usuario")
            user.groups.add(group)
        login(request, user)
        return redirect(login_destination(request, user, request.POST.get("next", "")))
    return render(request, "users/register.html", {"form": form, "next": request.POST.get("next", request.GET.get("next", "")), "register": True})
