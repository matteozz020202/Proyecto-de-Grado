
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from .wompi_config import validate_wompi_sandbox_config


TEST_CREDENTIALS = {
    "WOMPI_PUBLIC_KEY": "pub_test_EXAMPLE",
    "WOMPI_PRIVATE_KEY": "prv_test_EXAMPLE",
    "WOMPI_INTEGRITY_SECRET": "test_integrity_EXAMPLE",
    "WOMPI_EVENTS_SECRET": "test_events_EXAMPLE",
}


class WompiConfigTests(SimpleTestCase):

    @patch.dict("os.environ", TEST_CREDENTIALS)
    def test_valid_sandbox_configuration(self):
        self.assertTrue(
            validate_wompi_sandbox_config()
        )

    @patch.dict(
        "os.environ",
        {
            **TEST_CREDENTIALS,
            "WOMPI_PUBLIC_KEY": "pub_prod_EXAMPLE",
        },
    )
    def test_production_public_key_is_rejected(self):
        with self.assertRaises(ImproperlyConfigured):
            validate_wompi_sandbox_config()

    @patch.dict(
        "os.environ",
        {
            **TEST_CREDENTIALS,
            "WOMPI_PRIVATE_KEY": "prv_prod_EXAMPLE",
        },
    )
    def test_production_private_key_is_rejected(self):
        with self.assertRaises(ImproperlyConfigured):
            validate_wompi_sandbox_config()

    @patch.dict(
        "os.environ",
        {
            **TEST_CREDENTIALS,
            "WOMPI_INTEGRITY_SECRET": "",
        },
    )
    def test_missing_integrity_secret_is_rejected(self):
        with self.assertRaises(ImproperlyConfigured):
            validate_wompi_sandbox_config()

    @patch.dict(
        "os.environ",
        {
            **TEST_CREDENTIALS,
            "WOMPI_EVENTS_SECRET": "",
        },
    )
    def test_missing_events_secret_is_rejected(self):
        with self.assertRaises(ImproperlyConfigured):
            validate_wompi_sandbox_config()
