
import hashlib
from copy import deepcopy

from django.test import SimpleTestCase

from .wompi import verify_wompi_event


class WompiWebhookTests(SimpleTestCase):

    SECRET = "test_events_EXAMPLE_ONLY"

    def make_event(self):
        event = {
            "event": "transaction.updated",
            "environment": "test",
            "data": {
                "transaction": {
                    "id": "TEST-12345",
                    "reference": "CL-1-TEST",
                    "status": "APPROVED",
                    "amount_in_cents": 3900000,
                    "currency": "COP",
                }
            },
            "signature": {
                "properties": [
                    "transaction.id",
                    "transaction.status",
                    "transaction.amount_in_cents",
                ],
                "checksum": "",
            },
            "timestamp": 1530291411,
        }

        payload = (
            "TEST-12345"
            "APPROVED"
            "3900000"
            "1530291411"
            + self.SECRET
        )

        event["signature"]["checksum"] = (
            hashlib.sha256(
                payload.encode("utf-8")
            ).hexdigest()
        )

        return event

    def test_valid_event(self):
        event = self.make_event()

        self.assertTrue(
            verify_wompi_event(event, self.SECRET)
        )

    def test_modified_amount_is_rejected(self):
        event = self.make_event()
        event["data"]["transaction"]["amount_in_cents"] = 1

        self.assertFalse(
            verify_wompi_event(event, self.SECRET)
        )

    def test_modified_status_is_rejected(self):
        event = self.make_event()
        event["data"]["transaction"]["status"] = "DECLINED"

        self.assertFalse(
            verify_wompi_event(event, self.SECRET)
        )

    def test_invalid_checksum_is_rejected(self):
        event = self.make_event()
        event["signature"]["checksum"] = "0" * 64

        self.assertFalse(
            verify_wompi_event(event, self.SECRET)
        )

    def test_production_event_is_rejected(self):
        event = self.make_event()
        event["environment"] = "prod"

        self.assertFalse(
            verify_wompi_event(event, self.SECRET)
        )

    def test_missing_signature_is_rejected(self):
        event = self.make_event()
        event.pop("signature")

        self.assertFalse(
            verify_wompi_event(event, self.SECRET)
        )

    def test_missing_signed_property_is_rejected(self):
        event = self.make_event()
        del event["data"]["transaction"]["status"]

        self.assertFalse(
            verify_wompi_event(event, self.SECRET)
        )

    def test_wrong_event_type_is_rejected(self):
        event = self.make_event()
        event["event"] = "other.event"

        self.assertFalse(
            verify_wompi_event(event, self.SECRET)
        )

    def test_wrong_secret_is_rejected(self):
        event = self.make_event()

        self.assertFalse(
            verify_wompi_event(
                event,
                "test_events_ANOTHER_SECRET",
            )
        )

    def test_signed_properties_order_matters(self):
        event = deepcopy(self.make_event())

        event["signature"]["properties"] = [
            "transaction.status",
            "transaction.id",
            "transaction.amount_in_cents",
        ]

        self.assertFalse(
            verify_wompi_event(event, self.SECRET)
        )
