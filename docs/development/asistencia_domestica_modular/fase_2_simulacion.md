---
title: "F2: navegación semántica y observaciones en una vivienda simulada"
---

> Actualización posterior: por petición del usuario se adelantó la [adaptación del AM-ARM200 original](/docs/development/asistencia_domestica_modular/adaptacion_am_arm200.md). Los blueprints de navegación y doméstico usan ahora ese modelo. Los resultados históricos de esta fase conservan su procedencia y fecha; los nuevos ensayos se registran por separado.


# Cierre de F2

**Estado:** completada el 13 de septiembre de 2026, sobre el commit de partida `dbe6fe27a0952d2988cef5b08ebb7bb124780be2`. El usuario confirmó utilizar una vivienda sintética. El [plan de trabajo](/docs/development/asistencia_domestica_modular/plan_trabajo.md) y los [contratos de F1](/docs/development/asistencia_domestica_modular/fase_1_definicion.md) siguen siendo la referencia.

El robot simulado recorre las estaciones de sala y dormitorio utilizando el stack de DimOS, confirma llegada y parada con poses recientes, y permite recuperar imágenes y nubes posteriores a la llegada. Se comprobaron cancelación durante movimiento y destino inaccesible con el paso cerrado. Este cierre acredita integración espacial en simulación; la manipulación, percepción del objeto y navegación física corresponden a fases posteriores.

## Escena y configuración

La [escena principal](/dimos/robot/alohamini2/assets/household_navigation.xml) tiene dos zonas separadas por una pared con un paso de 2,4 m: sala al oeste y dormitorio al este, dentro de un recinto de 8 × 6 m. Hay mesa de recogida, botella, control remoto en el suelo, mesa de entrega con región coloreada y una cama. La [variante bloqueada](/dimos/robot/alohamini2/assets/household_navigation_blocked.xml) cierra el paso. Son primitivas sintéticas y objetos fijos; no se han simulado agarres ni movimientos del objeto.

Las estaciones están en [spatial_sim.json](/dimos/experimental/household_assistant/configs/spatial_sim.json), separadas de las geometrías físicas aún desconocidas de `pilot.json`. Sus identificadores coinciden exactamente con F1. Coordenadas en metros y yaw en radianes respecto de `world`:

| Lugar | Base para observar (x, y, yaw) | Base para aproximación de manipulación (x, y, yaw) | Superficie |
| --- | --- | --- | --- |
| `mesa_sala` | −2,5; 0,5; π/2 | −2,5; 0,65; π/2 | 0,75 m |
| `mesa_dormitorio` | 2,5; 0,5; π/2 | 2,5; 0,65; π/2 | 0,75 m |
| `suelo_sala` | −3,2; −1,2; π/2 | −3,2; −0,65; π/2 | 0 m |

La tolerancia de observación es 0,25 m y 0,4 rad. Se eligió considerando que el controlador local existente termina su rotación dentro de 0,35 rad; no es precisión de manipulación. Las aproximaciones de manipulación reservan tolerancias menores, declaradas en la configuración, que necesitan alineación posterior y no se acreditan con este ensayo. La pose de `suelo_sala` está registrada para preparar B, pero el recorrido de aceptación de F2 cubre las dos mesas.

El elevador permanece fijo en el modelo conservado; `lift_height_m: null` significa que aún no existe una altura de elevador calibrada o comandable. La altura prevista de las superficies sí está fijada para la escena. Las poses de aproximación no demuestran alcance del brazo ni habilitan ACT. Tampoco se ha añadido un objeto a la pinza o validado `loaded_home`.

## Componentes y flujo

El [blueprint household-navigation-sim](/dimos/robot/alohamini2/blueprints/household_navigation_sim.py) compone seis módulos:

1. `AlohaMini2SimModule`: física holonómica y sensores sintéticos.
2. `VoxelGridMapper`: acumulación de las nubes observadas.
3. `CostMapper`: mapa de costos a partir de esa acumulación.
4. `ReplanningAStarPlanner`: planificación y comandos de navegación.
5. `MovementManager`: envío de velocidad a la base.
6. `HouseholdSpatialModule`: destinos semánticos, estado comprobado y observaciones recientes.

Se amplió la función pública de [composición AlohaMini2](/dimos/robot/alohamini2/blueprints/alohamini2_nav_sim.py) para elegir escena y posición inicial conservando el perfil ligero. Los blueprints previos mantienen sus configuraciones. El registro se regeneró con la prueba oficial; se añadieron el blueprint y el módulo espacial.

