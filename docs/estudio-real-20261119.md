# Estudio empírico inicial de temas, pronóstico anual y atribuciones

Se ejecutó el protocolo de `evidencias_locales/research-protocol-20261119.json`
sobre la instantánea real de ocho tablas recibida por Jairo. La autorización se
registra como declaración del autor tras su conversación con Lorena; no se
inventa una licencia ni una aprobación particular de cada decisión experimental.
Los resultados no completan por sí solos todos los objetivos del plan firmado.

## Protocolo anterior al entrenamiento

- Unidad: documentos de la instantánea preparada, no toda la producción científica.
- Ventana de reconstrucción: 2000–2021. Se excluye la cola 2022–2023 por cobertura
  incierta. La cobertura de los años restantes tampoco se presume poblacional.
- Textos: título y resumen disponibles, normalización NFKC y mínimo de cinco
  tokens. Sin imputación de resúmenes ni lematización/idiomas declarados falsamente.
- Duplicados exactos normalizados: conservar primero por fecha de publicación e
  ID. Todas las decisiones y los registros preparados permanecen en una base local.
- Tópicos: vocabulario, IDF y NMF ajustados solamente con documentos hasta 2015.
  Tres candidatos k=6,8,10; semilla 42; máximo 5.000 términos; min_df 3 y max_df 0,90.
  Lista prespecificada de palabras funcionales inglesas/españolas y términos de
  edición. Usar esa lista no significa haber detectado el idioma de cada documento.
- Selección de k por NPMI de entrenamiento, con diversidad y menor complejidad
  como desempate. El NPMI usa coocurrencia documental de los diez términos por tema.
- Vocabulario y temas congelados al inferir documentos posteriores. No se ajustan
  con el texto reservado para prueba ni se usan keywords como verdad de terreno.
- Predictor: Ridge conjunto para las series de temas, con rezagos 1–3 y promedio
  de los tres años anteriores, todos en escala log1p. Objetivo log1p(conteo).
- Alpha∈{0,1;1;10;100}, seleccionado únicamente por MAE de validación 2016–2018.
  Se compara una referencia equivalente de último valor. No se oculta si gana.
- Prueba: 2019–2021, origen móvil de un año. Cada ajuste usa solo años previos;
  observaciones de prueba anteriores pueden entrar en un corte posterior, como
  corresponde a una evaluación de actualización anual. Los parámetros no se
  vuelven a seleccionar durante prueba.
- La proyección posterior al corte es para 2022. No es una predicción actual para
  2026/2027. No se usan las observaciones parciales 2022 para evaluar esa proyección.
- Es reconstrucción por publicación; no existe fecha de indexación histórica.

## Resultados reales obtenidos

De 39.951 artículos de origen, 33.761 quedaron preparados; 6.967 documentos anteriores
o iguales a 2015 se utilizaron para ajustar los temas. Se seleccionaron ocho temas.
NPMI medio: 0,32293 en entrenamiento y 0,20271 en prueba; diversidad de términos: 0,975.
Estas cifras no reemplazan la revisión humana de interpretabilidad de los temas.
Hay temas amplios y términos cuya representación requiere revisión; no se han
asignado nombres de áreas de conocimiento como si fueran etiquetas validadas.

Se detectaron dos grupos de DOI con años distintos en la fuente (1995/2020 y
2021/2022). Ninguno comparte DOI entre las particiones preparadas del estudio,
pero la semántica de esas fechas requiere revisión con el propietario de los
datos. Se conservaron sus fechas originales y no se corrigieron a partir del DOI.

| Conjunto | Modelo | MAE | RMSE | Pares tema/año |
|---|---|---:|---:|---:|
| Validación | Ridge alpha 0,1 | 56,9695 | 120,5886 | 24 |
| Validación | Último valor | 123,8333 | 235,7092 | 24 |
| Prueba | Ridge alpha 0,1 | 138,7625 | 301,4198 | 24 |
| Prueba | Último valor | 72,5417 | 130,1117 | 24 |

Ridge gana en validación pero pierde en prueba. El resultado no demuestra una
mejora generalizable sobre la referencia. No se cambiaron parámetros para
aprovechar el resultado de prueba ni se presenta una selección como definitiva
para producción. Se conserva la referencia y la advertencia en el dashboard.

## Atribuciones y evaluación de explicaciones

Para el modelo lineal z=b+Σwᵢxᵢ, se fija una referencia μ con los datos de
entrenamiento inicial. La base es b+Σwᵢμᵢ y cada contribución es wᵢ(xᵢ−μᵢ).
La suma reconstruye exactamente z. La salida en documentos es max(0,exp(z)−1).
Las contribuciones se expresan en escala log1p, no se suman como artículos.

Es una descomposición algebraica `linear_exact`, no SHAP calculado ni causalidad.
El residuo máximo de aditividad fue 1,77636e-15. Esa comprobación mide fidelidad
algebraica al modelo, no comprensión humana ni fidelidad causal.
La magnitud global es la media absoluta en 24 predicciones de prueba. La deriva
L1 media entre refits con un año real adicional fue 0,14871, sobre los mismos
inputs y fondo fijo. No se generaron registros ni ruido simulados; tampoco se
declara un umbral universal de estabilidad o intervalos de confianza inexistentes.

