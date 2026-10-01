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
muestra reservas y pagos del sistema; permite seleccionar datos sintéticos,
históricos reales o todos los orígenes. Los estados e ingresos son acumulados;
la agenda y el contador de hoy corresponden a la fecha de Bogotá.
