# Ingesta del corpus de desarrollo

Incremento del 22 de octubre de 2026. Relacionado con R03, R07, R08, R11, R12 y R30. Implementa adaptación del formato recibido y diagnóstico local. No representa entrenamiento, autorización de uso académico/publicación, despliegue Lakehouse ni cierre de esos requerimientos.

## Alcance

`python -m app.corpus` reconoce los tres CSV del paquete Centinela. Exige encabezados y anchura de filas del contrato, UTF-8, identificadores válidos, fechas completas y concordancia del año. Usa lectura por bloques de 1–1000 filas y valida los artículos con la curación existente. Mantiene restricciones únicas y claves foráneas entre artículos, autores y descriptores, incluso si los conflictos aparecen en bloques distintos. Un conflicto aborta la instantánea completa; no se omiten filas silenciosamente.

Los originales permanecen intactos. La base SQLite debe estar fuera del directorio del corpus y no existir previamente. Se construye en un archivo temporal, se confirma la transacción y se publica mediante un enlace de archivo en el mismo directorio que rehúsa sobrescribir un destino existente. Se requieren permisos y soporte de enlaces de archivo en el sistema de archivos de destino. Si falla la publicación se elimina el temporal. Las huellas originales se comprueban antes y después de procesar para detectar cambios durante la ingestión.

`inspect` usa almacenamiento temporal desechable. No deja una base persistente ni modifica los CSV. Su salida contiene agregados, huellas y advertencias, no títulos/resúmenes/identificadores de artículos. `ingest` conserva registros originales y documentos normalizados en una base local de desarrollo. No publicar esa base ni los CSV en GitHub.

## Semántica preservada

- `scopus_id` se conserva como identificador de origen. No se fabrica DOI.
- Las keywords se separan por `|`. Las relaciones `topic_article` se conservan como descriptores múltiples, sin presentarlas como temas inferidos.
- La coincidencia con keywords se comprueba mediante normalización NFKC, espacios y mayúsculas. Las discrepancias quedan contadas; no se sustituyen por coincidencias inventadas.
- Idioma, texto completo y fecha de disponibilidad histórica permanecen desconocidos.
- `processed_at` y el `retrieved_at` del documento normalizado registran el procesamiento/lectura local actual, nunca una fecha de disponibilidad en el pasado.
- Citaciones, autores y afiliaciones originales se conservan en su contexto, sin incorporarlos automáticamente a variables predictivas. No se imputa texto faltante.
- Una fecha sintácticamente válida no acredita precisión diaria/mensual. La auditoría cuenta fechas con día 01 y fechas de 1 de enero, pero no afirma que sean imputadas.
- El uso queda marcado `development_only_pending_clarification`, cobertura `unverified_snapshot` y precisión temporal `unverified`. La situación de 2025 requiere aclaración de la fuente.

## Relaciones múltiples y conteos

Las tablas de artículos, relaciones autorales y relaciones con descriptores son independientes. La consulta de descriptores cuenta artículos distintos por descriptor y año; su denominador es el número de artículos del año en esta instantánea. Variantes normalizadas de un descriptor no duplican el artículo.

Un artículo puede contribuir a varios descriptores. Las participaciones de descriptores distintos no tienen por qué sumar uno. Un cero significa ausencia de esa relación en la instantánea, no ausencia de producción científica en toda la población. Los conteos anuales son descriptivos; seis años no acreditan un pronóstico anual adecuado. No se expone entrenamiento o pronóstico en este adaptador. Las asociaciones no constituyen etiquetas de áreas del conocimiento validadas.

## Git Bash: ejecutar y revisar

Desde la raíz de analytics-service, activar `.venv`. La carpeta de evidencias queda fuera del repositorio:

```bash
source .venv/Scripts/activate
mkdir -p ../evidencias_locales
python -X utf8 -m app.corpus inspect --directory ../corpus_centinela > ../evidencias_locales/corpus-audit.json
```

Leer el resultado antes de guardar la base. Para una instantánea nueva:

```bash
python -X utf8 -m app.corpus ingest --directory ../corpus_centinela --database ../evidencias_locales/corpus-development-v1.sqlite --batch-size 500 > ../evidencias_locales/corpus-ingest-v1.json
python -X utf8 -m app.corpus descriptors --database ../evidencias_locales/corpus-development-v1.sqlite --descriptor decision-making
```

No repetir `ingest` sobre un destino existente. Para repetir el proceso, elegir otro nombre de versión. Las lecturas de conteos abren la base en modo de solo lectura. El adaptador no convierte SQLite en Lakehouse; esa integración queda pendiente de infraestructura y decisiones verificadas.

Código de salida: 0 operación completada, 2 fallo de entrada, integridad o almacenamiento. Un resultado correcto de ingesta no autoriza entrenamiento ni demuestra que cobertura y fechas estén verificadas.

## Verificación y registro manual

```bash
python -m ruff check .
python -m black --check app tests
python -m pytest --cov=app --cov-report=term-missing
```

Las pruebas del adaptador usan exportaciones sintéticas pequeñas con las mismas columnas, no copias de datos restringidos. Cubren bloques, identidad, relaciones, fecha/año, transacción, originales intactos, fallos y conteos multietiqueta. La prueba de integración sobre el corpus real se hace con almacenamiento temporal de desarrollo, sin entrenar modelos.

Verificación local del incremento: 25 pruebas nuevas aprobadas; suite completa de 343 pruebas aprobadas, sin fallos, cobertura conjunta de líneas/ramas de 99,34 %. Ruff, Black y `pip check` conformes. Se conserva la advertencia de deprecación de TestClient/httpx en las dependencias fijadas. La ejecución temporal sobre los tres CSV originales terminó sin conflictos de identidad/relaciones y confirmó huellas iguales antes/después. No se guardó una base persistente del corpus durante esa comprobación. Esto verifica ingesta y software, no precisión predictiva ni autorización de publicación.

El [manifiesto de este incremento](environment-corpus-20261022.json) y el [inventario](inventory-corpus-20261022.json) registran el software actual, con 36 módulos y sin infracciones de dependencia entre capas. Los manifiestos anteriores se conservan como instantáneas históricas.

En Azure, registrar avance de T07.1–T07.3, T08.1–T08.3 y la base descriptiva de R11–R12. No resolver modelado temático, validación histórica, pronóstico, XAI o Lakehouse por esta ingesta. Los estados los modifica el titular.

El titular revisará y confirmará en Git los archivos de código, pruebas y documentación. Mantener los CSV, bases y evidencias fuera del repositorio. Flujo: rama feature desde develop, PR hacia develop, 2 aprobaciones y CODEOWNERS. La confirmación del permiso Write por correo se verifica operacionalmente al reintentar el push.
