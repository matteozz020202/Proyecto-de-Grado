"""Contratos v1.0: fixtures ilustrativos, sin acceso a BD ni a OpenAI."""

import copy
import json

from django.test import SimpleTestCase
from pydantic import ValidationError

from .ai.prompts import ADMIN_PROMPT, CONTRACT_VERSION, PROMPT_NAME
from .ai.schemas import AIAnalysis, InputContract, InsightPriority, InsightType
from .ai.validators import InvalidAIResponse, METRIC_UNITS, evidence_catalog, validate_analysis


def example_input():
    return {
        "contract_version": "1.0",
        "analysis_context": {
            "venue_id": 1, "venue_name": "Arena de demostración", "court_id": None,
            "court_name": None, "start_date": "2026-08-01", "end_date": "2026-08-31",
            "analysis_type": "HISTORICAL", "data_source": "SYNTHETIC",
            "currency": "COP", "response_language": "es",
        },
        "summary": {
            "occupancy_rate": 50, "valid_reservations": 2, "reserved_hours": 2,
            "available_hours": 4, "reservation_value": 200000, "approved_deposits": 60000,
            "pending_balance": 140000, "cancellation_rate": 0,
            "average_booking_lead_hours": None,
        },
        "reservation_status_counts": {
            "pending_payment": 0, "confirmed": 0, "completed": 2, "cancelled": 0, "expired": 0,
        },
        "occupancy_by_court": [{"court_id": 101, "court_name": "Cancha 1",
                                "reserved_hours": 2, "available_hours": 4, "occupancy_rate": 50}],
        "occupancy_by_day": [
            {"day": day, "reserved_hours": 1, "available_hours": 2, "occupancy_rate": 50}
            for day in ("Friday", "Saturday")
        ],
        "occupancy_by_time_slot": [{"time_slot": "18:00-20:00", "reserved_hours": 2,
                                    "available_hours": 4, "occupancy_rate": 50}],
        "comparisons": {"previous_period": None, "occupancy_variation_pp": None,
                        "reservations_variation_pct": None},
        "extremes": {
            "highest_occupancy_days": [{"reference": day, "value": 50} for day in ("Friday", "Saturday")],
            "lowest_occupancy_days": [{"reference": day, "value": 50} for day in ("Friday", "Saturday")],
            "highest_occupancy_time_slots": [{"reference": "18:00-20:00", "value": 50}],
            "lowest_occupancy_time_slots": [{"reference": "18:00-20:00", "value": 50}],
        },
    }


def example_output(with_insight=True):
    return {
        "contract_version": "1.0",
        "analysis_summary": "El período de demostración registra una ocupación del 50%.",
        "insights": [{
            "type": "GENERAL", "priority": "LOW",
            "finding": "La ocupación global del período es del 50%.",
            "evidence": [{"metric": "summary.occupancy_rate", "reference": None, "value": 50}],
            "recommendation": "Monitorear la evolución de la ocupación en períodos posteriores.",
            "justification": "La ocupación actual permite establecer una referencia para seguimiento.",
        }] if with_insight else [],
        "limitations": ["El análisis utiliza datos sintéticos destinados a demostración y validación funcional."],
    }


