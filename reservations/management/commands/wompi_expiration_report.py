
from collections import Counter

from django.core.management.base import BaseCommand
from django.utils import timezone

from reservations.models import Reservation
from reservations.wompi_expiration_policy import (
    classify_expired_reservation,
)


class Command(BaseCommand):
    help = (
        "Muestra un diagnostico de reservas vencidas "
        "sin modificar la base de datos."
    )

    def handle(self, *args, **options):
        now = timezone.now()

        reservation_ids = list(
            Reservation.objects.filter(
                reservation_status="PENDING_PAYMENT",
                hold_expires_at__isnull=False,
                hold_expires_at__lte=now,
            )
            .order_by("pk")
            .values_list("pk", flat=True)
        )

        counters = Counter()

        self.stdout.write(
            "\nDIAGNOSTICO DE RESERVAS VENCIDAS"
        )
        self.stdout.write("-" * 45)

        for reservation_id in reservation_ids:
            classification = classify_expired_reservation(
                reservation_id
            )

            counters[classification] += 1

            self.stdout.write(
                f"Reserva #{reservation_id}: "
                f"{classification}"
            )

        self.stdout.write("-" * 45)

        self.stdout.write(
            f"Total candidatas revisadas: "
            f"{len(reservation_ids)}"
        )

        for status in [
            "CAN_EXPIRE",
            "NEEDS_RECONCILIATION",
            "FINANCIAL_REVIEW",
            "NOT_ELIGIBLE",
        ]:
            self.stdout.write(
                f"{status}: {counters[status]}"
            )

        self.stdout.write(
            self.style.SUCCESS(
                "\nDiagnostico completado. "
                "No se modificaron registros."
            )
        )
