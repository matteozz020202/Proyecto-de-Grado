
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.core.exceptions import (
    ImproperlyConfigured,
    ValidationError,
)
from django.test import SimpleTestCase
from django.utils import timezone

from .wompi import generate_integrity_signature
from .wompi_checkout import build_wompi_checkout_data


TEST_KEYS = {
    "WOMPI_PUBLIC_KEY": "pub_test_EXAMPLE",
    "WOMPI_INTEGRITY_SECRET": "test_integrity_EXAMPLE",
}


class WompiCheckoutTests(SimpleTestCase):

    def setUp(self):
        self.reservation = SimpleNamespace(
            reservation_status="PENDING_PAYMENT",
            hold_expires_at=(
                timezone.now() + timedelta(minutes=10)
            ),
            deposit_required=Decimal("39000.00"),
        )

        self.payment = SimpleNamespace(
            pk=1,
            reservation=self.reservation,
            provider="WOMPI",
            payment_type="DEPOSIT",
            payment_status="PENDING",
            currency="COP",
            amount=Decimal("39000.00"),
            transaction_reference="CL-TEST-001",
        )

    @patch.dict("os.environ", TEST_KEYS)
    def test_builds_valid_checkout_data(self):
        data = build_wompi_checkout_data(
            self.payment
        )

        self.assertEqual(
            data["checkout_url"],
            "https://checkout.wompi.co/p/",
        )
        self.assertEqual(
            data["public-key"],
            "pub_test_EXAMPLE",
        )
        self.assertEqual(
            data["amount-in-cents"],
            3900000,
        )
        self.assertEqual(data["currency"], "COP")
        self.assertEqual(
            data["reference"],
            "CL-TEST-001",
        )

        expected_signature = generate_integrity_signature(
            "CL-TEST-001",
            3900000,
            "test_integrity_EXAMPLE",
            expiration_time=data["expiration-time"],
        )

        self.assertTrue(
            data["expiration-time"].endswith("Z")
        )

        self.assertEqual(
            data["signature:integrity"],
            expected_signature,
        )

    @patch.dict("os.environ", TEST_KEYS)
    def test_expired_reservation_is_rejected(self):
        self.reservation.hold_expires_at = (
            timezone.now() - timedelta(minutes=1)
        )

        with self.assertRaises(ValidationError):
            build_wompi_checkout_data(
                self.payment
            )

    @patch.dict("os.environ", TEST_KEYS)
    def test_confirmed_reservation_is_rejected(self):
        self.reservation.reservation_status = "CONFIRMED"

        with self.assertRaises(ValidationError):
            build_wompi_checkout_data(
                self.payment
            )

    @patch.dict("os.environ", TEST_KEYS)
    def test_wrong_deposit_amount_is_rejected(self):
        self.payment.amount = Decimal("100.00")

        with self.assertRaises(ValidationError):
            build_wompi_checkout_data(
                self.payment
            )

    @patch.dict("os.environ", TEST_KEYS)
    def test_approved_payment_is_rejected(self):
        self.payment.payment_status = "APPROVED"

        with self.assertRaises(ValidationError):
            build_wompi_checkout_data(
                self.payment
            )

    @patch.dict(
        "os.environ",
        {
            "WOMPI_PUBLIC_KEY": "pub_prod_EXAMPLE",
            "WOMPI_INTEGRITY_SECRET": "test_integrity_EXAMPLE",
        },
    )
    def test_production_key_is_rejected(self):
        with self.assertRaises(ImproperlyConfigured):
            build_wompi_checkout_data(
                self.payment
            )

    @patch.dict("os.environ", TEST_KEYS)
    def test_expiration_is_included_in_integrity_signature(self):
        import hashlib

        data = build_wompi_checkout_data(self.payment)

        expiration = data["expiration-time"]

        raw_payload = (
            "CL-TEST-001"
            "3900000"
            "COP"
            + expiration
            + "test_integrity_EXAMPLE"
        )

        expected_hash = hashlib.sha256(
            raw_payload.encode("utf-8")
        ).hexdigest()

        self.assertEqual(
            data["signature:integrity"],
            expected_hash,
        )

        # Verificar que la firma sin vencimiento
        # sea distinta de la firma del checkout.
        old_signature = generate_integrity_signature(
            "CL-TEST-001",
            3900000,
            "test_integrity_EXAMPLE",
        )

        self.assertNotEqual(
            data["signature:integrity"],
            old_signature,
        )
