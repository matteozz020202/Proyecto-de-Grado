from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from courts.models import Cancha


class Reserva(models.Model):
    ESTADOS = [
        ("PENDING_PAYMENT", "Pendiente de pago"),
        ("CONFIRMED", "Confirmada"),
        ("COMPLETED", "Completada"),
        ("CANCELLED", "Cancelada"),
        ("EXPIRED", "Expirada"),
    ]

    ORIGENES_DATOS = [
        ("SYNTHETIC", "Sintético"),
        ("HISTORICAL_REAL", "Histórico real"),
        ("SYSTEM", "Sistema"),
    ]

    usuario = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="reservas"
    )

    cancha = models.ForeignKey(
        Cancha,
        on_delete=models.PROTECT,
        related_name="reservas"
    )

    fecha = models.DateField()

    hora_inicio = models.TimeField()
    hora_fin = models.TimeField()

    precio = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    abono_requerido = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0
    )

    saldo_pendiente = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0
    )

    estado = models.CharField(
        max_length=20,
        choices=ESTADOS,
        default="PENDING_PAYMENT"
    )

    hold_expira_en = models.DateTimeField(
        null=True,
        blank=True
    )

    fecha_cancelacion = models.DateTimeField(
        null=True,
        blank=True
    )

    origen_datos = models.CharField(
        max_length=20,
        choices=ORIGENES_DATOS,
        default="SYSTEM"
    )

    fecha_creacion = models.DateTimeField(
        auto_now_add=True
    )

    class Meta:
        verbose_name = "Reserva"
        verbose_name_plural = "Reservas"
        ordering = ["-fecha", "hora_inicio"]

    def clean(self):
        # La hora de inicio debe ser menor que la hora de finalización.
        if self.hora_inicio and self.hora_fin:
            if self.hora_inicio >= self.hora_fin:
                raise ValidationError(
                    "La hora de inicio debe ser anterior a la hora de finalización."
                )

        # Una reserva cancelada no bloquea el horario.
        if self.estado in ["CANCELLED", "EXPIRED"]:
            return

        # Comprobar si existe otra reserva que se cruce
        # con la misma cancha, fecha y horario.
        if (
            self.cancha_id
            and self.fecha
            and self.hora_inicio
            and self.hora_fin
        ):
            conflictos = Reserva.objects.filter(
                cancha=self.cancha,
                fecha=self.fecha,
                hora_inicio__lt=self.hora_fin,
                hora_fin__gt=self.hora_inicio
            ).exclude(
                estado__in=["CANCELLED", "EXPIRED"]
            )

            # Si estamos editando una reserva existente,
            # no debe compararse consigo misma.
            if self.pk:
                conflictos = conflictos.exclude(pk=self.pk)

            if conflictos.exists():
                raise ValidationError(
                    "La cancha ya tiene una reserva que se cruza con este horario."
                )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"{self.usuario.username} - "
            f"{self.cancha.nombre} - "
            f"{self.fecha} "
            f"{self.hora_inicio}"
        )
        