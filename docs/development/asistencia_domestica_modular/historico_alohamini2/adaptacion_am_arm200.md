---
title: "Adaptación adelantada del AlohaMini2 original con AM-ARM200"
---

# Resultado

Se adelantó la adaptación que estaba reservada para F7/F8 por petición del usuario. La simulación doméstica ahora utiliza el **AlohaMini2 original con dos brazos AM-ARM200 articulados**, sus pinzas y el elevador. El modelo anterior SO101 deja de ser el robot de los blueprints de navegación por defecto y del asistente doméstico.

El modelo portable (`dimos/robot/alohamini2/assets/am_arm200/robot.xml`, ruta histórica) deriva del URDF suministrado en `/home/luigidu/AlohaMini/AlohaMini2/urdf/alohamini2/urdf/alohamini2.urdf`. Se conservan sus articulaciones, ejes, transformaciones, masas e inercias. Los meshes se simplifican para ejecutar en CPU. La procedencia, hashes, orden de actuadores y supuestos están en el manifiesto (`dimos/robot/alohamini2/assets/am_arm200/manifest.json`, ruta histórica) y el README del modelo (`dimos/robot/alohamini2/assets/am_arm200/README.md`, ruta histórica).

## Qué comandos usan el original

| Blueprint | Modelo actual |
| --- | --- |
| `household-navigation-sim` | Original AM-ARM200, vivienda sintética, estaciones y monitor de llegada/parada. |
| `alohamini2-nav-sim` | Original AM-ARM200, oficina ligera y visualización de navegación. |
| `alohamini2-nav-sim-full` | Original AM-ARM200, oficina completa y sensores de mayor resolución. |
| `alohamini2-nav-manip-sim` | **Perfil legado SO101**, conservado para no aplicar sus IK/planificadores/controles de cinco ejes a los AM-ARM200. No usarlo como validación del original. |

La composición de navegación selecciona el nuevo MJCF y configura `arm_model="am_arm200"`, `dof=15` y altura de base de 0,005 m. El driver rechaza mezclar este modo con la configuración SO101. El blueprint doméstico hereda esta selección. Las imágenes incluyen la geometría de los brazos originales; ya no se omite el grupo de visuales CAD en los sensores de este modelo.

Con escritorio gráfico: `.venv/bin/dimos --transport zenoh run household-navigation-sim`. Desde otra terminal, `.venv/bin/dimos --transport zenoh shell` permite usar los RPC habituales de navegación y los nuevos de articulación.

## Control articular de simulación

AlohaMini2SimModule (`dimos/robot/alohamini2/sim_module.py`, ruta histórica) expone `get_sim_joint_state()` y `set_sim_joint_positions(...)`. Son RPC de depuración, no habilidades de agarre ni control de hardware. El comando exige las 15 articulaciones, valores finitos y límites del modelo; no comprueba una trayectoria libre de colisiones.

En `dimos shell`, obtener `q = app.AlohaMini2SimModule.get_sim_joint_state()`. Sus claves proceden de MuJoCo y pueden llevar el prefijo `/`; utilizar las claves devueltas. Para un pequeño ensayo del elevador, asignar `q[next(k for k in q if k.lstrip('/') == 'vertical_move')] = 0.05` y enviar `app.AlohaMini2SimModule.set_sim_joint_positions(q)`. Leer de nuevo el estado para comprobar el movimiento. `app.AlohaMini2SimModule.reset()` restablece la simulación a la referencia inicial, incluida la pose de base; no equivale a ejecutar una trayectoria home.

Orden del vector completo: `vertical_move`, después los siete joints `left_*` y luego los siete `right_*`, en el orden del manifiesto. Cada brazo incluye `shoulder_pan`, `shoulder_lift`, `elbow_flex`, `wrist_flex`, `wrist_yaw_joint`, `wrist_roll` y `gripper`. El elevador usa metros; brazos y pinzas usan radianes. No se heredan el orden ni los límites de SO101.

La postura cero del URDF es la referencia inicial de simulación. El retorno con botella en pinza (`loaded_home`), el TCP y los límites físicos continúan pendientes. No se ha entrenado ACT ni trasladado la configuración RoboPlan/Pink de SO101 al original.

## Comprobaciones y reproducción

La prueba del modelo (`dimos/robot/alohamini2/test_am_arm200.py`, ruta histórica) compara la cinemática directa de todas las piezas contra una lectura independiente del URDF en tres configuraciones. Comprueba 15 actuadores, ausencia de penetraciones entre piezas en la referencia, movimiento de muñecas/pinzas/elevador mediante los actuadores y rechazo de comandos incompletos, no finitos o fuera de límites.

El ensayo de articulación (`dimos/robot/alohamini2/demo_am_arm200.py`, ruta histórica) renderiza el robot y sus cinco cámaras, inicia una instancia de DimOS, mueve ambas muñecas, ambas pinzas y el elevador mediante RPC, comprueba el feedback y verifica reset. Repetir con `MUJOCO_GL=glfw xvfb-run -a .venv/bin/python -m dimos.robot.alohamini2.demo_am_arm200 .ignore.am_arm200/articulacion_nueva`, usando un directorio nuevo.

El [ensayo doméstico](/dimos/experimental/household_assistant/demo_spatial.py) ahora registra el identificador del modelo original y hashes del nuevo MJCF/manifiesto. Se comprobó llegada a sala, llegada a dormitorio, imágenes/nubes, cancelación y parada posterior. También se comprobó el paso cerrado. Repetir con `MUJOCO_GL=glfw xvfb-run -a .venv/bin/python -m dimos.experimental.household_assistant.demo_spatial --output .ignore.am_arm200/recorrido_nuevo`; añadir `--blocked` para el fallo de ruta.

Los artefactos de aceptación y conteos exactos se recogen en [adaptacion_am_arm200_validacion.json](/docs/development/asistencia_domestica_modular/historico_alohamini2/adaptacion_am_arm200_validacion.json). Las grabaciones históricas de F2/F3 permanecen identificadas como ensayos anteriores; no se presentan como resultados del nuevo robot.

La envolvente CAD en la referencia tiene aproximadamente 0,532 m de ancho y un radio horizontal máximo de 0,451 m. Cabe dentro de la anchura de planificación de 0,58 m y el diámetro de giro de 0,95 m ya configurados. Esta comprobación solo vale para la postura de referencia: mover brazos o transportar una carga puede cambiar la huella y requiere supervisión posterior.

## Qué permanece sin validar físicamente

Las dinámicas del patín/base, fuerzas y ganancias de servos y colisiones convexas son aproximaciones. Los límites angulares amplios del URDF no se han certificado contra el SDK ni el robot. Las pruebas de colisión de referencia no acreditan todo el espacio de movimientos.

Las cámaras usan los links originales y parámetros ópticos de simulación. La ubicación del L2, extrínsecos/intrínsecos de D435i y cámaras de muñeca, alcance al suelo y a mesas, retención en pinza y `loaded_home` deben contrastarse con el equipo real. Los sensores aproximados de navegación permiten continuar el desarrollo, pero no constituyen una reproducción calibrada del hardware elegido.