class ContractTests(SimpleTestCase):
    def setUp(self):
        self.input = example_input()
        self.output = example_output()

    def test_official_prompt_and_version(self):
        self.assertEqual(CONTRACT_VERSION, "1.0")
        self.assertEqual(PROMPT_NAME, "Cancha Lista Admin Prompt v1")
        for rule in ("Generate at most 5 insights", "Spanish", "Never alter an evidence value",
                     "return an empty insights array", "Preserve ties"):
            self.assertIn(rule, ADMIN_PROMPT)

    def test_supported_contexts(self):
        for kind in ("HISTORICAL", "FUTURE"):
            for source in ("SYNTHETIC", "PLATFORM", "HISTORICAL"):
                with self.subTest(kind=kind, source=source):
                    self.input["analysis_context"].update(analysis_type=kind, data_source=source)
                    self.assertEqual(InputContract.model_validate(self.input).analysis_context.analysis_type, kind)

    def test_nulls_empty_breakdowns_and_ties_are_preserved(self):
        parsed = InputContract.model_validate(self.input)
        self.assertIsNone(parsed.summary.average_booking_lead_hours)
        self.assertEqual(len(parsed.extremes.highest_occupancy_days), 2)
        for group in ("occupancy_by_court", "occupancy_by_day", "occupancy_by_time_slot"):
            self.input[group] = []
        self.assertEqual(InputContract.model_validate(self.input).occupancy_by_day, [])

    def test_invalid_context_and_dates(self):
        for field, value in (("analysis_type", "ALL"), ("data_source", "SYSTEM"),
                             ("currency", "USD"), ("response_language", "en"),
                             ("start_date", "2026-09-01"), ("end_date", "invalid"),
                             ("start_date", "20260801")):
            with self.subTest(field=field, value=value):
                data = example_input()
                data["analysis_context"][field] = value
                with self.assertRaises(ValidationError):
                    InputContract.model_validate(data)

    def test_percentage_boundaries_and_invalid_numbers(self):
        for value in (0, 100, 62.4, None):
            self.input["summary"]["occupancy_rate"] = value
            InputContract.model_validate(self.input)
        for value in (-1, 101, True, "50", float("nan"), float("inf")):
            with self.subTest(value=value):
                self.input["summary"]["occupancy_rate"] = value
                with self.assertRaises(ValidationError):
                    InputContract.model_validate(self.input)

    def test_negative_variations_are_valid(self):
        self.input["comparisons"]["occupancy_variation_pp"] = -20
        self.input["comparisons"]["reservations_variation_pct"] = -100
        InputContract.model_validate(self.input)

    def test_negative_hours_money_and_fractional_counts_fail(self):
        for field, value in (("reserved_hours", -1), ("pending_balance", -1),
                             ("valid_reservations", 1.5), ("valid_reservations", True)):
            with self.subTest(field=field):
                data = example_input()
                data["summary"][field] = value
                with self.assertRaises(ValidationError):
                    InputContract.model_validate(data)

    def test_duplicate_breakdown_identifiers_fail(self):
        for group in ("occupancy_by_court", "occupancy_by_day", "occupancy_by_time_slot"):
            with self.subTest(group=group):
                data = example_input()
                data[group].append(copy.deepcopy(data[group][0]))
                with self.assertRaises(ValidationError):
                    InputContract.model_validate(data)

    def test_no_unexpected_fields_or_personal_data(self):
        for target in (self.input, self.input["analysis_context"], self.input["summary"],
                       self.input["occupancy_by_court"][0]):
            target["email"] = "example@example.test"
            with self.assertRaises(ValidationError):
                InputContract.model_validate(self.input)
            del target["email"]

    def test_versions_and_missing_fields_fail(self):
        for data, schema in ((self.input, InputContract), (self.output, AIAnalysis)):
            original = data.pop("contract_version")
            with self.assertRaises(ValidationError):
                schema.model_validate(data)
            data["contract_version"] = "1.1"
            with self.assertRaises(ValidationError):
                schema.model_validate(data)
            data["contract_version"] = original
        del self.output["insights"][0]["justification"]
        with self.assertRaises(ValidationError):
            AIAnalysis.model_validate(self.output)

    def test_zero_one_and_five_insights(self):
        for count in (0, 1, 5):
            self.output["insights"] = [copy.deepcopy(example_output()["insights"][0]) for _ in range(count)]
            self.assertEqual(len(validate_analysis(self.input, self.output).insights), count)

    def test_more_than_five_insights_fail(self):
        self.output["insights"] *= 6
        with self.assertRaises(ValidationError):
            AIAnalysis.model_validate(self.output)

    def test_enums(self):
        for kind in InsightType:
            self.output["insights"][0]["type"] = kind.value
            AIAnalysis.model_validate(self.output)
        for priority in InsightPriority:
            self.output["insights"][0]["priority"] = priority.value
            AIAnalysis.model_validate(self.output)
        for field in ("type", "priority"):
            data = example_output()
            data["insights"][0][field] = "UNSUPPORTED"
            with self.assertRaises(ValidationError):
                AIAnalysis.model_validate(data)

    def test_empty_evidence_and_blank_text_fail(self):
        for field, value in (("evidence", []), ("finding", "  "), ("recommendation", "")):
            with self.subTest(field=field):
                data = example_output()
                data["insights"][0][field] = value
                with self.assertRaises(ValidationError):
                    AIAnalysis.model_validate(data)

    def test_output_extra_fields_including_unit_fail(self):
        for target in (self.output, self.output["insights"][0], self.output["insights"][0]["evidence"][0]):
            target["unit"] = "%"
            with self.assertRaises(ValidationError):
                AIAnalysis.model_validate(self.output)
            del target["unit"]

    def test_json_and_models_and_malformed_json(self):
        validate_analysis(json.dumps(self.input), json.dumps(self.output))
        validate_analysis(InputContract.model_validate(self.input), AIAnalysis.model_validate(self.output))
        with self.assertRaises(ValidationError):
            validate_analysis(self.input, "{broken")


