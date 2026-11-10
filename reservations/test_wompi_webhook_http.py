
import json
from unittest.mock import patch
from django.db import DatabaseError
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase
from django.urls import reverse

from .wompi_client import WompiAPIError


class WompiWebhookHTTPTests(SimpleTestCase):

    def setUp(self):
        self.url = reverse(
            "reservations:wompi_webhook"
        )

        self.event = {
            "event": "transaction.updated",
            "environment": "test",
            "data": {
                "transaction": {
                    "id": "TX-WEBHOOK-001",
                    "status": "APPROVED",
                    "amount_in_cents": 3900000,
                }
            },
            "timestamp": 1793574000,
            "signature": {
                "properties": [
                    "transaction.id",
                    "transaction.status",
                    "transaction.amount_in_cents",
                ],
                "checksum": "TEST-CHECKSUM",
            },
        }

    def send_event(self, event=None):
        if event is None:
            event = self.event

        return self.client.post(
            self.url,
            data=json.dumps(event),
            content_type="application/json",
        )

    @patch.dict(
        "os.environ",
        {"WOMPI_EVENTS_SECRET": "test_events_EXAMPLE"},
    )
    @patch(
        "reservations.wompi_webhook."
        "process_wompi_transaction_notification"
    )
    @patch(
        "reservations.wompi_webhook."
        "verify_wompi_event",
        return_value=True,
    )
    def test_valid_event_is_processed(
        self,
        mock_verify,
        mock_process,
    ):
        response = self.send_event()

        self.assertEqual(response.status_code, 200)

        mock_verify.assert_called_once_with(
            self.event,
            "test_events_EXAMPLE",
        )

        mock_process.assert_called_once_with(
            "TX-WEBHOOK-001"
        )

    @patch.dict(
        "os.environ",
        {"WOMPI_EVENTS_SECRET": "test_events_EXAMPLE"},
    )
    @patch(
        "reservations.wompi_webhook."
        "process_wompi_transaction_notification"
    )
    @patch(
        "reservations.wompi_webhook."
        "verify_wompi_event",
        return_value=False,
    )
    def test_invalid_signature_is_rejected(
        self,
        mock_verify,
        mock_process,
    ):
        response = self.send_event()

        self.assertEqual(response.status_code, 400)
        mock_process.assert_not_called()

    @patch.dict(
        "os.environ",
        {"WOMPI_EVENTS_SECRET": ""},
    )
    def test_missing_secret_is_rejected(self):
        response = self.send_event()

        self.assertEqual(response.status_code, 503)

    @patch.dict(
        "os.environ",
        {"WOMPI_EVENTS_SECRET": "test_events_EXAMPLE"},
    )
    def test_invalid_json_is_rejected(self):
        response = self.client.post(
            self.url,
            data="{invalid",
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)

    @patch.dict(
        "os.environ",
        {"WOMPI_EVENTS_SECRET": "test_events_EXAMPLE"},
    )
    @patch(
        "reservations.wompi_webhook."
        "process_wompi_transaction_notification"
    )
    @patch(
        "reservations.wompi_webhook."
        "verify_wompi_event",
        return_value=True,
    )
    def test_production_event_is_rejected(
        self,
        mock_verify,
        mock_process,
    ):
        event = {
            **self.event,
            "environment": "prod",
        }

        response = self.send_event(event)

        self.assertEqual(response.status_code, 400)
        mock_process.assert_not_called()

    @patch.dict(
        "os.environ",
        {"WOMPI_EVENTS_SECRET": "test_events_EXAMPLE"},
    )
    @patch(
        "reservations.wompi_webhook."
        "process_wompi_transaction_notification"
    )
    @patch(
        "reservations.wompi_webhook."
        "verify_wompi_event",
        return_value=True,
    )
    def test_provider_failure_returns_503(
        self,
        mock_verify,
        mock_process,
    ):
        mock_process.side_effect = WompiAPIError(
            "Servicio no disponible."
        )

        response = self.send_event()

        self.assertEqual(response.status_code, 503)

    @patch.dict(
        "os.environ",
        {"WOMPI_EVENTS_SECRET": "test_events_EXAMPLE"},
    )
    @patch(
        "reservations.wompi_webhook."
        "process_wompi_transaction_notification"
    )
    @patch(
        "reservations.wompi_webhook."
        "verify_wompi_event",
        return_value=True,
    )
    def test_invalid_transaction_returns_400(
        self,
        mock_verify,
        mock_process,
    ):
        mock_process.side_effect = ValidationError(
            "Referencia incorrecta."
        )

        response = self.send_event()

        self.assertEqual(response.status_code, 400)

    def test_get_method_is_not_allowed(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 405)


    @patch.dict(
        "os.environ",
        {"WOMPI_EVENTS_SECRET": "test_events_EXAMPLE"},
    )
    @patch(
        "reservations.wompi_webhook."
        "process_wompi_transaction_notification"
    )
    @patch(
        "reservations.wompi_webhook."
        "verify_wompi_event",
        return_value=True,
    )
    def test_duplicate_webhook_returns_200(
        self,
        mock_verify,
        mock_process,
    ):
        first_response = self.send_event()
        second_response = self.send_event()

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)

        self.assertEqual(mock_process.call_count, 2)

        mock_process.assert_any_call("TX-WEBHOOK-001")

    @patch.dict(
        "os.environ",
        {"WOMPI_EVENTS_SECRET": "test_events_EXAMPLE"},
    )
    @patch(
        "reservations.wompi_webhook."
        "process_wompi_transaction_notification"
    )
    @patch(
        "reservations.wompi_webhook."
        "verify_wompi_event",
        return_value=True,
    )
    def test_retry_after_provider_failure(
        self,
        mock_verify,
        mock_process,
    ):
        mock_process.side_effect = [
            WompiAPIError("Wompi temporalmente no disponible"),
            None,
        ]

        first_response = self.send_event()
        self.assertEqual(first_response.status_code, 503)

        second_response = self.send_event()
        self.assertEqual(second_response.status_code, 200)

        self.assertEqual(mock_process.call_count, 2)

    @patch.dict(
        "os.environ",
        {"WOMPI_EVENTS_SECRET": "test_events_EXAMPLE"},
    )
    @patch(
        "reservations.wompi_webhook."
        "process_wompi_transaction_notification"
    )
    @patch(
        "reservations.wompi_webhook."
        "verify_wompi_event",
        return_value=True,
    )
    def test_retry_after_database_failure(
        self,
        mock_verify,
        mock_process,
    ):
        mock_process.side_effect = [
            DatabaseError("Error temporal de PostgreSQL"),
            None,
        ]

        first_response = self.send_event()
        self.assertEqual(first_response.status_code, 503)

        second_response = self.send_event()
        self.assertEqual(second_response.status_code, 200)

        self.assertEqual(mock_process.call_count, 2)
