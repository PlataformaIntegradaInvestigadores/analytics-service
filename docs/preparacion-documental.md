# Preparación documental y consultas para desarrollo

Incremento relacionado con R08–R12, R19, R20, R24 y R30. Implementa software de preparación/consulta y protocolos de candidatos. No ejecuta entrenamiento, no elige un algoritmo definitivo y no transforma el permiso de desarrollo en autorización académica. La cobertura temporal, idioma y precisión de fechas siguen sin verificar.

## Procesamiento y conjuntos reproducibles

Se conserva el documento recibido en la instantánea del corpus. La preparación genera otro registro: título y resumen normalizados con Unicode NFKC y espacios, texto combinado, tokens Unicode sin inventar idioma, cantidad de tokens y huellas. La separación por tokens es una operación neutral para desarrollo; no acredita un preprocesamiento lingüístico óptimo. No se aplican stopwords, lematización ni stemming dependientes de idioma. Los signos originales se mantienen en el texto preparado; la detección de duplicados utiliza el texto normalizado sin distinguir mayúsculas, conservando puntuación.

Los criterios configurables son ausencia de resumen (`exclude` o `title_only`), mínimo de tokens, filtro anual y duplicados (`keep` o `exclude_later`). El filtro anual selecciona documentos de una instantánea; no crea por sí mismo particiones temporales libres de fuga. Los candidatos a deduplicar se examinan después de cumplir los otros criterios. El orden estable es por identificador de artículo, no por fecha; `exclude_later` significa posterior en ese orden, no posterior publicación.

El manifiesto registra configuración, versión del procesador, fuente original, procesamiento de esa fuente, huellas del software, identificadores incluidos, huella de cada registro preparado, exclusiones motivadas y grupos duplicados. La misma fuente/configuración/software produce la misma identidad. Cambios de software modifican la identidad. Contiene identificadores del corpus y debe permanecer en el espacio autorizado, fuera de GitHub.

La instantánea fuente se abre en modo de solo lectura con una transacción consistente. La preparación se guarda en una base nueva y separada, transaccionalmente, sin sobrescribir. Se publica solo al finalizar. La lectura de conjuntos preparados comprueba identidad del manifiesto, pertenencia y huellas de registros. Estas comprobaciones detectan alteraciones respecto del manifiesto; no son una firma del proveedor ni una certificación de completitud.

## Consultas y exploración

- Artículos paginados, ordenados por identificador; filtros por año, presencia de resumen, autor y descriptor normalizado.
- Detalle documental con asociaciones de autor y descriptores. No se entrega el registro bruto de citaciones como variable predictiva.
- Descriptores paginados por frecuencia de artículos distintos, con desempate alfabético. Los autores/descriptores se consultan mediante subconsultas para evitar multiplicación por cruces de relaciones.
- Resumen de diagnóstico con alcance de uso, cantidades y distribuciones de la instantánea. Mantiene la distinción entre descriptores del origen y temas inferidos, y entre fecha de publicación y disponibilidad histórica.
- Estado `empty` para páginas sin elementos. `loading` y `error` pertenecen al ciclo de la consulta en el frontend; `ready_for_development` describe datos disponibles para desarrollo, no un modelo listo para producción.

Las páginas admiten 1–100 elementos y offset hasta 1.000.000. Las consultas no alteran las bases. La exploración sigue limitada a la instantánea, sin equiparar un cero a ausencia de producción en la población.

## Preparación del modelado y evaluación estructural

El protocolo de candidato enlaza nombre/configuración con el conjunto preparado y enumera evidencia que requerirá una ejecución: librerías, semilla cuando aplique, huella del modelo ajustado, documentos de ajuste, variables, asignaciones, términos y documentos representativos. El ejemplo `development-contract-check` comprueba contratos; no nombra un algoritmo seleccionado o ejecutado. Su estado es `pending_use_clarification`.

La evaluación estructural acepta salidas declaradas: versión del modelo, identificadores de ajuste, asignaciones y términos por tema. Rechaza documentos desconocidos o excluidos, ajuste con identificadores repetidos, temas desconocidos, términos vacíos/excesivos/repetidos. Calcula cobertura de asignación, documentos no asignados, tamaños por tema y diversidad de términos como términos únicos/total de términos declarados. Estas son métricas estructurales sobre la salida suministrada; no acreditan que un modelo haya sido entrenado. La coherencia temática queda nula y no se inventa una calificación de calidad ni fidelidad XAI.

El ajuste y evaluación empírica requieren autorización/alcance aclarados, idioma/preprocesamiento apropiados y un protocolo temporal válido cuando se vaya a pronosticar. La selección de algoritmos y sus dependencias vendrá después; este incremento no instala librerías de ML ni aprovecha citaciones potencialmente futuras.

## Consola en Git Bash

Desde analytics-service, con una instantánea creada mediante el adaptador del incremento anterior:

```bash
source .venv/Scripts/activate
mkdir -p ../evidencias_locales
python -X utf8 -m app.documents summary --database ../evidencias_locales/corpus-development-v1.sqlite
python -X utf8 -m app.documents articles --database ../evidencias_locales/corpus-development-v1.sqlite --year 2024 --limit 10
python -X utf8 -m app.documents descriptors --database ../evidencias_locales/corpus-development-v1.sqlite --limit 20
python -X utf8 -m app.documents preview --database ../evidencias_locales/corpus-development-v1.sqlite --input docs/examples/preparation.json > ../evidencias_locales/preparation-preview.json
python -X utf8 -m app.documents prepare --database ../evidencias_locales/corpus-development-v1.sqlite --input docs/examples/preparation.json --output ../evidencias_locales/prepared-development-v1.sqlite > ../evidencias_locales/prepared-manifest-v1.json
python -X utf8 -m app.documents workset --database ../evidencias_locales/prepared-development-v1.sqlite
python -X utf8 -m app.documents protocol --database ../evidencias_locales/prepared-development-v1.sqlite --input docs/examples/topic-candidate.json
```

