---
title: "Plan de tesis: asistencia doméstica modular con DimOS, VLM y ACT"
---

# Plan de trabajo por fases

**Fecha:** 12 de septiembre de 2026. **Estado:** F0 completada; F1–F10 pendientes. Véase el [registro de cierre de F0](/docs/development/asistencia_domestica_modular/fase_0_limpieza.md).

Este plan persigue la propuesta actual: un asistente robótico que permita a una persona con movilidad reducida solicitar, supervisar y completar tareas de acceso a objetos mediante lenguaje natural. Integra DimOS, memoria y navegación semántica, supervisión visual y habilidades de manipulación ACT. El éxito final requiere entregar el objeto correcto en una región accesible acordada.

Se considera un único tesista, tres meses disponibles y la llegada del AlohaMini2 armado, cámaras de muñeca, LiDAR Unitree L2 y RealSense D435i aproximadamente dentro de veinte días. Son referencias relativas de planificación; no se presupone que el robot llegue calibrado ni integrado con DimOS. El equipo de cómputo y la variante exacta del robot deben documentarse antes de fijar modelos y controladores.

La fuente es `propuesta_tesis_asistencia_domestica.pdf`, once páginas, proporcionada por el usuario en `/home/luigidu/Downloads/`. SHA-256: `9d6d12973f432c250a37a78bcc2a29f43a00cd25770a74926702163e524fa642`. Se revisaron el código y los documentos presentes en el checkout con HEAD `ea4980756`; esta revisión no incluye ensayos físicos.

**La implementación antigua en `dimos/experimental/domestic_assistance` fue retirada en F0 por decisión del usuario**, junto con su blueprint dependiente y las entradas generadas. No se adopta como núcleo, no se importarán sus contratos y no se heredan sus misiones ni objetivos científicos. El stack genérico de navegación AlohaMini2 se conserva.

## 1. Qué debe demostrar la tesis

Los identificadores siguientes organizan los objetivos del PDF; no representan contribuciones adicionales ni resultados ya obtenidos.

| Objetivo | Referencia en el PDF | Entregable del repositorio | Evidencia de cumplimiento |
| --- | --- | --- | --- |
| O1. Solicitar y supervisar asistencia a distancia | Apartados 1, 2 y 10 | Interfaz con solicitud, destino, estado, consultas y cancelación | Un usuario completa el flujo desde otro dispositivo sin usar terminales de desarrollo. |
| O2. Usar mapa y memoria para buscar y navegar | Apartados 4–6 | Catálogo de lugares, memoria de observaciones y adaptador de navegación | Recuperación de un lugar candidato, navegación comprobada y confirmación actual del objeto. |
| O3. Interpretar intención y contexto visual | Apartado 7 | Supervisor VLM con entrada visual efectiva y decisiones validadas | Selección de una habilidad disponible, resolución de ambigüedad y reacción a cambios observables. |
| O4. Ejecutar manipulaciones aprendidas | Apartados 8 y 9 | Datos, configuraciones de entrenamiento, checkpoints identificados y adaptador ACT | Transferencias físicas repetibles dentro del dominio entrenado. |
| O5. Coordinar una misión completa | Apartados 3, 9 y 11 | Gestor de ejecución, verificación y actualización de memoria | Objeto correcto entregado, o fallo/inconclusión comunicado sin declarar éxito falso. |
| O6. Ampliar el repertorio | Apartados 9, 12 y 13 | Procedimiento de instalación e integración de una habilidad adicional | Nueva capacidad compuesta con las anteriores, con esfuerzo de datos, entrenamiento e integración registrado por separado. |
| O7. Evaluar el sistema y sus límites | Apartado 13 | Protocolo, registros, métricas, análisis y documentación reproducible | Resultados físicos, incertidumbre, costo y limitaciones; simulación e imágenes offline se reportan aparte. |

Las tres contribuciones que guían las decisiones son:

- **C1 — Autonomía funcional:** completar solicitudes desde la petición hasta la entrega, distinguiendo aclaraciones del usuario, rescates por teleoperación y ayuda física.
- **C2 — Extensibilidad:** incorporar y componer una habilidad nueva mediante una interfaz estable, midiendo el esfuerzo real requerido.
- **C3 — Acceso y supervisión:** permitir solicitar tareas, entender su progreso y corregir o cancelar la asistencia mediante una interfaz sencilla.

La comparación de configuraciones permitirá estudiar el aporte del contexto visual. No se presupone que DimOS, ACT o el uso de un VLM constituyan una novedad algorítmica propia. Tampoco se presupone una mejora de costo o autonomía antes de medirla. Entrenar un crítico, estimar ventajas, hacer aprendizaje por refuerzo o postentrenar el VLM no son requisitos de esta propuesta.

## 2. Alcance propuesto para tres meses

### Misión principal y ampliación obligatoria

**Misión A:** recibir una solicitud para traer una botella ligera u otro objeto rígido manejable desde una estación de recogida hasta una mesa de entrega, atravesando dos zonas conectadas. El objeto final se fija tras comprobar alcance, agarre y utilidad. Se usan una planta, superficies conocidas y posiciones de interacción registradas.

Como primera solución de transporte se propone una bandeja fija al robot. Dos habilidades ACT pueden cubrir las transferencias superficie–bandeja y bandeja–superficie. La descomposición definitiva debe reducir estados intermedios frágiles y permitir comprobación visual. Durante manipulación, la base estará detenida; el ajuste de altura se hará antes de iniciar la política en el primer prototipo.

