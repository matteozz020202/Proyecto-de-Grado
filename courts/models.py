from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator


class Venue(models.Model):
    # 1. venue_id
    venue_id = models.BigAutoField(
        primary_key=True
    )

    # 2. venue_name
    venue_name = models.CharField(
        max_length=150
    )

    # 3. city
    city = models.CharField(
        max_length=100,
        default="Barranquilla"
    )

    # 4. address
    address = models.CharField(
        max_length=255
    )

    # 5. deposit_percentage
    deposit_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=30,
        validators=[
            MinValueValidator(0),
            MaxValueValidator(100)
        ],
        verbose_name="Porcentaje de abono"
    )

    # 6. is_active
    is_active = models.BooleanField(
        default=True
    )

    # Campo adicional de la aplicación.
    image = models.ImageField(
        upload_to="venues/",
        null=True,
        blank=True,
        verbose_name="Imagen del establecimiento"
    )

    class Meta:
        db_table = "venues"
        verbose_name = "Establecimiento"
        verbose_name_plural = "Establecimientos"
        ordering = ["venue_name"]

    def __str__(self):
        return self.venue_name


class Court(models.Model):
    # 1. court_id
    court_id = models.BigAutoField(
        primary_key=True
    )

    # 2. venue_id
    #
    # En Python usamos court.venue.
    # En PostgreSQL la columna física será venue_id.
    venue = models.ForeignKey(
        Venue,
        on_delete=models.PROTECT,
        related_name="courts",
        db_column="venue_id",
        verbose_name="Establecimiento"
    )

    # 3. court_name
    court_name = models.CharField(
        max_length=100
    )

    # 4. price_per_hour
    price_per_hour = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    # 5. is_active
    is_active = models.BooleanField(
        default=True
    )

    # Campos adicionales de la aplicación.
    description = models.TextField(
        blank=True
    )

    image = models.ImageField(
        upload_to="courts/",
        null=True,
        blank=True,
        verbose_name="Imagen de la cancha"
    )

    class Meta:
        db_table = "courts"
        verbose_name = "Cancha"
        verbose_name_plural = "Canchas"
        ordering = ["court_name"]

    def __str__(self):
        if self.venue:
            return (
                f"{self.venue.venue_name} - "
                f"{self.court_name}"
            )

        return self.court_name


class CourtSchedule(models.Model):
    DAYS_OF_WEEK = [
        (1, "Lunes"),
        (2, "Martes"),
        (3, "Miércoles"),
        (4, "Jueves"),
        (5, "Viernes"),
        (6, "Sábado"),
        (7, "Domingo"),
    ]

    # 1. schedule_id
    schedule_id = models.BigAutoField(
        primary_key=True
    )

    # 2. court_id
    court = models.ForeignKey(
        Court,
        on_delete=models.CASCADE,
        related_name="schedules",
        db_column="court_id"
    )

    # 3. day_of_week
    day_of_week = models.IntegerField(
        choices=DAYS_OF_WEEK
    )

    # 4. start_time
    start_time = models.TimeField()

    # 5. end_time
    end_time = models.TimeField()

    # 6. slot_duration_minutes
    slot_duration_minutes = models.PositiveSmallIntegerField(
        default=60,
        verbose_name="Duración del slot en minutos"
    )

    # 7. is_active
    is_active = models.BooleanField(
        default=True
    )

    class Meta:
        db_table = "court_schedule"
        verbose_name = "Horario"
        verbose_name_plural = "Horarios"
        ordering = [
            "court",
            "day_of_week",
            "start_time"
        ]

    def __str__(self):
        return (
            f"{self.court} - "
            f"{self.get_day_of_week_display()} "
            f"{self.start_time} - "
            f"{self.end_time}"
        )