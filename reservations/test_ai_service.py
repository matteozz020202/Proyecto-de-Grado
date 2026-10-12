"""Servicio y validación de cambios: pruebas sin red ni base de datos."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx2
from django.test import SimpleTestCase, override_settings
from openai import APIConnectionError, APIStatusError, APITimeoutError
from pydantic import ValidationError

from .ai.schemas import AIAnalysis
from .ai.services import AIAnalysisError, AIAnalysisService
from .ai.validators import InvalidAIResponse, validate_analysis
from .test_ai import example_input, example_output


def comparison_input():
    data = example_input()
    data["comparisons"] = {
        "previous_period": {"start_date": "2026-07-01", "end_date": "2026-07-31",
                            "occupancy_rate": 40, "valid_reservations": 4},
        "occupancy_variation_pp": 10, "reservations_variation_pct": -50,
    }
    return data


def change_output(kind="OCCUPANCY_CHANGE"):
    output = example_output()
    insight = output["insights"][0]
    insight["type"] = kind
    metric, value = ("occupancy_variation_pp", 10) if kind == "OCCUPANCY_CHANGE" else ("reservations_variation_pct", -50)
    insight["evidence"] = [{"metric": "comparisons." + metric, "reference": None, "value": value}]
    return output


class ChangeValidationTests(SimpleTestCase):
    def test_historical_and_future_valid_changes(self):
        for analysis in ("HISTORICAL", "FUTURE"):
            for kind in ("OCCUPANCY_CHANGE", "RESERVATION_CHANGE"):
                with self.subTest(analysis=analysis, kind=kind):
                    data = comparison_input()
                    data["analysis_context"]["analysis_type"] = analysis
                    validate_analysis(data, change_output(kind))

    def test_original_observed_problem_is_rejected(self):
        output = example_output()
        output["insights"][0]["type"] = "OCCUPANCY_CHANGE"
        with self.assertRaises(InvalidAIResponse) as caught:
            validate_analysis(example_input(), output)
        self.assertEqual(caught.exception.code, "MISSING_CHANGE_COMPARISON")

    def test_current_level_is_not_change_evidence(self):
        for kind in ("OCCUPANCY_CHANGE", "RESERVATION_CHANGE"):
            output = example_output()
            output["insights"][0]["type"] = kind
            with self.assertRaises(InvalidAIResponse) as caught:
                validate_analysis(comparison_input(), output)
            self.assertEqual(caught.exception.code, "MISSING_CHANGE_EVIDENCE")

    def test_missing_period_or_metric_or_variation_fails(self):
        for kind, metric, variation in (("OCCUPANCY_CHANGE", "occupancy_rate", "occupancy_variation_pp"),
                                        ("RESERVATION_CHANGE", "valid_reservations", "reservations_variation_pct")):
            for missing in ("period", "previous", "current", "variation"):
                with self.subTest(kind=kind, missing=missing):
                    data = comparison_input()
                    if missing == "period":
                        data["comparisons"]["previous_period"] = None
                    elif missing == "previous":
                        data["comparisons"]["previous_period"][metric] = None
                    elif missing == "current":
                        data["summary"][metric] = None
                    else:
                        data["comparisons"][variation] = None
                    # Evidencia actual válida: comprobamos la precondición semántica.
                    output = example_output()
                    output["insights"][0]["type"] = kind
                    output["insights"][0]["evidence"] = [{"metric": "reservation_status_counts.completed",
                                                          "reference": None, "value": 2}]
                    with self.assertRaises(InvalidAIResponse) as caught:
                        validate_analysis(data, output)
                    self.assertEqual(caught.exception.code, "MISSING_CHANGE_COMPARISON")

    def test_zero_previous_reservations_cannot_support_percentage_change(self):
        data = comparison_input()
        data["comparisons"]["previous_period"]["valid_reservations"] = 0
        with self.assertRaises(InvalidAIResponse) as caught:
            validate_analysis(data, change_output("RESERVATION_CHANGE"))
        self.assertEqual(caught.exception.code, "MISSING_CHANGE_COMPARISON")

    def test_zero_previous_occupancy_can_support_percentage_points(self):
        data = comparison_input()
        data["comparisons"]["previous_period"]["occupancy_rate"] = 0
        data["comparisons"]["occupancy_variation_pp"] = 50
        output = change_output()
        output["insights"][0]["evidence"][0]["value"] = 50
        validate_analysis(data, output)

    def test_empty_insights_still_need_synthetic_notice(self):
        output = example_output(False)
        validate_analysis(example_input(), output)
        output["limitations"] = []
        with self.assertRaises(InvalidAIResponse) as caught:
            validate_analysis(example_input(), output)
        self.assertEqual(caught.exception.code, "SYNTHETIC_NOTICE_MISSING")


@override_settings(OPENAI_API_KEY="credential-for-offline-tests", OPENAI_MODEL="configured-test-model")
class ServiceTests(SimpleTestCase):
    def setUp(self):
        self.client = MagicMock()
        self.client.with_options.return_value = self.client
        self.output = AIAnalysis.model_validate(example_output())
        self.client.responses.parse.return_value = self.response(self.output)
        self.sleep_patch = patch("reservations.ai.services.time.sleep")
        self.sleep = self.sleep_patch.start()
        self.addCleanup(self.sleep_patch.stop)

    @staticmethod
    def response(parsed, status="completed", output=None):
        return SimpleNamespace(status=status, output_parsed=parsed, output=output or [])

    def generate(self, data=None, **kwargs):
        return AIAnalysisService(client=self.client, **kwargs).generate(data or example_input())

    def test_success_uses_existing_schema_and_config(self):
        result = self.generate()
        self.assertIsInstance(result, AIAnalysis)
        request = self.client.responses.parse.call_args.kwargs
        self.assertIs(request["text_format"], AIAnalysis)
        self.assertEqual(request["model"], "configured-test-model")
        self.assertFalse(request["store"])
        self.assertEqual(request["timeout"], 30)
        self.assertEqual(request["max_output_tokens"], 4096)
        self.assertNotIn("credential-for-offline-tests", json.dumps(request["input"]))
        self.assertIn("Permitted change types for this input: []", request["input"][1]["content"])
        self.client.with_options.assert_called_once_with(max_retries=0, timeout=30.0)

    def test_owned_client_is_closed_and_sdk_retries_disabled(self):
        with patch("reservations.ai.services.OpenAI") as factory:
            factory.return_value.__enter__.return_value = self.client
            AIAnalysisService().generate(example_input())
        factory.assert_called_once_with(api_key="credential-for-offline-tests", timeout=30.0, max_retries=0)
        factory.return_value.__exit__.assert_called_once()

    def test_invalid_input_prevents_network_and_personal_data(self):
        data = example_input()
        data["email"] = "private@example.test"
        with self.assertRaises(AIAnalysisError) as caught:
            self.generate(data)
        self.assertEqual(caught.exception.code, "INVALID_INPUT")
        self.client.responses.parse.assert_not_called()

    def test_configuration_and_input_size_prevent_network(self):
        with override_settings(OPENAI_MODEL=""):
            with self.assertRaisesRegex(AIAnalysisError, "CONFIGURATION_ERROR"):
                self.generate()
        with self.assertRaisesRegex(AIAnalysisError, "INPUT_TOO_LARGE"):
            self.generate(max_input_bytes=1)
        self.client.responses.parse.assert_not_called()

    def test_invalid_limits_are_rejected(self):
        for options in ({"timeout": 0}, {"timeout": float("nan")}, {"timeout": 31},
                        {"max_attempts": 3}, {"max_attempts": True}, {"max_input_bytes": 0},
                        {"max_output_tokens": 4097}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                AIAnalysisService(**options)

    def test_zero_insights_is_a_success(self):
        self.client.responses.parse.return_value = self.response(AIAnalysis.model_validate(example_output(False)))
        self.assertEqual(self.generate().insights, [])

    def test_rejected_change_retries_once_with_safe_feedback(self):
        wrong = example_output()
        wrong["insights"][0]["type"] = "OCCUPANCY_CHANGE"
        self.client.responses.parse.side_effect = [self.response(AIAnalysis.model_validate(wrong)),
                                                 self.response(self.output)]
        self.generate()
        self.assertEqual(self.client.responses.parse.call_count, 2)
        retry = self.client.responses.parse.call_args.kwargs["input"]
        self.assertIn("MISSING_CHANGE_COMPARISON", retry[1]["content"])
        self.sleep.assert_called_once_with(1)

    def test_invalid_responses_never_return_partial_or_fake_result(self):
        for invalid in ("value", "notice", "change"):
            with self.subTest(invalid=invalid):
                data = example_output()
                if invalid == "value":
                    data["insights"][0]["evidence"][0]["value"] = 31
                elif invalid == "notice":
                    data["limitations"] = []
                else:
                    data["insights"][0]["type"] = "RESERVATION_CHANGE"
                self.client.responses.parse.reset_mock()
                self.client.responses.parse.return_value = self.response(AIAnalysis.model_validate(data))
                with self.assertRaises(AIAnalysisError) as caught:
                    self.generate()
                self.assertTrue(caught.exception.retryable)
                self.assertEqual(self.client.responses.parse.call_count, 2)
                self.assertIsNone(caught.exception.__cause__)

    def test_incomplete_and_schema_failures_are_bounded(self):
        self.client.responses.parse.return_value = self.response(None, status="incomplete")
        with self.assertRaisesRegex(AIAnalysisError, "INCOMPLETE_RESPONSE"):
            self.generate()
        self.assertEqual(self.client.responses.parse.call_count, 2)
        self.client.responses.parse.reset_mock()
        try:
            AIAnalysis.model_validate({})
        except ValidationError as error:
            self.client.responses.parse.side_effect = error
        with self.assertRaisesRegex(AIAnalysisError, "INVALID_OUTPUT_SCHEMA"):
            self.generate()
        self.assertEqual(self.client.responses.parse.call_count, 2)

    def test_refusal_is_not_retried(self):
        refusal = SimpleNamespace(content=[SimpleNamespace(type="refusal")])
        self.client.responses.parse.return_value = self.response(None, output=[refusal])
        with self.assertRaisesRegex(AIAnalysisError, "REFUSAL"):
            self.generate()
        self.client.responses.parse.assert_called_once()

    def test_provider_permanent_errors_not_retried_or_exposed(self):
        request = httpx2.Request("POST", "https://api.openai.com/v1/responses")
        for status, code, expected in ((401, "invalid_api_key", "AUTHENTICATION"),
                                       (404, "model_not_found", "MODEL_ACCESS"),
                                       (429, "insufficient_quota", "BILLING"),
                                       (429, "rate_limit_exceeded", "RATE_LIMIT"),
                                       (400, "invalid_json_schema", "REQUEST_ERROR")):
            self.client.responses.parse.reset_mock()
            self.client.responses.parse.side_effect = APIStatusError(
                "private provider message", response=httpx2.Response(status, request=request), body={"code": code}
            )
            with self.assertRaisesRegex(AIAnalysisError, expected) as caught:
                self.generate()
            self.assertNotIn("private", str(caught.exception))
            self.assertFalse(caught.exception.retryable)
            self.client.responses.parse.assert_called_once()

    def test_transient_errors_retry_once(self):
        request = httpx2.Request("POST", "https://api.openai.com/v1/responses")
        for error in (APITimeoutError(request=request), APIConnectionError(request=request),
                      APIStatusError("server error", response=httpx2.Response(503, request=request), body={})):
            self.client.responses.parse.reset_mock()
            self.client.responses.parse.side_effect = [error, self.response(self.output)]
            self.generate()
            self.assertEqual(self.client.responses.parse.call_count, 2)

    def test_one_attempt_disables_retry(self):
        self.client.responses.parse.return_value = self.response(None)
        with self.assertRaises(AIAnalysisError):
            self.generate(max_attempts=1)
        self.client.responses.parse.assert_called_once()
        self.sleep.assert_not_called()
