# Mapa temático sobre el estudio real

Referencia de trabajo: F_AA_234A_Jairo_Quispe-signed.pdf actualizado, SHA256
d871c96927b99f3c70ef55403c4ab25921425376dc16f4d81ee75f605c951ba6.
Su aprobación formal sigue pendiente. Se usan títulos y resúmenes; la implementación
no requiere artículos completos en PDF.

## Contrato y trazabilidad

- R12/T12.4: asignación exclusiva congelada, empate al menor índice, pesos cero
  sin asignación; denominador de documentos preparados elegibles por filtro.
- R31/T31.1–T31.5: API, mapa circular reproducible, tabla equivalente, filtros,
  consulta paginada de títulos y verificación de consistencia.
- R19/R20/R27: identidad existente, estados, versiones y correspondencia entre
  visualización y API. No se añade un mecanismo de identidad alternativo.
- R09/T09.4: reutiliza publicaciones atómicas ya existentes y sus verificaciones
  de integridad. No declara Lakehouse distribuido o despliegue institucional.
- R13–R15: reutiliza las series, referencia de último valor y pronóstico del estudio
  real. No vuelve a seleccionar modelos mirando 2019–2021 ya observados.
- R25/T25.4, T32.1 y T33.1: `evaluacion-protocolo.json` propone tareas e instrumentos
  para revisión con la tutora. No acredita aprobación ni ejecución de sesiones.

GET `/api/v1/topic-map` acepta `release_id`, `start_year`, `end_year` y `threshold`
entre 0 y 1. Devuelve release, modelo, nodos, conteos, denominador, no asignados,
términos y enlaces de similitud coseno en componentes NMF TF-IDF normalizados.
Los filtros no reentrenan ni cambian los enlaces semánticos. Un año fuera de la
instantánea produce un conjunto vacío, no una conclusión de producción cero.

GET `/api/v1/topic-map/documents` exige release y tema, acepta los mismos años,
offset y un límite máximo de 50. Solo devuelve identificador de artículo, título
y año. No expone resúmenes, pesos por documento, archivos o rutas privadas.
Todas las lecturas pasan por `analytics_read_access` antes del procesamiento.

La selección se fija a una publicación y modelo; las consultas de documentos
conservan ese release incluso si se publica posteriormente otra versión.
La interfaz cancela peticiones obsoletas al cambiar filtros o selección.
El área del círculo es proporcional al conteo, con radio proporcional a su raíz.
La disposición circular no expresa distancia semántica ni causalidad.

## Verificación real reproducible

Desde analytics-service, con Python 3.11 y el entorno activado:

```bash
python -m pytest -q
python -m app.map_audit \
  --store ../evidencias_locales/research-layers-20261120 \
  --output ../evidencias_locales/map-audit-mi-reproduccion.json
```

La salida debe ser nueva. La auditoría usa los artefactos reales existentes:
33.761 documentos, 8 temas, 0 no asignados y 6 enlaces con umbral 0,2. Reconciliación
por tema: 1410, 1027, 1906, 4949, 17089, 815, 1625 y 4940. Comprueba filtros,
identidad del modelo, documentos paginados, series y ausencia de escritura al
catálogo. Es verificación de integración de un estudio existente, no una nueva
evaluación científica independiente ni evaluación con usuarios.

## Ejecución local

```bash
source .venv/Scripts/activate
export ANALYTICS_LAKE_DIRECTORY="$(cd ../evidencias_locales/research-layers-20261120 && pwd -W)"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8036
```

El frontend debe dirigir `/api/analytics` al backend. La ruta nueva es
`/research-analytics/map`; aparece enlazada en la página del corpus. El entorno
aislado de integración documentado en `integracion-capas-20261120.md` conserva
identidad y gateway; requiere recompilar sus imágenes para incluir esta vista.
Un build estático anterior no incorpora cambios de código automáticamente.

## Preparación del análisis humano

Tras revisión del instrumento y sesiones reales, mantener el CSV anonimizado
fuera del repositorio. Cabecera exacta:
`participant_id,task_id,success,seconds,comprehension,actionability`.
Faltantes vacíos; éxito 0/1, segundos no negativos y valoraciones propuestas 1..5.
Las anclas de las valoraciones y el criterio de éxito deben acordarse antes de
recoger respuestas. No se presenta esta rúbrica como cuestionario validado.

```bash
python -m app.evaluation ../respuestas_privadas.csv ../analisis_privado.json
```

La herramienta rechaza duplicados participante/tarea y valores inválidos; calcula
n, faltantes, media, mediana y rango por tarea/medida, sin publicar identidades.
No genera respuestas. El análisis cualitativo requiere codificación humana y su
registro; no queda completado por este cálculo descriptivo.

## Dependencias pendientes

BERTopic no está instalado y no se encontró caché local de embeddings en la
comprobación del incremento. T10.5–T10.7 no quedan cumplidas. Antes del benchmark
se necesitan dependencias compatibles, un codificador local identificado y su
licencia/revisión, presupuesto de recursos y protocolo congelado. No se descargó
ni envió el corpus a servicios externos; no se inventó una comparación BERTopic.
La decisión de adopción queda abierta; el mapa NMF es operativo.

No quedan ejecutadas las sesiones R32, el análisis de respuestas reales R33,
la aprobación de prototipos o el cierre científico de R23. Los periodos ya
examinados conservan su carácter exploratorio. Ningún estado de Azure se cambia
por la existencia de estos archivos.
