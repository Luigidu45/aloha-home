---
title: "F0 completada: retirada del proyecto anterior y referencia del entorno"
---

# F0 — Limpieza y punto de partida

**Fecha:** 12 de septiembre de 2026. **Estado:** completada según los criterios del [plan de trabajo](/docs/development/asistencia_domestica_modular/plan_trabajo.md).

Se retiró el proyecto anterior para iniciar la tesis de asistencia doméstica modular con un alcance independiente. La fase entrega limpieza, consistencia del registro y una referencia del entorno; no implementa todavía el nuevo asistente.

## Punto de partida

La rama de trabajo era `feat/aloha-home`, con HEAD `cada8ed7b43bcfd3f566ce4c10ece5053fccc56d`. El árbol de trabajo estaba limpio al iniciar F0. Los borrados de documentación anteriores ya formaban parte de esta referencia; no se restauraron archivos históricos.

El [manifiesto del entorno](/docs/development/asistencia_domestica_modular/fase_0_entorno.json) registra versiones instaladas, plataforma, hashes de `pyproject.toml`, `uv.lock` y el registro resultante. Las dependencias y el lockfile permanecieron iguales. El manifiesto identifica el commit base más los cambios de esta fase; no pretende identificar un nuevo commit ya publicado.

## Cambios realizados

| Elemento | Resultado |
| --- | --- |
| `dimos/experimental/domestic_assistance/` | Eliminados sus 32 archivos versionados: implementación, pruebas, configuraciones y referencia artificial. Retirado también el directorio local. |
| `dimos/robot/alohamini2/blueprints/alohamini2_domestic_sim.py` | Retirado el único consumidor externo de ese paquete encontrado en el código. |
| [Registro generado](/dimos/robot/all_blueprints.py) | Regenerado mediante el test oficial; su diff contiene únicamente tres entradas eliminadas. |
| [Plan de trabajo](/docs/development/asistencia_domestica_modular/plan_trabajo.md) | F0 marcada como completada y primer criterio de H1 actualizado. |

Entradas retiradas: `alohamini2-domestic-clothes-sim`, `alohamini2-domestic-tray-sim` y `domestic-assistance-simulation-module`. El registro resultante contiene 145 blueprints y 137 módulos.

Se conservaron `alohamini2-nav-sim`, `alohamini2-nav-sim-full` y `alohamini2-nav-manip-sim`. Se comprobó que el único cambio bajo `dimos/robot/alohamini2/` es la eliminación del blueprint doméstico antiguo: código de navegación, sensores simulados, recursos, configuración, control y pruebas conservados no tienen modificaciones.

## Verificaciones y reproducción

Los comandos se ejecutaron desde la raíz del repositorio usando `.venv/bin/python`. No se añadieron pruebas que repitan el registro; se utilizaron las comprobaciones existentes de generación, resolución, extensiones y AlohaMini2.

| Comprobación | Resultado |
| --- | --- |
| Regeneración oficial | Escribió el registro esperado. El test local terminó con el aviso previsto de cambios sin commit. |
| Consistencia en modo CI, descubrimiento y configuración de blueprints | 48 pruebas aprobadas. |
| Carga de los tres blueprints AlohaMini2 y control básico | 6 pruebas aprobadas; 153 casos deseleccionados por los filtros. |
| Búsqueda de referencias antiguas en `dimos/` | Sin coincidencias para paquete, blueprint y nombres de registro retirados. |
| Integridad del stack conservado | Tres nombres AlohaMini2 presentes; ninguna modificación adicional bajo la plataforma. |

La regeneración se ejecutó con `.venv/bin/python -m pytest -p no:launch_pytest dimos/robot/test_all_blueprints_generation.py -q`. El aviso «all_blueprints.py was updated and has uncommitted changes» corresponde al comportamiento del generador local, no a un registro inconsistente. Se revisó el diff y después se validó sin escribir en modo CI.

La primera comprobación aprobada fue `CI=1 .venv/bin/python -m pytest -p no:launch_pytest dimos/robot/test_all_blueprints_generation.py dimos/robot/test_get_all_blueprints.py dimos/robot/test_external_blueprints.py dimos/robot/alohamini2/blueprints/test_alohamini2_nav_sim.py -q --tb=short`: **48 passed**, 8,16 segundos reportados por pytest.

La segunda comprobación fue `.venv/bin/python -m pytest -p no:launch_pytest dimos/robot/test_all_blueprints.py dimos/robot/alohamini2/test_sim_module.py -k 'alohamini2 or command_buffer or body_velocity or navigation_mjcf or wrist_camera or so101_arms or office_scene or lite_scene or navigation_cameras or planar_driver' -q --tb=short`: **6 passed, 153 deselected**, 3,41 segundos. Los seis casos ejecutados fueron carga de los tres blueprints, límites de velocidad, watchdog de comandos y transformación de velocidad según orientación.

Los filtros por marcadores configurados en el repositorio permanecieron activos. Por ello este resultado no acredita los casos de simulación dinámica deseleccionados ni una ejecución completa del robot en MuJoCo. Tampoco acredita hardware físico.

Para buscar referencias se utilizó `rg -n 'domestic_assistance|alohamini2_domestic|alohamini2-domestic|domestic-assistance-simulation' dimos`. Su código de salida 1, sin texto, indica ausencia de coincidencias. Las menciones históricas en este documento y en el plan son deliberadas.

## Particularidades del entorno

- El primer intento de pytest falló antes de recoger pruebas: la carga automática de `launch_pytest`, procedente de ROS Jazzy, requería `lark`, ausente en el entorno. Se excluyó únicamente ese plugin con `-p no:launch_pytest`, sin cambiar dependencias ni configuración del proyecto.
- El siguiente intento encontró un bloqueo del sandbox al abrir el socket local de `pytest-rerunfailures`. Las ejecuciones posteriores se hicieron fuera del sandbox con autorización; no se modificaron las pruebas para sortear la restricción.
- Pytest emitió un `ResourceWarning` de un subproceso durante su arranque; las dos comprobaciones finales terminaron con código 0. No se investigó ese aviso ajeno al alcance de la limpieza.
- Python es 3.12.3, pytest 8.3.5 y MuJoCo 3.5.0. LeRobot no está instalado en esta referencia; su preparación sigue perteneciendo a F7. La lista completa de dependencias seleccionadas y sus versiones está en el manifiesto.

## Cierre y siguiente fase

F0 satisface sus criterios: paquete descartado retirado, referencias de ejecución eliminadas, registro consistente y comprobaciones focalizadas del stack conservado aprobadas. Los cambios quedan disponibles para revisión local.

El siguiente paso es F1: fijar la misión, el catálogo mínimo, los contratos y los criterios de éxito de la tesis actual. Las pruebas y resultados eliminados no se usarán como evidencia de las fases nuevas.
