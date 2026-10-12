"""Generación independiente del dashboard. Solo entradas y salidas validadas."""

import json
import math
import time

from django.conf import settings
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI
from pydantic import ValidationError

from .prompts import ADMIN_PROMPT
from .schemas import AIAnalysis, InputContract
from .validators import InvalidAIResponse, available_change_types, evidence_catalog, validate_analysis


class AIAnalysisError(Exception):
    """Código seguro para consumidores. Nunca incluye texto crudo del proveedor."""

    def __init__(self, code, *, retryable=False):
        self.code = code
        self.retryable = retryable
        super().__init__(code)


class AIAnalysisService:
    def __init__(self, *, client=None, timeout=30.0, max_attempts=2,
                 max_output_tokens=4096, max_input_bytes=64000):
        if (not isinstance(timeout, (int, float)) or isinstance(timeout, bool)
                or not math.isfinite(timeout) or not 0 < timeout <= 30):
            raise ValueError("timeout debe estar entre 0 y 30 segundos.")
        if type(max_attempts) is not int or max_attempts not in (1, 2):
            raise ValueError("max_attempts debe ser 1 o 2.")
        for value, ceiling in ((max_output_tokens, 4096), (max_input_bytes, 64000)):
            if type(value) is not int or not 0 < value <= ceiling:
                raise ValueError("Los límites deben ser enteros positivos dentro del máximo permitido.")
        self.client = client
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.max_output_tokens = max_output_tokens
        self.max_input_bytes = max_input_bytes

    def generate(self, input_data: InputContract | dict) -> AIAnalysis:
        try:
            payload = InputContract.model_validate(input_data)
        except ValidationError:
            raise AIAnalysisError("INVALID_INPUT") from None
        # Incluye prompt y catálogo en el límite; no trunca ni pierde parte del input.
        if len(json.dumps(self.messages(payload), ensure_ascii=False).encode("utf-8")) > self.max_input_bytes:
            raise AIAnalysisError("INPUT_TOO_LARGE")
        if not settings.OPENAI_API_KEY or not settings.OPENAI_MODEL:
            raise AIAnalysisError("CONFIGURATION_ERROR")
        if self.client is not None:
            # El cliente inyectado conserva la propiedad del transporte; no se cierra aquí.
            return self._generate(self.client.with_options(max_retries=0, timeout=self.timeout), payload)
        with OpenAI(api_key=settings.OPENAI_API_KEY, timeout=self.timeout, max_retries=0) as client:
            return self._generate(client, payload)

    @staticmethod
    def messages(payload, retry_code=None):
        references = [{"metric": metric, "reference": reference}
                      for metric, reference in evidence_catalog(payload)]
        instruction = (
            "Evidence reference convention: null for summary, reservation_status_counts and comparisons; "
            "court_id as a string for occupancy_by_court; exact day/time_slot labels for other breakdowns. "
            "Translate day names to Spanish in human-readable text; preserve English day references in evidence. "
            "For SYNTHETIC, limitations must explicitly say 'datos sintéticos' and indicate "
            "'demostración', 'pruebas' or 'validación funcional'. "
            "Change insights require a non-null previous period, current and previous metric, and variation. "
            "Their evidence must cite comparisons.occupancy_variation_pp or "
            "comparisons.reservations_variation_pct respectively. A zero previous reservation count "
            "does not support percentage change. Do not describe current levels as changes. "
            "Permitted change types for this input: "
            + json.dumps(sorted(available_change_types(payload)))
            + ". Only these metric/reference pairs are permitted as evidence; read their exact values "
            "from the user input. Do not cite extremes as metrics: "
            + json.dumps(references, ensure_ascii=False)
        )
        if retry_code:
            instruction += f" Previous attempt was rejected ({retry_code}). Return a new complete valid analysis."
        return [{"role": "system", "content": ADMIN_PROMPT},
                {"role": "developer", "content": instruction},
                {"role": "user", "content": payload.model_dump_json()}]

    def _generate(self, client, payload):
        retry_code = None
        for attempt in range(self.max_attempts):
            error = None
            try:
                messages = self.messages(payload, retry_code)
                if len(json.dumps(messages, ensure_ascii=False).encode("utf-8")) > self.max_input_bytes:
                    raise AIAnalysisError("INPUT_TOO_LARGE")
                response = client.responses.parse(
                    model=settings.OPENAI_MODEL, input=messages,
                    text_format=AIAnalysis, max_output_tokens=self.max_output_tokens,
                    timeout=self.timeout, store=False,
                )
                if any(getattr(content, "type", None) == "refusal"
                       for item in response.output for content in getattr(item, "content", [])):
                    raise AIAnalysisError("REFUSAL")
                if response.status != "completed" or response.output_parsed is None:
                    raise AIAnalysisError("INCOMPLETE_RESPONSE", retryable=True)
                return validate_analysis(payload, response.output_parsed)
            except AIAnalysisError as exc:
                error = exc
            except InvalidAIResponse as exc:
                error = AIAnalysisError(exc.code, retryable=True)
            except ValidationError:
                error = AIAnalysisError("INVALID_OUTPUT_SCHEMA", retryable=True)
            except APITimeoutError:
                error = AIAnalysisError("TIMEOUT", retryable=True)
            except APIConnectionError:
                error = AIAnalysisError("CONNECTION_ERROR", retryable=True)
            except APIStatusError as exc:
                error = self.provider_error(exc)
            if not error.retryable or attempt + 1 == self.max_attempts:
                raise error from None
            retry_code = error.code
            time.sleep(1)
        raise AIAnalysisError("GENERATION_FAILED")  # No resultado ficticio como fallback.

    @staticmethod
    def provider_error(exc):
        codes = {"insufficient_quota": "BILLING", "model_not_found": "MODEL_ACCESS",
                 "invalid_api_key": "AUTHENTICATION"}
        if exc.code in codes:
            return AIAnalysisError(codes[exc.code])
        code = {400: "REQUEST_ERROR", 401: "AUTHENTICATION", 403: "PERMISSION",
                404: "MODEL_ACCESS", 429: "RATE_LIMIT"}.get(exc.status_code, "API_ERROR")
        # No reintentar 429 automáticamente: Retry-After podría exceder nuestro presupuesto.
        return AIAnalysisError(code, retryable=exc.status_code >= 500 or exc.status_code in (408, 409))
