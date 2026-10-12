"""Pruebas manuales H4-02. Sin rutas web, consultas de BD o servicio de dashboard."""

import json
import logging
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI
from pydantic import ValidationError

from reservations.ai.schemas import InputContract
from reservations.ai.services import AIAnalysisError, AIAnalysisService


EXAMPLE_PATH = Path(__file__).resolve().parents[2] / "ai" / "examples" / "input_v1.json"


class Command(BaseCommand):
    help = "Prueba manual Responses API: simple y luego structured. Consume API; no usa Neon."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--fase", choices=("simple", "structured", "servicio", "ambas"), default="ambas")
        parser.add_argument("--input", type=Path, help="Input Contract v1.0 JSON; por defecto ejemplo sintético.")

    def handle(self, *args, **options):
        missing = [name for name in ("OPENAI_API_KEY", "OPENAI_MODEL") if not getattr(settings, name, "")]
        if missing:
            raise CommandError("Configuración incompleta: " + ", ".join(missing) + ". Configura .env o el entorno.")

        # Sin logs del transporte ni mensajes crudos del proveedor (podrían contener secretos).
        previous_logging = logging.root.manager.disable
        logging.disable(logging.CRITICAL)
        try:
            with OpenAI(api_key=settings.OPENAI_API_KEY, timeout=30.0, max_retries=0) as client:
                if options["fase"] in ("simple", "ambas"):
                    self.simple(client)
                if options["fase"] in ("structured", "servicio", "ambas"):
                    self.structured(client, options["input"] or EXAMPLE_PATH,
                                    max_attempts=2 if options["fase"] == "servicio" else 1)
        except APITimeoutError:
            raise CommandError("TIMEOUT: OpenAI no respondió dentro del límite de 30 segundos.") from None
        except APIConnectionError:
            raise CommandError("CONNECTION_ERROR: no se pudo conectar con OpenAI; revisar red/DNS/TLS.") from None
        except APIStatusError as exc:
            messages = {
                "insufficient_quota": "BILLING: cuota/crédito insuficiente; revisar billing y límites del proyecto.",
                "model_not_found": "MODEL_ACCESS: el modelo configurado no existe o no está disponible para esta cuenta.",
                "invalid_api_key": "AUTHENTICATION: la API key no es válida.",
            }
            message = messages.get(exc.code)
            if message is None:
                message = {
                    401: "AUTHENTICATION: credencial rechazada por OpenAI.",
                    403: "PERMISSION: acceso denegado por OpenAI.",
                    404: "MODEL_ACCESS: recurso o modelo no disponible.",
                    429: "RATE_LIMIT: límite de solicitudes/cuota alcanzado.",
                    400: "REQUEST_ERROR: solicitud o schema no admitido por el modelo/API.",
                }.get(exc.status_code, "API_ERROR: OpenAI devolvió un error.")
            raise CommandError(message) from None
        except ValidationError:
            raise CommandError("SCHEMA_ERROR: input o respuesta no cumple el contrato v1.0.") from None
        except AIAnalysisError as exc:
            raise CommandError(f"AI_ANALYSIS_ERROR: {exc.code}.") from None
        finally:
            logging.disable(previous_logging)

    def simple(self, client):
        response = client.responses.create(
            model=settings.OPENAI_MODEL,
            input="Responde únicamente con OK para confirmar esta prueba de conexión.",
            max_output_tokens=512,
            store=False,
        )
        if response.status != "completed" or not response.output_text.strip():
            raise CommandError("SIMPLE_INCOMPLETE: la respuesta no está completa o no contiene texto.")
        self.stdout.write(self.style.SUCCESS("SIMPLE_OK: autenticación, modelo y respuesta confirmados."))

    def structured(self, client, path, *, max_attempts=1):
        try:
            payload = InputContract.model_validate_json(Path(path).read_text(encoding="utf-8"))
        except (OSError, UnicodeError):
            raise CommandError("INPUT_ERROR: no se pudo leer el archivo de entrada JSON.") from None
        result = AIAnalysisService(client=client, max_attempts=max_attempts).generate(payload)
        self.stdout.write(self.style.SUCCESS(
            f"STRUCTURED_OK: AIAnalysis validado; {len(result.insights)} insights; "
            "evidencia y limitación sintética verificadas."
        ))
        self.stdout.write(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
