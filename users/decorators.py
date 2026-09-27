from functools import wraps

from django.contrib import messages
from django.shortcuts import redirect


def admin_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):

        es_admin = (
            request.user.is_authenticated
            and (
                request.user.is_superuser
                or request.user.is_staff
                or request.user.groups.filter(
                    name="Administrador"
                ).exists()
            )
        )

        if not es_admin:
            messages.error(
                request,
                "No tienes permisos para acceder a esta sección."
            )
            return redirect("users:home")

        return view_func(
            request,
            *args,
            **kwargs
        )

    return wrapper