El [adaptador espacial](/dimos/experimental/household_assistant/spatial_module.py) llama al planificador mediante `NavigationInterfaceSpec`. `go_to(place_id, purpose)` admite únicamente lugares registrados y localización reciente; devuelve la solicitud en marcha. Mientras haya navegación, parada pendiente o parada sin confirmar, rechaza otra solicitud. No interpreta lenguaje natural.

Una llegada requiere señal del planificador, posición y orientación dentro de las tolerancias, y una ventana de poses posteriores a la orden de parada con movimiento inferior a los umbrales configurados. No basta con `is_goal_reached()`. Se rechazan muestras repetidas o desordenadas, relojes futuros, poses antiguas y frames distintos de `world`. La parada se estima mediante cambios de pose; no es una lectura de velocidad de ruedas.

`cancel()` pasa a `stopping`; el estado `cancelled` aparece tras comprobar la parada. Si falta evidencia, queda `stop_unconfirmed` y bloquea nuevos objetivos. El timeout de navegación ordena parar y termina como `failed` una vez confirmada la detención. Su motivo `navigation_timeout_or_blocked` no pretende diagnosticar por sí solo qué obstáculo existe. La cancelación aquí afecta a la base; no hay políticas de brazos/elevador en ejecución.

`get_observation(place_id)` devuelve un `SpatialSnapshot` solo si la base sigue detenida en la estación y hay imagen y nube recientes, ambas posteriores a la llegada. El snapshot conserva datos, tiempos, frames y evidencia de cada componente. No incorpora nombres ni posiciones exactas de objetos extraídos del simulador. F3 deberá interpretar las imágenes.

## Streams, marcos y procedencia

| Nombre lógico | Tipo y frame | Procedencia / uso |
| --- | --- | --- |
| `/odom` | `PoseStamped`, `world` | Pose exacta de la base de MuJoCo, etiquetada como `mujoco_ground_truth`; sustituye localización física en este piloto. |
| `/front_camera_image` | `Image`, `front_camera_color_optical_frame` | RGB sintético que recibe el adaptador; 256 × 144, perfil de 2 FPS. |
| `/back_camera_image`, `/chest_camera_image`, `/left_camera_image`, `/right_camera_image` | `Image`, frame óptico de cada cámara | Vistas adicionales del modelo conservado. |
| `/camera_info` | `CameraInfo`, frame óptico frontal | Intrínsecos de la cámara simulada; no son calibración de D435i. |
| `/pointcloud` | `PointCloud2`, `world` | Combinación de cuatro cámaras de raycast; no es un driver del L2. |
| `/global_map`, `/global_costmap`, `/path` | Nube, ocupación y trayectoria en `world` | Resultados del stack de mapeo y planificación. |
| `/nav_cmd_vel`, `/cmd_vel` | `Twist`, convención de `base_link` | Velocidad de cuerpo: +X adelante, +Y izquierda, +Z angular antihorario. |
| `/spatial_status` | `SpatialStatus`, pose en `world` | Solicitud, destino, propósito, estado, motivo y tiempo comprobado. |

Estos son nombres lógicos; Zenoh aplica el prefijo y la codificación de tipos de DimOS. El estado consumible de F2 es `/spatial_status`: el stream `navigation_state` del planificador existente sigue sin implementar su publicación.

Los tiempos usan el reloj Unix del host. El tiempo de física de MuJoCo puede avanzar más lentamente que el reloj del host; estos ensayos no miden rendimiento del hardware futuro. La [publicación RGB](/dimos/robot/alohamini2/sim_module.py) ahora conserva el instante de captura del frame en lugar de renovarlo al publicar. La [nube combinada](/dimos/simulation/engines/mujoco_sim_module.py) usa el instante de la captura más antigua que contribuye, evitando que un raycast nuevo rejuvenezca puntos viejos. No es una nube con tiempos por punto.

La localización simulada es una dependencia explícita del piloto. Los nombres y transformaciones de objetos de la escena permanecen fuera del adaptador y del snapshot. Las posiciones de estaciones son configuración conocida, como sería un punto previamente registrado en un mapa; no constituyen detección visual del objeto.

## Reproducción y uso

