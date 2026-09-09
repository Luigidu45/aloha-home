# Fase 2: simulación e integración DimOS

## 1. Objetivo

Esta fase valida la arquitectura de ejecución de la tesis antes de conectar ACT
o el robot físico. Su objetivo no es demostrar agarres ni simular ropa
deformable con alta fidelidad. Debe demostrar que una decisión semántica
atraviesa de forma segura y reproducible el siguiente circuito:

```text
misión y escenario versionados
        -> supervisor de referencia
        -> MissionRunner
        -> navegación DimOS / habilidad simulada
        -> observación posterior nueva
        -> verificador congelado
        -> journal y keyframes auditables
```

La navegación sí se ejecuta mediante el stack real de DimOS sobre MuJoCo. Las
habilidades `SEARCH`, `PICK`, `PLACE` y `VERIFY` actualizan un estado simbólico y
se etiquetan de forma explícita como simulación simbólica. Por tanto, un éxito
de esta fase prueba integración de software, pero no generalización de ACT,
calidad perceptiva ni éxito físico.

## 2. Alcance implementado

### 2.1 Poses de zonas separadas de la misión

Los archivos:

- `recoger_ropa_simulation_zones.json`;
- `preparar_bandeja_simulation_zones.json`;

asocian las zonas semánticas a poses del mapa
`alohamini2_office_lite_v1`. El cargador exige versión, correspondencia exacta
de `task_id` y el mismo conjunto de zonas que la misión. Calcula además un hash
SHA-256 guardado en `ExperimentManifest.environment_config_sha256`.

Las coordenadas no se añadieron a `Mission`: así se puede conservar la misma
misión al cambiar de mapa, simulador o vivienda.

### 2.2 Navegación DimOS

`DimosNavigationAdapter` convierte `NAVIGATE(zone=...)` en un `PoseStamped` y
usa `NavigationInterfaceSpec`:

- `set_goal()` inicia la navegación;
- `get_state()` e `is_goal_reached()` separan aceptación de terminación;
- `cancel_goal()` solicita la parada;
- `is_idle()` no confirma cancelación hasta que el planificador está en `IDLE`.

Un estado `IDLE` sin `is_goal_reached()` no se interpreta como fallo inmediato,
porque el planificador puede estar entre dos intentos de replanning. La interfaz
actual no expone un estado terminal de fallo; en ese caso el timeout acotado del
runner decide y cancela. Si el costmap todavía no existe, la meta permanece
pendiente y se reintenta sin bloquear el runner.

Una navegación hacia la zona en la que el robot ya está detenido se registra
como no-op exitoso, pero solo después de verificar pose y parada.

### 2.3 Observación y percepción de integración

`SimulationObserver` consume odometría y la cámara frontal de MuJoCo. Produce el
mismo contrato `Observation` que consumirá el supervisor físico y aplica estas
reglas:

- requiere odometría e imagen sincronizadas;
- no devuelve una observación postacción hasta que **ambos sensores** tengan
  muestras posteriores a la finalización del ejecutor;
- resuelve la zona desde la pose y sus tolerancias;
- infiere `base_stopped` usando estado `IDLE` y tres poses consecutivas estables,
  porque el simulador actual publica `PoseStamped` y no velocidad base;
- guarda keyframes JPEG con timestamp y SHA-256;
- marca los objetos, pinzas y relaciones como
  `symbolic-simulation-state`, no como predicciones visuales.

Esta fase prueba transporte, sincronización, frescura y evidencia de cámara. La
segmentación/detección visual de objetos queda fuera del alcance y deberá
sustituir el estado simbólico antes de obtener resultados perceptivos de tesis.

### 2.4 Ejecutor compuesto y estado bimanual

`SimulationExecutor` garantiza una única acción activa. Enruta `NAVIGATE` al
adaptador DimOS y las demás habilidades al mundo simbólico. Una bandeja
bimanual ocupa ambas pinzas; sus objetos dependientes conservan la relación
`ON` y se trasladan con ella. Los resultados simbólicos incluyen la advertencia
de que no se ejecutó una policy ACT ni dinámica de manipulación.

### 2.5 Módulo y Blueprints

`DomesticAssistanceSimulationModule` es dueño del episodio. Conecta los streams,
crea el runner y el journal, ejecuta ticks a frecuencia fija y expone RPCs para:

- `start_nominal_episode(episode_id, seed)`;
- `cancel_episode()`;
- `episode_status()`.

Los Blueprints registrados son:

```bash
alohamini2-domestic-clothes-sim
alohamini2-domestic-tray-sim
```

Ambos reutilizan `AlohaMini2SimModule`, mapeo, costmap, A*, control de movimiento
y los contratos/verificador de las fases anteriores.

## 3. Ejecución

En un host sin multicast loopback configurado se puede usar Zenoh como
transporte global:

