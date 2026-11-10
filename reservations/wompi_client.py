
import json
import os
import re

from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


WOMPI_SANDBOX_URL = "https://sandbox.wompi.co/v1"

WOMPI_TIMEOUT = 10


class WompiAPIError(Exception):
    """
    Error al consultar Wompi.
    No incluye credenciales ni respuestas sensibles.
    """


def get_wompi_transaction(transaction_id):
    """
    Consulta una transaccion en Wompi Sandbox.

    Utiliza exclusivamente la llave privada de pruebas.

    No actualiza pagos ni reservas.
    """

    if (
        not isinstance(transaction_id, str)
        or not re.fullmatch(
            r"[A-Za-z0-9_-]{1,150}",
            transaction_id,
        )
    ):
        raise ValueError(
            "El identificador de transaccion no es valido."
        )

    private_key = os.environ.get(
        "WOMPI_PRIVATE_KEY",
        "",
    )

    if not private_key.startswith("prv_test_"):
        raise WompiAPIError(
            "La llave privada de Wompi Sandbox "
            "no esta configurada correctamente."
        )

    url = (
        f"{WOMPI_SANDBOX_URL}/transactions/"
        f"{transaction_id}"
    )

    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {private_key}",
        },
        method="GET",
    )

    try:
        with urlopen(
            request,
            timeout=WOMPI_TIMEOUT,
        ) as response:
            if response.status != 200:
                raise WompiAPIError(
                    "Wompi devolvio una respuesta inesperada."
                )

            payload = json.load(response)

    except HTTPError as exc:
        raise WompiAPIError(
            "Wompi rechazo la consulta de la transaccion."
        ) from exc

    except (URLError, TimeoutError, OSError) as exc:
        raise WompiAPIError(
            "No fue posible comunicarse con Wompi."
        ) from exc

    except (ValueError, UnicodeError) as exc:
        raise WompiAPIError(
            "Wompi devolvio una respuesta no valida."
        ) from exc

    if not isinstance(payload, dict):
        raise WompiAPIError(
            "La estructura de respuesta no es valida."
        )

    data = payload.get("data")

    if not isinstance(data, dict):
        raise WompiAPIError(
            "La transaccion no contiene datos validos."
        )

    if data.get("id") != transaction_id:
        raise WompiAPIError(
            "El identificador de respuesta no coincide."
        )

    return data
