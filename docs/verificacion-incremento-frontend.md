# Incremento: exploración documental y diagnóstico del predictor heredado

Verificación local del 22 de octubre de 2026. Se implementó código en analytics-service y centinela-front. predictive-service se inspeccionó en modo lectura. No se efectuaron operaciones Git ni cambios en Azure, Prism, el plan o el corpus original.

## Entregables comprobados

| Repositorio | Entregable | Alcance y límite |
| --- | --- | --- |
| centinela-front | Módulo lazy research-analytics, acceso desde el encabezado, contratos HTTP relativos, filtros, paginación y detalle | Implementación local dentro del frontend existente; conexión real con identidad/gateway pendiente |
| centinela-front | Conteos anuales y descriptores frecuentes | Estadística descriptiva de una instantánea; no pronósticos, modelos temáticos ni cobertura poblacional verificada |
| analytics-service | CLI app.legacy | AST, huellas de cinco archivos y encabezado del CSV; sin ejecución de código externo, pickle, inferencia o entrenamiento |
| predictive-service | Inspección de contratos y artefactos presentes | Su tarea es proyección por afiliación. Las constantes MAE/RMSE en la fuente no son evaluación reproducida por esta tesis |

La guía detallada de frontend está en `centinela-front/docs/research-analytics.md`, dentro de su propio repositorio. La inspección está descrita en [predictor-heredado.md](predictor-heredado.md).

## Evidencia técnica

- Backend: 360 pruebas aprobadas; cobertura conjunta de líneas/ramas 99,14 %. Ruff, Black y consistencia de dependencias aprobados. Se conserva la advertencia de deprecación TestClient/httpx. Inventario: 42 módulos y cero infracciones de límites entre capas.
- Frontend: 2103 pruebas aprobadas, incluidas diez nuevas del explorador. Node 18.20.2, Angular 16 y Chrome Headless 155 en Windows. Cobertura: statements 95,74 %, ramas 90,24 %, funciones 94,77 %, líneas 95,93 %. Se conserva el umbral de 90 % en las cuatro dimensiones.
- ESLint del módulo nuevo, routing y environments aprobado. Los dos specs heredados de salarios tienen 19 usos previos de any detectados por ESLint; no se cambió esa regla ni se afirma lint global aprobado.
- Los seis fallos iniciales de salarios se resolvieron fijando la dependencia regional exclusivamente en esos grupos de pruebas. No se modificó su código de producción.
- Las compilaciones development y local aprobaron. El build local final registró hash c6e652dc6ea8e904 y salida 0; no se ejecutó build de producción ni despliegue. Las pruebas HTTP/DOM utilizan respuestas sintéticas identificadas como tales; no requieren participantes y no equivalen a integración real con el stack ni evaluación empírica del modelo.
- Adicionalmente se consultó la API en proceso con TestClient y la instantánea real de desarrollo: 28100 artículos, página inicial de 20 y diez descriptores; resumen/listado/detalle/descriptores/filtro respondieron 200 y un identificador inexistente respondió 404. El filtro año 2024 sin resumen devolvió un total de 38. Se verificaron los campos requeridos por los contratos Angular. SHA-256 de los tres CSV originales y de la instantánea iguales antes/después. Esta es una comprobación de contratos sobre datos reales, no una sesión de navegador ni conexión de red con gateway/identidad.

Logs y auditoría quedan fuera de los repositorios, en `evidencias_locales/frontend-tests-final.log`, `evidencias_locales/predictive-source-audit.json` y `evidencias_locales/frontend-backend-contract-smoke.json`. Los manifiestos [environment-frontend-20261022.json](environment-frontend-20261022.json) e [inventory-frontend-20261022.json](inventory-frontend-20261022.json) corresponden al backend de este incremento; no son inventarios de dependencias Angular. Las instantáneas anteriores conservan su carácter histórico.

## Registro manual en Azure

Las referencias funcionales R19/R20/R27 reciben evidencia de consultas/presentación y contratos, pero deben conservar pendientes los criterios de integración y resultados de modelos que todavía no se ejecutaron. R01/R05/R16 reciben evidencia de inspección y compatibilidad de entradas; no acreditan entrenamiento, pronóstico temático ni XAI. Antes de cambiar un estado, el titular debe cotejar el título y todos los criterios del elemento CMMI real. No se cierran requisitos completos por haber terminado sus subtareas locales.

Pendientes: preparar ramas/PR, revisión del equipo, stack local con identidad/gateway, autorización de publicación, precisión/rezago del corpus, decisiones de entrenamiento, modelos temáticos, pronóstico y XAI propios. La exclusión de participantes no convierte CR01 en un cambio académico aprobado.

## Commit del backend a cargo del titular

Después de revisar los archivos en VSC y confirmar que son los cambios que desea incluir:

```bash
cd /c/Users/Pato/Downloads/TESIS/analytics-service
source .venv/Scripts/activate
git status --short --branch
git diff --check
git diff
git add app/legacy.py tests/test_legacy_inspection.py docs/predictor-heredado.md docs/preparacion-documental.md docs/environment-frontend-20261022.json docs/inventory-frontend-20261022.json docs/verificacion-incremento-frontend.md
git diff --cached
git commit -m "feat(analytics): inspect inherited predictor contracts" \
  -m "Record source declarations and artifact identities without executing inherited models or treating source constants as verified thesis results."
```

Revisar también archivos nuevos en VSC: git diff no muestra su contenido antes de agregarlos. Verificar la rama antes de confirmar y no mezclar trabajo ajeno. Un push a una rama que ya tiene PR modifica ese PR; el titular elige mantener ese alcance o preparar una revisión separada conforme al flujo del equipo. Los PR van a develop con dos aprobaciones y CODEOWNERS. Para frontend, seguir la preparación de rama de su propia guía; su checkout se encontró en main y no debe confirmarse ahí.
