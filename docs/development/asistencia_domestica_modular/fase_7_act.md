---
title: "F7: preparación ACT, captura y adaptación física"
---

# F7: pipeline ACT antes del robot

**Fecha: 22/09/2026. Estado: preparación de software completada con datos artificiales; ejecución física bloqueada.** Se comprobó captura/exportación → lectura LeRobot → optimización ACT reducida en CPU → guardado/carga de checkpoint → inferencia desde DimOS → receptor sin actuadores. Las pruebas no entrenaron un agarre ni una colocación físicos.

## Decisiones confirmadas y cambio de brazos

El usuario confirmó dos políticas iniciales independientes, recogida de botella y colocación sobre mesa; brazo derecho por defecto; tres cámaras activas y registradas (`top_rgb`, `right_wrist_rgb`, `left_wrist_rgb`); dos maestros SO101 para teleoperar y dos seguidores SO101 de **7,4 V** montados sobre la base/elevador del AlohaMini1. No hay GPU disponible todavía. La ampliación bimanual necesita otro perfil, demostraciones y validación; no se habilita cambiando un nombre de brazo.

El SO101 estándar tiene **seis motores por brazo, incluida la pinza**. La cifra siete del BOM oficial cuenta una referencia de motor dentro del conjunto maestro–seguidor. Las fuentes oficiales describen los cinco ejes del brazo y el eje de pinza, y sus relaciones de reducción: [TheRobotStudio](https://github.com/TheRobotStudio/SO-ARM100#parts-for-one-follower-arm), [guía SO101 de LeRobot](https://huggingface.co/docs/lerobot/so101).

Esto sustituye el BOM antiguo de brazos SO100/STS3215 de 12 V de AlohaMini1; no sustituye el BOM de base/elevador. **7,4 V identifica la variante del servo**, no una autorización para reutilizar la alimentación de 12 V de la base ni una especificación medida de la fuente final.

El simulador conserva por ahora la geometría CAD original del AlohaMini1 y sus brazos bloqueados. No se ha integrado una geometría SO101 nueva ni se han medido los montajes. El antiguo `right_joint6` no se identifica automáticamente con la pinza SO101. La [ficha actualizada](/docs/development/asistencia_domestica_modular/fase_1_hardware.md) y la [plantilla física](/dimos/experimental/household_assistant/configs/act_hardware_pending.json) separan hechos, propuesta de interfaz y mediciones pendientes.

## Entregables

| Elemento | Archivo y alcance |
| --- | --- |
| Perfil de observación/acción | [act_contracts.py](/dimos/experimental/household_assistant/act_contracts.py): dimensiones, orden, procedencia, tres cámaras, tiempos, límites artificiales y huella del perfil. |
| Perfiles iniciales | [Recogida](/dimos/experimental/household_assistant/configs/act_act_pick_table.json), [colocación](/dimos/experimental/household_assistant/configs/act_act_place.json); ambos explícitamente artificiales, no calibraciones motoras. |
| Ruta principal de datos | [act_lerobot.py](/dimos/experimental/household_assistant/act_lerobot.py): `LeRobotDataset` oficial, manifest de sesiones, descarte de episodios, normalización y entrenamiento ACT. No hay un segundo exportador personalizado de Parquet. |
| Adaptador de ejecución | [act_adapter.py](/dimos/experimental/household_assistant/act_adapter.py): consume contratos `ExecutorCommand` de F4 y produce `ExecutorResult`; receptor de prueba sin transportes físicos. |
| Separación de entornos | [act_process.py](/dimos/experimental/household_assistant/act_process.py): proceso LeRobot propio, protocolo JSON, deadline, carga estricta del checkpoint y validación de perfil. |
| Entrenamiento y cómputo | [act_training_plan.json](/dimos/experimental/household_assistant/configs/act_training_plan.json): ensayo reducido ejecutado y propuesta física aún sin ejecutar. |
| Reproducción | [demo_act.py](/dimos/experimental/household_assistant/demo_act.py), [demo_act_resources.py](/dimos/experimental/household_assistant/demo_act_resources.py), comandos debajo. |
| Evidencia | [fase_7_validacion.json](/docs/development/asistencia_domestica_modular/fase_7_validacion.json), resultados y hashes; archivos grandes locales en `.ignore.f7/`. |

No se agregó un binding físico al blueprint de misiones: F4/F6 conservan la manipulación artificial identificada. El adaptador ACT se ensaya por separado con sus mismos contratos de órdenes/resultados. `finished` significa fin de trayectoria; el éxito de recoger/entregar necesita la verificación independiente de F4.

## Políticas y representación de acciones

| Aspecto | Ensayo ejecutado | Perfil físico propuesto, pendiente de calibración |
| --- | --- | --- |
| Habilidades | `pick_bottle_from_table`, `place_on_table`, checkpoints separados | Mismas habilidades; el control remoto queda fuera. |
| Observación | Tres RGB de 128×128 y vector de seis valores artificiales | Tres RGB; empezar evaluando 224×224. Cinco posiciones articulares y pinza del brazo derecho; supervisión del otro brazo separada. |
| Acción | Posiciones absolutas artificiales; no IDs, grados, radianes ni ticks | Cinco posiciones absolutas en grados con `use_degrees=True`; pinza en escala calibrada 0–100 del driver LeRobot. |
| Orden | `synthetic_axis_1..6`, imposible confundir con calibración física | `shoulder_pan`, `shoulder_lift`, `elbow_flex`, `wrist_flex`, `wrist_roll`, `gripper`, prefijados por brazo. Verificar IDs reales individualmente. |
| Ritmo | Máximo 10 envíos/s; predice cuatro acciones y utiliza dos | Medir antes de fijar FPS/chunk; propuesta inicial 10 Hz, chunk 20, ejecución de cinco pasos, sin garantía de tiempo real. |
| Normalización | Media/desviación solo de sesiones de entrenamiento | Misma regla; guardar normalizadores junto al checkpoint. No usar estadísticas globales que incluyan validación/test. |
| Postura inicial | Indicador artificial confirmado, base/elevador/otro brazo detenidos | Medir postura de aproximación, pinza vacía para recoger y objeto sujeto para colocar. Sin ángulos home inventados. |
| Dominio | Patrones RGB y señales sintéticas | Botella acordada y región de mesa medida. Entrenar colocación para cada dominio de destino que se pretenda habilitar. |
| Final | Fin de movimiento sin éxito de tarea inferido | Recogida: objeto correcto sostenido. Colocación: objeto liberado dentro de la región, estable. |

El SDK local SOFollower declara grados para los cinco ejes con `use_degrees=True` y normalización 0–100 para la pinza. Eso no prueba límites ni calibración del montaje. `action` registra el **objetivo realmente emitido después de limitar el mando de teleoperación**; `observation.state` registra la lectura del seguidor. No sustituir el objetivo por el estado medido ni convertir la pinza como si fuera otro ángulo.

Las tres cámaras son obligatorias en los perfiles actuales y deben permanecer adquiriendo imágenes mientras funcione la asistencia. F7 verifica su presencia en el contrato y dataset; aún no prueba tres dispositivos USB físicos continuos. `top_rgb` es el alias usado por la tesis para la frontal/superior. ACT consume RGB, no profundidad/LiDAR. El texto de tarea es metadato: ACT estándar no interpreta automáticamente instrucciones ni selecciona el objeto pedido; esa selección pertenece a F3/F5 y a la admisión de F4. [Referencia ACT](https://huggingface.co/docs/lerobot/act).

## Datos y cancelación

Cada dataset es LeRobot v3, con imágenes sin pérdida para el ensayo, `observation.state`, `action`, las tres `observation.images.*` y `capture_times`: tiempo del estado, de cada cámara y del comando emitido. `meta/household.json` añade perfil, procedencia, sesión, reinicio de escena, split y cantidad de frames. Los registros motores quedan separados de eventos semánticos de misión.

Se guardan episodios completos, no frames mezclados al azar. Una sesión no puede aparecer en entrenamiento y test/validación. El ensayo usa tres sesiones artificiales, dos episodios de 12 frames por sesión: **72 frames por política**. El conjunto test se conserva sin emplearlo para ajustar el modelo. Un salto temporal, cámara ausente, dato obsoleto o episodio demasiado corto se rechaza; `discard_episode()` permite repetir después de restablecer la escena. No se rellenan imágenes perdidas con ceros ni con el último frame para aparentar continuidad.

El adaptador controla tanto la edad de cada observación como la de la imagen que originó el bloque ACT; recibir imágenes nuevas no rejuvenece una predicción vieja. Revisa otra vez las condiciones antes de cada envío, limita el paso por eje y no acelera para recuperar ticks atrasados. La cancelación vacía la cola inmediatamente, detiene el receptor y cambia la generación: una inferencia tardía no puede producir comandos después. El proceso de inferencia tiene un deadline propio y se cierra al liberar el adaptador. Esta parada es del receptor software, no evidencia de frenado o retención física de una botella.

## Entorno y reproducción

El código local de LeRobot revisado corresponde al commit `9a6bb61043bac8c14353fcb6ea513b7473c118e3`. El entorno Miniforge usa Python 3.12.13 y Torch 2.11.0, sin CUDA disponible. Su instalación editable apunta a `/home/luigidu/handumi/lerobot/src`, no al checkout indicado por el usuario; además tiene `draccus 0.10.0` y el checkout exige `>=0.11.6,<0.12`.

Se resolvió sin editar LeRobot ni Miniforge: ruta explícita de fuentes y `draccus==0.11.6` aislado en `.ignore.f7/deps`. El primer intento documentado falló al guardar el checkpoint por esa incompatibilidad; las pruebas posteriores completaron el ciclo. No se modificaron los pesos/modelos de F5, el Excel ni dependencias globales de DimOS.

Desde la raíz de DimOS, para recrear la dependencia aislada si falta:

```bash
uv pip install --python /home/luigidu/miniforge3/envs/lerobot/bin/python --target .ignore.f7/deps --no-deps 'draccus==0.11.6'
```

Aplicar las variables solo al proceso LeRobot y ejecutar el ensayo de recogida en un directorio **nuevo**:

```bash
PYTHONPATH=/home/luigidu/dimos/.ignore.f7/deps:/home/luigidu/lerobot/src:/home/luigidu/dimos \
HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1 \
/home/luigidu/miniforge3/envs/lerobot/bin/python -m dimos.experimental.household_assistant.act_lerobot smoke \
  --profile dimos/experimental/household_assistant/configs/act_act_pick_table.json \
  --output .ignore.f7/mi_recogida --steps 5 --device cpu
```

Para colocación, cambiar el perfil a `act_act_place.json` y la salida a otro directorio. El ensayo no descarga backbone ni publica datasets/checkpoints. Los datos son artificiales y las imágenes no representan ni la botella ni los brazos SO101. Ambos ensayos usan señales equivalentes y la misma semilla: los pesos no acreditan dos habilidades distintas.

Desde el Python de DimOS, cargar el checkpoint resultante y probar F4 → ACT → receptor:

```bash
.venv/bin/python -m dimos.experimental.household_assistant.demo_act \
  --python /home/luigidu/miniforge3/envs/lerobot/bin/python \
  --lerobot-source /home/luigidu/lerobot/src --deps .ignore.f7/deps \
  --profile dimos/experimental/household_assistant/configs/act_act_pick_table.json \
  --checkpoint .ignore.f7/mi_recogida/checkpoint --output .ignore.f7/mi_adaptador
```

`demo_act_resources` acepta esos mismos argumentos y carga además las rutas locales predeterminadas de Qwen, CLIP, YOLO y el corpus F5. Ejecutarlo sin otras inferencias de prueba para medir coexistencia. No envía acciones a ningún receptor durante esta medición.

## Procedimiento para el primer episodio físico

Este procedimiento empieza cuando estén disponibles el robot, las calibraciones y el adaptador de lectura/control físico; el perfil artificial incluido no admite `physical` ni puede habilitar motores.

1. **Identificar y calibrar.** Asignar identificadores estables a cuatro buses (dos maestros, dos seguidores), guardar calibración individual y versión del driver. Contrastar mapeo de seis ejes, unidades y límites medidos con la plantilla física. Validar la alimentación específica de seguidores SO101 y mantenerla diferenciada de base/elevador.
2. **Preparar la escena.** Medir botella y mesa, fijar el dominio de posiciones, comprobar alcance y montaje. Colocar base/elevador y brazo izquierdo en posturas verificadas y detenidas; elegir la política de recogida. Para colocación, comenzar con la botella ya sostenida. `loaded_home` y el trayecto de retorno necesitan su prueba propia.
3. **Comprobar adquisición sin mover.** Mantener las tres cámaras activas con seriales/identificadores estables, verificar imágenes y reloj del estado articular. Medir latencia y desfase. Conservar tiempo de captura y transformación de reloj; si solo existe tiempo de recepción, declararlo y no presentarlo como captura sincronizada.
4. **Crear el perfil físico nuevo.** Sustituir ejes abstractos por nombres/unidades/mapeos medidos, límites por eje y paso máximo; congelar resolución/FPS efectivos, calibraciones y versión. Implementar y ensayar el receptor físico con watchdog/parada independiente antes de conectarlo a ACT. Los límites de F7 son artificiales y no se copian.
5. **Teleoperar y registrar.** Usar el maestro derecho, registrar el estado del seguidor y el objetivo realmente emitido junto a las tres imágenes. Mantener el maestro/seguidor izquierdo fuera de la acción unilateral. Usar el API oficial `LeRobotDataset` mediante el contrato de captura, con sesión y `reset_id` nuevos. Registrar aparte intervenciones y final observado; no escribir automáticamente «éxito» por acabar el vídeo.
6. **Validar el primer episodio antes de ampliar.** Abrirlo otra vez con `LeRobotDataset`, reproducir las tres vistas, comprobar orden/signos/unidades, estado frente a comando, tiempos, frames y ausencia de saltos. Unir cualquier toma fallida al registro de incidencias; descartarla del lote aceptado y repetir el reinicio de escena. Reservar primero cinco episodios diagnósticos por habilidad.
7. **Separar sesiones y entrenar.** Crear sesiones distintas para entrenamiento, validación y test antes de ajustar el modelo. Proponer un primer lote de 30 episodios por habilidad y medir curvas con 10/20/30; el número final dependerá de resultados, no de una promesa de éxito. Variar posición de botella, aproximación e iluminación dentro del dominio acordado. Toda nueva geometría/cámara/calibración invalida la compatibilidad directa con el checkpoint anterior.

El controlador SO101 individual y el bimanual `bi_so_follower` existen en el checkout LeRobot; no prueban por sí solos base/elevador ni la geometría híbrida. Los comandos estándar `lerobot-record` son una referencia de teleoperación, pero no generan automáticamente la procedencia, los tiempos multifuente ni los gates físicos de esta tesis. No se ejecutaron utilidades que escriben IDs/EEPROM o mueven motores.

## Resultados y límites de cómputo

Se ejecutaron cinco actualizaciones por política con ResNet18 sin pesos preentrenados y transformer reducido de **11.320.854 parámetros**. Se guardaron estadísticas, configuración y checkpoint; se verificaron acciones finitas de forma `[4,6]` y carga desde el otro entorno. El tiempo de optimización/guardado fue aproximadamente 1,2 s por política; excluye creación del dataset y arranque. Es una prueba pequeña de infraestructura, no una estimación del entrenamiento real.

La prueba conjunta cargó ACT reducido, Qwen2.5-VL-3B, CLIP, YOLO y Chroma. Se ejecutaron inferencias ACT mientras el VLM procesaba una imagen de replay. En la medición final aislada se obtuvieron 133 inferencias ACT concurrentes: p95 89.4 ms y 4 respuestas por encima de 100 ms. El pico agregado de RSS fue 11.37 GiB; suma procesos y puede contar páginas compartidas más de una vez. No representa VRAM. El manifiesto conserva las latencias y la respuesta visual. La percepción/memoria se ejercitaron antes de la ventana concurrente; no se simula que un SLAM o controlador físico estuvieran funcionando.

La pauta inicial es **VLM con el robot detenido → habilidad ACT → verificación**, evitando superponer inferencias intensivas en CPU en el camino de control. El presupuesto debe repetirse con ACT completo, cámaras reales y la computadora definitiva. GPU prestada/laboratorio: el usuario puede gestionarla, pero no tiene acceso ni reserva confirmados. Este cierre no declara entrenamiento físico validado ni disponibilidad de RTX.

Pasaron **154 pruebas en DimOS** (un módulo opcional LeRobot omitido allí) y **6 pruebas de captura en el entorno LeRobot**, Ruff y Mypy en seis archivos de producción. Los hooks de licencia, estilo, JSON, enlaces y LFS pasaron. El único fallo global fue el límite de 75 KB para tres archivos preexistentes: cronograma Excel, propuesta PDF y reporte visual HTML; no se modificaron. El proceso de medición terminó correctamente y emitió un aviso de limpieza de un semáforo de multiprocessing al salir; no dejó workers ACT/VLM activos. Los resultados exactos y las incidencias de hooks se conservan en el manifiesto. Los ensayos CPU quedan reproducibles; **F8 mantiene pendientes geometría SO101, límites/calibración, drivers, primera demostración real, entrenamiento útil y agarre/transporte físico**.
