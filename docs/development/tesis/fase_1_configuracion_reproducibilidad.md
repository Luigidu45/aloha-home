---
title: "Fase 1: configuración y reproducibilidad"
---

**Estado: completada el 8 de septiembre de 2026.** Esta fase convierte las
configuraciones, reglas de verificación y métricas del núcleo doméstico en
artefactos explícitamente versionados y reproducibles.

## Objetivo

La tesis aprenderá Q(s,a), V(s) y A(s,a) desde rollouts y usará esa señal para
reranking y AWR/SFT. Ese aprendizaje solo es interpretable si una misma misión,
acción y etiqueta significan lo mismo entre sesiones y métodos. La Fase 1 evita
que diferencias de configuración o verificación se confundan con una mejora
del supervisor.

Esta fase no implementa todavía M0–M4 ni mejora habilidades físicas. Prepara la
base para comparar esos métodos bajo configuraciones congeladas.

## Implementación

### Configuraciones versionadas y carga conjunta

Los cuatro JSON activos declaran `config_schema_version: 1`. El módulo
[`configuration.py`](/dimos/experimental/domestic_assistance/configuration.py)
introduce `ConfigBundle` y `load_config_bundle()` para:

- exigir una versión explícita y soportada;
- cargar misión y escenario como una única unidad;
- validar ambos contratos y su correspondencia;
- calcular SHA-256 sobre los bytes exactos de cada archivo;
- devolver los hashes que debe conservar `ExperimentManifest`.

La demo dejó de cargar y hashear cada JSON por su cuenta. Así, futuros
blueprints, herramientas y tests pueden reutilizar una sola ruta de carga.

### Validación simbólica del escenario nominal

`Scenario.validate_mission()` ahora comprueba además:

- versión común con la misión;
- una colocación inicial única para cada objeto de la misión;
- ausencia de objetos iniciales extra o faltantes;
- coherencia de zona durante búsqueda, agarre y colocación;
- capacidad de una o dos pinzas según el objeto;
- presencia del destino móvil en la zona de colocación;
- traslado de objetos dependientes, como vaso y plato sobre la bandeja;
- ausencia de relaciones cíclicas;
- cumplimiento final de todas las metas;
- un `VERIFY` nominal explícito para cada meta.

Es una ejecución simbólica del guion, no una simulación física. No demuestra
alcanzabilidad, colisiones, estabilidad, percepción ni éxito de ACT.

### Fingerprint y registro de verificadores

`ObservedFactsVerifier` expone ahora nombre, versión y fingerprint SHA-256 de su
política declarada. `MissionRunner` exige que los tres coincidan con el
manifiesto antes de iniciar un episodio.

`VerifierRegistry` resuelve la implementación indicada por cada journal. El
auditor ya no está acoplado directamente a `DEFAULT_VERIFIER`: puede recibir un
registro que contenga versiones antiguas y reproducir el verificador declarado.
Los journals antiguos sin fingerprint continúan siendo resolubles por
nombre/versión; los episodios nuevos creados por el runner deben incluirlo.

El fingerprint complementa, pero no sustituye, el commit/hash del código. Una
campaña física debe congelar ambos.

### Métricas offline de solo lectura

[`metrics.py`](/dimos/experimental/domestic_assistance/metrics.py) deriva una
fila por episodio únicamente después de que `audit_episode()` lo considere
completo. Registra, entre otros:

- éxito de misión y éxito autónomo;
- validez experimental y asistencia;
- decisiones ejecutadas y precondiciones rechazadas;
- decisiones consecutivas repetidas;
- conteos de resultados del ejecutor y del verificador;
- duración, intervenciones, método, origen, escenario y split.

`aggregate_metrics()` calcula tasas solo sobre episodios auditables y no
excluidos. El análisis no modifica los JSONL originales.

Uso:

```bash
.venv/bin/python -m dimos.experimental.domestic_assistance.metrics \
  /ruta/a/rollouts/*.jsonl
```

Para conservar una salida derivada en un archivo distinto:

```bash
.venv/bin/python -m dimos.experimental.domestic_assistance.metrics \
  /ruta/a/rollouts/*.jsonl --output /ruta/a/metricas.json
```

El comando rechaza usar un journal de entrada como archivo de salida.

## Compatibilidad con la Fase 0

Añadir el campo explícito de versión cambió los bytes y, por tanto, los hashes
de los cuatro JSON. Los hashes golden se actualizaron de forma deliberada. La
referencia volvió a ejecutar las dos misiones y confirmó que no cambió su
comportamiento:

| Misión | Decisiones | Eventos | Resultado |
| --- | ---: | ---: | --- |
| `recoger_ropa` | 18 | 38 | Éxito autónomo |
| `preparar_bandeja` | 19 | 40 | Éxito autónomo |

Por ello se conserva `software-reference-v1`: cambió la representación
versionada, no la secuencia ni la semántica golden.

## Hallazgos y límites

La validación inicialmente prevista solo comprobaba duplicados y objetos
faltantes. Al implementarla se encontró que eso no detectaba planes imposibles,
por ejemplo `PLACE` sin `PICK`. Se añadió la ejecución simbólica porque ofrece
una garantía mayor con poco coste y sin acoplarse a drivers.

No se añadió todavía una métrica de “recuperación”. Contar cualquier fallo
seguido de un éxito sería ambiguo y podría sesgar la tesis. Esa métrica debe
definirse al introducir perturbaciones: qué evento inicia la recuperación, qué
acciones forman parte de ella y qué resultado la cierra.

Tampoco se añadió confianza perceptiva ni una nueva versión del journal. No eran
necesarias para cumplir esta fase y habrían ampliado el alcance prematuramente.

## Criterio de cierre

La fase se considera completa cuando:

- todos los configs activos tienen versión explícita;
- el cargador central produce hashes y rechaza versiones desconocidas;
- escenarios incompletos o incoherentes son rechazados;
- cada episodio nuevo congela el fingerprint del verificador;
- el auditor puede resolver verificadores por registro;
- las métricas se regeneran sin alterar journals;
- la referencia de Fase 0 y el paquete completo siguen pasando.

## Relación con la siguiente fase

La Fase 2 puede usar `ConfigBundle` para construir Blueprints de simulación,
traducir zonas semánticas a poses y producir episodios `Origin.SIMULATION`.
Debe reutilizar los mismos contratos, journal, registro de verificadores y
métricas; no crear un camino paralelo exclusivo de MuJoCo.
