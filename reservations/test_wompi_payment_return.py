from .models import Payment, Reservation
from .services import create_wompi_payment_attempt
from .payment_processing import process_verified_wompi_transaction
from .wompi import amount_to_cents
from datetime import time, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from courts.models import Court, CourtSchedule, Venue

from .models import Reservation
from .services import create_pending_reservation


class WompiPaymentReturnTests(TestCase):

    def setUp(self):
        cache.clear()
        User = get_user_model()

        self.user = User.objects.create_user(
            username="return_owner",
            password="TestPassword123!",
        )

        self.other_user = User.objects.create_user(
            username="return_other",
            password="TestPassword123!",
        )

        venue = Venue.objects.create(
            venue_name="Arena Return Test",
            deposit_percentage=30,
        )

        court = Court.objects.create(
            venue=venue,
            court_name="Cancha Return Test",
            price_per_hour=130000,
        )

        day = timezone.localdate() + timedelta(days=7)

        CourtSchedule.objects.create(
            court=court,
            day_of_week=day.isoweekday(),
            start_time=time(8),
            end_time=time(22),
        )

        self.reservation = create_pending_reservation(
            user=self.user,
            court=court,
            reservation_date=day,
            start_time=time(18),
            end_time=time(19),
        )

        self.url = reverse(
            "reservations:wompi_payment_return",
            kwargs={"reserva_id": self.reservation.pk},
        )

        self.client.force_login(self.user)

    def test_pending_reservation_shows_pending(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)

        self.assertContains(
            response,
            "Confirmación pendiente",
        )

        self.reservation.refresh_from_db()

        self.assertEqual(
            self.reservation.reservation_status,
            "PENDING_PAYMENT",
        )

    def test_url_parameter_cannot_approve_reservation(self):
        with patch(
            "reservations.wompi_return_verification.get_wompi_transaction",
            side_effect=ValueError("invalid"),
        ):
            response = self.client.get(
                self.url + "?id=FAKE-TRANSACTION&status=APPROVED"
            )

        self.assertEqual(response.status_code, 200)

        self.assertContains(
            response,
            "Confirmación pendiente",
        )

        self.reservation.refresh_from_db()

        self.assertEqual(
            self.reservation.reservation_status,
            "PENDING_PAYMENT",
        )

    def test_verified_return_can_confirm_own_reservation(self):
        payment = create_wompi_payment_attempt(self.reservation)
        transaction_data = {
            "id": "TX-RETURN-VERIFIED-001",
            "reference": payment.transaction_reference,
            "amount_in_cents": amount_to_cents(payment.amount),
            "currency": "COP",
            "status": "APPROVED",
        }

        with patch(
            "reservations.wompi_return_verification.get_wompi_transaction",
            return_value=transaction_data,
        ):
            response = self.client.get(
                self.url + "?id=TX-RETURN-VERIFIED-001"
            )

        self.assertContains(response, "Reserva confirmada")
        self.reservation.refresh_from_db()
        self.assertEqual(
            self.reservation.reservation_status,
            "CONFIRMED",
        )

    def test_foreign_reference_cannot_update_reservation(self):
        payment = create_wompi_payment_attempt(self.reservation)
        transaction_data = {
            "id": "TX-RETURN-FOREIGN-001",
            "reference": "REFERENCE-FROM-ANOTHER-RESERVATION",
            "amount_in_cents": amount_to_cents(payment.amount),
            "currency": "COP",
            "status": "APPROVED",
        }

        with patch(
            "reservations.wompi_return_verification.get_wompi_transaction",
            return_value=transaction_data,
        ):
            response = self.client.get(
                self.url + "?id=TX-RETURN-FOREIGN-001"
            )

        self.assertContains(response, "no fue aplicado")
        self.reservation.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(
            self.reservation.reservation_status,
            "PENDING_PAYMENT",
        )
        self.assertEqual(payment.payment_status, "PENDING")

    def test_other_user_cannot_view_result(self):
        self.client.force_login(self.other_user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 404)

    def test_expired_reservation_shows_expired(self):
        Reservation.objects.filter(
            pk=self.reservation.pk,
        ).update(
            reservation_status="EXPIRED",
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)

        self.assertContains(
            response,
            "Reserva expirada",
        )

    def test_post_is_not_allowed(self):
        response = self.client.post(
            self.url,
            {"status": "APPROVED"},
        )

        self.assertEqual(response.status_code, 405)

    def test_login_is_required(self):
        self.client.logout()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)


    def test_approved_payment_shows_confirmed_reservation(self):
        """
        El procesador registra una aprobacion valida.
        La pantalla de retorno muestra el estado local.
        """
        payment = create_wompi_payment_attempt(
            self.reservation
        )

        transaction_data = {
            "id": "TX-RETURN-APPROVED-001",
            "reference": payment.transaction_reference,
            "amount_in_cents": amount_to_cents(payment.amount),
            "currency": "COP",
            "status": "APPROVED",
        }

        process_verified_wompi_transaction(
            payment.pk,
            transaction_data,
        )

        response = self.client.get(
            self.url + "?id=TX-RETURN-APPROVED-001"
        )

        self.assertEqual(response.status_code, 200)

        self.assertContains(
            response,
            "Reserva confirmada",
        )

        self.reservation.refresh_from_db()
        payment.refresh_from_db()

        self.assertEqual(
            self.reservation.reservation_status,
            "CONFIRMED",
        )

        self.assertEqual(
            payment.payment_status,
            "APPROVED",
        )

    def test_late_approval_does_not_show_confirmation(self):
        """
        Si Wompi informa una aprobacion despues
        del vencimiento, no debemos anunciar que
        la cancha esta confirmada.
        """
        payment = create_wompi_payment_attempt(
            self.reservation
        )

        Reservation.objects.filter(
            pk=self.reservation.pk
        ).update(
            hold_expires_at=(
                timezone.now() - timedelta(minutes=1)
            )
        )

        transaction_data = {
            "id": "TX-RETURN-LATE-001",
            "reference": payment.transaction_reference,
            "amount_in_cents": amount_to_cents(payment.amount),
            "currency": "COP",
            "status": "APPROVED",
        }

        process_verified_wompi_transaction(
            payment.pk,
            transaction_data,
        )

        response = self.client.get(
            self.url + "?id=TX-RETURN-LATE-001&status=APPROVED"
        )

        self.assertEqual(response.status_code, 200)

        self.assertNotContains(
            response,
            "Reserva confirmada",
        )

        self.reservation.refresh_from_db()
        payment.refresh_from_db()

        self.assertEqual(
            self.reservation.reservation_status,
            "PENDING_PAYMENT",
        )

        self.assertEqual(
            payment.payment_status,
            "APPROVED",
        )

        self.assertTrue(
            payment.requires_reconciliation
        )

        self.assertEqual(
            payment.reconciliation_reason,
            "LATE_APPROVAL",
        )

    def test_refresh_link_preserves_id_and_requeries_wompi(self):
        payment = create_wompi_payment_attempt(self.reservation)
        transaction_id = "TX-RETURN-REFRESH-001"
        transaction_data = {
            "id": transaction_id,
            "reference": payment.transaction_reference,
            "amount_in_cents": amount_to_cents(payment.amount),
            "currency": "COP",
            "status": "PENDING",
        }

        with patch(
            "reservations.wompi_return_verification.get_wompi_transaction",
            return_value=transaction_data,
        ) as get_transaction:
            first_response = self.client.get(
                self.url + f"?id={transaction_id}"
            )
            second_response = self.client.get(
                self.url + f"?id={transaction_id}"
            )

        expected_refresh_url = self.url + f"?id={transaction_id}"
        self.assertContains(
            first_response,
            f'href="{expected_refresh_url}"',
        )
        self.assertContains(
            first_response,
            "Volver a consultar Wompi",
        )
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(get_transaction.call_count, 2)
