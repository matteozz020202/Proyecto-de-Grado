"""Pruebas aisladas del comando H4-02. Nunca consumen la API ni requieren claves."""

import io
import json
import logging
from types import SimpleNamespace
from unittest.mock import patch

import httpx2
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

from .ai.prompts import ADMIN_PROMPT
from .ai.schemas import AIAnalysis
from .management.commands.probar_openai import Command, EXAMPLE_PATH
from .test_ai import example_output


@override_settings(OPENAI_API_KEY="credential-for-offline-tests", OPENAI_MODEL="configured-test-model")
class OpenAIConnectionTests(SimpleTestCase):
    def setUp(self):
        self.stdout = io.StringIO()
        self.factory_patch = patch("reservations.management.commands.probar_openai.OpenAI")
        self.factory = self.factory_patch.start()
        self.addCleanup(self.factory_patch.stop)
        self.client = self.factory.return_value.__enter__.return_value
        self.client.with_options.return_value = self.client
        self.client.responses.create.return_value = SimpleNamespace(status="completed", output_text="OK")
        self.client.responses.parse.return_value = SimpleNamespace(
            status="completed", output=[], output_parsed=AIAnalysis.model_validate(example_output())
        )

    def run_command(self, **kwargs):
        call_command("probar_openai", stdout=self.stdout, **kwargs)

    def test_missing_config_stops_before_api(self):
        for key, model in (("", ""), ("", "configured-test-model"), ("credential-for-offline-tests", "")):
            with override_settings(OPENAI_API_KEY=key, OPENAI_MODEL=model):
                with self.assertRaisesRegex(CommandError, "Configuración incompleta"):
                    self.run_command()
        self.factory.assert_not_called()

    def test_simple_uses_config_without_administrative_prompt(self):
        self.run_command(fase="simple")
        self.factory.assert_called_once_with(api_key="credential-for-offline-tests", timeout=30.0, max_retries=0)
        kwargs = self.client.responses.create.call_args.kwargs
        self.assertEqual(kwargs["model"], "configured-test-model")
        self.assertNotIn(ADMIN_PROMPT, kwargs.values())
        self.assertFalse(kwargs["store"])
        self.client.responses.parse.assert_not_called()
        self.assertIn("SIMPLE_OK", self.stdout.getvalue())
        self.assertNotIn("credential-for-offline-tests", self.stdout.getvalue())

    def test_both_phases_run_in_order(self):
        self.run_command()
        self.assertEqual([call[0] for call in self.client.responses.mock_calls], ["create", "parse"])
        self.assertIn("STRUCTURED_OK", self.stdout.getvalue())

    def test_failed_simple_prevents_structured_call(self):
        self.client.responses.create.return_value.output_text = ""
        with self.assertRaisesRegex(CommandError, "SIMPLE_INCOMPLETE"):
            self.run_command()
        self.client.responses.parse.assert_not_called()

    def test_structured_reuses_prompt_schema_and_validators(self):
        self.run_command(fase="structured")
        kwargs = self.client.responses.parse.call_args.kwargs
        self.assertIs(kwargs["text_format"], AIAnalysis)
        self.assertEqual(kwargs["input"][0], {"role": "system", "content": ADMIN_PROMPT})
        self.assertEqual(kwargs["input"][-1]["role"], "user")
        self.assertIn('"metric": "summary.occupancy_rate", "reference": null', kwargs["input"][1]["content"])
        self.assertIn('"metric": "occupancy_by_court.occupancy_rate", "reference": "101"', kwargs["input"][1]["content"])
        self.assertEqual(json.loads(kwargs["input"][-1]["content"])["contract_version"], "1.0")
        self.assertFalse(kwargs["store"])

    def test_structured_zero_insights_is_valid(self):
        self.client.responses.parse.return_value.output_parsed = AIAnalysis.model_validate(example_output(False))
        self.run_command(fase="structured")
        self.assertIn("0 insights", self.stdout.getvalue())

    def test_evidence_mismatch_and_missing_synthetic_notice_fail(self):
        for invalid in ("evidence", "notice"):
            data = example_output()
            if invalid == "evidence":
                data["insights"][0]["evidence"][0]["value"] = 31
            else:
                data["limitations"] = []
            self.client.responses.parse.return_value.output_parsed = AIAnalysis.model_validate(data)
            with self.assertRaisesRegex(CommandError, "AI_ANALYSIS_ERROR"):
                self.run_command(fase="structured")
        self.assertNotIn("STRUCTURED_OK", self.stdout.getvalue())

    def test_empty_or_incomplete_structured_response_fails(self):
        for status, parsed in (("completed", None), ("incomplete", AIAnalysis.model_validate(example_output()))):
            self.client.responses.parse.return_value = SimpleNamespace(status=status, output=[], output_parsed=parsed)
            with self.assertRaisesRegex(CommandError, "INCOMPLETE_RESPONSE"):
                self.run_command(fase="structured")

    def test_unreadable_input_prevents_parse(self):
        with self.assertRaisesRegex(CommandError, "INPUT_ERROR"):
            self.run_command(fase="structured", input="/missing/contract.json")
        self.client.responses.parse.assert_not_called()

    def test_provider_errors_are_classified_without_raw_message_or_key(self):
        request = httpx2.Request("POST", "https://api.openai.com/v1/responses")
        for status, code, expected in ((429, "insufficient_quota", "BILLING"),
                                       (404, "model_not_found", "MODEL_ACCESS"),
                                       (401, "invalid_api_key", "AUTHENTICATION"),
                                       (400, "invalid_json_schema", "REQUEST_ERROR"),
                                       (429, "rate_limit_exceeded", "RATE_LIMIT")):
            response = httpx2.Response(status, request=request)
            self.client.responses.create.side_effect = APIStatusError(
                "credential-for-offline-tests", response=response, body={"code": code}
            )
            with self.assertRaisesRegex(CommandError, expected) as caught:
                self.run_command()
            self.assertNotIn("credential-for-offline-tests", str(caught.exception))
            self.assertIsNone(caught.exception.__cause__)
        self.client.responses.parse.assert_not_called()

    def test_connection_and_timeout_are_bounded(self):
        request = httpx2.Request("POST", "https://api.openai.com/v1/responses")
        for error, message in ((APIConnectionError(request=request), "CONNECTION_ERROR"),
                               (APITimeoutError(request=request), "TIMEOUT")):
            self.client.responses.create.side_effect = error
            with self.assertRaisesRegex(CommandError, message):
                self.run_command()

    def test_logging_state_restored_on_error(self):
        previous = logging.root.manager.disable
        self.client.responses.create.return_value.output_text = ""
        with self.assertRaises(CommandError):
            self.run_command()
        self.assertEqual(logging.root.manager.disable, previous)


