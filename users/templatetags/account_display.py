from django import template

register = template.Library()


@register.filter
def initials(user):
    """Presentación de los nombres existentes, sin almacenar datos de avatar."""
    parts = user.get_full_name().split()
    if parts:
        return (parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")).upper()
    return user.username[:2].upper()