**Ampliación B:** reservar una nueva habilidad de manipulación, por ejemplo recoger un estuche o control desde una superficie compatible, e integrarla en la misma misión de entrega. Su selección no tiene que quedar fijada antes de probar las pinzas, pero su evaluación sí forma parte de C2. Cambiar el nombre del objeto o registrar de nuevo el mismo checkpoint no constituye por sí solo una habilidad nueva.

El AlohaMini2 es una plataforma bimanual. La coordinación simultánea de ambos brazos se incorpora solo si las habilidades básicas ya funcionan y aporta una ventaja útil. Si no se evalúa, debe declararse así y ajustar el título y las afirmaciones sobre manipulación bimanual. Esto es una recomendación de alcance, no una afirmación de que esa parte ya esté resuelta.

### Requisitos finales y extensiones

| Requisito de cierre | Extensión que puede esperar |
| --- | --- |
| Solicitud por texto y una vía de voz con transcripción corregible | Activación por palabra clave y escucha permanente. |
| Selección explícita de un punto de entrega | Localización automática de la persona. |
| Dos zonas, lugares nombrados y memoria de observaciones | Cobertura de una vivienda arbitraria y seguimiento exhaustivo de todos sus objetos. |
| Identificación actual del objetivo y consulta ante ambigüedad | Manipulación general de cualquier objeto pedido. |
| Políticas ACT entrenadas para un dominio declarado | Control simultáneo aprendido de base, elevador y ambos brazos. |
| Una ampliación real del repertorio | Varias tareas bimanuales, abrir cajas y recuperar objetos del suelo. |
| Estados, cámara, mapa básico, pausa/cancelación y consultas | Favoritos, historial avanzado y solicitudes compuestas. |
| Verificación y recuperación limitada | Aprendizaje continuo y fine-tuning del VLM. |

La entrega se define mediante una región elegida con el usuario, no solo por pertenecer a una habitación. La identificación de necesidades y la evaluación de interfaz pueden empezar sin robot; los beneficios físicos de asistencia requieren evidencia posterior.

## 3. Base reutilizable y límites comprobados

| Componente existente | Uso previsto | Límite que el plan debe resolver |
| --- | --- | --- |
| [Módulos](/docs/usage/modules.md) y [blueprints](/docs/usage/blueprints.md) | Componer procesos, streams y RPC mediante las interfaces de DimOS. | Una conexión tipada no valida unidades, calibración ni condiciones físicas. |
| [Simulación AlohaMini2](/docs/usage/alohamini2-simulation.md) y [blueprints de navegación](/dimos/robot/alohamini2/blueprints/alohamini2_nav_sim.py) | Reutilizar navegación, cámaras, mapa, costo y planificación. | La versión articulada usa SO101. No acredita la cinemática ni los agarres de los AM-ARM200 objetivo. |
| [Navegación semántica](/dimos/agents/skills/navigation.py) | Etiquetas y búsqueda de destinos por texto. | Algunos caminos devuelven que empezó la navegación; el gestor debe comprobar llegada y parada. |
| [Memoria espacial](/dimos/perception/spatial_perception.py) | Buscar observaciones por texto, imagen y ubicación. | Una imagen recuperada es una pista histórica, no una posición actual confirmada del objeto. |
| [WorldBelief](/dimos/perception/worldbelief_module.py) | Evaluar posteriormente si simplifica identidad y recuperación de objetos. | No será una dependencia obligatoria del piloto. |
| [Agente visual](/dimos/agents/vlm_agent.py) y [adaptador Qwen](/dimos/models/vl/qwen.py) | Reutilizar codificación de imágenes y llamadas visuales. | La ruta de texto no añade por sí sola una imagen; el adaptador Qwen actual usa por defecto un servicio remoto. |
| [Cliente MCP](/dimos/agents/mcp/mcp_client.py) y [anotación de habilidades](/dimos/agents/annotation.py) | Exponer capacidades y descubrir herramientas cuando sea necesario. | El nuevo gestor debe ser el único responsable del despacho físico; no debe existir otro agente enviando movimientos en paralelo. |
| [RealSense](/dimos/hardware/sensors/camera/realsense/camera.py) | Color, profundidad, información de cámara y nubes. | Faltan montajes, calibración y sincronización del equipo que llegará. |
| [Point-LIO nativo](/dimos/hardware/sensors/lidar/pointlio/cpp/main.cpp) | Referencia para odometría y publicación de nube. | La fuente actual inicializa Livox. La etiqueta `unilidar` no acredita conexión directa del L2. |
| [Grabación y preparación de datos](/dimos/imitation/README.md) | Registrar demostraciones y exportarlas a LeRobot. | Adaptar AM-ARM200 y múltiples cámaras; el ejemplo usa el siguiente estado articular como acción, no necesariamente el comando enviado. |
| [Stack web](/web/README.md) | Ampliar cockpit y conexión con el robot. | Implementar el flujo asistencial y probar otro dispositivo, micrófono y reconexión. |

