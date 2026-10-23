# Calidad y preparación versionada del corpus de desarrollo

Este incremento conecta diagnóstico y preparación mediante contratos HTTP tipados para el frontend existente. No ejecuta entrenamiento, detección de idioma o predicción; tampoco convierte una selección de desarrollo en partición temporal final. Aporta a R08, R09, R19, R20 y R24; el cierre de cada requisito depende de todos sus criterios, no de la presencia de una pantalla.

## Diagnóstico y selección

`GET /api/v1/corpus/quality` calcula artículos, ausencias de resumen, longitud del resumen en cuatro intervalos de tokens Unicode, grupos de título/resumen normalizados repetidos y exceso de registros en esos grupos. También cuenta idiomas declarados/desconocidos y fechas con día 1 y 1 de enero. El segundo conteo está incluido en el primero. No se suman como grupos disjuntos. Un texto repetido es un candidato a revisión, no una certificación de duplicación de publicaciones. Los conteos de fechas no prueban precisión, cobertura ni rezago de indexación.

`POST /api/v1/corpus/preparation/preview` reutiliza las reglas existentes de preparación y devuelve únicamente configuración, identidad, procedencia y conteos agregados; no devuelve los identificadores incluidos/excluidos ni los textos. La selección configurable comprende años, mínimo de tokens, resúmenes ausentes y política de repeticiones. `exclude_later` conserva el primero por identificador estable, no por fecha de publicación. El filtrado anual no acredita disponibilidad histórica de los registros.

## Creación y recuperación

Configurar en la terminal del backend, desde analytics-service:

```bash
export ANALYTICS_ENVIRONMENT=local
export ANALYTICS_CORPUS_DATABASE="../evidencias_locales/corpus-development-v1.sqlite"
export ANALYTICS_WORKSET_DIRECTORY="../evidencias_locales/worksets"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8006
```

La API no acepta rutas del navegador. `POST /api/v1/corpus/worksets` recibe:

```json
{
  "configuration": {
    "missing_abstract": "exclude",
    "duplicates": "exclude_later",
    "min_tokens": 5,
    "start_year": 2020,
    "end_year": 2025
  },
  "expected_workset_id": "IDENTIFICADOR_SHA256_REAL_DEVUELTO_POR_PREVIEW"
}
```

El identificador del ejemplo es explicativo y debe reemplazarse por los 64 caracteres hexadecimales reales. Si la preparación ya no coincide con la previsualización, se rechaza antes de publicar la versión. La creación escribe un archivo temporal y publica mediante enlace sin sobrescribir; una versión idéntica existente se verifica y reutiliza. Ante error se limpia el archivo temporal. El destino queda fuera del repositorio y su nombre deriva exclusivamente de la identidad del conjunto. `GET /api/v1/corpus/worksets/{id}` comprueba manifiesto, registros e identidad del nombre antes de devolver un resumen compacto.

Estas bases SQLite son conjuntos locales auxiliares, no un Lakehouse implementado. La autorización del backend para staging/production sigue pendiente: las rutas analíticas devuelven `503 integration_pending` en esos entornos. La restricción local no sustituye autenticación para un despliegue compartido. El almacenamiento no configurado devuelve 503; configuración inválida o identidad/integridad incorrecta, 422; conjunto inexistente, 404. No hay cambio de pipelines ni despliegue.

El CLI agrega `python -X utf8 -m app.documents quality --database RUTA.sqlite`. La preparación existente por CLI sigue disponible, sin cambiar su formato completo de manifiesto.

## Verificación con datos reales de desarrollo

La comprobación técnica usó la instantánea de 28100 artículos y los criterios del ejemplo. La primera ejecución reconcilió 27917 incluidos y 183 excluidos: 140 por resumen ausente y 43 por repetición textual. El diagnóstico encontró 42 grupos repetidos; grupo y exceso de registros son unidades diferentes. Se registraron 24679 fechas con día 1 y, dentro de ellas, 14779 con 1 de enero. No se atribuye causa a estas concentraciones. La ejecución final, pruebas y límites se registran en el informe del incremento; esto no es evaluación empírica de temas, pronóstico o XAI.

Los conjuntos y reportes detallados permanecen exclusivamente en `evidencias_locales`, fuera de Git. El verificador local contrasta SHA-256 de los tres CSV y de la instantánea antes/después, compara previsualización/creación/lectura y comprueba que la repetición no sobrescriba la versión. Los tests unitarios utilizan exportaciones sintéticas explícitas, cubren almacenamiento, errores, manipulación e integridad y no representan validación humana.
