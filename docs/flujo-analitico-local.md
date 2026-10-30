# Desarrollo del flujo analítico local

Esta entrega amplía R03, R07–R08, R11–R16, R19, R20, R24 y R30 hasta el nivel que permite el estado actual del proyecto. Implementa comportamiento de software verificable; no sustituye la obtención del corpus ni la validación de modelos. El plan, el Excel, Prism, los repositorios externos y los estados de Azure no se modifican.

La inspección de este incremento queda en [el manifiesto de entorno](environment-workflow-20261021.json) y [el inventario](inventory-workflow-20261021.json). Los JSON previos sin `workflow` en su nombre se conservan como evidencia histórica del incremento anterior; no se espera que sus huellas coincidan con estas nuevas fuentes.

## Capacidades y límites

| Bloque | Implementación disponible | Condición pendiente |
| --- | --- | --- |
| Exportaciones | CSV/JSONL UTF-8, diccionario, mapeo explícito, diagnóstico, manifiesto por archivo y lotes lógicos; curación y deduplicación entre lotes del mismo archivo | Adaptar la extracción a la fuente autorizada; verificar cobertura, derechos y conflictos entre archivos |
| Catálogo | Identificadores, etiquetas, términos, asignaciones documentales, documentos sin asignar, huellas del catálogo/definición y evidencia de ajuste declarada | Entrenar el modelo temático y obtener términos/documentos representativos; validación temática y etiquetas para clasificación |
| Referencias | Último valor y estacional ingenua comparados sobre los mismos orígenes, horizonte y observaciones | Objetivo definitivo y selección de modelos entrenados con corpus autorizado |
| Experimentos | Solicitud, resultado calculado, versiones, software, relaciones entre artefactos y repetición verificable | Artefactos de modelos finales, datos reales, infraestructura compartida y paquete científico final |
| Consulta | Listado paginado/filtrado, recuperación por identificador, vacío, insuficiencia y errores explícitos | Identidad remota y control de acceso integrado |
| XAI | Contrato local/global enlazado con experimento, modelo, entradas y predicciones; estado pendiente o no disponible | Seleccionar e implementar el explicador compatible; calcular atribuciones y evaluar fidelidad/estabilidad |
| Dashboard | Contrato y proyección de datos con observado y pronosticado separados, filtros temporales, unidades y cobertura | Implementación visual en el Angular existente `centinela-front`; pruebas de integración |

SQLite sigue siendo el repositorio local de evidencia. No es el Data Lakehouse exigido por el plan y no reemplaza Neo4j/MongoDB. Estos adaptadores y el despliegue Lakehouse siguen pendientes de recursos y configuración reales.

## Importación sin inferencias sobre la fuente

`python -m app.imports dictionary` publica los campos admitidos. Se exigen `source`, `source_id`, `title` y `retrieved_at`; las fechas de publicación/disponibilidad desconocidas permanecen ausentes o nulas. No se convierte una fecha de descarga en disponibilidad histórica.

Cada archivo admite hasta **8 MiB y 1000 filas**. `--batch-size` divide el manifiesto en grupos de 1–1000 filas; no elimina el límite por archivo ni habilita ingestión distribuida. La deduplicación se ejecuta sobre el archivo completo para detectar duplicados y conflictos que crucen sus grupos. Los identificadores del manifiesto incluyen formato, huella original, mapeo y tamaño de grupo; la identidad del dataset curado sigue sus propias reglas.

CSV requiere encabezados únicos y filas con igual número de columnas. Las palabras clave se representan como un arreglo JSON dentro de la celda; no se adivinan delimitadores. Una celda opcional vacía pasa a nulo, salvo palabras clave vacías, que pasan a lista vacía, y acceso vacío, que conserva `unknown`. JSONL exige un objeto por línea y rechaza líneas vacías, claves duplicadas y números no finitos. Un salto final de línea es válido.

Un archivo opcional de mapeo usa **campo canónico → columna de origen**. Los campos ajenos deben ignorarse explícitamente:

```json
{
  "fields": {
    "source": "provider",
    "source_id": "external_id",
    "title": "title",
    "retrieved_at": "retrieved_at",
    "publication_date": "published_on"
  },
  "ignored_columns": ["unused_export_column"]
}
```

El diagnóstico devuelve filas originales adaptadas y resultado de curación. Revisar su contenido antes de compartirlo, puesto que puede contener textos autorizados del corpus. Código de salida: 0 compatible, 1 requiere correcciones de filas, 2 error estructural, de contrato o lectura. No se escribe una base durante la inspección. Para guardar un lote corregido, pasar su objeto `batch` al comando existente `app.cli curate --database`.

## Catálogo y prevención de fuga temática

