import django.db.models.deletion

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(
            settings.AUTH_USER_MODEL
        ),
        (
            "courts",
            "0001_initial",
        ),
    ]

    operations = [

        # ============================================================
        # RESERVATIONS
        # Orden físico exacto del dataset:
        #
        # 1. reservation_id
        # 2. court_id
        # 3. user_id
        # 4. reservation_date
        # 5. start_time
        # 6. end_time
        # 7. total_amount
        # 8. deposit_required
        # 9. remaining_amount
        # 10. reservation_status
        # 11. created_at
        # 12. hold_expires_at
        # 13. cancelled_at
        # 14. data_source
        # ============================================================

        migrations.CreateModel(
            name="Reservation",
            fields=[
                (
                    "reservation_id",
                    models.BigAutoField(
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "court",
                    models.ForeignKey(
                        db_column="court_id",
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="reservations",
                        to="courts.court",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        db_column="user_id",
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="reservations",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "reservation_date",
                    models.DateField(),
                ),
                (
                    "start_time",
                    models.TimeField(),
                ),
                (
                    "end_time",
                    models.TimeField(),
                ),
                (
                    "total_amount",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=10,
                    ),
                ),
                (
                    "deposit_required",
                    models.DecimalField(
                        decimal_places=2,
                        default=0,
                        max_digits=10,
                    ),
                ),
                (
                    "remaining_amount",
                    models.DecimalField(
                        decimal_places=2,
                        default=0,
                        max_digits=10,
                    ),
                ),
                (
                    "reservation_status",
                    models.CharField(
                        choices=[
                            (
                                "PENDING_PAYMENT",
                                "Pendiente de pago",
                            ),
                            (
                                "CONFIRMED",
                                "Confirmada",
                            ),
                            (
                                "COMPLETED",
                                "Completada",
                            ),
                            (
                                "CANCELLED",
                                "Cancelada",
                            ),
                            (
                                "EXPIRED",
                                "Expirada",
                            ),
                        ],
                        default="PENDING_PAYMENT",
                        max_length=20,
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        auto_now_add=True,
                    ),
                ),
                (
                    "hold_expires_at",
                    models.DateTimeField(
                        blank=True,
                        null=True,
                    ),
                ),
                (
                    "cancelled_at",
                    models.DateTimeField(
                        blank=True,
                        null=True,
                    ),
                ),
                (
                    "data_source",
                    models.CharField(
                        choices=[
                            (
                                "SYNTHETIC",
                                "Sintético",
                            ),
                            (
                                "HISTORICAL_REAL",
                                "Histórico real",
                            ),
                            (
                                "SYSTEM",
                                "Sistema",
                            ),
                        ],
                        default="SYSTEM",
                        max_length=20,
                    ),
                ),
            ],
            options={
                "verbose_name": "Reserva",
                "verbose_name_plural": "Reservas",
                "db_table": "reservations",
                "ordering": [
                    "-reservation_date",
                    "start_time",
                ],
            },
        ),

        # ============================================================
        # PAYMENTS
        # Orden físico exacto:
        #
        # 1. payment_id
        # 2. reservation_id
        # 3. amount
        # 4. payment_type
        # 5. payment_status
        # 6. provider
        # 7. transaction_reference
        # 8. created_at
        # 9. approved_at
        # ============================================================

        migrations.CreateModel(
            name="Payment",
            fields=[
                (
                    "payment_id",
                    models.BigAutoField(
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "reservation",
                    models.ForeignKey(
                        db_column="reservation_id",
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="payments",
                        to="reservations.reservation",
                    ),
                ),
                (
                    "amount",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=10,
                    ),
                ),
                (
                    "payment_type",
                    models.CharField(
                        choices=[
                            (
                                "DEPOSIT",
                                "Abono",
                            ),
                            (
                                "BALANCE",
                                "Saldo",
                            ),
                        ],
                        default="DEPOSIT",
                        max_length=20,
                    ),
                ),
                (
                    "payment_status",
                    models.CharField(
                        choices=[
                            (
                                "PENDING",
                                "Pendiente",
                            ),
                            (
                                "APPROVED",
                                "Aprobado",
                            ),
                            (
                                "REJECTED",
                                "Rechazado",
                            ),
                        ],
                        default="PENDING",
                        max_length=20,
                    ),
                ),
                (
                    "provider",
                    models.CharField(
                        default="SIMULATED",
                        max_length=50,
                    ),
                ),
                (
                    "transaction_reference",
                    models.CharField(
                        max_length=100,
                        unique=True,
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        auto_now_add=True,
                    ),
                ),
                (
                    "approved_at",
                    models.DateTimeField(
                        blank=True,
                        null=True,
                    ),
                ),
            ],
            options={
                "verbose_name": "Pago",
                "verbose_name_plural": "Pagos",
                "db_table": "payments",
                "ordering": [
                    "-created_at",
                ],
            },
        ),
    ]