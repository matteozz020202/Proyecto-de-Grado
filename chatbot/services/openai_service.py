import json
from django.conf import settings
from django.utils import timezone
from openai import (OpenAI, OpenAIError, AuthenticationError, RateLimitError,
                    PermissionDeniedError, NotFoundError, APITimeoutError)
from pydantic import ValidationError
from chatbot.prompts import BOOKING_PROMPT
from chatbot.schemas import BookingIntent


class InterpretationError(Exception):
    """Error seguro sin respuesta cruda del proveedor ni credenciales."""


class BookingInterpreter:
    def __init__(self, client=None):
        self.client = client

    def interpret(self, message, state):
        if not settings.OPENAI_API_KEY or not settings.OPENAI_MODEL:
            raise InterpretationError('configuration')
        now = timezone.localtime()
        payload = {'now': now.isoformat(), 'timezone': str(timezone.get_current_timezone()),
                   'state': state, 'message': message}
        try:
            if self.client is not None:
                return self._parse(self.client.with_options(timeout=25, max_retries=0), payload)
            with OpenAI(api_key=settings.OPENAI_API_KEY, timeout=25, max_retries=0) as client:
                return self._parse(client, payload)
        except AuthenticationError:
            raise InterpretationError('authentication') from None
        except RateLimitError as exc:
            code = 'billing' if getattr(exc, 'code', None) == 'insufficient_quota' else 'rate_limit'
            raise InterpretationError(code) from None
        except (PermissionDeniedError, NotFoundError):
            raise InterpretationError('model_access') from None
        except APITimeoutError:
            raise InterpretationError('timeout') from None
        except (OpenAIError, ValidationError, ValueError):
            raise InterpretationError('provider') from None

    @staticmethod
    def _parse(client, payload):
        response = client.responses.parse(
            model=settings.OPENAI_MODEL,
            input=[{'role': 'system', 'content': BOOKING_PROMPT},
                   {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}],
            text_format=BookingIntent, store=False, max_output_tokens=1800,
        )
        if any(getattr(content, 'type', None) == 'refusal'
               for item in response.output for content in getattr(item, 'content', [])):
            raise InterpretationError('refusal')
        if response.status != 'completed' or response.output_parsed is None:
            raise InterpretationError('incomplete')
        return BookingIntent.model_validate(response.output_parsed)