Para un detalle: `python -m app.documents article --database RUTA_CORPUS.sqlite --id ID_REAL`. Para verificar salidas reales ya disponibles y autorizadas: `python -m app.documents evaluate --database RUTA_PREPARADA.sqlite --input SALIDAS.json`. El último archivo sigue `TopicOutputs` de OpenAPI/Pydantic y no se suministra con resultados ficticios. Código de salida: 0 operación correcta, 2 error.

No repetir `prepare` sobre un destino existente; elegir otro nombre de versión. Los originales y las bases de trabajo se mantienen fuera del repositorio. No reemplazar el archivo de configuración usado por una ejecución sin conservar su manifiesto correspondiente.

## API y dashboard

Configurar en la terminal del servidor, usando rutas relativas desde analytics-service:

```bash
export ANALYTICS_ENVIRONMENT=local
export ANALYTICS_CORPUS_DATABASE="../evidencias_locales/corpus-development-v1.sqlite"
export ANALYTICS_WORKSET_DATABASE="../evidencias_locales/prepared-development-v1.sqlite"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8006
```

OpenAPI en `/docs` expone:

| Método | Ruta bajo /api/v1 | Resultado |
| --- | --- | --- |
| GET | /corpus/articles | Página filtrable de artículos |
| GET | /corpus/articles/{identifier} | Detalle y relaciones |
| GET | /corpus/descriptors | Descriptores y frecuencia |
| GET | /corpus/summary | Diagnóstico para desarrollo |
| POST | /corpus/worksets/preview | Selección y exclusiones sin escritura persistente |
| GET | /corpus/workset | Manifiesto preparado verificado |
| POST | /topics/candidates/protocol | Protocolo de candidato pendiente |
| POST | /topics/outputs/evaluate | Controles y métricas estructurales de salidas proporcionadas |

Las rutas se mantienen deshabilitadas en staging/production. Las ubicaciones se configuran en el servidor; el navegador no elige archivos. Un detalle inexistente devuelve 404, entradas inválidas 422 y configuración ausente 503. El navegador solo debe consultar estos datos en el contexto local autorizado hasta resolver identidad y publicación.

Los contratos backend están implementados. La pantalla Angular todavía no está implementada: el checkout local no contiene centinela-front. Cuando el titular prepare ese repositorio se integrarán estas consultas en sus servicios/componentes existentes, conservando estados de carga, vacío, error, filtros y distinción entre diagnóstico descriptivo y resultados de modelos. No se crea una interfaz paralela.

## Git, revisiones y trazabilidad

Los estados de Azure y operaciones Git corresponden al titular. Revisar antes de agregar o confirmar cambios. Como el PR de la rama anterior puede estar en revisión, continuar añadiendo commits a esa misma rama también modifica su PR. Para conservar la revisión delimitada se puede guardar este incremento en una rama dependiente creada por el titular desde el estado actual. Esta incluirá inicialmente los commits anteriores: antes de abrir su PR hacia develop deberá integrarse el primer trabajo y revisarse la base con el procedimiento del equipo. Conservar los cambios locales al cambiar de rama. Los PR se dirigen a develop y mantienen las dos aprobaciones y CODEOWNERS.

Alcance para Azure: R08/R09 avanzan en preparación y selección para desarrollo; R10/R11 en contratos y controles estructurales, con entrenamiento pendiente; R19 en consultas locales; R20/R27 solo en respaldo backend, con Angular e integración pendientes; R24/R30 en pruebas y reproducción. No cerrar el requerimiento completo por disponer de contratos o métricas estructurales.

## Evidencia técnica del incremento

La verificación local final aprobó 357 pruebas, con cobertura conjunta de líneas y ramas de 99,29 %. Ruff y Black conformes; el inventario registra 41 módulos y cero infracciones de límites entre capas. Se mantiene la advertencia de deprecación TestClient/httpx de las dependencias fijadas. El [manifiesto actual](environment-documents-20261022.json) y el [inventario](inventory-documents-20261022.json) conservan las huellas del software; las instantáneas anteriores son históricas.

También se ejecutó ingesta, preparación, lectura verificada y consultas sobre el corpus real en almacenamiento temporal desechable, comprobando que las huellas de los originales no cambiaron. La configuración del ejemplo sirve para desarrollo y no representa selección científica definitiva. No se entrenó un modelo, no se midió coherencia temática y no se publicaron datos del corpus en el repositorio. Las pruebas unitarias usan exclusivamente registros sintéticos pequeños.

Para que el titular deje disponibles los repositorios faltantes, si aún no existen localmente:

```bash
cd /c/Users/Pato/Downloads/TESIS
git clone https://github.com/PlataformaIntegradaInvestigadores/centinela-front.git
git clone https://github.com/PlataformaIntegradaInvestigadores/predictive-service.git
```

Clonar no integra cambios ni requiere ejecutar los modelos heredados. La selección de ramas, instalación según los requisitos reales y análisis de esos repositorios se hará después de revisar sus instrucciones y estado. No se inspeccionaron ni modificaron sus fuentes en este incremento.
