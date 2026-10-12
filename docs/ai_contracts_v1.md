# Contratos administrativos de IA v1.0

Capa determinística H4-01/H4-03 en `reservations/ai/`: prompt oficial único,
contratos Pydantic estrictos, catálogo de unidades y validación contra el input.
Los schemas y validators no conectan OpenAI ni calculan KPIs. El adaptador y el
servicio integran esta capa al dashboard bajo solicitud manual. Los ejemplos
siguientes son ilustrativos.

## Uso

```python
from reservations.ai.schemas import InputContract, AIAnalysis
from reservations.ai.validators import validate_analysis, InvalidAIResponse

input_validado = InputContract.model_validate(input_dict)
resultado = validate_analysis(input_validado, output_dict)  # También acepta JSON.
json_schema = AIAnalysis.model_json_schema()
```

`ValidationError` de Pydantic indica un error de estructura; `InvalidAIResponse`
indica evidencia incorrecta o ausencia del aviso sintético. Un resultado inválido
no devuelve insights parciales. El futuro servicio debe capturar estos errores.
Todos los campos son requeridos, incluso los que admiten `null`. No se convierten
strings o booleanos en números, ni se aceptan NaN, infinito o campos adicionales.

## Referencias de evidencia

El documento funcional no fija referencias para métricas globales ni identifica
cómo distinguir canchas con nombres iguales. La implementación usa esta convención
sin agregar campos al contrato:

| Métrica | `reference` |
| --- | --- |
| `summary.*`, `reservation_status_counts.*`, `comparisons.*` | `null` |
| `occupancy_by_court.*` | ID como texto, por ejemplo `"101"` |
| `occupancy_by_day.*` | Etiqueta exacta, por ejemplo `"Friday"` |
| `occupancy_by_time_slot.*` | Etiqueta exacta, por ejemplo `"18:00-20:00"` |

El catálogo se construye exclusivamente con métricas permitidas y valores no nulos
presentes en el input. Compara valores sin tolerancia ni redondeo; `50` y `50.0`
representan el mismo valor. No normaliza referencias. La unidad se obtiene mediante
`METRIC_UNITS`; `unit` se rechaza en la salida del modelo.

Para SYNTHETIC, al menos un elemento de `limitations` debe contener explícitamente
«datos sintéticos» y su destino de «demostración», «pruebas» o «validación funcional».
La comparación ignora mayúsculas y acentos y rechaza negaciones directas. Texto
recomendado: «El análisis utiliza datos sintéticos destinados a demostración y
validación funcional». Se exige también cuando `insights` está vacío.

Esta validación verifica estructura, referencias, cifras y la presencia del aviso;
no demuestra que toda la prosa esté en español o que la recomendación esté
semánticamente justificada. Sí exige comparación y evidencia de variación para
los tipos de cambio; rechaza variaciones porcentuales de reservas con base cero.
El resto de las reglas semánticas sigue en el prompt y requiere revisión funcional.
No se usa otro modelo como validador.

## Límites de integración pendientes

El adaptador de `dashboard_data` comparte el alcance de filtros con el dashboard.
El conteo y los valores financieros distinguen histórico/programado. El saldo
pendiente usa pagos aprobados por reserva, sin compensar sobrepagos entre reservas.
Mapea `SYSTEM`→`PLATFORM`, `HISTORICAL_REAL`→`HISTORICAL`; `ALL` exige escoger una
fuente. El contrato no cambió de versión ni incorporó campos adicionales.

La ocupación fuera de 0–100 se rechaza sin recortar ni corregir el KPI. Los datos
con capacidad inconsistente bloquean el análisis. Empates y null se conservan.
Los decimales del contrato usan la precisión de dos decimales del panel. Las
comparaciones se calculan en backend solo para histórico, usando un período previo
de igual duración; una base cero no genera un porcentaje de variación de reservas.

## Pruebas aisladas

