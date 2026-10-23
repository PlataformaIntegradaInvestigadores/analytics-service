# Inspección estática de predictive-service

El incremento añade `python -X utf8 -m app.legacy --repository ../predictive-service`. Lee fuentes, encabezado CSV y huellas de archivos fijos; no importa los módulos del repositorio, no ejecuta su preprocesamiento, no deserializa los pickle y no ejecuta inferencia ni entrenamiento.

La inspección del checkout local identifica:

- Modelo `publication_model.pkl`, codificador `affiliation_encoder.pkl` y datos históricos `publication_data.csv` presentes.
- Entradas declaradas en `_run_prediction`: year, affiliation_encoded, publication_count y distinct_authors.
- CSV histórico con affiliation_name, year, publication_count y distinct_authors.
- Proyección recursiva de publicaciones por afiliación, con actualización de publicaciones/autores en la lógica de servicio.
- `get_model_details` contiene constantes MAE 2.20 y RMSE 4.67 y una descripción de entrenamiento histórico. Son afirmaciones de la fuente, no métricas ejecutadas/verificadas por esta tesis. No se transcriben como resultados propios ni se muestran en el nuevo explorador documental.
- `preprocess_data.py` agrega artículos y autores distintos por afiliación/año y tiene escritura de CSV al ejecutarse. La auditoría lo conserva como texto y huella, sin ejecutarlo.

La firma de entrada y la tarea por afiliación no equivalen a temas descubiertos, series por tema ni explicaciones locales/globales. La reutilización inmediata es de patrones de contrato y representación de observaciones/proyecciones. La reutilización del modelo exige comprobar objetivo, fechas de las variables, evidencia de entrenamiento, versión del artefacto y evaluación temporal apropiada.

El informe automático señala `unverified_source_constants_not_executed_evaluation` y conserva identidades SHA-256 de lo inspeccionado. Las fuentes externas son mutables: repetir la inspección cuando cambie predictive-service. No se modificaron fuentes de predictive-service ni se actualizaron sus dependencias en este incremento.

Ejecutar y conservar un informe local, fuera de Git, si se necesita registrar evidencia:

```bash
python -X utf8 -m app.legacy --repository ../predictive-service > ../evidencias_locales/predictive-source-audit.json
```

Para Azure: aporta a diagnóstico/reutilización de R01/R05 y definición de entradas de R16. No acredita entrenamiento, rendimiento predictivo o XAI. Las operaciones Git y estados remotos siguen a cargo del titular.
