---
title: "Asistencia doméstica: primer incremento ejecutable"
---

**Estado: 7 de septiembre de 2026.** Implementación inicial de los contratos, ciclo de misión y registro propuestos en el [plan de tesis](/docs/development/plan_tesis_asistencia_domestica.md). La demo usa exclusivamente un ejecutor determinista de prueba: no controla MuJoCo ni hardware y no necesita un VLM, GPU o policy motora.

**Hardware objetivo confirmado:** AlohaMini2 completo con dos AM-ARM200, LiDAR Unitree L2 superior, D435i superior y dos cámaras de muñeca. Sustituye la decisión anterior de usar SO101. La mini PC prevista es Beelink GTi15 Ultra; disponer de 24 GB de VRAM es una expectativa, no un recurso comprobado. Qwen3-VL-4B-Instruct es un candidato de supervisor; su tamaño y backend no están fijados. Todavía no hay datasets ni checkpoints motores.

**Qué está implementado**

| Pieza | Comportamiento |
| --- | --- |
| [Contratos](/dimos/experimental/domestic_assistance/contracts.py) | Catálogo cerrado, destinos relacionales `IN`/`ON`, evidencia tipada, estado bimanual, contexto de decisión, manifiesto experimental, escenarios e intervenciones. La etiqueta terminal no forma parte de la observación. |
| [Interfaces](/dimos/experimental/domestic_assistance/interfaces.py) | Ejecutor no bloqueante, observador capaz de entregar snapshots posteriores, supervisor con contexto reproducible y verificador inyectable. Solo el runner despacha acciones. |
| [Runner](/dimos/experimental/domestic_assistance/runner.py) | Separa rechazo, despacho, ejecución y verificación; espera percepción posterior, conserva límites y cancelación confirmada, y registra ayuda o exclusión experimental. |
| [Observaciones](/dimos/experimental/domestic_assistance/observations.py) | Buffer de snapshots inmutables con lectura estrictamente posterior; no reemplaza estados nuevos ni actualiza artificialmente timestamps. La fusión de sensores sigue perteneciendo al adaptador. |
| [Verificación](/dimos/experimental/domestic_assistance/verification.py) | Exige hechos frescos y evidencia posterior. Distingue búsqueda sin hallazgo de resultado inconcluso y comprueba relaciones con cesto, bandeja o superficie, no solo coincidencia de zona. |
| [Registro y auditoría](/dimos/experimental/domestic_assistance/rollouts.py) | JSONL v2 con fsync, contexto exacto del modelo, evaluaciones de candidatos, historial reproducible, intervención, validez, hashes y verificación semántica auditable. |
| [Supervisor de prueba](/dimos/experimental/domestic_assistance/supervisor.py) | Secuencia reproducible con reintento acotado y petición de ayuda ante UNKNOWN. Usa el contrato que implementará después el VLM. No es una política aprendida. |
| [Ejecutor determinista](/dimos/experimental/domestic_assistance/testing_executor.py) | Efectos semánticos artificiales e inyección de fallo, evidencia desconocida, timeout y cancelación no confirmada. Su origen siempre es test. |

**Ejecutar y revisar**

Desde la raíz del repositorio y con el entorno instalado, el primer caso traslada un solo objeto. Genera un archivo distinto por ejecución y no sobrescribe episodios anteriores:

```bash
.venv/bin/python -m dimos.experimental.domestic_assistance.demo_mission --task recoger_ropa --output /tmp/dimos-domestic-demo
```

Para probar las dos tareas con dos objetos y las rutas de recuperación:

```bash
.venv/bin/python -m dimos.experimental.domestic_assistance.demo_mission --task recoger_ropa --output /tmp/dimos-domestic-demo
.venv/bin/python -m dimos.experimental.domestic_assistance.demo_mission --task preparar_bandeja --output /tmp/dimos-domestic-demo
.venv/bin/python -m dimos.experimental.domestic_assistance.demo_mission --fault failed --output /tmp/dimos-domestic-demo
.venv/bin/python -m dimos.experimental.domestic_assistance.demo_mission --fault unknown --output /tmp/dimos-domestic-demo
.venv/bin/python -m dimos.experimental.domestic_assistance.demo_mission --fault timeout --output /tmp/dimos-domestic-demo
.venv/bin/python -m dimos.experimental.domestic_assistance.demo_mission --fault cancel_unconfirmed --output /tmp/dimos-domestic-demo
```

