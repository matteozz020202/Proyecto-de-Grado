from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect


def login_view(request):
    if request.user.is_authenticated:
        return redirect("users:home")

    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")

        user = authenticate(
            request,
            username=username,
            password=password
        )

        if user is not None:
            login(request, user)
            return redirect("users:home")

        messages.error(request, "Usuario o contraseña incorrectos.")

    return render(request, "users/login.html")


@login_required
def home_view(request):
    rol = "Sin rol"

    if request.user.groups.filter(name="Administrador").exists():
        rol = "Administrador"
    elif request.user.groups.filter(name="Usuario").exists():
        rol = "Usuario"
    elif request.user.is_superuser:
        rol = "Superusuario"

    return render(
        request,
        "users/home.html",
        {
            "rol": rol
        }
    )


@login_required
def logout_view(request):
    if request.method == "POST":
        logout(request)
        return redirect("users:login")

    return redirect("users:home")