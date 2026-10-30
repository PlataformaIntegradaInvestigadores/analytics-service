# Revisión estructurada del corpus bibliográfico provisto

Fecha: 2026-10-21. Trazabilidad: R02, T02.1/19, T02.2/20 y T02.3/21.
Estado: protocolo aplicado a los seis documentos disponibles y extracción focalizada en los apartados indicados. Es una revisión de literatura provista, no una búsqueda exhaustiva en bases de datos ni una revisión independiente por dos evaluadores.

## Protocolo y registro de selección

Preguntas de revisión:

- P1: ¿Qué propiedades de almacenamiento, consistencia y procedencia requiere el flujo analítico?
- P2: ¿Cómo distinguir descubrimiento temático, evolución descriptiva y pronóstico, evitando fuga temporal?
- P3: ¿Cómo seleccionar y evaluar explicadores compatibles con las entradas y la tarea del predictor?
- P4: ¿Qué funciones bibliométricas y restricciones de cobertura deben reflejar las interfaces analíticas?

Universo: los seis PDF de `TESIS/papers` que corresponden a la bibliografía del plan vigente. No se afirma haber realizado nuevas búsquedas en Scopus, WoS o Google Scholar.

Inclusión: documento disponible en texto completo; identidad bibliográfica contrastable con el propio PDF; relación directa con P1–P4; aportación metodológica que pueda identificarse y separarse de resultados propios de Centinela.

Exclusión: copia binaria duplicada, referencia con identidad no comprobable, texto completo no disponible o ausencia de relación con P1–P4. Para este conjunto: seis archivos identificados, seis incluidos y cero excluidos. Las retiradas de versiones anteriores del plan pertenecen al registro bibliográfico previo, no se vuelven a contabilizar como búsquedas o exclusiones de esta revisión.

Extracción: referencia, DOI/URL, tipo de trabajo, problema, método, datos/tarea, aplicación prevista, limitaciones y localizadores de evidencia. Los localizadores son páginas físicas del PDF. La extracción es dirigida; no acredita lectura exhaustiva de todas las referencias citadas dentro de cada estudio.

Síntesis: agrupación por arquitectura de datos, tópicos/pronóstico, XAI e interfaces. No se calcula un puntaje de calidad inventado ni se atribuye superioridad de un modelo antes de evaluarlo con el corpus propio.

## Matriz de extracción

