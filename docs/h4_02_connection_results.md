# H4-02: comprobación real del 11 de octubre de 2026

SDK instalado y declarado: `openai==3.7.0`. Django carga `.env` mediante
`load_dotenv(BASE_DIR / ".env")`, sin reemplazar variables existentes del proceso.
`OPENAI_API_KEY` y `OPENAI_MODEL` se leen solo en el servidor, sin valores por defecto.
No se registra aquí la clave. No se cambiaron el dashboard ni la base de datos.

## Resultados

- `probar_openai --fase simple`: `SIMPLE_OK`. La clave corregida, el modelo configurado
  y `responses.create` funcionaron. El problema inicial de autenticación quedó resuelto.
- `probar_openai --fase structured`: inicialmente rechazado por la validación local.
  Una repetición identificó `INVALID_EVIDENCE_REFERENCE`. Se añadió a la instrucción
  complementaria el catálogo de parejas métrica/referencia disponibles en el input.
  No se relajaron las validaciones ni se cambió el prompt oficial.
- La prueba posterior devolvió `STRUCTURED_OK`: `response.output_parsed` contenía
  `AIAnalysis` con 3 insights. Pasaron estructura v1.0, evidencia exacta y aviso sintético.
  Los insights describieron ocupación del 50%, empate entre viernes/sábado y cero
  cancelaciones. Son resultados de un ejemplo sintético, no métricas reales del negocio.
- No se observaron errores de billing o acceso al modelo en las llamadas exitosas.
- Suite aislada: 89 pruebas aprobadas. Incluye el SDK real con transporte HTTP simulado;
  las pruebas automatizadas no consumen API ni usan Neon.

## Límite detectado y resuelto en el siguiente incremento

El modelo etiquetó el hallazgo global como `OCCUPANCY_CHANGE` aunque el input no
incluía comparación previa. En la prueba inicial, los validadores solo comprobaban
estructura y evidencia. Por tanto, `STRUCTURED_OK` no certifica
que todos los textos y tipos satisfagan todas las reglas funcionales del prompt.
El incremento posterior añadió una comprobación determinística para los tipos de
cambio: período anterior y métricas disponibles, variación citada en la evidencia
y base de reservas mayor que cero para cambio porcentual. No se añadieron campos
ni se cambió la versión del contrato. Sigue pendiente la evaluación semántica del
resto de categorías y textos; por ejemplo, no hay umbrales contractuales para llamar
«alta» a una ocupación del 50%, y el modelo puede reproducir etiquetas de días en
inglés dentro de textos visibles.

## Servicio implementado y comprobado

Se creó `AIAnalysisService` en `reservations/ai/services.py` con
`generate(input_data) -> AIAnalysis`. Reutiliza el prompt, el catálogo,
`responses.parse(text_format=AIAnalysis)` y `validate_analysis`. Recibe únicamente
datos agregados validados, con límites y máximo dos intentos. Ante error devuelve
una excepción propia segura, sin inventar insights.

`probar_openai --fase servicio` funcionó en una prueba real: devolvió 4 insights,
evidencia exacta y limitación explícita sintética. Reconoció la ausencia de período
anterior y no produjo categorías de cambio. La suite aislada pasó 109 pruebas.

El trabajo local está en `sprint4/ai-analysis-service`, creada desde `main`
conservando los cambios existentes. No se creó commit ni se publicó la rama.

En esta comprobación H4-02 el servicio todavía no se conectaba al dashboard.
La integración manual posterior de H4-04 se describe en README.md.
