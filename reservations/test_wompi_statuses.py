
from django.test import SimpleTestCase

from .models import Payment


class WompiPaymentStatusTests(SimpleTestCase):

    def test_wompi_statuses_are_supported(self):
        statuses = dict(Payment.PAYMENT_STATUSES)

        for status in (
            "PENDING",
            "APPROVED",
            "DECLINED",
            "VOIDED",
            "ERROR",
        ):
            with self.subTest(status=status):
                self.assertIn(status, statuses)

    def test_legacy_rejected_status_is_preserved(self):
        statuses = dict(Payment.PAYMENT_STATUSES)

        self.assertIn("REJECTED", statuses)

    def test_payment_status_field_supports_new_values(self):
        field = Payment._meta.get_field(
            "payment_status"
        )

        self.assertGreaterEqual(
            field.max_length,
            len("DECLINED"),
        )

        self.assertGreaterEqual(
            field.max_length,
            len("APPROVED"),
        )
