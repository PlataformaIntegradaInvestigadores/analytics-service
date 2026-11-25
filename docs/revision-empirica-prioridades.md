# Revisión empírica de predicción, temas y calidad

Este incremento amplía el estudio del 19 de noviembre de 2026. Usa la misma
instantánea autorizada por declaración del tesista y los mismos CSV originales.
El estudio anterior y los originales permanecen sin cambios. No descarga fuentes
externas ni utiliza el corpus de desarrollo de Danny como si fuese el corpus final.

## Qué ejecuta

1. Descompone los errores del Ridge anterior por tema, año y observación. Informa
   el signo del error y su concentración; no atribuye causalmente esos errores a
   acontecimientos, indexación o calidad de las fechas.
2. Compara 15 candidatos sobre los mismos pares tema/año: último valor, media y
   deriva de tres observaciones, Ridge agrupado y por tema, con y sin escalado,
   en escala original o logarítmica. Ajusta el escalador con cada entrenamiento.
   Conserva coeficientes, parámetros, cortes y hashes de las filas de ajuste.
3. Compara cinco diseños temáticos: los NMF anteriores de 6/8/10 temas, NMF de
   ocho temas con limpieza de marcas HTML y LDA de ocho temas con esa limpieza.
   Aprende vocabulario, IDF y componentes solo con documentos hasta 2015.
   Calcula NPMI, diversidad, cobertura, tamaños y dominancia de las asignaciones.
   Dos ajustes NMF adicionales con inicialización aleatoria permiten medir
   estabilidad mediante alineación húngara, coseno y Jaccard de términos.
4. Genera un catálogo privado con términos y hasta tres documentos reales de
   entrenamiento por tema/candidato. Las etiquetas y la revisión semántica
   permanecen vacías y pendientes; no se presentan como opiniones de expertos.
5. Reconcilia las cuatro relaciones exportadas, DOI, textos normalizados,
   títulos, fechas y conteos. Prepara casos con el registro original de CSV para
   revisión del propietario. Conserva `corpus=True/False` como dato de origen,
   sin utilizarlo como filtro cuyo significado no se conoce.
6. Calcula el efecto sobre los conteos de excluir los DOI con años contradictorios.
   Es una sensibilidad con registros reales: no modifica el corpus, no asigna un
   año supuesto y no vuelve a entrenar silenciosamente el estudio anterior.

La comparación NMF/LDA contrasta diseños completos: TF-IDF con vocabulario máximo
5000 frente a conteos con máximo 3000. Sus diferencias no permiten atribuir una
mejora exclusivamente al algoritmo. La dominancia de pesos no es una probabilidad
calibrada. La estabilidad de temas tampoco equivale a estabilidad de explicaciones
XAI; las explicaciones del estudio anterior siguen vinculadas a su propio modelo.
BERTopic continúa sujeto a viabilidad; LDA no se declara sustitución aprobada.

## Protocolo temporal y límites

- Selección predictiva: MAE de 2016–2018; desempate por identificador estable.
- Comprobación anidada de desarrollo: para predecir 2017 se selecciona con 2016;
  para 2018, con 2016–2017. Cada ajuste usa exclusivamente años anteriores.
- Diagnóstico 2019–2021: esos resultados ya se habían visto en el estudio anterior.
  Las nuevas comparaciones son exploratorias y no una prueba final intacta.
- Temas: ajuste hasta 2015, comparación 2016–2018; no se consultan textos del
  periodo 2019–2021 en esta nueva comparación temática.
- La proyección siguiente al último corte no tiene observación: no se puntúa ni
  se presenta como predicción acertada. No representa automáticamente el presente.
- Los conteos describen una instantánea retrospectiva por año de publicación;
  no se conocen las fechas históricas de incorporación ni la cobertura completa.

Un candidato mejor en validación no reemplaza automáticamente al modelo del
dashboard ni a sus explicaciones. La confirmación final, las decisiones semánticas
del propietario y las pruebas con personas de OE6 siguen requiriendo su evidencia.
Los PDF de texto completo y la integración institucional con Lakehouse también
continúan pendientes. Este incremento no acredita su terminación.

## Correspondencia comprobada con Azure CMMI

