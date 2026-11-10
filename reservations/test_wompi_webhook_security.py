
import hashlib
import json

from unittest.mock import patch

from django.test import SimpleTestCase
from django.urls import reverse


class WompiWebhookSecurityTests(SimpleTestCase):

    SECRET = "test_events_EXAMPLE"

    def setUp(self):
        self.url = reverse("reservations:wompi_webhook")

        self.event = {
            "event": "transaction.updated",
            "environment": "test",
            "data": {
                "transaction": {
                    "id": "TX-SECURITY-001",
                    "status": "APPROVED",
                    "amount_in_cents": 3900000,
                    "reference": "CL-1-TEST",
                }
            },
            "timestamp": 1793574000,
            "signature": {
                "properties": [
                    "transaction.id",
                    "transaction.status",
                    "transaction.amount_in_cents",
                ],
                "checksum": "",
            },
        }

    def sign_event(self, event):
        values = []

        for property_path in event["signature"]["properties"]:
            value = event["data"]

            for part in property_path.split("."):
                value = value[part]

            values.append(str(value))

        values.append(str(event["timestamp"]))
        values.append(self.SECRET)

        event["signature"]["checksum"] = hashlib.sha256(
            "".join(values).encode("utf-8")
        ).hexdigest()

        return event

    def post_event(self, event):
        return self.client.post(
            self.url,
            data=json.dumps(event),
            content_type="application/json",
        )

    @patch.dict(
        "os.environ",
        {"WOMPI_EVENTS_SECRET": SECRET},
    )
    @patch(
        "reservations.wompi_webhook."
        "process_wompi_transaction_notification"
    )
    def test_genuinely_signed_event_is_accepted(
        self,
        mock_process,
    ):
        event = self.sign_event(self.event)

        response = self.post_event(event)

        self.assertEqual(response.status_code, 200)

        mock_process.assert_called_once_with(
            "TX-SECURITY-001"
        )

    @patch.dict(
        "os.environ",
        {"WOMPI_EVENTS_SECRET": SECRET},
    )
    @patch(
        "reservations.wompi_webhook."
        "process_wompi_transaction_notification"
    )
    def test_modified_transaction_id_is_rejected(
        self,
        mock_process,
    ):
        event = self.sign_event(self.event)

        event["data"]["transaction"]["id"] = (
            "TX-FRAUDULENT-001"
        )

        response = self.post_event(event)

        self.assertEqual(response.status_code, 400)
        mock_process.assert_not_called()

    @patch.dict(
        "os.environ",
        {"WOMPI_EVENTS_SECRET": SECRET},
    )
    @patch(
        "reservations.wompi_webhook."
        "process_wompi_transaction_notification"
    )
    def test_modified_status_is_rejected(
        self,
        mock_process,
    ):
        self.event["data"]["transaction"]["status"] = (
            "DECLINED"
        )

        event = self.sign_event(self.event)

        event["data"]["transaction"]["status"] = (
            "APPROVED"
        )

        response = self.post_event(event)

        self.assertEqual(response.status_code, 400)
        mock_process.assert_not_called()

    @patch.dict(
        "os.environ",
        {"WOMPI_EVENTS_SECRET": SECRET},
    )
    @patch(
        "reservations.wompi_webhook."
        "process_wompi_transaction_notification"
    )
    def test_modified_timestamp_is_rejected(
        self,
        mock_process,
    ):
        event = self.sign_event(self.event)

        event["timestamp"] += 1000

        response = self.post_event(event)

        self.assertEqual(response.status_code, 400)
        mock_process.assert_not_called()

    @patch.dict(
        "os.environ",
        {"WOMPI_EVENTS_SECRET": SECRET},
    )
    @patch(
        "reservations.wompi_webhook."
        "process_wompi_transaction_notification"
    )
    def test_different_signed_property_order(
        self,
        mock_process,
    ):
        self.event["signature"]["properties"] = [
            "transaction.amount_in_cents",
            "transaction.id",
            "transaction.status",
        ]

        event = self.sign_event(self.event)

        response = self.post_event(event)

        self.assertEqual(response.status_code, 200)

        mock_process.assert_called_once_with(
            "TX-SECURITY-001"
        )

    @patch.dict(
        "os.environ",
        {"WOMPI_EVENTS_SECRET": SECRET},
    )
    @patch(
        "reservations.wompi_webhook."
        "process_wompi_transaction_notification"
    )
    def test_wrong_events_secret_is_rejected(
        self,
        mock_process,
    ):
        event = self.sign_event(self.event)

        with patch.dict(
            "os.environ",
            {
                "WOMPI_EVENTS_SECRET":
                "test_events_DIFFERENT"
            },
        ):
            response = self.post_event(event)

        self.assertEqual(response.status_code, 400)
        mock_process.assert_not_called()

    @patch.dict(
        "os.environ",
        {"WOMPI_EVENTS_SECRET": SECRET},
    )
    @patch(
        "reservations.wompi_webhook."
        "process_wompi_transaction_notification"
    )
    def test_empty_signed_properties_are_rejected(
        self,
        mock_process,
    ):
        self.event["signature"]["properties"] = []

        event = self.sign_event(self.event)

        response = self.post_event(event)

        self.assertEqual(response.status_code, 400)
        mock_process.assert_not_called()

    @patch.dict(
        "os.environ",
        {"WOMPI_EVENTS_SECRET": SECRET},
    )
    @patch(
        "reservations.wompi_webhook."
        "process_wompi_transaction_notification"
    )
    def test_unsigned_transaction_id_is_rejected(
        self,
        mock_process,
    ):
        self.event["signature"]["properties"] = [
            "transaction.status",
            "transaction.amount_in_cents",
        ]

        event = self.sign_event(self.event)

        # La firma sigue siendo correcta porque
        # el ID no forma parte de sus propiedades.
        event["data"]["transaction"]["id"] = (
            "TX-UNSIGNED-999"
        )

        response = self.post_event(event)

        self.assertEqual(response.status_code, 400)
        mock_process.assert_not_called()

    @patch.dict(
        "os.environ",
        {"WOMPI_EVENTS_SECRET": SECRET},
    )
    @patch(
        "reservations.wompi_webhook."
        "process_wompi_transaction_notification"
    )
    def test_unknown_signed_property_is_rejected(
        self,
        mock_process,
    ):
        self.event["signature"]["properties"] = [
            "transaction.id",
            "transaction.nonexistent_field",
        ]

        self.event["signature"]["checksum"] = "0" * 64

        response = self.post_event(self.event)

        self.assertEqual(response.status_code, 400)
        mock_process.assert_not_called()
