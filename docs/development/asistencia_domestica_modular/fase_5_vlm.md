# F5 — Supervisor visual local y decisiones acotadas

Fecha: 18/09/2026. Alcance acordado: CPU, límite de 60 segundos por decisión, misión A (botella, sala → mesa del dormitorio), brazo derecho. El control remoto continúa reservado para la ampliación. No se modificó el cronograma Excel.

**Estado:** F5 completada en su alcance de software/simulación. La regresión final de decisiones cumplió 15/15 clases esperadas, con imágenes reales del renderizador y un VLM local real. No acredita una misión doméstica autónoma completa.

## Implementación

- `planner_contracts.py` y `configs/planner_cpu.json`: entrada y salida tipadas, revisión del modelo, dispositivo, precisión, hilos, tamaño visual y límites. `configs/planner_prompt.txt` versiona las instrucciones.
- `planner_backend.py`: Qwen2.5-VL-3B en un proceso propio, pesos locales, sin inferencia remota ni descarga automática. Comprueba el PNG recibido contra el hash RGB, registra los tensores visuales entregados al modelo y ejecuta dos consultas al mismo VLM: inspección visual breve y propuesta contextual. Ambas comparten un único plazo de 60 segundos; cargar el modelo tiene un límite independiente y ocurre antes de admitir trabajo.
- `planner_options.py`: catálogo filtrado por las precondiciones de F4, cámaras, carga y destino. No elige una acción ni usa posiciones de objetos de MuJoCo. Las opciones pueden incluir observación, movimiento o manipulación según la evidencia. Una inspección visual ambigua/incierta en recogida veta acciones y exige una pregunta; no crea hechos positivos de identidad, agarre ni ausencia global.
- `planner.py`: instrucción, imágenes identificadas, resultados de YOLO, recuperación histórica CLIP/Chroma, estado, resultado anterior y catálogo. El VLM propone una etapa o consulta; el plan de hasta tres etapas es revisable y nunca se ejecuta como lote. El supervisor exige JSON válido, parámetros admitidos, imágenes verificadas y evidencia actual.
- `MissionManager.admit_planner`: admisión atómica frente a cancelaciones y cambios de misión. El VLM no tiene comandos articulares ni acceso directo a motores. Las propuestas usan los ejecutores y verificadores de F4. La interpretación de una solicitud aún no admitida también se puede cancelar, descartando cualquier respuesta tardía.
- Una solicitud nueva debe mencionar el objeto y el destino: el filtro conservador admite «botella/botellita» y «dormitorio/habitación/mesa_dormitorio». Si falta alguno, restringe la respuesta a una consulta y el supervisor rechaza una misión inventada. El modelo sigue interpretando la petición y formulando la pregunta; el filtro no autoriza por sí solo una misión. Otros sinónimos requieren aclaración o ampliar y reevaluar este vocabulario.
- `demo_planner_live.py`: conexión por RPC al stack DimOS/MuJoCo de AlohaMini1 con `automatic_sequence=False`, cámara frontal real de la simulación y memoria F3. No se ejecuta el guion `MissionSequence` para decidir sus acciones.

La recepción de un tensor visual acredita que el backend utilizó píxeles; no demuestra por sí sola que su interpretación sea correcta. La evaluación registra también errores y decisiones rechazadas. La recuperación de memoria sigue siendo una pista histórica, nunca prueba de presencia actual.

## Modelo y evaluación

Se compararon únicamente SmolVLM2-500M y Qwen2.5-VL-3B. SmolVLM produjo respuestas no estructuradas y una detección incorrecta en la mesa vacía durante el sondeo inicial. Se seleccionó Qwen y se aplicó generación restringida al esquema JSON, manteniendo la validación posterior independiente.

