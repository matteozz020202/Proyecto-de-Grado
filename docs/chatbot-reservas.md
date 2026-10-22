# Chatbot público de reservas

Rama: `feature/booking-chatbot`. No requiere migraciones ni dependencias nuevas.

## Arquitectura

`widget → Django → BookingInterpreter (OpenAI) → BookingIntent → BookingOrchestrator → disponibilidad existente → opciones reales → selección → resumen existente`.

OpenAI interpreta español mediante `client.responses.parse(text_format=BookingIntent)` con el SDK oficial ya instalado (3.7.0). El prompt es independiente del análisis administrativo. La respuesta conversacional y las tarjetas se componen en Django: no hace falta una segunda llamada al modelo para redactar resultados. Se comprueban refusal, salida incompleta, esquema inválido, errores del SDK y timeout.

`BookingIntent` contiene intención, fecha, hora, consulta de establecimiento/cancha, duración opcional, franja horaria, preferencia por cualquier establecimiento y sugerencias de campos faltantes. Django determina las preguntas, sin confiar en las sugerencias del modelo. El esquema no admite IDs, precios ni campos adicionales. El modelo no recibe reservas, usuarios, claves ni acceso a la base de datos.

Django normaliza fechas relativas con la zona horaria del proyecto, valida fechas entre hoy y los próximos 90 días y usa `get_availability()`, `validate_minimum_booking_advance()` y `calculate_reservation_values()` de `reservations/services.py`. Nunca genera slots nuevos ni decide precios desde OpenAI. Una hora ambigua entre 1 y 11 se interpreta como tarde/noche, mostrando siempre el formato 24h antes de continuar. AM y formatos explícitos tienen prioridad.

La búsqueda consulta hasta 25 canchas activas y muestra como máximo 6 opciones. Si la hora exacta no está disponible, ofrece alternativas reales hasta dos horas antes/después. Una franja sin hora exacta usa los horarios configurados de esa franja. Las duraciones solicitadas deben coincidir con slots existentes.

## Contexto y selección

La sesión de Django conserva únicamente preferencias estructuradas, última respuesta y opciones vigentes. El contexto caduca tras 30 minutos de inactividad y las opciones/preselecciones tras 10 minutos. No hay modelos ni tablas de conversaciones; el almacenamiento sigue el backend habitual de sesiones. Se envía a OpenAI solo el estado y el mensaje actual, sin historial ilimitado; `store=False` evita guardar la respuesta como recurso recuperable de Responses (no modifica las políticas de retención aplicables al proveedor).

Cada opción tiene un identificador aleatorio ligado a la sesión. El POST de selección acepta únicamente ese identificador; no acepta precios ni metadatos del navegador. Django vuelve a cargar la cancha y revalida disponibilidad y anticipación mínima. Guarda únicamente ID, fecha, inicio, fin y fecha de creación en `chatbot_booking_draft`.

- Visitante: selección → login con `next=/chatbot/resume/` → login o registro existente → nueva validación → resumen de reserva existente.
- Usuario autenticado: selección → validación → resumen directamente.
- Si el horario cambió o venció durante el login, se elimina la preselección y se vuelve al catálogo con un aviso.

La preselección se consume una sola vez. El chatbot no crea, cancela ni modifica reservas. La confirmación continúa en el flujo normal, con sus validaciones existentes.

## UI y seguridad

El mismo partial aparece en Home, catálogo, detalle del establecimiento y disponibilidad. No aparece dentro del panel administrativo. El widget utiliza archivos locales, texto seguro mediante `textContent`, panel móvil, scroll interno, `visualViewport` para acomodar el teclado, foco inicial y recuperación al cerrar, Escape, etiquetas accesibles y `prefers-reduced-motion`.

Los endpoints POST conservan `CsrfViewMiddleware`; no se usa `csrf_exempt`. Antes de cada POST, el widget obtiene un token vigente desde GET `/chatbot/state/`, con cookies del mismo origen y sin caché, y lo envía mediante `X-CSRFToken`. Esto evita reutilizar el token anterior a un login. El panel no modifica formularios de autenticación.

Mensajes de 1 a 500 caracteres y JSON pequeño, límite por sesión de 8 consultas/minuto y por IP de 30/minuto, y bloqueo de una consulta simultánea por sesión. Se usa `REMOTE_ADDR`, no encabezados de proxy suministrados por el cliente. El SDK tiene timeout de 25 segundos, sin reintentos automáticos; la interfaz aborta después de 35 segundos y ofrece el catálogo. Los errores no exponen respuestas internas, claves ni excepciones del proveedor.

## Configuración

Reutiliza las variables existentes `OPENAI_API_KEY` y `OPENAI_MODEL`, cargadas desde el entorno/`.env` por Django. Ninguna clave/modelo está hardcodeado. No hay nuevas variables obligatorias ni SDK adicional. Mantener `.env` fuera de Git.

Pruebas aisladas, sin llamadas a OpenAI ni escritura en Neon:

```sh
.venv/bin/python manage.py test --settings=config.test_settings
node --check chatbot/static/chatbot/widget.js
node --test tests/dashboard_insights.test.cjs
```

Prueba explícita de interpretación real (consume tres solicitudes de la API, sin crear reservas):

```sh
.venv/bin/python manage.py probar_chatbot --settings=config.test_settings
```

Comprueba mañana a las 20:00, viernes a las 19:00 y Arena Caribe el sábado con hora faltante. La disponibilidad se prueba por separado con los servicios reales de Django y una base aislada.

## Archivos

Nuevos: `chatbot/apps.py`, `schemas.py`, `prompts.py`, `security.py`, `urls.py`, `views.py`, `tests.py`; `services/conversation.py`, `dates.py`, `openai_service.py`, `orchestrator.py`; `templates/chatbot/widget.html`; `static/chatbot/widget.css`, `widget.js`; `management/commands/probar_chatbot.py`; inicializadores de paquetes; este documento.

Modificados: `config/settings.py`, `config/urls.py`, `users/navigation.py`, `users/templates/users/home.html`, `courts/templates/courts/establecimientos.html`, `canchas.html`, `disponibilidad.html`, y `README.md`.

## Límites y deuda fuera del MVP

- El caché local predeterminado aplica los límites/bloqueos por proceso. Producción con varios workers requiere un caché compartido. Detrás de un proxy, configurar correctamente la IP confiable para evitar agrupar visitantes bajo la misma IP.
- El límite de 25 canchas es deliberado; catálogos mayores necesitarán paginación/priorización y optimización de consultas. No se ha cambiado la lógica existente de disponibilidad.
- Los tests de base de datos usan SQLite y no sustituyen las pruebas de concurrencia en PostgreSQL. La reserva definitiva mantiene la responsabilidad de impedir conflictos en el checkout existente.
- La comprobación del teclado móvil automatizada reduce el viewport; hace falta una prueba manual en dispositivo para validar teclados concretos de iOS/Android.
