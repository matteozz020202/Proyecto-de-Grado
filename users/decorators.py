from functools import wraps

from django.contrib import messages
from django.shortcuts import redirect
from .navigation import is_admin


def admin_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):

        es_admin = is_admin(request.user)

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
