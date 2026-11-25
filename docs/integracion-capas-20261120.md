# Integración y capas versionadas — prioridades 4 y 5

Alcance: R05/30, R07/38, R09/46, R19/86, R20/90, R21/94 y R24/106.
Se mantiene el plan firmado y el corpus real; ninguna prueba técnica sustituye
la evaluación con personas de OE6. No se incorporan pipelines ni fuentes externas.

La capa existente de Parquet y catálogo SQLite se amplía con publicaciones
atómicas que agrupan todas las tablas y artefactos. Las capas bronze conservan
ocho CSV exactos y sus registros; silver contiene documentos, relaciones válidas,
textos preparados y asignaciones; gold conserva series y comparaciones; models
conserva los modelos inertes usados. Neo4j/MongoDB siguen siendo responsabilidad
operacional de los servicios existentes: no se recrean ni modifican sus grafos.

Cada publicación identifica fuentes, plan, código, estudio y revisión por hash.
El catálogo publica el conjunto completo en una transacción con control del padre.
Un fallo antes de esa transacción no publica un conjunto parcial. Los objetos
sin referencia que pueda dejar una interrupción no son visibles como publicación.
La reejecución idéntica devuelve la misma versión; un padre desactualizado falla.
Las consultas históricas conservan sus objetos. Se verifican hashes y esquema.
Es almacenamiento local versionado, no una declaración de Lakehouse distribuido,
compatibilidad Delta/Iceberg ni despliegue institucional.

Cuando `ANALYTICS_LAKE_DIRECTORY` está configurado, `/study` y `/study/review`
restauran las salidas desde los objetos versionados. Las series mostradas se leen
del Parquet gold y se cotejan con el estudio. `/lineage/current` y `/lineage/releases`
exponen metadatos, sin descargas de corpus, modelos o documentos privados.

En staging/producción las consultas requieren un bearer validado mediante el
endpoint existente de identity-service y una lista explícita de principales
autorizados. La ausencia de configuración bloquea el acceso. La API no confía en
cabeceras de principal suministradas por clientes. Las operaciones de procesamiento
y escritura siguen locales. El gateway aplica `auth_request` y la API vuelve a
validar identidad para impedir el acceso directo sin autorización. No se comparten
claves de firma de identidad con analytics. No se afirma que exista un sistema
institucional de roles analíticos que todavía no ha sido entregado.

El frontend usa `/api/analytics` en el mismo origen, conserva el interceptor y añade
la vista `/research-analytics/lineage`. El estudio muestra la versión de datos.
Los errores de autenticación, autorización, ausencia de versión e indisponibilidad
se distinguen. El gateway publica el OpenAPI de analytics en su hub existente.

## Ejecución desde Git Bash

En `TESIS/analytics-service`, con el entorno activado:

```bash
python -m app.layer materialize \
  --source-directory ../corpus/raw \
  --corpus ../evidencias_locales/corpus-real-20261118/service-corpus.sqlite \
  --study-directory ../evidencias_locales/research-study-20261119-v2 \
  --review-directory ../evidencias_locales/research-review-20261120 \
  --plan ../F_AA_234A_Jairo_Quispe-signed.pdf \
  --store ../evidencias_locales/research-layers-20261120
python -m app.layer verify --store ../evidencias_locales/research-layers-20261120
```

Una actualización distinta exige indicar `--expected-parent ID_ACTUAL`. Los
originales se mantienen fuera del almacén y no se sobrescriben. Los objetos y
catálogos privados no se suben al repositorio.

En la raíz TESIS, con Docker Desktop y su motor activos, el entorno aislado usa
`evidencias_locales/tooling/real-integration/compose.yml` y un archivo privado de
credenciales generado localmente. Ese archivo no debe compartirse ni publicarse.

```bash
docker compose --env-file evidencias_locales/tooling/real-integration/private.env \
  -f evidencias_locales/tooling/real-integration/compose.yml up -d --build
analytics-service/.venv/Scripts/python.exe \
  evidencias_locales/tooling/real-integration/verify.py
```

Frontend aislado: `http://127.0.0.1:18451/research-analytics/lineage`.
La provisión local de identidad crea cuentas técnicas en PostgreSQL aislado;
no crea participantes ni acredita login/MFA o evaluación humana. Los tokens
se guardan solo en `real-integration/private`, nunca en logs o código publicado.
Para detener los contenedores: el mismo comando compose con `stop`; no hace falta
borrar volúmenes ni datos.

Fuentes técnicas: [contrato auth_request de Nginx](https://nginx.org/en/docs/http/ngx_http_auth_request_module.html)
y [tiempos de espera HTTPX](https://www.python-httpx.org/advanced/timeouts/).
La evidencia de ejecución es la de los JSON y logs fechados de evidencias_locales;
la existencia de configuración o código no acredita por sí sola un despliegue.
