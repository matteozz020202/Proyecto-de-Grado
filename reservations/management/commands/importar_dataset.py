import json
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from reservations.dataset_import import DatasetError, build_objects, import_core, read_core, summarize


class Command(BaseCommand):
    help = "Valida el Core sintético sin escribir; --commit aplica la importación transaccional."

    def add_arguments(self, parser):
        parser.add_argument("archivo", help="ZIP v1.1 ajustado o Excel Core")
        parser.add_argument("--commit", action="store_true", help="Guardar datos en la base configurada")

    def handle(self, *args, **options):
        try:
            data = read_core(options["archivo"])
            objects = build_objects(data)
            self.stdout.write(json.dumps(summarize(data), ensure_ascii=False, indent=2))
            if options["commit"]:
                counts = import_core(data, objects)
                self.stdout.write(self.style.SUCCESS("Carga completa: " + json.dumps(counts)))
            else:
                self.stdout.write(self.style.SUCCESS("Validación completa. No se escribió en la base."))
        except (DatasetError, OSError, KeyError, ValueError, ValidationError) as exc:
            raise CommandError(str(exc)) from exc
