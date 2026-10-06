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