| ID y referencia | Problema y método | Aplicación a Centinela | Límites de transferencia | Evidencia localizada |
|---|---|---|---|---|
| B01. Danilevsky et al. (2020), *A Survey of the State of Explainable AI for Natural Language Processing*. DOI: 10.18653/v1/2020.aacl-main.46 | Revisión y categorización de explicaciones en NLP, alcance local/global y enfoques de evaluación | Distinguir tipos de explicación y justificar una evaluación técnica explícita de fidelidad | Una explicación plausible no garantiza fidelidad ni efectos sobre confianza; no aporta un predictor temático para Centinela | pp. 1–2, metodología y categorización; pp. 6–8, evaluación y brechas |
| B02. Madsen, Reddy y Chandar (2022), *Post-hoc Interpretability for Neural NLP: A Survey*. DOI: 10.1145/3546577 | Taxonomía de métodos post-hoc según comunicación, acceso al modelo e información requerida; discusión de validación | Elegir el explicador después de concretar tarea, entradas y modelo; separar evaluación funcional y humana | Predomina NLP neuronal; la transferencia a regresión temporal requiere comprobar compatibilidad. La evaluación funcional no demuestra usabilidad | pp. 1–4, alcance y taxonomía; pp. 7–8, medidas de interpretabilidad |
| B03. Armbrust et al. (2021), *Lakehouse: A New Generation of Open Platforms that Unify Data Warehousing and Advanced Analytics*. [CIDR](http://cidrdb.org/cidr2021/papers/cidr2021_paper17.pdf) | Propuesta de arquitectura que combina archivos abiertos con una capa de metadatos, transacciones, versiones y acceso analítico/ML | Separar originales, curados y resultados; reconstruir conjuntos por versión y seleccionar una capa de tablas real | No es una certificación de SQLite ni prueba de rendimiento en el equipo local; formato, motor e infraestructura deben concretarse | pp. 1–4, planteamiento y diseño; fig. 2, capa de metadatos y transacciones |
| B04. Grootendorst (2022), *BERTopic: Neural topic modeling with a class-based TF-IDF procedure*. DOI: 10.48550/arXiv.2203.05794 | Representaciones de documentos, agrupación y c-TF-IDF para representar temas; extensión descriptiva temporal | Candidato de modelado temático y referencia para conservar identidad de temas y términos por versión | No constituye por sí mismo pronóstico futuro ni atribución XAI del predictor. La creación global de temas con documentos futuros exige adaptación al protocolo temporal | pp. 1–4, método y modelado dinámico; pp. 4–5, configuración experimental |
| B05. Ofer, Kaufman y Linial (2024), *What's next? Forecasting scientific research trends*. DOI: 10.1016/j.heliyon.2023.e23781 | Pronóstico de popularidad/cambio de temas mediante series y fuentes heterogéneas, referencias y validación temporal | Justificar variables históricas, referencia equivalente, separación temporal y métricas de regresión | Usa principalmente PubMed y tareas/etiquetas distintas; no se transfieren sus métricas, cobertura ni horizonte automáticamente a Centinela | pp. 1–3, objetivos y métodos; p. 6, comparación; pp. 10–11, limitaciones |
| B06. Moral-Muñoz et al. (2020), *Software tools for conducting bibliometric analysis in science: An up-to-date review*. DOI: 10.3145/epi.2020.ene.03 | Revisión comparativa de fuentes, herramientas y funciones de análisis bibliométrico y visualización | Seleccionar visualizaciones según pregunta, metadatos disponibles y cobertura; distinguir funciones que quedan fuera del alcance | Panorama de herramientas de 2020; no describe su disponibilidad actual ni valida un dashboard propio. Sesgos de fuentes y cobertura deben examinarse | pp. 1–3, alcance y bases; pp. 15–16, discusión y conclusiones |

Los seis documentos respaldan decisiones de diseño. Sus resultados no se presentan como resultados de la tesis.

## Identidad de los PDF revisados

Los archivos están fuera del repositorio de software, en la carpeta de fuentes del proyecto. Sus huellas permiten contrastar una copia autorizada sin incorporarla automáticamente al repositorio.

| ID | Archivo en `TESIS/papers` | SHA-256 |
|---|---|---|
| B01 | 01_Danilevsky_2020_XAI_NLP.pdf | 411756b9223b287d836f75d5f2e378b4c90539b57cac18bc0bcfb2bbeface3b5 |
| B02 | 02_Madsen_2022_Interpretabilidad_NLP.pdf | 791056feedf50e0f899ce2167f7a21636f8f1545f7193c7defded2888ec8a2bf |
| B03 | 03_Armbrust_2021_Lakehouse.pdf | df79a5de561b4c23354da08f3f9247bd33413b7339da1d8afee30ccfee4b5faa |
| B04 | 04_Grootendorst_2022_BERTopic.pdf | 3d7ea2fbe10a306bc687c4aa8d07780476ebc9e33a4919ca92ee2f02423c89c4 |
| B05 | 05_Ofer_Kaufman_Linial_2024_Pronostico_Tendencias.pdf | 94377a87a1ac7c2f091b28f1b65b5a5ca537c24735415d35ae5aa7dbcfe485c0 |
| B06 | 06_Moral_Munoz_2020_Herramientas_Bibliometricas.pdf | 345e73a5a445d8ca1a1360313ffe3af23de383702b2a19f274cd2d354da6120a |

## Síntesis de decisiones

1. Arquitectura: B03 fundamenta una capa analítica con versiones y transacciones; el diseño debe materializar un Lakehouse real. SQLite conserva artefactos locales mientras se concreta esa infraestructura.
2. Temas y pronóstico: B04 orienta el descubrimiento y B05 el análisis temporal. Se compararán métodos adecuados al corpus; las definiciones aprendidas deben ajustarse en entrenamiento y conservarse durante la evaluación.
3. Explicabilidad: B01–B02 justifican separar explicaciones locales/globales y comprobar fidelidad. Si el predictor utiliza rezagos y volúmenes, esas son sus variables explicables; no atribuir importancia predictiva a palabras que el modelo no consume.
4. Interfaz: B06 orienta funciones analíticas, pero su eficacia humana no queda demostrada por un gráfico correcto. Se preservan unidades, cobertura, estados de ausencia y versiones.
5. Evaluación: las métricas corresponden a la tarea. MAE/RMSE para regresión; métricas de clasificación solo si existe esa tarea y etiquetas válidas. Ni una prueba de software ni la bibliografía sustituyen la evaluación empírica.

## Pendientes académicos

- Revisión del tutor del alcance y suficiencia de los seis estudios para OE1.
- Incorporar ampliaciones justificadas si se requiere una búsqueda externa adicional, registrando estrategias y resultados reales.
- Resolver CR01 respecto de OE6. La decisión de no usar participantes se mantiene en la propuesta metodológica; no se declara aprobada por esta revisión.
- Incorporación a la tesis y ajuste de citas por el titular; este archivo no modifica Prism ni el plan.
