from django.db import models


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
        (0, "Lunes"),
        (1, "Martes"),
        (2, "Miércoles"),
        (3, "Jueves"),
        (4, "Viernes"),
        (5, "Sábado"),
        (6, "Domingo"),
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