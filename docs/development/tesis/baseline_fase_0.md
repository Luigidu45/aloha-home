---
title: "Fase 0: referencia congelada de asistencia doméstica"
---

**Estado: completada el 8 de septiembre de 2026.** Esta fase congela el
comportamiento observable del núcleo de asistencia doméstica antes de integrar
DimOS, ACT/SmolVLA, el supervisor VLM y el crítico Q/V.

## Objetivo

La referencia permite saber si un cambio posterior altera silenciosamente la
semántica experimental. No intenta mejorar la tasa de éxito y no es el método
M0 de la tesis. M0 será el supervisor VLM inicial con ejecutores físicos
congelados; esta referencia es exclusivamente una prueba de infraestructura con
`Origin.TEST`.

La contribución científica continúa siendo aprender Q(s,a), V(s) y A(s,a) a
nivel de skills desde rollouts reales, usar Q para reranking y usar la ventaja
para post-training AWR/SFT del VLM. Congelar la infraestructura protege esa
comparación: evita que una variante gane porque recibió otras reglas de
ejecución, verificación o etiquetado.

## Elementos congelados

El manifiesto
[`software_reference_v1.json`](/dimos/experimental/domestic_assistance/baselines/software_reference_v1.json)
registra:

- ID `domestic-assistance-software-reference-v1`;
- journal schema v2;
- verificador `observed-facts-v2` y fingerprint de su política;
- origen exclusivamente `test`;
- hashes SHA-256 de las dos misiones y sus escenarios nominales;
- número de decisiones y eventos esperado;
- secuencia de skills y predicados de verificación;
- éxito físico/autónomo esperado sin intervenciones.

No se congelan UUID, timestamps ni rutas temporales. Esos campos cambian entre
ejecuciones y fijarlos no protegería comportamiento relevante. En cada test se
genera un JSONL completo nuevo, se proyectan sus decisiones semánticas y se
comparan contra la referencia golden.

## Resultados de referencia

| Misión | Decisiones | Eventos JSONL | Resultado | Auditoría |
| --- | ---: | ---: | --- | --- |
| `recoger_ropa` | 18 | 38 | Éxito autónomo | Completa, sin errores |
| `preparar_bandeja` | 19 | 40 | Éxito autónomo | Completa, sin errores |

Cada decisión nominal debe tener despacho `EXECUTED`, resultado del ejecutor
`SUCCESS` y verificación `SUCCESS`. Además, los predicados deben corresponder a
llegada y parada, búsqueda, agarre o relación espacial según la acción.

## Invariantes protegidas

| ID | Invariante | Evidencia automatizada |
| --- | --- | --- |
| I-01 | Solo se despacha una acción cuando el ejecutor está detenido. | Tests de ciclo nominal y cancelación. |
| I-02 | Un rechazo de precondición no se registra como fallo del ejecutor. | `test_precondition_rejection_is_not_logged_as_executor_failure`. |
| I-03 | El éxito del ejecutor no sustituye la verificación semántica. | `test_executor_success_without_grasp_evidence_becomes_unknown`. |
| I-04 | La verificación espera una observación posterior a la ejecución. | `test_runner_waits_for_a_new_post_action_observation` y auditoría. |
| I-05 | Un timeout confirma parada antes de un nuevo despacho. | `test_timeout_confirms_stop_before_retry`. |
| I-06 | Si la parada no se confirma no se vuelve a despachar. | `test_unconfirmed_cancellation_never_dispatches_again`. |
| I-07 | Evidencia de prueba no puede presentarse como física. | Tests de origen del runner y buffer. |
| I-08 | La observación representa exactamente las dos pinzas sin contradicciones. | Tests de contratos y ejecutor bimanual. |
| I-09 | Ayuda humana conserva éxito físico, pero elimina éxito autónomo. | `test_human_intervention_preserves_success_but_removes_autonomous_label`. |
| I-10 | Un `SUCCESS` terminal exige todas las metas verificadas. | Golden rollouts y `test_auditor_rejects_fabricated_terminal_success`. |
| I-11 | El contexto del supervisor reproduce todo el historial anterior. | `audit_episode`. |
| I-12 | Fallos y episodios truncados permanecen detectables. | Tests de journal y auditoría. |

El archivo
[`test_baseline.py`](/dimos/experimental/domestic_assistance/test_baseline.py)
añade tres pruebas herméticas: una para versiones/hashes y una ejecución golden
por misión.

## Uso durante las fases siguientes

Ejecutar primero la referencia:

```bash
.venv/bin/pytest \
  dimos/experimental/domestic_assistance/test_baseline.py -q
```

Después ejecutar todo el paquete:

```bash
.venv/bin/pytest dimos/experimental/domestic_assistance -q
```

Un fallo de baseline no significa automáticamente que el cambio sea incorrecto.
Significa que modificó una referencia congelada y exige una decisión explícita:

1. si es una regresión, corregir el código;
2. si es un cambio compatible, conservar la referencia y añadir cobertura;
3. si cambia intencionalmente la semántica, crear `software_reference_v2.json`,
   documentar la razón y mantener la capacidad de auditar v1 cuando corresponda.

No se debe actualizar el resultado esperado únicamente para conseguir que el
test vuelva a pasar.

## Alcance de la garantía

La fase demuestra que las dos misiones nominales conservan una semántica
estable y auditable en el ejecutor determinista. No prueba navegación, dinámica,
percepción, ACT/SmolVLA, VLM, Q/V ni operación física. Es una protección para
construir esas capas sin perder las garantías ya alcanzadas.