## Artefactos e integridad

Ejecución vigente: `evidencias_locales/research-study-20261119-v2/`.
`protocol.json`, `prepared.sqlite`, `models.sqlite`, `study.sqlite`, `report.json`,
`run-manifest.json`, `verification.json`, `public-results.json` y `executed-source.zip`.
Los identificadores enlazan corpus, decisiones, fuentes del software, modelos,
series, cortes y predicciones. Los SQL/JSON con textos y parámetros permanecen
fuera de Git. El ZIP del código ejecutado no contiene corpus ni credenciales.

Una primera ejecución quedó conservada en `research-study-20261119`. La segunda
reproduce el mismo protocolo después de ubicar el orquestador en la raíz de
composición, respetando la arquitectura. Se comprobó igualdad de métricas y de
selección entre ambas. No son experimentos independientes ni nuevos resultados
usados para escoger al ganador. Cada ejecución tiene su propio código y hashes.

Se verificaron hashes de los ocho CSV, límite de ajuste temático, integridad de
artefactos, ausencia de DOI compartidos entre particiones preparadas y respuesta
de las APIs reales. Los tests pequeños de contrato se separan de esta ejecución.
La API de estudio expone agregados y omite textos, IDs de ajuste y aprobación.
La lectura del estudio y del registro sigue restringida al entorno local hasta
la integración institucional de identidad. GET nunca entrena ni crea una base.

## Reproducción y consulta

En Git Bash, desde analytics-service y con Python 3.11 activado:

```bash
source .venv/Scripts/activate
python -m pip install -r requirements-dev.txt
python -m app.study \
  --corpus ../evidencias_locales/corpus-real-20261118/service-corpus.sqlite \
  --protocol ../evidencias_locales/research-protocol-20261119.json \
  --output ../evidencias_locales/research-study-reproduccion
```

La salida debe ser nueva: se rechaza sobrescribir una ejecución. Los metadatos
están versionados y se exige el snapshot de investigación, no el corpus anterior
limitado al desarrollo. No hay descargas automáticas de fuentes o modelos.

Para levantar las consultas del incremento ya ejecutado:

```bash
export ANALYTICS_CORPUS_DATABASE="$(cd .. && pwd)/evidencias_locales/corpus-real-20261118/service-corpus.sqlite"
export ANALYTICS_STUDY_DATABASE="$(cd .. && pwd)/evidencias_locales/research-study-20261119-v2/study.sqlite"
export ANALYTICS_MODEL_DATABASE="$(cd .. && pwd)/evidencias_locales/research-study-20261119-v2/models.sqlite"
export ANALYTICS_WORKSET_DIRECTORY="$(cd .. && pwd)/evidencias_locales/research-worksets-20261119"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8046
```

Desde centinela-front, usando el Node 18 fijado por el repositorio:

```bash
export PATH="/c/Users/Pato/Downloads/TESIS/evidencias_locales/tooling/node-v18.20.2-win-x64:$PATH"
node node_modules/@angular/cli/bin/ng.js build --configuration local \
  --main tools/analytics-browser/main.ts --ts-config tools/analytics-browser/tsconfig.json \
  --index tools/analytics-browser/index.html --output-path ../evidencias_locales/research-browser-dist
node ../evidencias_locales/tooling/serve-research.mjs
```

Abrir http://127.0.0.1:4246/research-analytics/study. El visor aislado importa los
componentes Angular reales; no cambia los guards de la aplicación institucional.
La ruta productiva `/research-analytics/study` conserva la protección existente.
Para institución siguen pendientes identidad/gateway y despliegue verificados.

## Trazabilidad con el backlog existente

| Trabajo solicitado | Implementación/evidencia | Requisitos relacionados; no cierre automático |
|---|---|---|
| 1. Interfaz con corpus real | Contratos y vistas Angular, consultas sobre 39.951 artículos | R19/86, R20/90, R27/118 |
| 2. Preparación reproducible | decisiones y textos preparados, manifiesto, exclusiones y corte | R07/38, R08/42, R09/46 |
| 3. Entrenamiento temático real | tres NMF, selección, registro, inferencia y NPMI | R10/50, R11/54 |
| 4. Evolución anual | conteos, denominadores, proporciones y gráfica por tema | R12/58, R20/90 |
| 5. Pronóstico anual evaluado | Ridge/último valor, cortes y errores reservados | R13/62, R14/66, R15/70, R23/102 |
| 6. Explicaciones | atribuciones locales/globales, aditividad y deriva entre refits | R16/74, R17/78, R18/82 |

Los IDs provienen del backlog local conocido; no se cambiaron estados de Azure,
Prism ni aprobaciones. No se modificó el plan firmado. Siguen pendientes los PDF
del corpus, Lakehouse final, interpretación humana de temas, evaluación con
participantes y cierre académico. La existencia de resultados preliminares no
permite marcar todas esas obligaciones como cumplidas.

Documentación técnica consultada: NMF, Ridge y TfidfVectorizer de scikit-learn 1.9.1
en https://scikit-learn.org/stable/modules/classes.html . Se usan dependencias
ya presentes en el proyecto y no se incorporan fuentes externas al corpus.
