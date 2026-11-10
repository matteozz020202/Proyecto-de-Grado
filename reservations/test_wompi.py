
import hashlib
from decimal import Decimal

from django.test import SimpleTestCase

from .wompi import (
    amount_to_cents,
    generate_integrity_signature,
)


class WompiTests(SimpleTestCase):

    def test_amount_to_cents(self):
        self.assertEqual(
            amount_to_cents(Decimal("39000.00")),
            3900000,
        )

        self.assertEqual(
            amount_to_cents(Decimal("36000.50")),
            3600050,
        )

    def test_invalid_amounts(self):
        invalid_amounts = [
            Decimal("0"),
            Decimal("-100"),
            Decimal("10.001"),
            Decimal("NaN"),
            10.5,
            None,
        ]

        for amount in invalid_amounts:
            with self.subTest(amount=amount):
                with self.assertRaises(ValueError):
                    amount_to_cents(amount)

    def test_integrity_signature(self):
        reference = "CL-TEST-001"
        amount = 3900000
        secret = "test_integrity_EXAMPLE_ONLY"

        expected_payload = (
            "CL-TEST-001"
            "3900000"
            "COP"
            "test_integrity_EXAMPLE_ONLY"
        )

        expected = hashlib.sha256(
            expected_payload.encode("utf-8")
        ).hexdigest()

        result = generate_integrity_signature(
            reference,
            amount,
            secret,
        )

        self.assertEqual(result, expected)
        self.assertEqual(len(result), 64)

    def test_signature_requires_sandbox_secret(self):
        with self.assertRaises(ValueError):
            generate_integrity_signature(
                "CL-TEST-001",
                3900000,
                "prod_integrity_EXAMPLE_ONLY",
            )

    def test_signature_rejects_invalid_amount(self):
        with self.assertRaises(ValueError):
            generate_integrity_signature(
                "CL-TEST-001",
                0,
                "test_integrity_EXAMPLE_ONLY",
            )