Desde la raíz del repositorio, con `.venv` y dependencias disponibles. En este equipo se usaron MuJoCo 3.5.0, Zenoh y GLFW bajo Xvfb. LCM intentó configurar multicast mediante `sudo`, y OSMesa falló al crear el framebuffer. Se empleó el backend Zenoh existente y una pantalla virtual, sin modificar la red del sistema.

Para repetir el recorrido y generar una grabación nueva: `MUJOCO_GL=glfw xvfb-run -a .venv/bin/python -m dimos.experimental.household_assistant.demo_spatial`. Para el paso bloqueado, añadir `--blocked`. Se puede indicar `--output` con un directorio nuevo; por defecto se utiliza el directorio de grabaciones de DimOS con un identificador temporal. El ejecutor cierra coordinador, trabajadores y simulador aun si falla una aserción.

El [ensayo reproducible](/dimos/experimental/household_assistant/demo_spatial.py) espera un mapa de costos real antes de navegar, visita ambas mesas, guarda snapshots y cancela el regreso después de observar desplazamiento. El caso bloqueado carga la otra escena y usa un timeout de 15 segundos; el recorrido normal dispone de 90 segundos por objetivo. Para este entorno, el ensayo limita el mapa a 100 000 bloques; esto es un ajuste de recursos del ensayo, no un mapa construido a partir de la geometría exacta de los objetos.

Con escritorio gráfico activo, iniciar manualmente con `.venv/bin/dimos --transport zenoh run household-navigation-sim`. Este blueprint abre la ventana nativa de MuJoCo según el ajuste `viewer`; no incorpora todavía la interfaz asistencial ni Rerun. Desde otra terminal, `.venv/bin/dimos --transport zenoh shell` permite usar `app.HouseholdSpatialModule.go_to("mesa_sala")`, consultar `app.HouseholdSpatialModule.get_status()` y cancelar mediante `app.HouseholdSpatialModule.cancel()`. La shell usa los RPC de DimOS y no necesita un servidor MCP. No ejecutar dos coordinadores sobre los mismos topics.

Las grabaciones de aceptación quedaron localmente en `.ignore.f2/route_final/` y `.ignore.f2/blocked_01/`. Cada una contiene `report.json` y `trajectory.jsonl`; el recorrido añade imágenes PNG y arrays RGB/nube NPZ por estación. Los binarios se mantienen fuera de Git. El [manifiesto versionable](/docs/development/asistencia_domestica_modular/fase_2_validacion.json) conserva resultados, rutas, versiones y hashes de entradas y arrays. Los logs de ejecución de esta sesión están en `/tmp/household_f2_route_final.log` y `/tmp/household_f2_blocked_01.log`.

La [lectura offline](/dimos/experimental/household_assistant/replay_spatial.py) verifica hashes y conserva timestamps originales. Reproducir los snapshots guardados: `.venv/bin/python -m dimos.experimental.household_assistant.replay_spatial .ignore.f2/route_final`. No se publican sobre el bus del robot ni se convierten en observaciones actuales. Para repetir el movimiento, se ejecuta otra vez el ensayo en la escena, sin reposicionar artificialmente la base entre estaciones.

## Evidencia de cierre

| Comprobación | Resultado registrado |
| --- | --- |
| Llegada a mesa de sala | `arrived`, pose dentro de tolerancias y parada confirmada. |
| Llegada a mesa de dormitorio | `arrived`, pose dentro de tolerancias y parada confirmada. |
| Observación en cada estación | Dos imágenes RGB completas con sus nubes: 1566 y 1581 puntos. Antigüedad RGB al recuperar: 0,154 y 0,435 s; nube: 0,094 y 0,355 s. |
| Cancelación durante regreso | `stopping` → `cancelled` en aproximadamente 0,580 s; desplazamiento posterior observado de 0 m durante un segundo. |
| Paso cerrado | `failed` después del timeout y de confirmar parada; permaneció del lado de la sala. |
| Grabación y lectura offline | 440 muestras de estado/pose en el recorrido; dos snapshots recuperados con sus hashes y tiempos originales. |

Son ensayos de integración, no una estimación estadística de autonomía. Durante la preparación se registró una llegada inválida del planificador al quedar cerca del destino pero bloqueado por el control en la trayectoria; el adaptador rechazó ese resultado. La escena final separa el control de la ruta principal. También se ajustaron la vista de observación y su tolerancia angular al campo de visión y al controlador existente. Las tolerancias más estrictas de manipulación siguen reservadas para alineación posterior.