Los métodos son `manual`, `keywords` y `topic_model`. Los dos primeros no aceptan metadatos de ajuste. `keywords` exige coincidencia exacta, sin distinguir mayúsculas, entre algún término del tema y una palabra clave del documento asignado; no lo presenta como tema inferido. No se entrena un clasificador a partir de estas asignaciones.

`topic_model` registra un artefacto **declarado por quien llama**: versión, documentos de ajuste conocidos y corte. Comprueba fechas de publicación y disponibilidad anteriores o iguales al corte y conserva una huella del contenido de ajuste. Esto comprueba coherencia de lo declarado, no demuestra que un modelo realmente haya sido entrenado.

`series/from-catalog` conserva la definición temática calculada y exige que un ajuste declarado anteceda al inicio de la ventana de la serie. Para una evaluación con varios ajustes temporales será necesario construir un catálogo independiente por partición, registrar sus documentos de ajuste y resolver la alineación entre temas. No se aplica aquí un único modelo ajustado con documentos futuros. El endpoint anterior `series/build` sigue aceptando asignaciones proporcionadas, con sus límites de evidencia documentados.

## Comparación temporal

`evaluations/compare` ejecuta las dos referencias y retiene la intersección de sus orígenes válidos. Los orígenes imposibles y los disponibles para un solo método se reportan; no se compara el promedio de una referencia con el de otra evaluada sobre un conjunto distinto. La prueba final permanece reservada.

Para los conteos históricos usados por esos orígenes se exige disponibilidad conocida antes de terminar el mes de publicación. Sin esa evidencia se rechaza la comparación de esta serie congelada; no se finge que una incorporación tardía ya era conocida. Una fuente con revisiones o llegadas tardías requerirá reconstrucción dinámica «as of», que aún no está implementada. Los documentos sin fecha siguen reportados como ausentes, y la cobertura completa sigue siendo una declaración que se deberá contrastar con la fuente.

Se agregan MAE, RMSE y WAPE sobre pares origen-objetivo. Los horizontes superpuestos se cuentan como eventos de pronóstico diferentes, no como observaciones independientes para inferencia estadística. MASE se presenta como media de los MASE por origen y se deja nulo si alguna escala necesaria es indefinida. Volumen cero deja WAPE nulo. Sin orígenes comunes, las métricas quedan nulas, `n=0` y no se declara preferencia.

`preferred_by_validation_mae` indica exclusivamente la referencia con menor MAE en esos pares, o empate. No selecciona un modelo entrenado ni acredita generalización. La identidad de comparación excluye valores reservados; las identidades de la serie/dataset completo pueden cambiar cuando se corrigen esos valores.

## Registro y reproducción

Tipos iniciales: `topic_catalog`, `reference_forecast`, `reference_comparison`. Cada solicitud se valida según su tipo. El servidor calcula el resultado; no acepta métricas o atribuciones que el cliente pretenda registrar como resultados calculados.

Un artefacto incluye solicitud canónica, resultado, huellas/versiones y manifiesto de software. Su identidad SHA-256 es determinista para ese contenido y entorno; la misma solicitud se guarda de forma idempotente si el resultado/software no cambian. Un cambio de código o paquetes genera otra identidad. La huella detecta diferencias y no constituye firma de origen.

El registro verifica los requisitos de ejecución de `requirements.txt` y registra también todas las distribuciones instaladas. No exige instalar herramientas de desarrollo para guardar un artefacto en un entorno de ejecución. La proyección de dashboard reconstruye conteos históricos desde la solicitud guardada y exige que el entorno/software coincida antes de combinarlos con el pronóstico guardado; ante diferencias se conserva accesible el detalle original, pero se rechaza esa reconstrucción.

Los padres deben existir, ser únicos y compartir dataset y clase de datos. Si el padre es un catálogo, el hijo debe usar su definición temática. No se permite enlazar arbitrariamente un experimento sintético con uno empírico. La transacción revierte inserciones fallidas y se comprueban payload e índice antes de confirmar; no se reparan silenciosamente registros alterados.

Las lecturas abren SQLite en modo de solo lectura. Un listado sobre una base inexistente devuelve vacío sin crearla. Paginación: `limit=1..100`, `offset=0..1000000`; orden por identidad. Filtros: tipo, clase de datos, tema y estado. No se devuelve el corpus completo en un listado. El detalle sí contiene la solicitud y debe tratarse como dato autorizado. Los artefactos individuales tienen un límite de 8 MiB incluyendo solicitud, resultado y manifiesto; puede ser necesario reducir el lote.

