# BERTopic y mapa temático: trabajo planificado

Refinamiento autorizado por el tesista el 20 de noviembre de 2026. El plan firmado
permanece intacto. El detalle canónico, criterios, IDs y decisiones se conserva en
el repositorio de gestión, documento `docs/bertopic-mapa-tematico-20261120.md`.

Azure: R31/162, bajo F07, concreta el mapa; T31.1–T31.5 / 169–173 especifican
contrato, API, interfaz, filtros y verificación. T10.4–T10.7 / 163–166 concretan
la factibilidad BERTopic/NMF bajo R10. T11.4/167 aborda revisión semántica,
T12.4/168 los denominadores y T25.4/174 el protocolo de interpretación con personas.
Los elementos nuevos están en Proposed; no se afirma implementación ni resultados.

El primer incremento debe congelar protocolo y recursos, preparar embeddings
locales versionados y definir el contrato de conteos y relaciones. El benchmark
utilizará documentos reales de entrenamiento y mantendrá 2019–2021 como diagnóstico
ya observado. No se harán descargas o envíos externos del corpus para esta planificación.

El mapa podrá usar NMF. El área del nodo representará artículos distintos; la
proporción usará documentos preparados elegibles y mostrará los no asignados. Los
enlaces serán similitud coseno en un espacio temático declarado del mismo modelo.
Filtros de año cambiarán conteos/documentos, conservando modelo, identidad temática
y representaciones ajustadas. No se confundirá similitud con causalidad, predicción
o XAI. Los documentos se consultarán mediante el mecanismo de acceso vigente.

Este documento no modifica endpoints ni contratos actuales. La formalización y
su implementación corresponden a las tareas nuevas, con evidencia propia antes de cierre.