@override_settings(OPENAI_MODEL="configured-test-model")
class RealSDKOfflineParseTests(SimpleTestCase):
    def test_installed_sdk_parses_existing_schema_and_command_validates(self):
        """SDK real + transporte HTTP simulado: prueba output_parsed sin pagar API."""
        requests = []

        def respond(request):
            body = json.loads(request.content)
            requests.append(body)
            text = json.dumps(example_output()) if "format" in body.get("text", {}) else "OK"
            return httpx2.Response(200, json={
                "id": "resp_offline", "object": "response", "created_at": 0,
                "status": "completed", "error": None, "incomplete_details": None,
                "instructions": None, "model": "configured-test-model",
                "output": [{"id": "msg_offline", "type": "message", "role": "assistant",
                            "status": "completed", "content": [{"type": "output_text",
                            "text": text, "annotations": []}]}],
                "parallel_tool_calls": False, "tools": [], "tool_choice": "auto",
            })

        output = io.StringIO()
        command = Command(stdout=output)
        with OpenAI(api_key="credential-for-offline-tests", max_retries=0,
                    http_client=httpx2.Client(transport=httpx2.MockTransport(respond))) as client:
            command.simple(client)
            command.structured(client, EXAMPLE_PATH)
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[1]["text"]["format"]["name"], "AIAnalysis")
        self.assertTrue(requests[1]["text"]["format"]["strict"])
        self.assertIn("STRUCTURED_OK", output.getvalue())