`replay` verifica primero software, paquetes y versiones del entorno. Si hay diferencias, devuelve `mismatch` y no recalcula. Si coinciden, vuelve a ejecutar únicamente el algoritmo implementado y compara el resultado completo. No escribe ni modifica el registro. Códigos: 0 coincide, 1 diferencia, 2 error. La lectura simple de un artefacto conserva su resultado sin entrenar ni recalcular modelos.

## API preparada para el frontend existente

Las nuevas rutas usan el mismo prefijo `/api/v1` y aparecen en OpenAPI:

| Método | Ruta | Función |
| --- | --- | --- |
| GET | `/datasets/dictionary` | Diccionario de exportación |
| POST | `/topics/catalog` | Verificar y versionar catálogo declarado |
| POST | `/series/from-catalog` | Construir serie con definición del catálogo |
| POST | `/evaluations/compare` | Comparación pareada de referencias |
| POST | `/experiments` | Calcular y guardar un experimento local |
| GET | `/experiments` | Consultar resúmenes paginados |
| GET | `/experiments/{id}` | Leer el artefacto completo |
| GET | `/experiments/{id}/explanation` | Consultar estado XAI local/global |
| GET | `/experiments/{id}/dashboard` | Datos observados y pronósticos separados |
| GET | `/dashboard/contract` | Estados, unidades y reglas de representación |

La ubicación SQLite se configura **en el servidor** mediante `ANALYTICS_ARTIFACT_DATABASE`. No se aceptan rutas de archivo del navegador. Sin configuración, las rutas de registro devuelven 503; una identidad inexistente devuelve 404; errores analíticos/contratos, 422; fallos SQLite, 503 sin detalles internos. Los límites HTTP existentes conservan sus respuestas 400/413 y el identificador de traza.

Todas estas rutas siguen restringidas a `ANALYTICS_ENVIRONMENT=local`. La configuración Compose heredada usa `local`; el responsable debe seleccionar explícitamente `staging`/`production` al desplegar hasta integrar identidad. No se ha publicado este registro en el gateway. El contenedor heredado es de solo lectura: la futura persistencia en contenedor requiere un volumen autorizado y configuración específica, que no se añade aquí.

Para el Angular existente: `loading` y `error` son estados de la solicitud en el cliente; la respuesta distingue `ready`, `empty` e `insufficient_data`. Mostrar observaciones hasta el corte y pronósticos posteriores en series/leyendas distintas. Mantener huecos de cobertura; no convertirlos en ceros ni presentar intervalos de confianza no calculados. Las explicaciones siguen `pending`/`unavailable`, con método nulo y atribuciones vacías. No se ha implementado todavía una pantalla Angular.

## Verificación manual en Git Bash

Ejecutar desde la raíz de `analytics-service`, con `.venv` activado. Las muestras incluidas son exclusivamente sintéticas y sirven para comprobar software:

```bash
source .venv/Scripts/activate
mkdir -p ../evidencias_locales
python -X utf8 -m app.imports dictionary
python -X utf8 -m app.imports inspect --input tests/fixtures/synthetic_corpus.jsonl --format jsonl --data-kind synthetic --batch-size 2 > ../evidencias_locales/import-workflow.json
python -X utf8 -m app.cli catalog --input tests/fixtures/synthetic_catalog.json > ../evidencias_locales/catalog-workflow.json
python -X utf8 -m app.cli compare --input tests/fixtures/synthetic_comparison.json > ../evidencias_locales/comparison-workflow.json
python -X utf8 -m app.experiments save --database ../evidencias_locales/analytics-workflow.sqlite --input tests/fixtures/synthetic_experiment.json > ../evidencias_locales/experiment-workflow.json
python -X utf8 -m app.experiments list --database ../evidencias_locales/analytics-workflow.sqlite --kind reference_forecast --data-kind synthetic
```

Copiar `experiment_id` de `experiment-workflow.json` y sustituir `ID_REAL`:

```bash
python -X utf8 -m app.experiments show --database ../evidencias_locales/analytics-workflow.sqlite --id ID_REAL
python -X utf8 -m app.experiments dashboard --database ../evidencias_locales/analytics-workflow.sqlite --id ID_REAL
python -X utf8 -m app.experiments explanation --database ../evidencias_locales/analytics-workflow.sqlite --id ID_REAL --scope global
python -X utf8 -m app.experiments replay --database ../evidencias_locales/analytics-workflow.sqlite --id ID_REAL
```

Para probar Swagger sobre la misma base, iniciar en una terminal aparte:

```bash
source .venv/Scripts/activate
export ANALYTICS_ENVIRONMENT=local
export ANALYTICS_ARTIFACT_DATABASE="../evidencias_locales/analytics-workflow.sqlite"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8006
```

