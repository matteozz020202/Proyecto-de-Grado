
import os

from django.core.exceptions import ImproperlyConfigured


SANDBOX_CREDENTIALS = {
    "WOMPI_PUBLIC_KEY": "pub_test_",
    "WOMPI_PRIVATE_KEY": "prv_test_",
    "WOMPI_INTEGRITY_SECRET": "test_integrity_",
    "WOMPI_EVENTS_SECRET": "test_events_",
}


def validate_wompi_sandbox_config():
    """
    Comprueba que las credenciales de Wompi
    Sandbox estén configuradas.

    No realiza conexiones HTTP.
    No devuelve ni imprime secretos.
    """

    invalid_variables = []

    for variable, prefix in SANDBOX_CREDENTIALS.items():
        value = os.environ.get(variable, "").strip()

        if (
            not value.startswith(prefix)
            or len(value) <= len(prefix)
        ):
            invalid_variables.append(variable)

    if invalid_variables:
        raise ImproperlyConfigured(
            "Configuración incompleta de Wompi Sandbox: "
            + ", ".join(invalid_variables)
        )

    return True