```bash
.venv/bin/python -m \
  dimos.experimental.domestic_assistance.demo_dimos_simulation \
  recoger_ropa ropa-sim-001 --transport zenoh
```

Para la misión de bandeja:

```bash
.venv/bin/python -m \
  dimos.experimental.domestic_assistance.demo_dimos_simulation \
  preparar_bandeja bandeja-sim-001 --transport zenoh
```

Los journals quedan por defecto en
`/tmp/dimos-domestic-assistance/journals/` y los keyframes en
`/tmp/dimos-domestic-assistance/evidence/`. Un proceso nuevo debe usarse para
cada reset nominal, evitando reutilizar accidentalmente el mundo simbólico ya
modificado.

## 4. Validación realizada

Las pruebas automatizadas cubren:

- versión, hash y cobertura exacta de zonas;
- aceptación distinta de terminación;
- espera de costmap;
- cancelación sin declarar parada anticipadamente;
- sincronización y frescura postacción de odometría y cámara;
- estimación de parada por poses;
- escritura y hash de keyframes;
- recorrido nominal completo de las dos misiones;
- estado bimanual y relaciones anidadas;
- cierre y auditoría de journals con `Origin.SIMULATION`;
- consistencia de duraciones con un reloj real que avanza entre lecturas;
- registro actualizado de los Blueprints.

Los dos Blueprints se desplegaron en MuJoCo con seis módulos y conectaron
correctamente odometría, cámara, mapa, costmap, planificador, movimiento y RPCs.
Los smoke tests completos obtuvieron:

| Misión | Decisiones | Duración | Terminación | Auditoría |
|---|---:|---:|---|---|
| Recoger ropa | 18 | 42.997 s | `SUCCESS` | completa, 0 errores |
| Preparar bandeja | 19 | 111.981 s | `SUCCESS` | completa, 0 errores |

Las métricas offline aceptaron ambos journals: 2/2 episodios auditables, 37
decisiones y 0 intervenciones. El campo `autonomous_success=true` significa en
este contexto que no hubo intervención durante el pipeline simulado; no debe
presentarse como éxito autónomo de ACT, porque la manipulación fue simbólica.

## 5. Hallazgos objetivos

### Mejor de lo previsto

- El stack ligero existente de AlohaMini2 pudo reutilizarse sin crear otro
  simulador ni duplicar navegación.
- La misma validación y auditoría de las fases 0 y 1 funciona con datos y reloj
  de procesos reales.
- La separación entre misión semántica y mapa evitó introducir coordenadas en
  el espacio de decisiones que luego aprenderá el critic.

### Problemas encontrados y corregidos

- Sensores listos no implicaban costmap listo; ahora la navegación tolera esa
  preparación transitoria.
- `IDLE` puede ocurrir durante replanning; ya no se etiqueta falsamente como
  fallo terminal.
- `PoseStamped` no contiene velocidad; la parada se confirma con historial de
  pose más estado del planificador.
- El auditor comparaba duraciones obtenidas de lecturas distintas del reloj;
  inicio, fin y evento ahora comparten la misma muestra monotónica.
- Una imagen anterior a la acción podía acompañar odometría posterior; ahora
  todos los sensores requeridos deben ser posteriores.

### Límites que permanecen

- El escenario `office_lite` no contiene cesto, prendas, vajilla, bandeja ni
  superficie de cocina con geometría funcional. Sus relaciones son simbólicas.
- No se ha integrado ACT ni una interfaz real de manipulación/cancelación de
  brazos.
- No hay percepción visual de `IN`, `ON`, agarre o liberación.
- `NavigationInterfaceSpec` no distingue “replanning transitorio” de “fallo
  terminal”; por ahora el timeout es la decisión conservadora.
- LCM requiere configurar multicast loopback en este host; Zenoh permitió el
  despliegue, aunque las cámaras continúan usando el transporte JPEG-LCM fijado
  por el Blueprint de AlohaMini2.

## 6. Estado de salida y siguiente puerta

La implementación y los dos smoke tests de la Fase 2 quedan completos para su alcance:
navegación DimOS, interfaces, cancelación, observación, evidencia y registro se
integran sin afirmar resultados de manipulación. Antes de considerar completada
una campaña experimental de simulación conviene repetir ambos Blueprints con
varias semillas/layouts y medir tasa de éxito y timeouts de navegación; dos
rollouts nominales solo son una comprobación de integración.

La siguiente fase puede reemplazar únicamente el backend simbólico por ACT y
los hechos simbólicos por percepción, conservando `Action`, `Observation`,
`ExecutionResult`, `MissionRunner`, verificador, journal y métricas. Esa es la
propiedad principal que esta fase debía dejar preparada para el critic futuro
`Q(s,a)`, `V(s)` y `A(s,a)`.
