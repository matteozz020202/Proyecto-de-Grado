"""Tres consultas públicas de interpretación; no accede a reservas ni crea datos."""
from django.core.management.base import BaseCommand, CommandError
from chatbot.services.dates import relative_request
from chatbot.services.openai_service import BookingInterpreter, InterpretationError


class Command(BaseCommand):
    help = 'Verifica interpretación real con OpenAI (consume tres solicitudes de la API).'

    def handle(self, *args, **options):
        parser = BookingInterpreter()
        samples = [('Quiero jugar mañana a las 8', '20:00', None),
                   ('Quiero jugar el viernes a las 7 pm', '19:00', None),
                   ('quiero Arena Caribe el sábado', None, 'Arena Caribe')]
        for message, hour, venue in samples:
            try:
                result = parser.interpret(message, {})
            except InterpretationError as exc:
                raise CommandError(f'Conexión no disponible: {exc}. No se muestran detalles del proveedor.') from None
            expected_date, _ = relative_request(message)
            if result.date != expected_date or result.time != hour or (venue and result.venue_query != venue):
                raise CommandError('La interpretación no coincide con la fecha/hora/establecimiento esperado.')
            self.stdout.write(self.style.SUCCESS(f'OK: {message} → {result.date}, {result.time or "falta hora"}'))
        self.stdout.write('Structured Outputs correcto; no se han creado reservas ni consultado datos privados.')
