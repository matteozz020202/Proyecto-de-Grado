"""Pruebas aisladas: python manage.py test --settings=config.test_settings.

SQLite en memoria no sustituye la validación de concurrencia en PostgreSQL.
"""
import os

# Evita seleccionar Neon incluso si está habilitado en el .env local.
os.environ["USE_NEON"] = "False"

from .settings import *  # noqa: F403, E402

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
