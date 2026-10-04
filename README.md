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

## Dataset sintético v1.1

Instalar `openpyxl` (declarado en `requirements.txt`). El comando acepta el ZIP
ajustado o su Excel Core; no importa las hojas analíticas/capacidad en tablas nuevas.

```bash
# Validar archivo y relaciones sin conectarse a la base ni guardar datos:
python manage.py importar_dataset /ruta/Cancha_Lista_Dataset_Sintetico_v1_1_Ajustado.zip

# Cargar en la base elegida por .env (USE_NEON=True para Neon):
python manage.py importar_dataset /ruta/Cancha_Lista_Dataset_Sintetico_v1_1_Ajustado.zip --commit
```

Se validan IDs, referencias, estados, pagos aprobados, montos y solapamientos.
La carga es transaccional: cualquier colisión revierte toda la operación. No borra
ni sobrescribe registros existentes. Una repetición con el mismo archivo omite
registros idénticos. Los IDs originales se conservan excepto los de usuarios,
que se mapean a cuentas `synthetic_v1_1_<id>`, inactivas, sin privilegios ni
contraseña utilizable. Los hashes/contraseñas del Excel no se importan.

El porcentaje de abono del Excel se convierte de fracción a porcentaje (0.30 → 30).
Se conservan fechas, valores, referencias de pago y estados del archivo, con
timezone de Django (Bogotá). No se desplazan fechas para simular demanda actual.
El dataset cubre enero–septiembre de 2026 y no describe actividad real.

En el dashboard, seleccionar **Sintético** para visualizar los datos importados.
La expiración lazy puede convertir pendientes históricos vencidos a `EXPIRED`
al consultar las vistas; repetir la importación no revierte esas expiraciones.
Las tablas de usuarios, canchas, horarios, reservas y pagos se bloquean durante
la carga PostgreSQL para impedir importaciones o escrituras simultáneas.
