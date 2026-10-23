# Operación local y evidencia reproducible

Trazabilidad: R01, R24, R29 y R30. Estos procedimientos verifican software y artefactos locales; no acreditan calidad predictiva con datos reales ni una integración externa ya desplegada.

## Entorno y comandos de auditoría

Usar el entorno `.venv` de Python 3.11 y las dependencias fijadas en el repositorio. Desde Git Bash, en la raíz de analytics-service:

```bash
source .venv/Scripts/activate
python -m pip check
python -X utf8 -m app.audit environment
python -X utf8 -m app.audit inventory
python -X utf8 -m app.audit schema --public-base-path /api/analytics
```

`environment` lee los requisitos/constraints locales, inventaría distribuciones instaladas y registra huellas de código/configuración sin invocar Git ni acceder a la red. No exporta `.env`, credenciales, rutas del intérprete ni nombre del usuario. Las restricciones no obligan a instalar todos los paquetes listados: se comprueban si están instalados; los requisitos directos sí se exigen.

El manifiesto registra Python, SQLite, versión del servicio, plataforma, paquetes y archivos. La verificación compara exactamente fuentes, pines, paquetes instalados y versiones de Python/SQLite; reporta por separado cambios de plataforma. Coincidencia de entorno no demuestra por sí sola equivalencia científica de modelos.

Guardar evidencias fuera del repositorio evita incluir datos de trabajo en el commit. El titular ejecuta:

```bash
mkdir -p ../evidencias_locales
python -X utf8 -m app.audit environment > ../evidencias_locales/environment.json
python -X utf8 -m app.audit verify-environment --manifest ../evidencias_locales/environment.json
python -X utf8 -m app.audit inventory > ../evidencias_locales/inventory.json
python -X utf8 -m app.audit schema --public-base-path /api/analytics > ../evidencias_locales/openapi.json
```

Si se modifica software o entorno, conservar el manifiesto anterior y generar otro; no sobrescribirlo para ocultar diferencias. Códigos de salida: 0 para comprobación conforme; 1 para diferencias o no conformidad; 2 para entrada inválida o error de lectura. El esquema OpenAPI es un contrato exportado, no evidencia de conectividad con el gateway.

## Artefactos de referencia

```bash
python -X utf8 -m app.cli forecast --input RUTA_SOLICITUD.json --database RUTA_ARTEFACTOS.sqlite
python -X utf8 -m app.cli restore-forecast --database RUTA_ARTEFACTOS.sqlite --run-id ID_REAL
python -X utf8 -m app.audit replay --database RUTA_ARTEFACTOS.sqlite --run-id ID_REAL
```

Los nombres en mayúsculas son parámetros que el titular debe sustituir. La solicitud sigue `ForecastRequest`, con serie, lote, tema, corte y horizonte. Declarar `synthetic` o `empirical` según corresponda: la etiqueta es una declaración del origen, no una certificación automática.

`restore-forecast` comprueba identidad y contratos, y devuelve exactamente el artefacto guardado. `replay` además compara fuentes y entorno registrado; si hay diferencias no reejecuta. Si coinciden, vuelve a calcular la referencia y compara el resultado. Esta comprobación no evalúa un modelo definitivo ni cuantifica generalización sobre un corpus real.

Las bases locales conservan entradas y resultados, por lo que deben mantenerse en la ubicación autorizada para los datos. La identidad por SHA-256 detecta diferencias, pero no constituye firma ni prueba de autenticidad del origen.

## Límites de entrada y persistencia

- HTTP: máximo predeterminado de 8 MiB por cuerpo, configurable con `ANALYTICS_MAX_REQUEST_BYTES` entre 1 KiB y 64 MiB. Se cuentan los bytes recibidos, aunque el envío sea por fragmentos o la longitud declarada sea incorrecta.
- JSON: UTF-8 con BOM opcional; rechazo de claves duplicadas, números no finitos, entradas excesivamente anidadas y contenido inválido. Los archivos de la consola se limitan a 8 MiB; dividir lotes grandes.
- Dominio: se mantienen 1000 documentos por lote, 240 meses y los límites documentados en OpenAPI.
- Escritura SQLite: controles de integridad dentro de la transacción; una escritura fallida se revierte y no se subsanan silenciosamente datos previamente alterados.
- Lectura de instantáneas/ejecuciones: conexión SQLite de solo lectura. No se cargan modelos pickle de fuentes no verificadas.
- Los POST analíticos continúan disponibles solo en el entorno `local`; habilitación remota y autorización requieren integración real de identidad.

La configuración Compose heredada usa `local` por defecto. Antes de cualquier despliegue, el responsable debe establecer explícitamente `ANALYTICS_ENVIRONMENT=staging` o `production` según corresponda; no se detecta automáticamente el entorno por la red desde la que llega la petición.

## Verificación local

```bash
python -m ruff check .
python -m black --check app tests
python -m pytest --cov=app --cov-report=term-missing --cov-report=xml --junitxml=report.xml
```

Los informes son evidencia de software y están excluidos del versionado por `.gitignore`. Registrar en Azure el commit real y los resultados de ejecución. Los tests con entradas controladas no se transcriben como resultados empíricos de la tesis.

## Pendientes para el cierre

Fijar y validar la infraestructura Lakehouse; obtener corpus autorizado y cobertura; verificar conexión con servicios, identidad y frontend; entrenar y evaluar modelos; completar XAI; probar el paquete de reproducción con datos/modelos reales y registrar la versión final. Docker/Compose y los workflows existentes se inspeccionaron, pero no se ejecutaron ni modificaron en esta entrega.
