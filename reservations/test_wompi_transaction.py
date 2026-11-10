
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from .wompi import validate_wompi_transaction


class WompiTransactionValidationTests(SimpleTestCase):

    def setUp(self):
        self.payment = SimpleNamespace(
            provider="WOMPI",
            payment_type="DEPOSIT",
            transaction_reference="CL-123-TEST",
            provider_transaction_id=None,
            amount=Decimal("39000.00"),
            currency="COP",
        )

        self.transaction = {
            "id": "TX-TEST-001",
            "reference": "CL-123-TEST",
            "amount_in_cents": 3900000,
            "currency": "COP",
            "status": "APPROVED",
        }

    def test_valid_transaction(self):
        result = validate_wompi_transaction(
            self.payment,
            self.transaction,
        )

        self.assertEqual(result["status"], "APPROVED")
        self.assertEqual(
            result["transaction_id"],
            "TX-TEST-001",
        )

    def test_wrong_reference(self):
        data = deepcopy(self.transaction)
        data["reference"] = "OTHER-REFERENCE"

        with self.assertRaises(ValidationError):
            validate_wompi_transaction(self.payment, data)

    def test_wrong_amount(self):
        data = deepcopy(self.transaction)
        data["amount_in_cents"] = 100

        with self.assertRaises(ValidationError):
            validate_wompi_transaction(self.payment, data)

    def test_wrong_currency(self):
        data = deepcopy(self.transaction)
        data["currency"] = "USD"

        with self.assertRaises(ValidationError):
            validate_wompi_transaction(self.payment, data)

    def test_invalid_status(self):
        data = deepcopy(self.transaction)
        data["status"] = "UNKNOWN"

        with self.assertRaises(ValidationError):
            validate_wompi_transaction(self.payment, data)

    def test_transaction_id_mismatch(self):
        self.payment.provider_transaction_id = "TX-OTHER"

        with self.assertRaises(ValidationError):
            validate_wompi_transaction(
                self.payment,
                self.transaction,
            )

    def test_boolean_amount_is_rejected(self):
        data = deepcopy(self.transaction)
        data["amount_in_cents"] = True

        with self.assertRaises(ValidationError):
            validate_wompi_transaction(self.payment, data)

    def test_non_wompi_payment_is_rejected(self):
        self.payment.provider = "SIMULATED"

        with self.assertRaises(ValidationError):
            validate_wompi_transaction(
                self.payment,
                self.transaction,
            )