class EvidenceTests(SimpleTestCase):
    def setUp(self):
        self.input = example_input()
        self.output = example_output()

    def evidence(self, metric, reference, value):
        self.output["insights"][0]["evidence"] = [{"metric": metric, "reference": reference, "value": value}]

    def test_exact_values_and_numeric_equivalence(self):
        for value in (50, 50.0):
            self.evidence("summary.occupancy_rate", None, value)
            validate_analysis(self.input, self.output)

    def test_mismatch_without_tolerance(self):
        for value in (31, 50.00000000001):
            self.evidence("summary.occupancy_rate", None, value)
            with self.assertRaises(InvalidAIResponse):
                validate_analysis(self.input, self.output)

    def test_all_breakdown_reference_conventions(self):
        for metric, reference in (("occupancy_by_court.occupancy_rate", "101"),
                                  ("occupancy_by_day.occupancy_rate", "Friday"),
                                  ("occupancy_by_time_slot.occupancy_rate", "18:00-20:00")):
            self.evidence(metric, reference, 50)
            validate_analysis(self.input, self.output)
            self.evidence(metric, "wrong", 50)
            with self.assertRaises(InvalidAIResponse):
                validate_analysis(self.input, self.output)

    def test_global_reference_must_be_null(self):
        self.evidence("summary.occupancy_rate", "Friday", 50)
        with self.assertRaises(InvalidAIResponse):
            validate_analysis(self.input, self.output)

    def test_unknown_metric_and_null_metric_are_rejected(self):
        for metric in ("summary.invented", "summary.average_booking_lead_hours",
                       "comparisons.previous_period.occupancy_rate", "comparisons.occupancy_variation_pp"):
            self.evidence(metric, None, 0)
            with self.assertRaises(InvalidAIResponse):
                validate_analysis(self.input, self.output)

    def test_every_catalog_metric_can_be_matched(self):
        self.input["summary"]["average_booking_lead_hours"] = 38.6
        self.input["comparisons"] = {
            "previous_period": {"start_date": "2026-07-01", "end_date": "2026-07-31",
                                "occupancy_rate": 60, "valid_reservations": 4},
            "occupancy_variation_pp": -10, "reservations_variation_pct": -50,
        }
        catalog = evidence_catalog(InputContract.model_validate(self.input))
        self.assertEqual({metric for metric, ref in catalog}, set(METRIC_UNITS))
        for (metric, reference), value in catalog.items():
            self.evidence(metric, reference, value)
            validate_analysis(self.input, self.output)

    def test_bool_string_null_and_nonfinite_evidence_fail(self):
        for value in (True, "50", None, float("nan"), float("inf")):
            with self.subTest(value=value):
                self.evidence("summary.occupancy_rate", None, value)
                with self.assertRaises(ValidationError):
                    validate_analysis(self.input, self.output)

    def test_invalid_later_insight_prevents_partial_result(self):
        self.output["insights"].append(copy.deepcopy(self.output["insights"][0]))
        self.output["insights"][1]["evidence"][0]["value"] = 51
        with self.assertRaises(InvalidAIResponse):
            validate_analysis(self.input, self.output)

    def test_synthetic_notice_required_even_without_insights(self):
        for count in (0, 1):
            self.output = example_output(bool(count))
            self.output["limitations"] = []
            with self.assertRaises(InvalidAIResponse):
                validate_analysis(self.input, self.output)

    def test_synthetic_notice_only_in_limitations(self):
        self.output["analysis_summary"] = self.output["limitations"][0]
        self.output["limitations"] = ["No hay información suficiente."]
        with self.assertRaises(InvalidAIResponse):
            validate_analysis(self.input, self.output)

    def test_explicit_synthetic_demo_notice_and_negation(self):
        for text in ("Datos sintéticos para demostración.", "DATOS SINTÉTICOS para pruebas."):
            self.output["limitations"] = [text]
            validate_analysis(self.input, self.output)
        for text in ("Datos sintéticos.", "Datos reales para demostración.",
                     "No se utilizan datos sintéticos para demostración."):
            self.output["limitations"] = [text]
            with self.assertRaises(InvalidAIResponse):
                validate_analysis(self.input, self.output)

    def test_non_synthetic_sources_do_not_require_notice(self):
        self.output["limitations"] = []
        for source in ("PLATFORM", "HISTORICAL"):
            self.input["analysis_context"]["data_source"] = source
            validate_analysis(self.input, self.output)

    def test_mutated_model_is_revalidated(self):
        output = AIAnalysis.model_validate(self.output)
        output.insights[0].evidence[0].value = True
        with self.assertRaises(ValidationError):
            validate_analysis(self.input, output)
