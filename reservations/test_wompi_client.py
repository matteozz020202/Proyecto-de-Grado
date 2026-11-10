import io
import json

from unittest.mock import patch
from urllib.error import HTTPError, URLError

from django.test import SimpleTestCase

from .wompi_client import (
    WompiAPIError,
    get_wompi_transaction,
)


class FakeResponse:
    status = 200

    def __init__(self, payload):
        self.buffer = io.BytesIO(
            json.dumps(payload).encode("utf-8")
        )

    def read(self, *args):
        return self.buffer.read(*args)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.buffer.close()


class WompiClientTests(SimpleTestCase):

    def setUp(self):
        self.transaction_id = "TX-TEST-001"

        self.payload = {
            "data": {
                "id": self.transaction_id,
                "reference": "CL-1-TEST",
                "status": "APPROVED",
                "amount_in_cents": 3900000,
                "currency": "COP",
                "payment_method_type": "CARD",
            }
        }

    @patch.dict(
        "os.environ",
        {"WOMPI_PRIVATE_KEY": "prv_test_EXAMPLE"},
    )
    @patch("reservations.wompi_client.urlopen")
    def test_successful_transaction_query(self, mock_open):
        mock_open.return_value = FakeResponse(
            self.payload
        )

        result = get_wompi_transaction(
            self.transaction_id
        )

        self.assertEqual(
            result["status"],
            "APPROVED",
        )

        request = mock_open.call_args.args[0]

        self.assertEqual(
            request.get_method(),
            "GET",
        )

        self.assertEqual(
            request.full_url,
            "https://sandbox.wompi.co/v1/"
            "transactions/TX-TEST-001",
        )

        self.assertEqual(
            request.get_header("Authorization"),
            "Bearer prv_test_EXAMPLE",
        )

        self.assertEqual(
            mock_open.call_args.kwargs["timeout"],
            10,
        )

    @patch.dict(
        "os.environ",
        {"WOMPI_PRIVATE_KEY": "prv_prod_EXAMPLE"},
    )
    def test_production_key_is_rejected(self):
        with self.assertRaises(WompiAPIError):
            get_wompi_transaction(
                self.transaction_id
            )

    @patch.dict(
        "os.environ",
        {"WOMPI_PRIVATE_KEY": ""},
    )
    def test_missing_key_is_rejected(self):
        with self.assertRaises(WompiAPIError):
            get_wompi_transaction(
                self.transaction_id
            )

    def test_invalid_transaction_id(self):
        with self.assertRaises(ValueError):
            get_wompi_transaction(
                "../other"
            )

    @patch.dict(
        "os.environ",
        {"WOMPI_PRIVATE_KEY": "prv_test_EXAMPLE"},
    )
    @patch("reservations.wompi_client.urlopen")
    def test_network_error(self, mock_open):
        mock_open.side_effect = URLError(
            "Connection failed"
        )

        with self.assertRaises(WompiAPIError):
            get_wompi_transaction(
                self.transaction_id
            )

    @patch.dict(
        "os.environ",
        {"WOMPI_PRIVATE_KEY": "prv_test_EXAMPLE"},
    )
    @patch("reservations.wompi_client.urlopen")
    def test_http_error(self, mock_open):
        mock_open.side_effect = HTTPError(
            url="https://sandbox.wompi.co",
            code=404,
            msg="Not Found",
            hdrs=None,
            fp=None,
        )

        with self.assertRaises(WompiAPIError):
            get_wompi_transaction(
                self.transaction_id
            )

    @patch.dict(
        "os.environ",
        {"WOMPI_PRIVATE_KEY": "prv_test_EXAMPLE"},
    )
    @patch("reservations.wompi_client.urlopen")
    def test_transaction_id_mismatch(self, mock_open):
        payload = {
            "data": {
                **self.payload["data"],
                "id": "ANOTHER-ID",
            }
        }

        mock_open.return_value = FakeResponse(payload)

        with self.assertRaises(WompiAPIError):
            get_wompi_transaction(
                self.transaction_id
            )

    @patch.dict(
        "os.environ",
        {"WOMPI_PRIVATE_KEY": "prv_test_EXAMPLE"},
    )
    @patch("reservations.wompi_client.urlopen")
    def test_missing_transaction_data(self, mock_open):
        mock_open.return_value = FakeResponse(
            {"data": None}
        )

        with self.assertRaises(WompiAPIError):
            get_wompi_transaction(
                self.transaction_id
            )
