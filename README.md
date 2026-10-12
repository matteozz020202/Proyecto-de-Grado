# Proyecto-de-Grado
PLATAFORMA INTELIGENTE PARA LA GESTIÓN DE RESERVAS DE CANCHAS DE FÚTBOL SINTÉTICAS MEDIANTE INTELIGENCIA ARTIFICIAL

## Pruebas locales aisladas

Con el entorno virtual activado y las dependencias de `requirements.txt` instaladas:

```bash
python manage.py test --settings=config.test_settings
```

Esta configuración usa SQLite en memoria y desactiva Neon. No modifica la base
de desarrollo ni la compartida. Valida el dashboard y el flujo de reservas;
los bloqueos y la concurrencia deben comprobarse también con PostgreSQL local.

El dashboard administrativo está en `/reservas/admin/dashboard/`. Por defecto
muestra reservas y pagos del sistema desde el 1 de enero hasta hoy; permite
seleccionar datos sintéticos, históricos reales o todos los orígenes.

## Filtros y ocupación

El panel permite filtrar por origen, establecimiento, cancha y fechas inclusivas
(máximo 366 días). Rechaza fechas inválidas y canchas ajenas al establecimiento
seleccionado. Estados, pagos aprobados, agendas y ocupación usan los mismos filtros.
Los pagos se filtran por fecha de la reserva, no por fecha de cobro.

El análisis histórico admite fechas hasta hoy y calcula ocupación exclusivamente
con reservas `COMPLETED`. El programado admite fechas desde hoy y usa `CONFIRMED`;
por defecto propone los próximos 30 días. Pendientes, canceladas y expiradas no
suman ocupación. Para hoy, el análisis programado cuenta solo la capacidad y las
horas confirmadas restantes desde la hora actual (incluye reservas en curso).
La agenda y el contador de hoy usan la fecha de Bogotá.

La ocupación es `SUM(horas reservadas) / SUM(horas disponibles) × 100`, calculada
globalmente y por cancha. La capacidad se deriva de los horarios activos con días
1–7, uniendo intervalos superpuestos para no duplicar capacidad. En el análisis
programado se excluye la capacidad de canchas o establecimientos inactivos.

Sin capacidad el porcentaje es `N/D` (null), no cero. Si las reservas exceden la
capacidad, se informa la inconsistencia sin recortar el resultado a 100%.
No existe un historial de cambios de horarios: la capacidad histórica utiliza
la configuración actual. Los resultados sintéticos se identifican como datos
de demostración que no representan actividad real de Barranquilla.

## Dashboard Sprint 3 (H3-08, H3-09 y H3-10)

El resumen prioriza ocupación, reservas válidas, horas reservadas, abonos aprobados
y cancelación. Abonos suma solo pagos `DEPOSIT` aprobados; el detalle económico
conserva el total de pagos aprobados (incluye saldos) y el valor almacenado de las
reservas válidas. Cancelación = `CANCELLED / (CONFIRMED + COMPLETED + CANCELLED)`;
sin reservas formalizadas devuelve N/D, no cero.

