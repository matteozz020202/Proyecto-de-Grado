from .navigation import is_admin


def navigation(request):
    return {"navigation_admin": is_admin(request.user)}