La demo imprime la razón de terminación, el número de decisiones, la ruta del JSONL y su auditoría. `complete=true` en la auditoría significa que el registro está completo y es consistente: también un episodio fallido puede estar bien registrado. `origin=test` indica que no es evidencia física. La duración usa un reloj artificial, no mide rendimiento de hardware. `--code-version` permite identificar la versión usada; su valor por defecto indica explícitamente desarrollo sin versionar.

**Semántica del registro**

Cada archivo comienza con misión, límites y metadatos. Cada decisión tiene candidatos, acción elegida, comportamiento del supervisor y observación anterior. Su cierre registra por separado el resultado del ejecutor y el resultado verificado, la duración y la observación posterior cuando está disponible. Solo el cierre de episodio contiene la etiqueta de éxito autónomo.

Los episodios interrumpidos conservan los eventos ya escritos. No se reanudan automáticamente: hay que reconciliar el estado de actuadores y auditar el archivo. Un error de escritura solicita parada y deja la instancia inhabilitada; no se inventa un cierre exitoso. CANCEL_UNCONFIRMED indica que el software no puede afirmar que el robot se haya detenido.

Los productores de observaciones deben derivar hechos de sensores, preservar timestamps y registrar evidencia real. El verificador comprueba los hechos recibidos; no constituye aún un detector visual de agarres ni verifica por sí mismo el contenido de una imagen. El adaptador determinista publica hechos artificiales solo para pruebas.

**Paso a DimOS, MuJoCo y hardware**

| Siguiente integración | Contrato que debe cumplir |
| --- | --- |
| Modelo AM-ARM200 | Usar cinemática, articulaciones, pinzas y montajes del URDF confirmado. No reutilizar índices, límites, poses HOME ni el URDF SO101. Véase la [ficha de hardware](/docs/development/tesis/hardware_objetivo.md). |
| Navegación | Conectar el planificador por Spec/RPC; set_goal solo acepta el objetivo. Exigir llegada comprobada y parada observada; cancelar ante timeout. Localización real, extrínsecos y huella deben validarse por separado. |
| Streams de sensores | Traducir D435i, cámaras de muñeca, odometría y percepción a ObservationBuffer con origen simulation o physical. La posición exacta del simulador no puede presentarse como localización física. |
| Manipulación | Seleccionar ACT o SmolVLA cuando existan datos y pruebas; adaptar su entrada/salida al AM-ARM200. Completar motores no prueba PICK/PLACE; se exige un verificador observable. |
| VLM | Implementar Supervisor con candidatos validados y tiempo de inferencia acotado. El VLM no recibe acceso directo a movimientos articulares ni ejecuta herramientas por su cuenta. |
| Blueprint | Componer módulos y Specs con un único dueño de la ejecución; añadir el blueprint al registro generado cuando tenga comportamiento integrado. No se registra todavía una misión doméstica física o MuJoCo. |

Los métodos del adaptador deben retornar rápido y tener plazos propios en RPC/SDK. El runner puede limitar una operación que se consulta por poll, pero no puede interrumpir un driver que bloquea indefinidamente dentro de start/poll/cancel. El dueño de la sesión debe llamar tick periódicamente, pedir cancelación al cerrar y esperar parada o timeout; el watchdog físico es una responsabilidad adicional del adaptador.

**Decisiones pendientes, sin bloquear las pruebas de software**

- Modelo exacto estándar/Pro que llegará, controladores y SDK de base/elevación/brazos, IDs de servos, dispositivos y límites calibrados.
- Cámaras de muñeca concretas, resolución/frecuencia, sincronización y sus transformaciones; extrínsecos de D435i y L2 superiores.
- Confirmación física de prendas, vaso, plato, cesto, bandeja, mesa y superficie elevada. Las configuraciones actuales fijan tres prendas y, para mantener 19 decisiones, un vaso y un plato en el piloto de bandeja.
- Se proponen keyframes antes/después de cada habilidad y video opcional; todavía no hay captura automática ni política de retención implementada.
- Elección y prueba del backend Qwen y del ejecutor motor. No se han instalado modelos ni iniciado entrenamientos.

Este incremento no implementa aún Q/V, ventajas, SFT, el adaptador físico, la migración del simulador a AM-ARM200 ni la campaña de evaluación. Entrega una base ejecutable y probada para conectarlos progresivamente, sin crear carpetas vacías que aparenten funcionalidad.
