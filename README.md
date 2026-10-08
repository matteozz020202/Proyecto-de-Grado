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
por fila; móvil los apila. Insights queda vacío hasta conectar GPT: no hay respuestas
ni comparaciones ficticias. `dashboard_data.analysis_context` conserva el alcance
seleccionado para una integración futura.

Deuda pendiente: versionar horarios históricos, comprobar concurrencia con
PostgreSQL local e integrar GPT con validación de su contrato. No se modificaron
modelos ni migraciones para esta entrega.