Validación de código:

- **63 pruebas rápidas aprobadas**, incluidas F1, 13 de reglas espaciales, dos de grabación y regresiones de timestamps. Comando: `.venv/bin/python -m pytest -p no:launch_pytest dimos/experimental/household_assistant dimos/robot/alohamini2/blueprints/test_alohamini2_nav_sim.py dimos/robot/alohamini2/blueprints/test_household_navigation_sim.py dimos/robot/alohamini2/test_sim_module.py dimos/simulation/engines/test_mujoco_sim_module.py -q --tb=short`.
- **12 comprobaciones de MuJoCo aprobadas**: diez del modelo/driver conservado y dos de las escenas nuevas. Ejecutar explícitamente con `MUJOCO_GL=glfw xvfb-run -a .venv/bin/python -m pytest -p no:launch_pytest -m mujoco dimos/robot/alohamini2/test_sim_module.py dimos/robot/alohamini2/blueprints/test_household_navigation_sim.py -q --tb=short`. Las dos pruebas nuevas corrigieron el prefijo `/` que MuJoCo añade a las cámaras al componer modelos y se repitieron satisfactoriamente.
- **Una comprobación del registro aprobada**: `CI=1 .venv/bin/python -m pytest -p no:launch_pytest dimos/robot/test_all_blueprints_generation.py -q --tb=short`. La generación previa avisó del cambio sin commit, como está previsto en F0.
- Ruff y formato correctos; mypy sin incidencias en once archivos de implementación revisados. Enlaces comprobados con `doclinks`.

El plugin ROS `launch_pytest` se desactiva como en F1 por su dependencia ausente `lark`; los ensayos no utilizan ROS. Los marcadores excluidos por la suite rápida no se presentan como aprobados por esa suite.

## Preparación del modelo AM-ARM200

Se revisó la disponibilidad local: existe el modelo SO101 conservado y `/home/luigidu/Downloads/alohamini2pro.urdf`, identificado internamente como `alohamini2pro_urdf` (SHA-256 `bd1b1e6d619d3160fcf1f7faa27a564f933128dc7d729ef87d6e170818389844`). En la revisión de F2 no se había localizado el URDF original entre los archivos entonces suministrados. **Actualización F3:** la nueva ruta del usuario sí contiene `alohamini2_urdf` y sus meshes; el [inventario del original](/docs/development/asistencia_domestica_modular/fase_3_urdf_original.json) registra hashes y problemas de rutas/límites. La correspondencia física con SDK/equipo continúa pendiente.

El archivo Pro contiene seis articulaciones rotacionales por brazo y una articulación de pinza, mientras el SO101 articulado conservado usa cinco más pinza. La semejanza de nombres no acredita correspondencia con el SDK ni límites del equipo original. No se importó el Pro como sustituto del robot elegido.

Antes de F7/F8, preparar la adaptación en `dimos/robot/alohamini2/` con estas comprobaciones:

1. URDF y meshes originales disponibles desde F3; verificar versión/licencia y contrastar su cinemática y límites con el robot recibido.
2. Crear la correspondencia por brazo entre articulaciones del modelo, IDs/orden del SDK, unidades, signos, cero y límites. Mantener las pinzas y el elevador como interfaces explícitas.
3. Verificar árbol de transforms, frames de herramienta y montajes de cámaras/L2; separar piezas fijas de las que se mueven con el elevador.
4. Comprobar FK en poses medidas y colisiones; no copiar el vector home ni el número de acciones de SO101. Si se incorpora una variante AM-ARM200, declararla por separado en la configuración de manipulación existente.
5. Medir alcance a ambas mesas y al suelo, luego validar trayectoria y retención de `loaded_home` con carga.
6. Solo después vincular unidades, límites y cámaras a teleoperación/ACT. Esta adaptación detallada no es requisito para repetir la navegación de F2.

Los pendientes físicos se mantienen en la [ficha de hardware](/docs/development/asistencia_domestica_modular/fase_1_hardware.md). La [F3 ya implementada](/docs/development/asistencia_domestica_modular/fase_3_memoria_percepcion.md) consume estas observaciones sin acceder al estado interno de objetos del simulador y precisa la diferencia entre estaciones etiquetadas y búsqueda semántica por memoria.
