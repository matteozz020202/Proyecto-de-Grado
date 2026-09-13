from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator

class Venue(models.Model):
    nombre = models.CharField(
        max_length=150
    )

    direccion = models.CharField(
        max_length=255
    )

    ciudad = models.CharField(
        max_length=100,
        default="Barranquilla"
    )

    porcentaje_abono = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=30,
        validators=[
            MinValueValidator(0),
            MaxValueValidator(100)
        ],
        verbose_name="Porcentaje de abono"
    )

    activo = models.BooleanField(
        default=True
    )

    fecha_creacion = models.DateTimeField(
        auto_now_add=True
    )

    fecha_actualizacion = models.DateTimeField(
        auto_now=True
    )

     

    class Meta:
        verbose_name = "Establecimiento"
        verbose_name_plural = "Establecimientos"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class Cancha(models.Model):
    venue = models.ForeignKey(
        Venue,
        on_delete=models.PROTECT,
        related_name="canchas",
        verbose_name="Establecimiento"
    )

    nombre = models.CharField(
        max_length=100
    )

    descripcion = models.TextField(
        blank=True
    )

    precio_hora = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    activa = models.BooleanField(
        default=True
    )

    fecha_creacion = models.DateTimeField(
        auto_now_add=True
    )

    fecha_actualizacion = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        verbose_name = "Cancha"
        verbose_name_plural = "Canchas"
        ordering = ["nombre"]

    def __str__(self):
        if self.venue:
            return f"{self.venue.nombre} - {self.nombre}"

        return self.nombre


class Horario(models.Model):
    DIAS_SEMANA = [
        (1, "Lunes"),
        (2, "Martes"),
        (3, "Miércoles"),
        (4, "Jueves"),
        (5, "Viernes"),
        (6, "Sábado"),
        (7, "Domingo"),
    ]

    cancha = models.ForeignKey(
        Cancha,
        on_delete=models.CASCADE,
        related_name="horarios"
    )

    dia_semana = models.IntegerField(
        choices=DIAS_SEMANA
    )

    hora_inicio = models.TimeField()
    hora_fin = models.TimeField()

    duracion_slot_minutos = models.PositiveSmallIntegerField(
        default=60,
        verbose_name="Duración del slot en minutos"
    )

    activo = models.BooleanField(
        default=True
    )

    class Meta:
        verbose_name = "Horario"
        verbose_name_plural = "Horarios"
        ordering = [
            "cancha",
            "dia_semana",
            "hora_inicio"
        ]

    def __str__(self):
        return (
            f"{self.cancha} - "
            f"{self.get_dia_semana_display()} "
            f"{self.hora_inicio} - "
            f"{self.hora_fin}"
        )