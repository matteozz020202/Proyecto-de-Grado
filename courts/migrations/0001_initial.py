import django.core.validators
import django.db.models.deletion

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [

        # ============================================================
        # VENUES
        # Orden físico:
        # 1. venue_id
        # 2. venue_name
        # 3. city
        # 4. address
        # 5. deposit_percentage
        # 6. is_active
        # 7. image (extra de la aplicación)
        # ============================================================

        migrations.CreateModel(
            name="Venue",
            fields=[
                (
                    "venue_id",
                    models.BigAutoField(
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "venue_name",
                    models.CharField(
                        max_length=150,
                    ),
                ),
                (
                    "city",
                    models.CharField(
                        default="Barranquilla",
                        max_length=100,
                    ),
                ),
                (
                    "address",
                    models.CharField(
                        max_length=255,
                    ),
                ),
                (
                    "deposit_percentage",
                    models.DecimalField(
                        decimal_places=2,
                        default=30,
                        max_digits=5,
                        validators=[
                            django.core.validators.MinValueValidator(0),
                            django.core.validators.MaxValueValidator(100),
                        ],
                        verbose_name="Porcentaje de abono",
                    ),
                ),
                (
                    "is_active",
                    models.BooleanField(
                        default=True,
                    ),
                ),
                (
                    "image",
                    models.ImageField(
                        blank=True,
                        null=True,
                        upload_to="venues/",
                        verbose_name="Imagen del establecimiento",
                    ),
                ),
            ],
            options={
                "verbose_name": "Establecimiento",
                "verbose_name_plural": "Establecimientos",
                "db_table": "venues",
                "ordering": ["venue_name"],
            },
        ),

        # ============================================================
        # COURTS
        # Orden físico:
        # 1. court_id
        # 2. venue_id
        # 3. court_name
        # 4. price_per_hour
        # 5. is_active
        # 6. description (extra)
        # 7. image (extra)
        # ============================================================

        migrations.CreateModel(
            name="Court",
            fields=[
                (
                    "court_id",
                    models.BigAutoField(
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "venue",
                    models.ForeignKey(
                        db_column="venue_id",
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="courts",
                        to="courts.venue",
                        verbose_name="Establecimiento",
                    ),
                ),
                (
                    "court_name",
                    models.CharField(
                        max_length=100,
                    ),
                ),
                (
                    "price_per_hour",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=10,
                    ),
                ),
                (
                    "is_active",
                    models.BooleanField(
                        default=True,
                    ),
                ),
                (
                    "description",
                    models.TextField(
                        blank=True,
                    ),
                ),
                (
                    "image",
                    models.ImageField(
                        blank=True,
                        null=True,
                        upload_to="courts/",
                        verbose_name="Imagen de la cancha",
                    ),
                ),
            ],
            options={
                "verbose_name": "Cancha",
                "verbose_name_plural": "Canchas",
                "db_table": "courts",
                "ordering": ["court_name"],
            },
        ),

        # ============================================================
        # COURT SCHEDULE
        # Orden físico:
        # 1. schedule_id
        # 2. court_id
        # 3. day_of_week
        # 4. start_time
        # 5. end_time
        # 6. slot_duration_minutes
        # 7. is_active
        # ============================================================

        migrations.CreateModel(
            name="CourtSchedule",
            fields=[
                (
                    "schedule_id",
                    models.BigAutoField(
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "court",
                    models.ForeignKey(
                        db_column="court_id",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="schedules",
                        to="courts.court",
                    ),
                ),
                (
                    "day_of_week",
                    models.IntegerField(
                        choices=[
                            (1, "Lunes"),
                            (2, "Martes"),
                            (3, "Miércoles"),
                            (4, "Jueves"),
                            (5, "Viernes"),
                            (6, "Sábado"),
                            (7, "Domingo"),
                        ],
                    ),
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
                    "slot_duration_minutes",
                    models.PositiveSmallIntegerField(
                        default=60,
                        verbose_name="Duración del slot en minutos",
                    ),
                ),
                (
                    "is_active",
                    models.BooleanField(
                        default=True,
                    ),
                ),
            ],
            options={
                "verbose_name": "Horario",
                "verbose_name_plural": "Horarios",
                "db_table": "court_schedule",
                "ordering": [
                    "court",
                    "day_of_week",
                    "start_time",
                ],
            },
        ),
    ]