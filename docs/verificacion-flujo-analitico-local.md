# Verificación del incremento de flujo analítico local

Fecha de registro: 21 de octubre de 2026. Entorno local Windows, Python 3.11.17. No representa ejecución de CI ni evaluación empírica de la tesis.

- Suite completa: **318 pruebas aprobadas**, 0 fallos, 0 errores.
- Cobertura conjunta de líneas y ramas: **99.36 %**, sobre un mínimo configurado del 90 %.
- Ruff y Black: comprobación de código conforme.
- `pip check`: sin dependencias incompatibles.
- Inventario: 34 módulos de aplicación, 0 infracciones de límites entre capas.
- Manifiesto de software actual: `36dc287ea4933e7f1a7d580c5396e03487cf058980e981e82cd5418fe12217d4`; verificación sin diferencias.
- Plan PDF y Excel metodológico: huellas coincidentes con `local_source_hashes` del backlog.
- Se conserva una advertencia de deprecación de Starlette/TestClient con httpx en las versiones fijadas; no se cambiaron dependencias.

## Alcance comprobado

Importación CSV/JSONL y mapeo; límites de tamaño/filas; rechazo de estructuras ambiguas; deduplicación entre grupos de un archivo; identidades y referencias del catálogo; distinción entre keywords y tema inferido declarado; fechas de ajuste y disponibilidad histórica; comparación pareada de referencias sin prueba final; métricas indefinidas; transacciones, idempotencia, corrupción y linaje; paginación y filtros; errores/API/OpenAPI; contratos XAI pendientes; separación de observado y pronosticado; bloqueo de reconstrucción ante cambios de software; restauración y repetición de resultados guardados.

También se ejecutaron los ejemplos de consola de importación, catálogo, comparación, registro, consulta, dashboard, estado XAI y repetición con los fixtures explícitamente sintéticos. Los tests finales incluyen los controles posteriores de coherencia de software para dashboard y los requisitos de ejecución usados al registrar experimentos.

Los XML generados por pytest/cobertura permanecen en la raíz del repositorio y están excluidos de Git. Esta nota conserva el resumen, no afirma un commit, PR, aprobación, despliegue ni cambio de estado en Azure.

## Pendientes

Corpus y cobertura autorizados, extracción desde servicios reales, infraestructura Lakehouse y acceso Neo4j/MongoDB, ajuste/evaluación de modelos, XAI calculado y su evaluación, Angular/identidad/gateway y reproducción científica definitiva. Las pruebas de software no sustituyen estos resultados.

Consultar [guía de operación, flujo y trazabilidad](flujo-analitico-local.md), [manifiesto](environment-workflow-20261021.json) e [inventario](inventory-workflow-20261021.json).
