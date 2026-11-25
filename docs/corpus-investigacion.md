# Importación del corpus de investigación de ocho tablas

Este adaptador incorpora la entrega real recibida por Jairo tras su conversación
con la tutora. La autorización se registra con una referencia explícita a la
comunicación recibida; no genera una licencia ni acredita una que no se haya
entregado. El adaptador anterior `app.corpus` mantiene su alcance de desarrollo.

Desde Git Bash, con el entorno Python 3.11 activado y situado en analytics-service:

```bash
python -m app.research ingest \
  --directory ../corpus/raw \
  --database ../evidencias_locales/corpus-real-20261118/service-corpus.sqlite \
  --approval-reference "Confirmación del autor tras acuerdo con Lorena Recalde, 2026-11-18"
```

La carpeta de destino debe existir y quedar fuera de las fuentes y del repositorio.
Si la base ya existe, se rechaza la operación: consultar esa base o elegir un nombre
nuevo para una nueva importación. No borrar instantáneas previas para repetirla.

Se esperan articles, authors, affiliations, author_keywords, articles_authors,
articles_affiliations, articles_author_keywords y authors_affiliations, en CSV.
Se validan los encabezados concretos y los identificadores textuales, conservando
ceros iniciales. Se admite el índice de exportación sin nombre en las relaciones
y hasta dos envolturas CSV alrededor de una fila; no se adivinan separadores.

Todas las filas interpretadas quedan en tablas `raw_*`, con número de registro.
La normalización no modifica archivos originales. Los identificadores duplicados
de entidades, filas mal formadas o fechas inválidas impiden publicar una base
parcial. Se comparan SHA256 antes y después y se publica atómicamente una base nueva.

Las proyecciones para consultas conservan cada artículo por su ID de origen:
un DOI compartido no fusiona publicaciones. DOI inválidos permanecen en el registro
original y quedan nulos en el documento canónico. Se conservan corpus=True/False y
los conteos originales sin interpretar su significado ni usarlos como filtro.
Las relaciones huérfanas y repetidas permanecen en `raw_*`; solo las relaciones
válidas distintas alimentan las consultas. El manifiesto registra sus conteos.
Las palabras clave son descriptores de autor, no temas aprendidos ni etiquetas
de verdad. Se registra la discrepancia entre nombre relacional y catálogo.

El esquema derivado es compatible con las consultas existentes de artículos,
detalle, autor, descriptor, calidad y preparación de conjuntos de trabajo. El resumen
distingue `ready_for_research_preparation` del origen de desarrollo y los conjuntos
creados llevan `research_preparation_not_final_temporal_partition`. El entrenamiento
continúa pendiente de un protocolo de modelado; no se convierte el NMF técnico
anterior en un resultado científico. La hora de ingesta no representa disponibilidad
histórica. Los meses/días no se certifican como precisos; no se entrenan pronósticos
mensuales ni se convierte cobertura desconocida en cero.

Puede configurarse `ANALYTICS_CORPUS_DATABASE` con la ruta absoluta de esta base
para las consultas de la API local. La migración visual completa del frontend a
los textos, filtros de años y estados del corpus de investigación sigue pendiente;
no se modificó automáticamente la demostración que usaba el corpus anterior.

No se cargan datos en Neo4j/MongoDB ni se afirma haber desplegado el Lakehouse
final. No se ajustan modelos, calculan métricas de predicción ni generan XAI al
importar. No hay extracción de PDF porque esta entrega no los incluye.
Los CSV, bases derivadas y textos quedan fuera de Git. En el repositorio solo
se incluyen código, pruebas de contrato y documentación sin datos del corpus.