El ejecutor exige una lectura autenticada del proyecto real, comprueba códigos,
IDs, tipos y relaciones padre/hijo, y guarda revisiones y descripciones remotas.
El plan firmado se identifica por SHA256. No genera IDs ni crea elementos nuevos.

| Requerimiento real | Aporte verificable | Tareas relacionadas | Pendiente que impide cierre global |
|---|---|---|---|
| R08 / 42 | Reconciliación y casos de calidad | T08.1–T08.3 / 43–45 | Semántica de origen y decisiones sobre anomalías |
| R09 / 46 | Protocolo, cortes, hashes y controles de fuga | T09.2–T09.3 / 48–49 | Nueva confirmación final; 2019–2021 ya observado |
| R10 / 50 | Comparación real de cinco diseños, estabilidad | T10.2–T10.3 / 52–53 | BERTopic sujeto a viabilidad y revisión de elección |
| R11 / 54 | Catálogo versionado y documentos representativos | T11.1–T11.3 / 55–57 | Revisión humana; clasificación solo con etiquetas válidas |
| R12 / 58 | Mismas series e identidad temática congelada | T12.1–T12.3 / 59–61 | Precisión/cobertura temporal y decisiones de origen |
| R13 / 62 | Mismo objetivo, unidad, horizonte y pares evaluados | T13.1–T13.3 / 63–65 | Generalización fuera de la instantánea |
| R14 / 66 | 15 candidatos y selección temporal registrada | T14.1–T14.3 / 67–69 | Confirmación final independiente y promoción revisada |
| R22 / 98 | Auditoría ampliada y sensibilidad no destructiva | T22.1–T22.3 / 99–101 | Resolución de casos y cierre del corpus final |
| R23 / 102 | Errores, MAE/RMSE, temas y trazabilidad por ejecución | T23.1–T23.3 / 103–105 | Confirmación final y evaluación humana correspondiente |

La tabla describe aportes a criterios, no declara todos esos elementos terminados.
Se mantiene la evaluación con personas acordada con la tutora; CR01 queda como
antecedente histórico sin prevalecer sobre esa decisión.

## Reproducción en Git Bash

Desde `C:/Users/Pato/Downloads/TESIS/analytics-service`, con el entorno Python 3.11:

```bash
source .venv/Scripts/activate
python -m app.review \
  --corpus ../evidencias_locales/corpus-real-20261118/service-corpus.sqlite \
  --study-directory ../evidencias_locales/research-study-20261119-v2 \
  --source-directory ../corpus/raw \
  --plan ../F_AA_234A_Jairo_Quispe-signed.pdf \
  --azure-snapshot ../evidencias_locales/azure-priorities-before-20261119.json \
  --backlog ../centinela-analitica/backlog.json \
  --protocol ../evidencias_locales/review-protocol-20261120.json \
  --output ../evidencias_locales/research-review-rerun
python ../evidencias_locales/tooling/verify-research-review.py \
  ../evidencias_locales/research-review-rerun
```

La salida debe ser nueva; el ejecutor rechaza sobrescribir una ejecución. Se
conservan el protocolo congelado, resultados, modelos privados, informe HTML,
manifiesto y una cápsula ZIP del código exacto de la ejecución. Para repetir ese
código se utiliza la cápsula con las versiones y fuentes indicadas, no una copia
futura que haya cambiado. El identificador cambia si cambian código o entradas.

El JSON `public-results.json` y `review.html` contienen resultados agregados.
`private-audit-cases.json`, `owner-decisions.csv`, `private-topic-catalog.json`,
`human-topic-review.csv`, modelos y bases quedan locales; no se publican en GitHub
ni se adjuntan automáticamente a Azure. Solo el adjunto agregado puede vincularse
a los requerimientos existentes, sin transiciones de estado.

## Consulta por API local

```bash
export ANALYTICS_REVIEW_DATABASE="C:/Users/Pato/Downloads/TESIS/evidencias_locales/research-review-20261120/review.sqlite"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8047
```

Abrir `http://127.0.0.1:8047/api/v1/study/review`. La API verifica el hash del
informe y omite su bloque de identidad interna. Sin configuración devuelve 503;
en staging/producción sigue bloqueada por la política de integración local.
El informe HTML se abre directamente en el navegador y permite revisar las tres
prioridades sin reiniciar el frontend ni sustituir resultados anteriores.