Abrir `http://127.0.0.1:8006/docs`. El proceso guarda únicamente cuando se invoca POST `/experiments`; catálogo, series y comparación aislados no escriben. El importador de consola es de solo lectura. No introducir credenciales ni corpus real en los fixtures versionados.

## Git y revisión a cargo del titular

En VS Code revisar nuevos módulos, pruebas y documentación. En Git Bash comprobar la rama y los archivos; conservar el trabajo previo que todavía no esté confirmado:

```bash
git branch --show-current
git status --short
git --no-pager diff --stat
git --no-pager diff
```

Si se continúa en `feature/r01-platform-baseline`, no hace falta cambiar de rama ni recrearla. Los archivos nuevos se revisan en VS Code porque `git diff` no los muestra antes de agregarlos. Mantener las bases, los diagnósticos con datos y las evidencias de trabajo fuera del repositorio, como en los comandos anteriores. Agregar únicamente los archivos revisados:

```bash
git add app tests docs README.md
git --no-pager diff --cached --stat
git --no-pager diff --cached
git commit \
  -m "feat(analytics): add versioned analytical workflows" \
  -m "Prepare explicit corpus imports, thematic evidence, paired reference evaluation and reproducible experiment queries before empirical integration."
```

No repetir el commit si ya se ejecutó; comprobar `git status`. Cuando Danny confirme el permiso de escritura, el titular podrá hacer push de la rama y abrir el PR hacia `develop`, con issue real, enlace al work item, 2 aprobaciones y CODEOWNERS. Si ya existe PR para la rama, el push lo actualizará. No afirmar en el PR que se entrenaron modelos, se integró el frontend o se validó corpus real.

## Evidencia en Azure sin cerrar anticipadamente el alcance

Estas sugerencias se basan en los títulos/criterios del backlog local; no son una lectura actualizada de los estados remotos. Revisar el estado existente antes de cambiarlo. Registrar commit real, prueba ejecutada, alcance y pendiente.

| Ítem | Avance de esta entrega | Tratamiento sugerido |
| --- | --- | --- |
| T07.1–T07.3 (39–41) | Adaptador CSV/JSONL, asociación por identificadores y manifiesto de archivo/grupos | `Active`: extracción de fuentes y reingestión del corpus autorizado pendientes |
| T11.1–T11.2 (55–56) | Catálogo versionado, referencias documentales y validaciones | `Active`: extracción de términos/documentos representativos y revisión empírica pendientes |
| T11.3 (57) | Se preserva la distinción entre keywords, declaración manual y modelo | Mantener pendiente de etiquetas válidas; no hay clasificador entrenado |
| T12.2 (60) | Definición temática y evidencia de ajuste conservadas | `Active`: catálogos por partición y alineación de temas reales pendientes |
| T13.3 (65) | Último valor y estacional ingenua comparables en pares temporales idénticos | Candidato a `Resolved` para implementación técnica tras revisar y ejecutar; R13 continúa abierto por el objetivo/corpus |
| T14.1–T14.3 (67–69) | Protocolo pareado y registro de configuraciones/resultados de referencias | `Active`: no hay candidatos entrenados, ajuste empírico ni modelo final seleccionado |
| T15.1–T15.2 (71–72) | Persistencia de referencias, contratos y estados de insuficiencia | La parte técnica está implementada; T15.2 puede resolverse tras revisión si no tiene criterios adicionales. R15 sigue abierto por evaluación reservada/modelo final |
| T16.1 (75) | Identidades de entradas, modelo y predicción enlazadas en contrato XAI | `Active`: identificar variables y salida del predictor definitivo sigue pendiente |
| T16.2–T16.3 (76–77), R17–R18 | No se selecciona ni ejecuta un explicador | Conservar pendientes; las atribuciones vacías no satisfacen XAI |
| T19.1/T19.3 (87/89) | Rutas, esquemas y pruebas de consulta/errores locales ampliadas | `Active`: contrato XAI calculado y restricciones integradas siguen pendientes |
| T19.2 (88) | Guardas locales conservadas | Pendiente la integración real de gateway/identidad |
| T20.1–T20.3 (91–93), R27 | Contrato backend para filtros, estados y observado/pronóstico | No resolver: aún no hay implementación Angular ni validación visual |
| T24.1–T24.2 (107–108) | Más pruebas de dominio, persistencia, API y consola | Registrar resultado local; no declararlo prueba de servicios externos |
| T30.1–T30.3 (131–133) | Registro de software/artefactos y repetición de algoritmos implementados | `Active`: faltan datos/modelos/informes definitivos y versión final |

No cerrar épicas/features por esta entrega. Eliminar dependencia de personas en pruebas sigue siendo la preferencia del proyecto y la propuesta CR01; no se presenta como cambio académico aprobado del OE6.