Fuentes de los modelos: [SmolVLM2-500M](https://huggingface.co/HuggingFaceTB/SmolVLM2-500M-Instruct), [Qwen2.5-VL-3B](https://huggingface.co/Qwen/Qwen2.5-VL-3B-Instruct). La restricción sintáctica usa [LM Format Enforcer](https://github.com/noamgat/lm-format-enforcer); no sustituye la comprobación de precondiciones ni selecciona la habilidad por el modelo.

Los resultados finales se consignan en [fase_5_validacion.json](/docs/development/asistencia_domestica_modular/fase_5_validacion.json). Los registros completos y las imágenes permanecen bajo `.ignore.f5/`, fuera del código y del control de versiones. El corpus tiene diez vistas sintéticas de F3, incluyendo dos vistas laterales marcadas `held_out` en su manifiesto. Al repetirlas en esta regresión no se presentan como una evaluación independiente: no se entrenaron pesos, pero se ajustaron instrucciones y validadores durante el desarrollo. Las anotaciones no entran al VLM. El reloj de reproducción se pausa durante la inferencia; el timeout del proceso utiliza tiempo real. Por ello la prueba del corpus no se presenta como una prueba de vigencia de cámaras en vivo.

Se prueban una/dos botellas, mesa vacía, taza, oclusión, vista lateral, paráfrasis en español, datos faltantes, solicitud fuera de catálogo y botella ya sostenida. YOLO y recuperación CLIP se ejecutan durante la inferencia para medir contención real en CPU. ACT aún no está implementado: su consumo conjunto deberá medirse en F7; no se atribuye rendimiento de ACT a esta fase.

La primera regresión completa obtuvo 14/15 resultados esperados. El error fue convertir «Tráeme algo al dormitorio» en una solicitud de botella: motivó la comprobación independiente de campos ausentes descrita arriba. Se conserva ese resultado previo en el informe para no ocultar el fallo. La cifra de aciertos mide la clase de decisión esperada, no el éxito de una misión ni la calidad lingüística general.

La repetición final (`.ignore.f5/acceptance_complete`) obtuvo **15/15 clases esperadas**, con cero propuestas rechazadas y cero timeouts en esos casos. «Tráeme algo al dormitorio» produjo «¿Qué objeto quieres que lleve al dormitorio?». Una botella motivó observación; dos, elección de color; una mesa vacía, consulta; una carga ya verificada, `prepare_transport`.

| Medición en CPU | Resultado |
| --- | --- |
| Tiempo por decisión, ambas consultas incluidas | 27,66–36,15 s; mediana 29,89 s |
| Carga inicial del conjunto de modelos | 10,24 s |
| Pico RSS del proceso VLM | 9314 MiB |
| Pico RSS del proceso de evaluación/percepción | 1768 MiB |
| Suma RSS muestreada de proceso padre e hijos | 11057 MiB; cota superior, puede contar páginas compartidas dos veces |
| Contención medida | VLM con YOLO y recuperación CLIP/Chroma concurrentes |

Las solicitudes del control remoto y de preparar café no despacharon acciones, pero sus preguntas no explicaron bien que esas tareas están fuera del alcance. Esto limita la calidad de la conversación y deberá mejorarse en F6; no se contabiliza como comprensión lingüística perfecta.

Con la cámara frontal en vivo de MuJoCo, el modelo procesó un tensor visual de 180 × 1176 y preguntó «¿Dónde está la botella en la sala?» en 26,55 s. La consulta fue admitida sin iniciar una misión; no se observó una ejecución completa controlada por el VLM. En otra sesión, cancelar durante la inferencia devolvió el RPC en 0,00072 s y confirmó la parada del gestor en 0,174 s. Los brazos y la pinza usan las confirmaciones artificiales de F4; estos tiempos no describen frenado físico. DimOS emitió al cerrar una advertencia de limpieza de un semáforo de multiprocessing; los workers y el proceso del modelo terminaron.

## Reproducción

Desde la raíz del repositorio, con las dependencias de percepción instaladas. Los pesos deben prepararse previamente; el runtime no los descarga. La revisión de Qwen está fijada en `planner_cpu.json`. En este equipo se prepararon `.ignore.f5/models/qwen`, `.ignore.f3/models/clip` y `.ignore.f3/models/yolo/yolo11n.pt`.

```bash
# Directorios de salida nuevos en cada ejecución.
MUJOCO_GL=egl .venv/bin/python -m dimos.experimental.household_assistant.demo_visual_corpus .ignore.f5/corpus_repeticion

.venv/bin/python -m dimos.experimental.household_assistant.demo_planner \
  .ignore.f5/corpus_repeticion .ignore.f5/evaluacion_repeticion \
  --model-path .ignore.f5/models/qwen \
  --clip-path .ignore.f3/models/clip \
  --yolo-path .ignore.f3/models/yolo/yolo11n.pt --concurrent

MUJOCO_GL=egl .venv/bin/python -m dimos.experimental.household_assistant.demo_planner_live \
  .ignore.f5/sesion_repeticion \
  --model-path .ignore.f5/models/qwen \
  --clip-path .ignore.f3/models/clip \
  --yolo-path .ignore.f3/models/yolo/yolo11n.pt \
  --instruction 'Lleva la botella de la sala a la mesa del dormitorio'
```

`--cancel-during-inference` comprueba cancelación con una solicitud normalizada de prueba mientras el VLM está ocupado. Ctrl+C solicita también la cancelación y cierra los recursos. Una pregunta detiene la sesión de demostración y queda en el reporte; la conversación desde la interfaz corresponde a F6. La elección de una instancia sigue pasando por `choose_target` con revisión de escena actual, sin convertir una descripción de color en una identidad física automáticamente.

Para una RTX, copiar el JSON y cambiar `device` a `cuda`; proporcionar ese archivo con `--config`. El modelo y su ruta también se pueden cambiar, pero deberán repetirse las pruebas y registrar la revisión y los hashes. No se presupone disponibilidad de GPU ni se contrató ningún servicio.

## Límites y próximos pasos

Esta integración utiliza navegación MuJoCo y ejecutores artificiales de F4. Las asociaciones de identidad, agarre, alineación, postura de transporte y entrega continúan siendo fixtures identificados como `test`. Las imágenes son reales del renderizador; eso no convierte la manipulación en física ni en una política ACT entrenada.

La comparación de escenas durante una inferencia es deliberadamente estricta: exige la misma revisión, hechos y píxeles, además de una nueva imagen con tiempo vigente al despachar. Un cambio descarta la respuesta y solicita revisión; no se reutiliza una predicción vieja. Ruido o variación de iluminación puede ocasionar descartes adicionales. La generalización visual, el seguimiento de instancias y la calibración se validarán con el robot; este corpus pequeño no estima precisión doméstica general.

F6 deberá conectar la solicitud, aclaraciones, selección de objeto y cancelación a la interfaz. F7 deberá incorporar ACT y medir el uso conjunto de recursos; F8–F10 mantienen las validaciones físicas y experimentales del plan.

## Comprobaciones de código

Pasaron 118 pruebas del paquete `household_assistant`, incluyendo rechazo de salidas inválidas, cambios de escena, imágenes caducadas, objetivo ambiguo, carga ya sujeta, cancelación y respuestas tardías. Mypy pasó sobre 12 archivos de producción; Ruff, enlaces de documentación y coherencia de `uv.lock` también pasaron. Los hooks aplicables a F5 pasaron después de formatear el JSON. El hook global de archivos grandes sigue señalando el Excel preexistente `artifacts/cronograma_tesis/cronograma_actualizado.xlsx` (132 KB frente al límite de 75 KB); no se alteró el archivo ni la regla para ocultar ese aviso.
