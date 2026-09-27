from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from courts.models import Court


class Reservation(models.Model):
    RESERVATION_STATUSES = [
        ("PENDING_PAYMENT", "Pendiente de pago"),
        ("CONFIRMED", "Confirmada"),
        ("COMPLETED", "Completada"),
        ("CANCELLED", "Cancelada"),
        ("EXPIRED", "Expirada"),
    ]

    DATA_SOURCES = [
        ("SYNTHETIC", "Sintético"),
        ("HISTORICAL_REAL", "Histórico real"),
        ("SYSTEM", "Sistema"),
    ]

    # 1. reservation_id
    reservation_id = models.BigAutoField(
        primary_key=True
    )

    # 2. court_id
    court = models.ForeignKey(
        Court,
        on_delete=models.PROTECT,
        related_name="reservations",
        db_column="court_id"
    )

    # 3. user_id
    user = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="reservations",
        db_column="user_id"
    )

    # 4. reservation_date
    reservation_date = models.DateField()

    # 5. start_time
    start_time = models.TimeField()

    # 6. end_time
    end_time = models.TimeField()

    # 7. total_amount
    total_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    # 8. deposit_required
    deposit_required = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0
    )

    # 9. remaining_amount
    remaining_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0
    )

    # 10. reservation_status
    reservation_status = models.CharField(
        max_length=20,
        choices=RESERVATION_STATUSES,
        default="PENDING_PAYMENT"
    )

    # 11. created_at
    created_at = models.DateTimeField(
        auto_now_add=True
    )

    # 12. hold_expires_at
    hold_expires_at = models.DateTimeField(
        null=True,
        blank=True
    )

    # 13. cancelled_at
    cancelled_at = models.DateTimeField(
        null=True,
        blank=True
    )

    # 14. data_source
    data_source = models.CharField(
        max_length=20,
        choices=DATA_SOURCES,
        default="SYSTEM"
    )

    class Meta:
        db_table = "reservations"
        verbose_name = "Reserva"
        verbose_name_plural = "Reservas"
        ordering = [
            "-reservation_date",
            "start_time"
        ]

    def clean(self):
        # La hora inicial debe ser menor que la final.
        if self.start_time and self.end_time:
            if self.start_time >= self.end_time:
                raise ValidationError(
                    "La hora de inicio debe ser anterior "
                    "a la hora de finalización."
                )

        # Las reservas canceladas o expiradas
        # no bloquean disponibilidad.
        if self.reservation_status in [
            "CANCELLED",
            "EXPIRED"
        ]:
            return

        # Validar solapamiento.
        if (
            self.court_id
            and self.reservation_date
            and self.start_time
            and self.end_time
        ):
            conflicts = Reservation.objects.filter(
                court=self.court,
                reservation_date=self.reservation_date,
                start_time__lt=self.end_time,
                end_time__gt=self.start_time
            ).exclude(
                reservation_status__in=[
                    "CANCELLED",
                    "EXPIRED"
                ]
            )

            # Al editar, no comparar la reserva consigo misma.
            if self.pk:
                conflicts = conflicts.exclude(
                    pk=self.pk
                )

            if conflicts.exists():
                raise ValidationError(
                    "La cancha ya tiene una reserva "
                    "que se cruza con este horario."
                )

    def save(self, *args, **kwargs):
        self.full_clean()

        super().save(
            *args,
            **kwargs
        )

    def __str__(self):
        return (
            f"{self.user.username} - "
            f"{self.court.court_name} - "
            f"{self.reservation_date} "
            f"{self.start_time}"
        )


class Payment(models.Model):
    PAYMENT_STATUSES = [
        ("PENDING", "Pendiente"),
        ("APPROVED", "Aprobado"),
        ("REJECTED", "Rechazado"),
    ]

    PAYMENT_TYPES = [
        ("DEPOSIT", "Abono"),
        ("BALANCE", "Saldo"),
    ]

    # 1. payment_id
    payment_id = models.BigAutoField(
        primary_key=True
    )

    # 2. reservation_id
    reservation = models.ForeignKey(
        Reservation,
        on_delete=models.PROTECT,
        related_name="payments",
        db_column="reservation_id"
    )

    # 3. amount
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    # 4. payment_type
    payment_type = models.CharField(
        max_length=20,
        choices=PAYMENT_TYPES,
        default="DEPOSIT"
    )

    # 5. payment_status
    payment_status = models.CharField(
        max_length=20,
        choices=PAYMENT_STATUSES,
        default="PENDING"
    )

    # 6. provider
    provider = models.CharField(
        max_length=50,
        default="SIMULATED"
    )

    # 7. transaction_reference
    transaction_reference = models.CharField(
        max_length=100,
        unique=True
    )

    # 8. created_at
    created_at = models.DateTimeField(
        auto_now_add=True
    )

    # 9. approved_at
    approved_at = models.DateTimeField(
        null=True,
        blank=True
    )

    class Meta:
        db_table = "payments"
        verbose_name = "Pago"
        verbose_name_plural = "Pagos"
        ordering = ["-created_at"]

    def __str__(self):
        return (
            f"Pago {self.transaction_reference} - "
            f"{self.reservation_id} - "
            f"{self.payment_status}"
        )