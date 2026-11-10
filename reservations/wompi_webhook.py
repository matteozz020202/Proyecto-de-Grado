
import json
import os

from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .wompi import verify_wompi_event
from .wompi_client import WompiAPIError
from .wompi_notification_processing import (
    process_wompi_transaction_notification,
)


MAX_WEBHOOK_BYTES = 65536


@csrf_exempt
@require_POST
def wompi_webhook(request):
    """
    Recibe eventos de Wompi Sandbox.

    No confia en el estado recibido en el evento:
    siempre consulta la transaccion en Wompi.

    No necesita una sesion de usuario ni token CSRF,
    porque Wompi es un servicio externo.
    """

    events_secret = os.environ.get(
        "WOMPI_EVENTS_SECRET", ""
    )

    if not events_secret.startswith("test_events_"):
        return JsonResponse(
            {"error": "Webhook no configurado."},
            status=503,
        )

    if len(request.body) > MAX_WEBHOOK_BYTES:
        return JsonResponse(
            {"error": "Evento demasiado grande."},
            status=413,
        )

    try:
        event = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return JsonResponse(
            {"error": "JSON no valido."},
            status=400,
        )

    if not isinstance(event, dict):
        return JsonResponse(
            {"error": "Evento no valido."},
            status=400,
        )

    try:
        signature_is_valid = verify_wompi_event(
            event,
            events_secret,
        )
    except (ValidationError, ValueError, TypeError, KeyError):
        return JsonResponse(
            {"error": "Firma no valida."},
            status=400,
        )

    if not signature_is_valid:
        return JsonResponse(
            {"error": "Firma no valida."},
            status=400,
        )

    # La firma debe proteger el identificador
    # que utilizaremos para consultar a Wompi.
    #
    # No exigimos un conjunto fijo de propiedades:
    # Wompi puede variar los campos firmados.

    signature = event.get("signature")

    if not isinstance(signature, dict):
        return JsonResponse(
            {"error": "Firma no valida."},
            status=400,
        )

    signed_properties = signature.get("properties")

    if (
        not isinstance(signed_properties, list)
        or "transaction.id" not in signed_properties
    ):
        return JsonResponse(
            {
                "error": (
                    "El identificador de la transaccion "
                    "no esta protegido por la firma."
                )
            },
            status=400,
        )


    # El verificador existente tambien debe comprobar
    # environment="test" y event="transaction.updated".
    if (
        event.get("environment") != "test"
        or event.get("event") != "transaction.updated"
    ):
        return JsonResponse(
            {"error": "Tipo de evento no permitido."},
            status=400,
        )

    transaction_data = event.get("data", {}).get(
        "transaction"
    )

    if not isinstance(transaction_data, dict):
        return JsonResponse(
            {"error": "Transaccion no valida."},
            status=400,
        )

    transaction_id = transaction_data.get("id")

    if (
        not isinstance(transaction_id, str)
        or not transaction_id
    ):
        return JsonResponse(
            {"error": "ID de transaccion no valido."},
            status=400,
        )

    try:
        process_wompi_transaction_notification(
            transaction_id
        )
    except (WompiAPIError, DatabaseError):
        # El proveedor podra reintentar el evento.
        return JsonResponse(
            {"error": "Procesamiento temporalmente no disponible."},
            status=503,
        )
    except (ValidationError, ValueError):
        return JsonResponse(
            {"error": "Transaccion rechazada."},
            status=400,
        )

    return JsonResponse(
        {"received": True},
        status=200,
    )
