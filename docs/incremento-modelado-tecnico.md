# Incremento técnico: modelado, temporalidad y reproducción

## Alcance y evidencia

Implementación local sobre la rama existente pendiente de revisión. No acredita uso
del corpus en evaluación final, entrenamiento empírico, comparación científica,
explicaciones calculadas, integración institucional ni despliegue.

### Referencia TF-IDF + NMF (R10 / T10.2)

`app.application.modeling.fit_nmf` ajusta vocabulario e IDF únicamente sobre IDs de
ajuste explícitos, ordenados de forma estable. Los documentos de inferencia no
intervienen en ese ajuste. Semilla, iteraciones, parámetros, dependencias, fuentes
de software, workset y huella de los textos quedan asociados al modelo.
Se limita el vocabulario a 20.000 términos, las iteraciones a 1.000 y BLAS a un hilo.
Estos límites no sustituyen una prueba de capacidad con el corpus autorizado.

El error de reconstrucción de entrenamiento es un diagnóstico técnico: no se usa
como prueba de coherencia semántica, exactitud predictiva o calidad de tesis.
Las cargas sin términos conocidos quedan sin asignación, nunca en el tema cero.
Los identificadores de tema son mecánicos; el etiquetado y evaluación siguen pendientes.

`ModelStore` conserva JSON inerte con componentes, vocabulario e IDF. No usa pickle
ni joblib para serialización. Detecta cambios de contenido y la inferencia exige la
misma versión de scikit-learn. El registro complementa `ExperimentStore`, que sigue
conservando catálogos y pronósticos; no modifica retroactivamente sus contratos.
La comparación entre modelos y el registro de una selección final no están hechos.

Instalación y comandos desde analytics-service, usando Python 3.11:

```bash
python -m pip install -r requirements-modeling.txt
python -m app.modeling capabilities
python -m app.modeling fit --input /ruta/controlada/request.json --database /ruta/externa/models.sqlite
python -m app.modeling show --id SHA256 --database /ruta/externa/models.sqlite
python -m app.modeling infer --id SHA256 --input /ruta/controlada/documents.json --database /ruta/externa/models.sqlite
python -m app.reproduce --output /ruta/externa/nueva-evidencia
```

`fit` recibe `documents` (document_id, text, publication_date y available_on
opcionales), `fit_ids`, `workset_id` SHA256, `topics`, `seed`, `cutoff` opcional.
`infer` recibe una lista de documentos. La evidencia de autorización/procedencia
del workset debe comprobarse fuera del runner: un identificador suministrado no
demuestra por sí mismo que el corpus sea utilizable en investigación final.
No se ejecutó `fit` sobre la exportación de Danny.

### BERTopic (R10 / T10.1)

Existe un adaptador con embeddings numéricos explícitos en orden de IDs, control de
finitud, corte temporal opcional, etiquetas y outliers. Comprueba dependencias
opcionales y no genera embeddings ni descarga modelos. No se instalaron los
componentes pesados ni se afirma haber entrenado BERTopic. Falta medir embeddings,
memoria, tiempo, temas obtenidos y persistencia nativa antes de elegirlo.

Contrato consultado: https://maartengr.github.io/BERTopic/getting_started/embeddings/embeddings.html

### Temporalidad (R09 / R12)

`app.domain.temporal` admite agregación anual, trimestral, mensual y diaria según
precisión declarada. Rechaza una resolución más fina y precisión desconocida;
conserva cobertura desconocida frente a la declaración explícita de completitud.
Los periodos declarados completos pueden tener cero documentos; no se generan
ceros para vacíos cuya cobertura se desconoce. No se interpreta enero/día 1 como
prueba de precisión. La disponibilidad histórica se exige cuando se proporciona
un corte para ajustar: no se rellena desde la fecha de publicación.

Esta utilidad **no altera** los endpoints mensuales ya publicados ni autoriza a
usarlos con fechas inciertas. La adaptación de pronóstico a otra frecuencia,
partición final y evaluación temporal requieren decidir la frecuencia válida.

### Tablas versionadas (R05 / T05.2)

`VersionedTable` es un prototipo local de viabilidad: objetos Parquet inmutables,
catálogo SQLite, escritura de catálogo transaccional, comprobación optimista del
padre, versiones históricas, proyección y evolución aditiva de columnas. Se
verifican SHA256 de metadatos y archivo antes de leer. Un fallo puede dejar un
objeto huérfano no publicado; no se hace recolección automática de archivos.

No es un formato transaccional distribuido, ni Delta/Iceberg, ni un Lakehouse
institucional. El ensayo compara escritura/proyección y bytes de disco de 5.000
filas controladas entre SQLite y el prototipo. No mide RSS, concurrencia, cargas
reales ni disponibilidad de infraestructura; no decide el almacenamiento final.
Fuente de instalación: https://arrow.apache.org/docs/python/install.html

### Predictor / explicador (R16)

`explanation_contract` valida orden exacto de características, finitud, salida,
objetivo y familia/método. Su estado es `compatible_not_explained`. No calcula SHAP,
fidelidad o estabilidad ni selecciona el explicador definitivo. No confundir
pesos NMF con contribuciones a un pronóstico.

### Reproducción (R30)

`app.reproduce` ejecuta ajuste/inferencia NMF, registro y recuperación, agregación
anual, historial/evolución de tablas, benchmark y contrato XAI con datos
controlados. Produce un informe agregado en un directorio nuevo y elimina los
artefactos intermedios de ensayo. Rechaza sobrescribir evidencias. El código y
dependencias quedan en Git; el informe local no contiene textos del corpus real.

### Integración y accesibilidad (R24 / R25 / R26)

El frontend incluye un harness independiente en `tools/analytics-browser`. Importa
los componentes y servicios HTTP reales en una aplicación de pruebas. No cambia
las rutas de producción ni autentica usuarios ni omite el guard de la aplicación
principal: ese guard queda fuera del alcance explícito del ensayo aislado.
El proxy de prueba solo expone el backend local por la ruta relativa existente.
Comprueba exploración, detalle, vacío, fallo/recuperación, preparación, teclado y
análisis axe a 360/768/1440 píxeles. Sus respuestas analíticas provienen del backend
con un corpus controlado, no de respuestas HTTP prefabricadas.
La auditoría automática no equivale a conformidad WCAG integral. La revisión
institucional de identidad/gateway y la inspección visual final siguen pendientes.