```bash
.venv/bin/python manage.py test reservations.test_ai --settings=config.test_settings
.venv/bin/python manage.py test --settings=config.test_settings
```

## Input válido ilustrativo

```json
{
  "contract_version": "1.0",
  "analysis_context": {
    "venue_id": 1,
    "venue_name": "Arena de demostración",
    "court_id": null,
    "court_name": null,
    "start_date": "2026-08-01",
    "end_date": "2026-08-31",
    "analysis_type": "HISTORICAL",
    "data_source": "SYNTHETIC",
    "currency": "COP",
    "response_language": "es"
  },
  "summary": {
    "occupancy_rate": 50,
    "valid_reservations": 2,
    "reserved_hours": 2,
    "available_hours": 4,
    "reservation_value": 200000,
    "approved_deposits": 60000,
    "pending_balance": 140000,
    "cancellation_rate": 0,
    "average_booking_lead_hours": null
  },
  "reservation_status_counts": {
    "pending_payment": 0,
    "confirmed": 0,
    "completed": 2,
    "cancelled": 0,
    "expired": 0
  },
  "occupancy_by_court": [
    {
      "court_id": 101,
      "court_name": "Cancha 1",
      "reserved_hours": 2,
      "available_hours": 4,
      "occupancy_rate": 50
    }
  ],
  "occupancy_by_day": [
    {
      "day": "Friday",
      "reserved_hours": 1,
      "available_hours": 2,
      "occupancy_rate": 50
    },
    {
      "day": "Saturday",
      "reserved_hours": 1,
      "available_hours": 2,
      "occupancy_rate": 50
    }
  ],
  "occupancy_by_time_slot": [
    {
      "time_slot": "18:00-20:00",
      "reserved_hours": 2,
      "available_hours": 4,
      "occupancy_rate": 50
    }
  ],
  "comparisons": {
    "previous_period": null,
    "occupancy_variation_pp": null,
    "reservations_variation_pct": null
  },
  "extremes": {
    "highest_occupancy_days": [
      {
        "reference": "Friday",
        "value": 50
      },
      {
        "reference": "Saturday",
        "value": 50
      }
    ],
    "lowest_occupancy_days": [
      {
        "reference": "Friday",
        "value": 50
      },
      {
        "reference": "Saturday",
        "value": 50
      }
    ],
    "highest_occupancy_time_slots": [
      {
        "reference": "18:00-20:00",
        "value": 50
      }
    ],
    "lowest_occupancy_time_slots": [
      {
        "reference": "18:00-20:00",
        "value": 50
      }
    ]
  }
}
```

## Output válido con insight

```json
{
  "contract_version": "1.0",
  "analysis_summary": "El período de demostración registra una ocupación del 50%.",
  "insights": [
    {
      "type": "GENERAL",
      "priority": "LOW",
      "finding": "La ocupación global del período es del 50%.",
      "evidence": [
        {
          "metric": "summary.occupancy_rate",
          "reference": null,
          "value": 50
        }
      ],
      "recommendation": "Monitorear la evolución de la ocupación en períodos posteriores.",
      "justification": "La ocupación actual permite establecer una referencia para seguimiento."
    }
  ],
  "limitations": [
    "El análisis utiliza datos sintéticos destinados a demostración y validación funcional."
  ]
}
```

## Output válido sin insights

```json
{
  "contract_version": "1.0",
  "analysis_summary": "La información disponible no permite formular recomendaciones adicionales sustentadas.",
  "insights": [],
  "limitations": [
    "El análisis utiliza datos sintéticos destinados a demostración y validación funcional."
  ]
}
```

## Demostración ejecutada con el validador

```text
Con insight: VALID (1 insights)
Sin insights: VALID (0 insights)
Evidencia alterada: REJECTED — Valor de evidencia distinto al input: ('summary.occupancy_rate', None).
SYNTHETIC sin limitación: REJECTED — Falta una limitación explícita de datos sintéticos de demostración.
```
