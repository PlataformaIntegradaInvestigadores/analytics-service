# Extracción preparatoria de texto PDF

## Correspondencia con el plan

El plan firmado, página 3, apartado IV.b «Ingeniería de Características y
Preprocesamiento», contempla expresamente procesar texto plano extraído de PDF.
Este incremento prepara esa operación; no modifica el plan, adopta un corpus,
descarga fuentes externas, ejecuta entrenamiento ni evalúa modelos científicos.

## Uso

Instalar `python -m pip install -r requirements-pdf.txt`. No se incorpora OCR.
Un manifiesto JSON contiene identificadores explícitos y rutas relativas:

```json
[{"document_id":"reference:bertopic","file":"04_Grootendorst_2022_BERTopic.pdf"}]
```

Desde analytics-service:

```bash
python -m app.pdftext batch --root ../papers --manifest ../evidencias_locales/manifest.json --registry ../evidencias_locales/pdf-text.sqlite
python -m app.pdftext show --registry ../evidencias_locales/pdf-text.sqlite --id IDENTIFICADOR
```

Los identificadores se declaran en el manifiesto: no se deduce una asociación con
Centinela por el nombre del archivo. Las entradas quedan bajo `preparation_only`.
El registro debe estar fuera de la carpeta de entrada y fuera de Git; contiene
texto de los documentos. El informe de lote solo muestra estados y conteos.
`show` expone texto únicamente cuando se solicita explícitamente en terminal local.

La primera operación guarda resultados por archivo y página, versión de pypdf,
huella del extractor, configuración, huellas de fuente y texto. Una repetición
verifica las huellas y reutiliza el resultado; un cambio del archivo, versión de
parser o código del extractor produce otra identidad. Un registro alterado se
rechaza, sin sobreescribirlo. Los fallos no almacenados pueden reintentarse.

Estados: `extracted`, `partial_text`, `no_extractable_text`, `encrypted`, errores
de extracción y validación, y `timeout`. Un archivo sin texto extraíble no se
clasifica automáticamente como escaneado: puede estar vacío o requerir revisión.
Los documentos cifrados se omiten sin intentar descifrarlos. Se conservan saltos
de página y texto; no se inventan resúmenes, DOI, palabras clave ni fechas.

Límites por documento: 50 MiB de entrada, 500 páginas, 2 millones de caracteres,
10 MiB de contenido decodificado por página y 90 segundos por defecto (máximo300).
Cada extracción ocurre en un subproceso con copia temporal de los bytes; el
timeout termina el proceso y el lote continúa. No hay límite duro de RAM: un
flujo comprimido puede consumir memoria antes de comprobar su tamaño decodificado.
Este comando local para archivos conocidos no es una API para PDF no confiables.

El orden de lectura, fórmulas, tablas, columnas y texto OCR requieren inspección
antes de usar los resultados para NLP. «Texto extraído» no significa calidad
semántica verificada. Fuente del parser y sus límites:
https://pypdf.readthedocs.io/en/stable/user/extract-text.html

## Verificación con archivos reales

`tools/verify_pdf_preparation.py` usa los seis PDF existentes de bibliografía
con identificadores `reference:...`, comprueba reanudación y compara huellas antes
y después. Genera un informe agregado nuevo; conserva texto exclusivamente en el
registro externo. No se distribuyen los PDF ni se suben extracciones a Git.
Las pruebas del código incluyen guardas de rutas, tiempos de espera, documentos
sin texto, cifrado, límites y corrupción; no son resultados científicos de tesis.

La conexión futura con las capas de datos, las rutas API y la asociación validada
al corpus definitivo quedan pendientes. No se modifican frontend, identidad,
gateway ni pipelines en este incremento.