Chart.js 4.5.1 se sirve desde los archivos estáticos del proyecto, con su licencia
MIT. Presenta barras de ocupación por día, línea por franjas de una hora y dona de
estados existentes en el período. Sigue la [integración oficial](https://www.chartjs.org/docs/latest/getting-started/integration.html)
y las [opciones responsive](https://www.chartjs.org/docs/latest/configuration/responsive.html).

`reservations/analytics.py` calcula los KPIs y prepara el JSON seguro para las
gráficas. Distribuye horas entre franjas (incluidas horas parciales), une horarios
superpuestos y divide las sumas de horas por las sumas de capacidad. No calcula
ocupación a partir del conteo de reservas ni promedia porcentajes de canchas.
Los días sin capacidad usan null; las franjas sin capacidad se omiten. Los ejes
gráficos van de 0 a 100%; si los datos exceden capacidad se muestra una advertencia
y los valores originales quedan disponibles en las tablas de detalle.

Todos los bloques usan el mismo origen, venue, cancha y rango inclusivo. Últimas
reservas ordena por fecha de servicio descendente; próximas reservas muestra las
pendientes/confirmadas que aún no empiezan, dentro del mismo rango. Las selecciones
se conservan en GET; cambiar de venue actualiza las canchas y limpia una selección
incompatible. Restablecer elimina los parámetros y recupera los defaults.

Las gráficas incluyen tablas accesibles y estados vacíos. Si la librería no carga,
se muestra la tabla sin interrumpir KPIs o reservas. Escritorio muestra dos gráficos
por fila; móvil los apila. Insights inicia vacío: no hay respuestas
ni comparaciones ficticias al cargar la página. El administrador solicita el análisis
con el botón del componente H4-04. `dashboard_data.analysis_context` conserva el alcance
seleccionado para la integración.

Deuda pendiente: versionar horarios históricos, comprobar concurrencia con
PostgreSQL local e integrar GPT con validación de su contrato. No se modificaron
modelos ni migraciones para esta entrega.

## Sprint 4: contratos de IA v1.0

`reservations/ai/` centraliza el prompt administrativo, los contratos de entrada y
salida y la validación determinística de evidencia. Permite de 0 a 5 insights;
rechaza métricas/referencias/valores que no coincidan con el input y exige una
limitación explícita para datos sintéticos. La capa determinística no llama OpenAI
ni modifica los KPIs o reservas. El servicio de generación se solicita desde el
dashboard únicamente al pulsar el botón de análisis. Las pruebas automatizadas no requieren clave de API.

Consulta [convenciones, ejemplos y límites de integración](docs/ai_contracts_v1.md).

### H4-02: pruebas manuales de conexión

Django carga `.env` con `python-dotenv` desde la raíz del proyecto; las variables
del entorno del proceso tienen prioridad. Configura `OPENAI_API_KEY` y
`OPENAI_MODEL` según `.env.example`. No existe modelo por defecto ni credencial
en código. La clave queda exclusivamente en el servidor.

```bash
.venv/bin/python manage.py probar_openai --fase simple
.venv/bin/python manage.py probar_openai --fase structured
```

Sin `--fase`, ejecuta ambas en orden y se detiene si la primera falla. La primera
usa `responses.create` sin el prompt administrativo. La segunda usa
`responses.parse(text_format=AIAnalysis)`, el prompt oficial como instrucción de
sistema y el Input Contract sintético de
`reservations/ai/examples/input_v1.json`. Obtiene `output_parsed` y lo pasa por
los validadores determinísticos antes de mostrarlo. También admite
`--input /ruta/input.json`, validado contra el contrato antes de enviarlo.
La instrucción complementaria enumera las parejas métrica/referencia disponibles
en ese input; no modifica el prompt oficial ni el contrato JSON.

Son pruebas manuales que consumen la API. No consultan Neon, no tienen reintentos
automáticos y limitan cada solicitud a 30 segundos. Usan `store=False` y límites
de salida de 512/4096 tokens para simple/structured. No muestran la clave ni el
mensaje crudo del proveedor. Clasifican fallos de autenticación, billing/cuota,
modelo, red, timeout, schema y evidencia. El comando es independiente del dashboard.

### AIAnalysisService y validación de cambios

`reservations/ai/services.py` ofrece `AIAnalysisService.generate(input_data)`.
Acepta únicamente un `InputContract` o dict validable y devuelve `AIAnalysis`
después de aplicar los validadores. No consulta reservas ni calcula KPIs.
Usa la clave/modelo del servidor, `store=False`, máximo 4096 tokens de salida,
64000 bytes de mensajes (incluye prompt y catálogo), timeout de 30 segundos por
solicitud y máximo dos intentos, separados por un segundo. El timeout es el del
transporte HTTP, no un plazo absoluto para toda la operación. Los reintentos del
SDK están desactivados, también para clientes inyectados. Nunca devuelve una
respuesta ficticia o parcial cuando falla.

Reintenta una vez errores de red/timeout/servidor y respuestas inválidas. No
reintenta rechazo explícito del modelo, credenciales, billing, modelo no disponible
ni rate limit. El consumidor recibe `AIAnalysisError.code` sin mensaje crudo del
proveedor. El servicio no escribe logs, no modifica el estado global de logging y
cierra los clientes que crea; un cliente inyectado pertenece al llamador.

Los tipos `OCCUPANCY_CHANGE` y `RESERVATION_CHANGE` requieren período anterior,
las métricas actual/anterior disponibles y una variación no nula citada en la
evidencia. El cambio porcentual de reservas requiere un conteo anterior mayor que
cero. Cero de ocupación previa sí permite variaciones en puntos porcentuales.
Estas comprobaciones no recalculan ni corrigen KPIs.

Prueba manual del servicio completo (máximo dos solicitudes):

```bash
.venv/bin/python manage.py probar_openai --fase servicio
```

Las fases `simple` y `structured` conservan un solo intento. La fase `structured`
reutiliza el mismo servicio con reintentos desactivados.

Las pruebas automatizadas de `reservations.test_openai` usan simulaciones y el
SDK real con transporte HTTP simulado; no consumen API ni dependen de credenciales.

La implementación sigue la documentación oficial de
[Responses y el SDK Python](https://developers.openai.com/api/reference/python) y
[Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses).

## H4-04: insights del dashboard

El panel carga en estado IDLE. «Generar análisis» envía POST con CSRF y los filtros
aplicados (incluye defaults normalizados), sin enviar KPIs editables por el navegador.
El endpoint `/reservas/admin/dashboard/analisis/` verifica permisos de administrador,
valida los filtros y reconstruye los KPIs en el servidor usando el alcance compartido.
No acepta canchas ajenas al establecimiento. La respuesta HTML escapa los textos
producidos por el modelo y presenta resumen, hallazgos, evidencia con unidades del
backend, recomendaciones, justificaciones y limitaciones. Cero insights es un éxito
válido con mensaje de información insuficiente. Las recomendaciones son opcionales
para el administrador; no se ejecuta ninguna acción de negocio.

JavaScript muestra LOADING, SUCCESS o ERROR, bloquea envíos repetidos durante la
solicitud y conserva KPIs y gráficos ante errores. Generar análisis consume la API;
abrir, filtrar o paginar el dashboard no la invoca. Cambiar filtros inicia un nuevo
contexto sin reutilizar respuestas anteriores. No se guarda el análisis en la base.

El adaptador `reservations/ai/adapters.py` mapea SYSTEM→PLATFORM e
HISTORICAL_REAL→HISTORICAL, conserva SYNTHETIC y exige un origen específico en vez
de ALL. Conserva null y todos los empates. Canchas, días y franjas usan las referencias
del contrato. Los valores decimales enviados usan dos decimales, como la presentación
del panel; el modelo debe citarlos exactamente. Inconsistencias de capacidad bloquean
la generación sin recortar los datos originales mostrados en el dashboard.

El resumen histórico usa COMPLETED y el programado CONFIRMED, también para conteo,
valor, abonos y saldo pendiente. Hoy, el programado excluye confirmadas ya terminadas.
El saldo es la suma de `max(valor - pagos aprobados, 0)` por reserva: incluye abonos y
saldos y evita compensar deudas con sobrepagos de otras reservas. La distribución de
estados y el total operativo de pagos mantienen todos los estados del contexto.
La anticipación promedio usa fecha/hora del servicio menos fecha real de creación;
si hay fechas de creación posteriores al servicio, se reporta null.

El histórico compara con el intervalo inmediatamente anterior de igual duración,
conservando origen y canchas. Base cero devuelve null para variación porcentual de
reservas. El programado no compara con un período pasado. Una capacidad previa
inconsistente deja las comparaciones no disponibles. Los horarios históricos se
estiman con la configuración actual; esa limitación se presenta en el componente.

Validación aislada:

```bash
.venv/bin/python manage.py test --settings=config.test_settings
node --test tests/dashboard_insights.test.cjs
```
