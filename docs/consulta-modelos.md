# Consulta de modelos técnicos registrados

El registro se crea explícitamente mediante `python -m app.modeling fit` usando
textos controlados y una base externa. Las consultas no entrenan, escriben,
inicializan registros ni cambian el corpus. No requieren dependencias numéricas
para leer metadatos de un registro existente.

Configurar `ANALYTICS_MODEL_DATABASE` con la ruta del registro existente y levantar
el backend normalmente. Abrir `/research-analytics/models` en Centinela. El frontend
conserva su guard y usa `/api/analytics/models`; su publicación por el gateway
institucional permanece pendiente de la integración operacional.

API local:

- `GET /api/v1/models?limit=20&offset=0`: paginación estable por ID, total y estado vacío.
- `GET /api/v1/models/{SHA256}`: metadatos verificados del modelo indicado.
- Registro sin configurar/ausente: 503, sin crear archivo.
- Modelo inexistente: 404. ID o paginación inválidos: 422.
- Artefacto alterado o metadatos incompatibles: 409, sin devolver contenido parcial.
- Base SQLite incorrecta/no disponible: 503. Fuera de entorno local: 503 con
  `integration_pending`, conservando el guard existente.

Cada elemento de la página se verifica por SHA256 y contrato antes de responder.
Si uno falla, se rechaza la página completa. Una página no verifica modelos de
otras páginas. La huella detecta cambios, pero no constituye firma digital ni
atestación externa de procedencia o calidad científica.

Los campos públicos son ID de modelo y workset, método, propósito técnico,
cantidad de documentos de ajuste, parámetros permitidos, versiones numéricas,
corte declarado y estado temporal. No se devuelven textos, IDs de documentos,
vocabulario, IDF, componentes, rutas locales ni diagnósticos de entrenamiento.
El estado `not_research_validated` se mantiene explícito para los modelos actuales.
La consulta no transforma disponibilidad histórica declarada en verificada.

Frontend: listado, paginación, consulta de detalle, cierre, reintento, carga,
vacío, registro no disponible, inexistencia y fallo de integridad. Las consultas
obsoletas se cancelan al cambiar de página/selección o destruir el componente.

Pruebas: HTTP contra FastAPI con registro NMF de textos controlados, igualdad de
huella del archivo antes/después de consultas, paginación sin duplicados,
integridad, registro ausente, esquema incorrecto y guard local. Angular prueba
servicio HTTP relativo, presentación, estados y cancelación de suscripciones.