El [SDK oficial del L2](https://github.com/unitreerobotics/unilidar_sdk2) ofrece nube e IMU, incluyendo interfaces ROS/ROS2. El plan debe elegir una cadena de odometría compatible y un puente a DimOS; recibir nube no resuelve por sí solo localización y relocalización.

El [software de AlohaMini para LeRobot](https://github.com/liyiteng/lerobot_alohamini) es un candidato para reutilizar control y teleoperación. Se debe fijar la variante, versión e interfaz efectivamente disponibles; no se instalarán variantes de dependencias incompatibles en el entorno principal sin comprobarlas.

## 4. Organización prevista en este repositorio

Las rutas nuevas de esta tabla son **destinos propuestos**, todavía no implementados. Se crearán progresivamente cuando contengan comportamiento verificable, evitando esqueletos vacíos. No habrá imports desde el paquete descartado.

| Ubicación | Responsabilidad |
| --- | --- |
| `docs/development/asistencia_domestica_modular/` | Este plan, decisiones, protocolo experimental y guías de reproducción. |
| `dimos/experimental/household_assistant/` | Núcleo nuevo y acotado de la aplicación: modelos de misión, catálogo, gestor, verificación y adaptadores semánticos. |
| `dimos/experimental/household_assistant/configs/` | Tareas, estaciones, catálogo y configuraciones versionadas. |
| `dimos/experimental/household_assistant/testing/` | Dobles de prueba e inyección de fallos; no exponerlos como habilidades físicas. |
| `dimos/robot/alohamini2/` | Adaptación específica de base, elevador, brazos, sensores y modelo físico. |
| `dimos/robot/alohamini2/blueprints/` | Composiciones nuevas de simulación, captura y ejecución física cuando estén integradas. |
| `dimos/models/vl/` | Extensión del backend visual únicamente si las interfaces existentes no cubren lo necesario. |
| `dimos/imitation/` | Reutilización del flujo de datos; cambios genéricos solo cuando sean necesarios para cámaras y acciones de la tesis. |
| `web/cockpit/src/` y `dimos/web/` | Vista asistencial y canal de solicitudes, estado y consultas. |

Se usarán Specs/RPC y streams existentes para conectar componentes. Los parámetros de red y despliegue seguirán la [configuración de DimOS](/docs/usage/configuration.md). El catálogo de habilidades de la aplicación complementa `@skill` con requisitos, observaciones y estados; no sustituye el registro del framework.

El flujo será: solicitud → contexto de memoria y percepción → propuesta VLM → validación del gestor → habilidad → verificación posterior → actualización del contexto y la interfaz. Navegación y ACT serán ejecutores especializados. Pausa y cancelación seguirán funcionando mientras el VLM espera o falla.

## 5. Fases anteriores a la llegada del robot

Las fases F0–F7 producen un piloto de integración sin hardware. Sus criterios se refieren explícitamente a software, imágenes offline o simulación. Ninguna acredita éxito físico. La numeración expresa dependencias; la preparación documental de hardware y datos empieza desde F1.

### F0. Retirar el proyecto descartado y fijar el punto de partida

**Estado:** completada el 12 de septiembre de 2026. Se retiraron 32 archivos del paquete y un archivo de blueprints, se regeneró el registro y pasaron 54 pruebas focalizadas. [Cambios, entorno y verificaciones](/docs/development/asistencia_domestica_modular/fase_0_limpieza.md).

**Objetivo:** eliminar ambigüedad sobre qué trabajo corresponde a la tesis actual. **Depende de:** nada. **Aporta a:** O5–O7 y reproducibilidad.

Trabajo:

1. Inventariar los cambios locales y preservar los borrados y trabajos del usuario ajenos a esta limpieza.
2. Retirar `dimos/experimental/domestic_assistance` y sus pruebas/configuraciones específicas. La inspección actual identifica 32 archivos versionados en ese paquete.
3. Retirar `dimos/robot/alohamini2/blueprints/alohamini2_domestic_sim.py`, que importa el paquete descartado. Buscar referencias adicionales antes de eliminar.
4. Regenerar el registro con `pytest dimos/robot/test_all_blueprints_generation.py`; no editar `all_blueprints.py` manualmente. Deben desaparecer las dos misiones antiguas y el módulo de simulación antiguo.
5. Conservar el stack genérico de navegación AlohaMini2 y sus recursos. Es reutilizable independientemente del proyecto descartado.
6. Registrar versión del código, dependencias relevantes y resultados de comprobaciones iniciales.

**Entregable:** cambio de limpieza delimitado y una referencia reproducible del entorno.

**Criterio de cierre:** ausencia de imports y entradas de registro hacia el proyecto antiguo; generación del registro consistente y comprobaciones de descubrimiento/blueprints conservados satisfactorias. Si el generador local informa cambios sin commit, revisar el diff y validar la consistencia en modo CI; ese aviso no demuestra por sí solo un fallo de generación. No se requiere publicar ni hacer push para completar la fase.

### F1. Convertir la propuesta en contratos y criterios observables

**Objetivo:** que cada parte comparta el significado de tarea, habilidad, estado y éxito. **Depende de:** F0 para iniciar el paquete nuevo. **Aporta a:** O1–O7; C1–C3.

Trabajo:

1. Fijar misión A, regiones de recogida/entrega, estrategia de transporte y perfil de usuario. Registrar las decisiones provisionales que dependen de alcance o pinzas.
2. Definir objetos, lugares, solicitud, decisión, ejecución, observación y verificación mediante modelos tipados. Mantener solo los campos que usa el primer ciclo.
3. Diseñar el catálogo: nombre, descripción, objetos y escenas compatibles, entradas, precondiciones, final esperado, timeout, cancelación y ejecutor asociado.
4. Distinguir solicitud aceptada, acción iniciada, acción terminada y resultado verificado. Una acción puede terminar sin acreditar éxito.
5. Registrar origen de cada evidencia: prueba artificial, simulación, grabación externa o hardware propio; conservar timestamps, frame y procedencia. El origen debe describirse por componente/evidencia en las ejecuciones mixtas.
6. Reservar desde ahora una habilidad de ampliación y su protocolo de medida. Recoger comentarios sobre utilidad y región de entrega con posibles usuarios cuando estén disponibles; marcar los requisitos aún no contrastados.
7. Abrir una ficha de interfaces del hardware: articulaciones, unidades, modos de control, cámaras, transformaciones y capacidades de parada por confirmar.

**Entregables:** configuración de misión inicial, contrato mínimo de skills, criterios de éxito y ficha de interfaces. Ubicación: paquete nuevo y documentación de esta carpeta.

**Criterio de cierre:** diez casos de escritorio representativos pueden describirse sin ambigüedad, incluyendo objeto ausente, dos candidatos, imagen obsoleta, agarre incierto y cancelación. No se aceptan destinos desconocidos ni habilidades sin ejecutor. Los casos no requieren un VLM ni un robot para comprobar las reglas.

### F2. Preparar una escena de navegación y observación útil

**Objetivo:** ensayar la parte espacial del ciclo en DimOS. **Depende de:** F0 y nombres/configuración de F1. **Aporta a:** O2, O5; C1.

Trabajo:

1. Reutilizar el stack de navegación AlohaMini2 y añadir dos estaciones conectadas, una superficie de recogida y otra de entrega.
2. Publicar poses, imágenes, nubes y estado de navegación con nombres y marcos documentados. Guardar una grabación corta para pruebas repetibles.
3. Distinguir pose para observar de pose para manipular: posición y orientación de base, altura prevista y tolerancias.
4. Integrar un adaptador que traduzca destinos semánticos a navegación y espere llegada/parada. Probar destino bloqueado y cancelación.
5. Separar las observaciones disponibles para el supervisor de la verdad interna del simulador. Si se usan posiciones exactas para evaluar, mantenerlas en el evaluador y declarar la localización simulada como tal.
6. Anotar las diferencias del modelo SO101. Revisar la disponibilidad del URDF AM-ARM200 y preparar su adaptación sin convertir un simulador de manipulación detallado en requisito de este piloto.

**Entregables:** escena/configuración pequeña, adaptador espacial, reproducción de un recorrido y blueprint nuevo cuando el comportamiento esté integrado.

**Criterio de cierre:** el robot simulado recorre ambas estaciones, informa llegada comprobada, se detiene al cancelar y permite recuperar una observación reciente en cada estación. Se registran fallos y limitaciones; no se afirma que se haya validado el L2 ni la navegación física.

### F3. Incorporar memoria y percepción del objetivo

**Objetivo:** conectar «qué necesito» con «dónde buscar» y «qué se observa ahora». **Depende de:** F1 y observaciones de F2; puede empezar con imágenes offline. **Aporta a:** O2, O3, O5; C1.

Trabajo:

1. Registrar nombres y alias de estaciones, regiones de entrega y lugares habituales de objetos.
2. Usar memoria espacial de DimOS para recuperar observaciones candidatas; adaptar sus resultados al contexto de la misión sin crear un segundo sistema de embeddings innecesario.
3. Mantener por separado ubicación habitual, última observación y confirmación actual. Actualizar la ubicación después de una colocación verificada.
4. Construir un conjunto pequeño de imágenes representativas, capturadas sin robot o renderizadas, con objetivo, distractores, ausencia y oclusión. Registrar fuente y anotaciones.
5. Elegir la combinación mínima de VLM/detector/segmentador para identificar el objetivo. Añadir profundidad y proyección física solo cuando haya profundidad e intrínsecos válidos; una foto RGB no acredita posición 3D métrica.
6. Diseñar búsqueda acotada: revisar lugares candidatos, obtener otra vista y consultar cuando falte información. La similitud semántica no se tratará como una probabilidad calibrada de presencia.

**Entregables:** catálogo de lugares, adaptador de memoria, resultados de percepción con procedencia y conjunto de casos visuales independiente del estado interno del simulador.

**Criterio de cierre:** localizar un candidato, distinguir dos objetos compatibles, mantener incertidumbre ante oclusión y descartar una ubicación histórica contradicha por observación actual. La evaluación reporta errores visuales; no basta con completar una llamada al modelo.

### F4. Implementar el gestor y la verificación de misiones

**Objetivo:** completar el ciclo de ejecución independientemente del modelo lingüístico. **Depende de:** F1; integra F2–F3 al estar disponibles. **Aporta a:** O4, O5; C1 y C2.

Trabajo:

1. Crear un gestor pequeño con estados de preparación, búsqueda, navegación, manipulación, verificación, consulta y terminación. Usar una secuencia programada solo para probarlo antes del VLM.
2. Asegurar un único despacho de acciones y evitar que una petición repetida de la interfaz duplique la ejecución.
3. Comprobar precondiciones inmediatamente antes de ejecutar. Invalidar decisiones si el robot o la escena cambiaron mientras se esperaba una inferencia.
4. Ejecutar operaciones largas sin bloquear el ciclo que recibe cancelaciones. Distinguir solicitud de parada de parada confirmada; no iniciar otra acción con cancelación incierta.
5. Definir pausa según la habilidad: alcanzar un estado de retención seguro o cancelar y preparar una nueva ejecución. No prometer reanudar un bloque ACT a mitad de movimiento sin reconciliar el estado.
6. Verificar con observaciones posteriores: llegada y parada, objeto sostenido, presencia en bandeja, liberación y pertenencia a la región de entrega. Mantener los resultados éxito/fallo/incierto.
7. Crear dobles de prueba de manipulación con fallos controlados. Identificarlos como artificiales y mantenerlos fuera del catálogo físico.
8. Registrar solicitud, decisiones, acciones, resultados, evidencia, intervenciones y tiempos. No almacenar razonamientos internos del modelo; bastan entradas, salidas estructuradas y razones operativas breves.

**Entregables:** gestor nuevo, contratos de ejecutores, verificadores y registros de una misión completa con navegación simulada y manipulación artificial declarada.

**Criterio de cierre:** casos reproducibles de misión nominal, objeto ausente, fallo de agarre, resultado incierto, timeout, cancelación y desconexión. Una pinza que completó el movimiento no debe producir automáticamente «objeto recogido». Al detenerse el VLM o fallar el backend, el gestor sigue respondiendo.

### F5. Conectar un VLM real a decisiones acotadas

**Objetivo:** pasar de un guion de prueba a decisiones condicionadas por la petición y la escena. **Depende de:** F1, F3 y F4. **Aporta a:** O3, O5; C1.

Trabajo:

1. Elegir un modelo visual preentrenado después de verificar cómputo, backend y calidad en el conjunto de F3. Comparar como máximo dos candidatos durante el piloto.
2. Implementar entrada con instrucción, imágenes recientes identificadas, memoria pertinente, estado, resultado previo y catálogo permitido. Comprobar que los bytes de imagen llegan efectivamente al backend.
3. Solicitar una propuesta estructurada de próxima habilidad o consulta. Validar nombre, parámetros, objeto, destino y vigencia de la evidencia antes del despacho.
4. Mantener el plan de alto nivel revisable y ejecutar una etapa comprobable cada vez. No dar al VLM comandos articulares ni permitir que ejecute herramientas físicas fuera del gestor.
5. Medir tiempos de respuesta, consumo de memoria y errores. Un backend remoto requiere registrar dependencia de red y destino de las imágenes; un backend local requiere medir recursos compartidos con percepción y ACT.
6. Implementar timeout y descarte de respuestas tardías. Si falla la inferencia, conservar un estado conocido y comunicar la incidencia.
7. Probar paráfrasis en español, objetivo ya presente en bandeja, dos candidatos, objeto ausente y solicitud fuera del catálogo.

**Entregables:** supervisor conectado, configuración versionada de modelo/prompt, informe corto de selección y decisiones reproducibles sobre escenas.

**Criterio de cierre:** decisiones de un VLM real con imágenes verificadas, rechazo de salidas inválidas, pregunta útil ante ambigüedad y reacción al cambio de escena. Se informa el rendimiento en el conjunto de casos; un doble de prueba no satisface esta fase. El modelo exacto queda configurable y no se exige fine-tuning.

### F6. Habilitar solicitud y supervisión desde la interfaz

**Objetivo:** probar la asistencia desde el punto de vista del usuario. **Depende de:** F1 y eventos de F4; integra F5 cuando esté listo. **Aporta a:** O1, O5; C3.

Trabajo:

1. Ampliar el cockpit con solicitud por texto, destino elegido, estado de misión y vista de cámara/mapa. Reutilizar el canal web existente.
2. Implementar consultas que conserven el contexto: elección entre objetos, cambio de destino y confirmación de una instrucción corregida.
3. Conectar pausa/cancelación a estados reales del gestor. Mostrar «deteniendo» hasta confirmar la parada, no «detenido» al pulsar el botón.
4. Probar reconexión y prevención de envío duplicado. Mostrar si las imágenes o la conexión están obsoletas.
5. Añadir voz desde el micrófono del dispositivo, indicador de escucha, transcripción corregible y notificación de resultado. El texto permanece como vía de respaldo.
6. Verificar acceso desde celular en la red prevista, incluyendo los requisitos de contexto seguro del micrófono/transporte. No considerar suficiente una prueba solo en localhost.

**Entregables:** flujo asistencial navegable y grabación de uso sin terminales de desarrollo.

**Criterio de cierre:** desde otro dispositivo se solicita una misión, se responde una ambigüedad y se cancela o cambia el destino con estado consistente. El hito previo al robot puede cerrar con texto y evidencia de conexión; voz y su prueba de uso siguen pendientes hasta F9 si no entran en los veinte días.

### F7. Preparar ACT, captura y adaptación física

**Objetivo:** llegar al robot con el flujo de datos y las interfaces preparados. **Depende de:** F1 y contrato de ejecutores F4. La ficha de hardware comienza en F1. **Aporta a:** O4, O6; C1 y C2.

Trabajo:

1. Definir cada política inicial: vistas, tamaño de imagen, frecuencia, estado articular, acciones, normalización, postura inicial, región de trabajo y final verificable.
2. Fijar una representación de acción coherente con el controlador. Registrar tanto estado como comandos cuando sea posible; no reutilizar sin revisión los índices, unidades ni poses SO101.
3. Preparar el adaptador de inferencia: carga del checkpoint, construcción de observaciones, control de ritmo, vaciado de acciones pendientes y cancelación. Probarlo primero contra un receptor de comandos de prueba.
4. Reutilizar captura/exportación de DimOS o el flujo compatible de LeRobot, escogiendo una ruta principal para evitar dos sistemas de datos diferentes.
5. Crear un dataset pequeño artificial o compatible para verificar exportación, carga, dimensiones y un ensayo breve de entrenamiento/inferencia. Etiquetarlo como prueba del pipeline; no llamarlo entrenamiento físico del AlohaMini2.
6. Preparar captura de múltiples cámaras, identificación de episodios, reinicio de escena y división por sesiones. Separar datos motores de los registros de decisiones de misión.
7. Documentar interfaces de L2, D435i, base, elevador y AM-ARM200. Si existen grabaciones compatibles, ensayar recepción/conversión; mantener como pendientes los drivers no comprobados con el equipo real.
8. Planificar el protocolo de demostraciones y reservar acceso efectivo a cómputo. Un primer lote pequeño sirve para detectar errores de datos; el número final depende de la curva de aprendizaje.

ACT utiliza imágenes y estado articular para generar bloques de acciones; el significado de la solicitud no condiciona automáticamente la política estándar. La [documentación oficial de ACT en LeRobot](https://huggingface.co/docs/lerobot/act) sirve de referencia para preparar el pipeline. Un checkpoint de otra morfología puede probar infraestructura, pero no acredita competencia en estos brazos.

**Entregables:** ficha de hardware, esquema de dataset, configuración de entrenamiento, adaptador ensayado sin actuadores y procedimiento de captura.

**Criterio de cierre:** datos de prueba pasan de captura/exportación a carga e inferencia; una incompatibilidad de dimensiones, cámara ausente o observación obsoleta impide enviar acciones; la cancelación elimina acciones pendientes. Se dispone de un procedimiento concreto para registrar el primer episodio físico. Si falta GPU, se documenta qué parte del ensayo no pudo ejecutarse; no se marca entrenamiento validado.

### Hito H1. Qué debe estar disponible antes del robot

- [x] Proyecto descartado retirado; registro, descubrimiento y configuración/carga de blueprints conservados comprobados en F0.
- [ ] Misión, catálogo, lugares y contratos nuevos documentados.
- [ ] Navegación entre estaciones y observaciones accesibles en simulación.
- [ ] Memoria que distingue información histórica de confirmación actual.
- [ ] Gestor con éxito, fallo, incertidumbre, consulta y cancelación comprobados.
- [ ] VLM real recibe imágenes y propone acciones validadas.
- [ ] Interfaz por texto completa un ciclo desde otro dispositivo.
- [ ] Captura, representación de acciones y adaptador ACT preparados.
- [ ] Registros identifican qué partes son simuladas o artificiales.
- [ ] Protocolo experimental redactado antes de ajustar el sistema con hardware.

Si H1 se completa, ya existe un asistente integrado de software que puede ensayarse; todavía faltan localización física, agarres aprendidos, transporte real y verificación sensorial física. El progreso se mide por componentes y evidencia, no con un porcentaje de «tesis terminada».

## 6. Fases que continúan cuando llegue el robot

### F8. Validar plataforma, sensores, teleoperación y navegación

**Objetivo:** convertir las interfaces preparadas en capacidades físicas comprobadas. **Depende de:** F1, F2 y F7; comenzar al llegar el robot aunque haya mejoras de interfaz pendientes. **Aporta a:** O2, O4, O5; C1.

Trabajo:

1. Confirmar variante y controladores; medir límites operativos, sentidos, unidades, homing y pinzas. No interpretar límites genéricos de un URDF como límites físicos validados.
2. Calibrar cámaras y transformaciones de base, brazos, elevador y L2. Si un sensor se mueve con el elevador, actualizar su transformación; las cámaras de muñeca dependen de la cinemática.
3. Validar watchdog, parada local y pérdida de comunicación por separado del VLM y del navegador web.
4. Obtener nube y odometría compatibles del L2; comprobar calidad temporal, frames y conversión a DimOS. Validar que guardar un mapa permita volver a usar sus lugares tras reiniciar/relocalizar.
5. Medir la huella con bandeja y brazos recogidos, rutas, tolerancia de llegada y ajuste a las estaciones.
6. Teleoperar transferencias con las mismas cámaras y representación de acción previstas para ACT.

**Entregables:** adaptadores físicos, calibraciones identificadas, blueprint de captura y prueba de recorrido real.

**Criterio de cierre:** sensores estables, teleoperación repetible, navegación entre estaciones con parada verificable y primera demostración registrada correctamente. Los problemas de localización y control se resuelven antes de entrenar grandes lotes de datos.

### F9. Entrenar las habilidades, cerrar la misión y demostrar ampliación

**Objetivo:** materializar C1 y C2 y cerrar el flujo de C3. **Depende de:** F3–F8. **Aporta a:** O1–O6.

Trabajo:

1. Recoger demostraciones de transferencias iniciales y entrenar ACT. Separar entrenamiento/validación por sesiones; documentar objetos, alturas, posturas y variaciones cubiertas.
2. Evaluar cada habilidad aislada antes de integrarla. Añadir demostraciones de las variaciones de llegada que efectivamente produce la navegación.
3. Implementar evidencia física de recogida, bandeja y entrega a partir de cámaras y señales disponibles de pinzas. No inferir agarre únicamente de la finalización del comando.
4. Ejecutar la misión desde la interfaz hasta la entrega; verificar presencia del objeto antes y después del transporte, y actualizar memoria después de colocarlo.
5. Resolver ambigüedad, ausencia, un reintento limitado y destino ocupado. Confirmar que detener una política no ejecuta bloques pendientes.
6. Congelar el núcleo y las habilidades iniciales; integrar la habilidad B reservada y componerla con navegación/entrega sin reentrenar toda la misión.
7. Medir por separado demostraciones, entrenamiento, horas de integración, archivos modificados y validación de B. Registrar cualquier cambio necesario en el núcleo en vez de ocultarlo.
8. Completar voz y comprobar la interfaz con solicitudes, consultas y cancelaciones representativas. Recoger comentarios de usabilidad y registrar qué participantes representan al usuario objetivo.

**Entregables:** checkpoints y datasets identificados, misiones físicas A/B, procedimiento de ampliación y piloto de uso.

**Criterio de cierre:** el ciclo físico funciona repetidamente en el dominio declarado y existe evidencia de la habilidad adicional. Una demostración simbólica de B solo valida integración de software y no satisface la extensibilidad física completa. Si B no llega a ejecutarse, C2 se reporta como limitada; no se elimina silenciosamente de la tesis.

### F10. Evaluación final, análisis y memoria de tesis

**Objetivo:** respaldar las contribuciones con resultados reproducibles. **Depende de:** F9 para ensayos finales; protocolo y scripts se preparan desde F1/F4. **Aporta a:** O7; C1–C3.

Trabajo:

1. Congelar configuración, modelos, prompts, calibración, dominio de tareas y protocolo antes de la evaluación final.
2. Ejecutar escenarios nominales y perturbados en orden aleatorizado, con variantes del sistema comparables y resets documentados.
3. Registrar todos los intentos e intervenciones. Conservar los fallos; reportar exclusiones con reglas definidas antes de mirar resultados.
4. Etiquetar el éxito final mediante revisión de evidencia independiente del VLM que decide. Mantener incierto cuando la evidencia no permite concluir.
5. Calcular métricas por misión, etapa y escenario, con incertidumbre. Presentar resultados físicos por separado de simulación, replay y pruebas artificiales.
6. Documentar costo, esfuerzo de ampliación, uso de interfaz y límites de generalización. Distinguir evidencia técnica de una evaluación de impacto en personas con movilidad reducida.
7. Entregar guía de reproducción, manifiestos de datos/checkpoints, resultados y material de defensa. Escribir método y decisiones durante todas las fases, no solo al final.

**Criterio de cierre:** cada afirmación de C1–C3 puede vincularse a ejecuciones, medidas o evidencia de uso; las limitaciones y resultados negativos permanecen visibles. El sistema puede iniciarse y evaluarse siguiendo la documentación en un entorno preparado.

## 7. Protocolo mínimo alineado con las contribuciones

### Comparaciones

| Configuración | Qué cambia | Qué permite concluir |
| --- | --- | --- |
| B0: secuencia predefinida con los mismos ejecutores | Sustituye al supervisor VLM; conserva comprobaciones y parada | Referencia de sistema para cuantificar el valor de decisiones adaptativas. No aísla solo la visión. |
| B1: supervisor VLM, memoria, imágenes y resultados verificados | Sistema propuesto | Rendimiento del asistente completo. |
| B2: mismo supervisor sin imágenes directas actuales | Se retiran únicamente esas imágenes; se conservan percepción estructurada y verificaciones físicas | Aporte marginal de dar imágenes al planner por encima de los hechos estructurados. No mide el valor de toda la percepción. |

Priorizar B0/B1 en hardware. Preparar B2 con escenas offline y llevarla a hardware si el presupuesto de ensayos permite conclusiones útiles. Si no se realiza, limitar la afirmación sobre el aporte aislado de las imágenes. No desactivar comprobaciones de parada ni forzar movimientos para construir una comparación.

Mantener fijos objetos, ejecutores, presupuesto de reintentos, criterios de éxito y escenas entre condiciones. Separar sesiones de entrenamiento, ajuste y evaluación final. Si se modifica una política motora o un verificador durante la campaña, identificar una nueva configuración y evitar mezclar resultados como si fueran iguales.

### Escenarios y medidas

Escenarios iniciales: objeto en lugar habitual; objeto desplazado dentro del dominio entrenado; dos candidatos; objeto ausente; oclusión; destino ocupado; agarre fallido observado; interrupción del usuario. En software se pueden inyectar fallos; en hardware se usan variaciones controladas compatibles con los límites del robot.

| Contribución o dimensión | Medida | Cuándo se prepara / obtiene |
| --- | --- | --- |
| C1: éxito completo | Objeto correcto liberado dentro de la región de entrega y robot detenido / intentos elegibles | Regla en F1; cálculo de prueba en F4; datos físicos en F9–F10. |
| C1: intervención | Aclaraciones, correcciones, teleoperación y ayuda física, con duración | Eventos en F4/F6; clasificación fijada antes de los ensayos. |
| C1: fiabilidad | Fallos por etapa, resultados inciertos, falsas declaraciones de éxito y recuperaciones | Verificación en F4; evidencia sensorial en F9. |
| Tiempo | Tiempo total, por etapa, inferencia y participación activa del usuario | Instrumentación en F4; medición real en F9–F10. |
| C2: ampliación | Tiempo de demostración, entrenamiento, integración y validación; cambios en el núcleo; éxito de B | Plantilla en F1; ejecución en F9. |
| C3: acceso y supervisión | Solicitudes enviadas correctamente, consultas resueltas, cancelaciones comprendidas, tiempo de tarea y comentarios | Piloto de interfaz en F6; uso integrado en F9–F10. |
| Contexto visual | Selección correcta del objetivo/acción, decisiones inválidas y éxito de misión según configuración | Casos en F3/F5; comparaciones en F10. |
| Robustez | Desglose por posición, fondo, iluminación y estado de la escena | Variaciones acotadas en F3; ensayos finales separados del ajuste. |
| Costo | Hardware y montajes, sensores, cómputo, servicios y horas de preparación | Registro desde F1; cierre en F10. |

Definir antes del ensayo qué significa «autónomo»: por ejemplo, sin teleoperación ni ayuda física, reportando aparte las aclaraciones. No mezclar esa medida con «sin ninguna interacción». La región accesible debe acordarse con el usuario y quedar registrada con dimensiones y altura.

Como presupuesto inicial de planificación, reservar 60–100 misiones físicas entre B0/B1, según duración, resets y fallos observados en el piloto; fijar la distribución antes de la campaña. El tamaño no garantiza significación estadística. Informar intervalos de confianza, conteos y variabilidad entre sesiones, evitando tratar cuadros de un mismo episodio como ensayos independientes.

La evaluación de interfaz puede empezar con participantes disponibles sin robot. Si no representan al usuario objetivo, reportar una evaluación exploratoria de interacción; no afirmar un beneficio asistencial demostrado para toda la población propuesta.

## 8. Calendario y prioridades para un único tesista

Este es un presupuesto de trabajo orientativo, no una garantía. Los veinte días son calendario. El primer ciclo F0–F7 se limita a versiones mínimas y puede requerir unas 80–110 horas concentradas; si la disponibilidad es menor, conservar H1 como lista de pendientes y trasladar mejoras sin retrasar la recepción y validación física.

| Ventana | Prioridad | Resultado esperado |
| --- | --- | --- |
| Días 1–3 | F0 y F1; abrir ficha física y protocolo | Base limpia, misión y contratos nuevos. |
| Días 4–8 | F2 y primera versión F3 | Estaciones, recorrido simulado y observaciones para memoria/percepción. |
| Días 9–12 | F4 e integración espacial | Ciclo verificable con ejecutor artificial y fallos declarados. |
| Días 13–16 | F5 y flujo de texto de F6 | VLM con imágenes y solicitud/consulta desde interfaz. |
| Días 17–20 | F7, otro dispositivo y ensayo H1 | Pipeline motor preparado, integración documentada y pendientes físicos claros. |
| Semana 4 | F8 | Interfaces físicas, calibración inicial y primera captura. |
| Semanas 5–6 | F8/F9 | Navegación real y primera transferencia ACT repetible. |
| Semanas 7–8 | F9 | Primera misión completa, verificación y voz/interfaz integradas. |
| Semanas 9–10 | Ampliación B, piloto y congelación | Evidencia de C2, selección de escenarios y presupuesto final. |
| Semanas 11–13 | F10 | Evaluación, análisis y defensa; escritura ya iniciada. |

Los números de días sirven para ordenar trabajo; F7 documental comienza en F1 y F10 metodológica empieza antes de tener hardware. No se mantiene el desarrollo de dos controladores, dos interfaces o varios VLM en paralelo. Cuando una integración exceda el presupuesto, registrar el problema y elegir la ruta mínima que conserve los objetivos.

**Decisiones de alcance ante dificultades:**

- Si F2 consume demasiado tiempo, reutilizar la escena existente y añadir solo las estaciones necesarias. Posponer el modelo de manipulación detallado.
- Si el VLM no corre localmente, evaluar un backend accesible y medido, o continuar contratos e interfaz con un doble marcado como prueba. F5 seguirá abierta hasta ensayar un modelo visual real.
- Si al final de la semana 6 no hay transferencia repetible, simplificar objeto, superficie, altura y pose inicial antes de añadir tareas.
- Si al final de la semana 8 no hay misión completa, posponer bimanualidad, WorldBelief y funciones secundarias. Mantener un hueco para la ampliación B; si no se logra, declarar la limitación de C2.
- Si se retrasa el robot, avanzar en imágenes reales offline, datos, interfaz y protocolo. Eso no sustituye la validación física ni justifica afirmar que se cumplieron O4/O5.

## 9. Criterio de trabajo y evidencia por fase

Cada fase deja una nota breve con fecha, cambio de código, forma de reproducción, entrada utilizada, comprobaciones realizadas, resultados, evidencia y pendientes. Solo se marca cerrada después de cumplir su criterio; las capacidades existentes de DimOS y las pruebas del proyecto descartado no cierran automáticamente fases nuevas.

Aplicar las [reglas de pruebas del repositorio](/docs/development/testing.md): comprobar comportamiento significativo, usar pruebas rápidas para lógica y reservar integración de modelos/simulador para los entornos apropiados. El pytest por defecto excluye los marcadores `mujoco` y `self_hosted`; un pase de la suite rápida no valida simulación ni hardware. Las pruebas de cancelación deben comprobar el estado, no solo que se llamó un método.

Las configuraciones, metadatos y scripts pertenecen al repositorio. Videos, datasets y checkpoints se guardan mediante el mecanismo de datos adecuado, con manifiestos, versiones, ubicaciones y licencias; no se incluyen como binarios grandes en Git ordinario. Registrar comando de entrenamiento, versión de LeRobot, cámaras, normalización y checkpoint usado por cada ejecución. Los datos externos o artificiales deben conservar su identificación.

### Orden inmediato de ejecución

1. F0 completada: paquete antiguo y blueprint dependiente retirados; registro regenerado y validado.
2. Crear la definición de misión A, el catálogo mínimo y la ficha de interfaces de F1.
3. Hacer que una solicitud atraviese un ciclo nuevo del gestor con pruebas de fallo, usando primero un ejecutor artificial explícito.
4. Conectar ese ciclo con las estaciones y observaciones de DimOS; incorporar memoria y VLM progresivamente.
5. Probarlo desde la interfaz mientras se deja listo el pipeline ACT para el primer día de captura física.

Este orden permite avanzar desde ahora hacia las contribuciones del PDF y deja identificada la evidencia que todavía dependerá del robot.
