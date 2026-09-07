# Estado del arte 2025–2026: recuperación aprendida en manipulación móvil

**Proyecto objetivo:** AlohaMini2-SO101 + DimOS
**Fecha de corte:** 30 de agosto de 2026
**Pregunta de revisión:** ¿Qué se ha publicado recientemente sobre detección, aprendizaje y ejecución de recuperaciones en manipulación móvil, y qué aporte de tesis continúa siendo defendible?

## 1. Dictamen ejecutivo

La idea general de «entrenar una política para recuperarse de fallos» **sí ha sido implementada** en varias formas recientes. Ya existen trabajos que:

- aprenden una política RL separada que vuelve desde un fallo a una skill nominal;
- corrigen una política visuomotora con demostraciones humanas de recuperación;
- adaptan una diffusion policy durante los reintentos usando preferencias derivadas de fallos;
- generan datos sintéticos de estados correctivos para una VLA móvil;
- reparan modelos de efectos de skills a partir de fallos reales de un manipulador móvil;
- usan un VLM en lazo cerrado para replanificar navegación y manipulación;
- y entrenan agentes visuales de alto nivel mediante SFT + RL para llamar herramientas de navegación y VLAs físicas.

Por ello, esta afirmación ya no sería una contribución suficiente:

> «Proponemos una policy aprendida que detecta un fallo, elige una recuperación y continúa una tarea de manipulación móvil».

La oportunidad científica que permanece abierta y es compatible con AlohaMini2 y DimOS es más específica:

> **Recuperación de misión consciente de transición para manipulación móvil de bajo costo: un modelo temporal y multicámara aprende a localizar en qué capa falló la misión —navegación, posicionamiento perceptual, activación VLA o manipulación— y a estimar qué macroacción DimOS tiene mayor probabilidad de restablecer progreso, con incertidumbre calibrada y consulta humana selectiva.**

La diferencia central sería que la política no aprende directamente torques, IK ni pequeños desplazamientos del efector. Aprende a **seleccionar y encadenar recuperaciones a nivel de skills**:

`reobservar → renavegar/reposicionar → reactivar VLA → verificar → retroceder de etapa → pedir ayuda → abortar seguro`.

Ese espacio se encuentra entre cuatro líneas que hoy están separadas:

1. recuperación local dentro de una política de manipulación;
2. reparación offline de modelos o datasets después de un fallo;
3. replanning semántico de alto nivel;
4. reward/progress models para entrenar políticas.

La tesis debe demostrar que un **modelo de transición condicionado por la recuperación candidata** mejora el éxito end-to-end frente a VLM-only replanning, reglas retry/reset y un Skill-State Graph sin ranking aprendido.

## 2. Criterio de inclusión y lectura crítica

Se priorizaron artículos o preprints primarios de 2025 y 2026 que cumplen al menos uno de estos criterios:

- manipulación móvil de largo horizonte con recuperación o adaptación;
- recuperación aprendida de políticas de manipulación;
- detección o razonamiento de fallos que pueda actuar como monitor;
- modelos de progreso/recompensa aplicables a recuperación no monótona;
- generación de datos correctivos para robustez de una VLA móvil.

Para no confundir resultados, se separan tres tipos de «recuperación»:

| Nivel | Qué se recupera | Ejemplos |
|---|---|---|
| Acción/policy | Un grasp, una inserción o un chunk de acciones | FAR, FLARE, FailSafe, RaC |
| Skill/modelo | La capacidad de una skill o su modelo de efectos | RecoveryChaining, Fail2Progress |
| Misión | La secuencia navegación–percepción–manipulación y su estado | MoMaStage, REAL |

También se distingue entre:

- **limitación declarada:** reconocida por los autores;
- **brecha inferida para esta tesis:** diferencia razonada a partir del alcance experimental del paper, no necesariamente un defecto general del trabajo.

## 3. Papers de mayor relevancia directa

### 3.1 Fail2Progress — CoRL 2025

**Referencia:** [Fail2Progress: Learning from Real-World Robot Failures with Stein Variational Inference](https://proceedings.mlr.press/v305/huang25d.html), CoRL 2025.

**Qué hace.** Es el antecedente más directamente relacionado con «aprender de fallos en manipulación móvil». El sistema usa modelos aprendidos de efectos de skills sobre estados simbólicos. Cuando el resultado observado de una skill no coincide con el efecto predicho, registra el fallo, reconstruye un escenario Real2Sim de baja fidelidad y usa Stein Variational Inference para generar un pequeño dataset diverso y de alta información, condicionado al fallo. Después afina el modelo de efectos y replantea la tarea.

Evalúa transporte de múltiples objetos, organización jerárquica de mesa y packing en estantes. Usa 40 000 ejecuciones para preentrenamiento y solo 20 muestras dirigidas por fallo para el ajuste. En la organización simulada, según la arquitectura de efectos, reporta 72–86% frente a 8–11% del modelo original; en el mundo real alcanza alrededor de 80%. El paper declara una F1 media de 0,92 para detectar relaciones.

**Lo fuerte.** No se limita a «reintentar»: convierte el fallo real en una consulta de active learning y genera datos específicamente informativos. Además demuestra manipulación móvil real, no solo tabletop.

**Limitaciones declaradas.** Los autores reconocen que:

- es una demostración esencialmente one-shot de actualización, no aprendizaje lifelong seguro;
- no corrige fallos debidos al gap sim-to-real;
- depende de Real2Sim, segmentación semántica y relaciones predefinidas;
- no cubre perturbaciones de personas, cambios de hardware, deformables o líquidos;
- solo representa poses de objetos como estado simulado;
- y deja la extensión a espacios abiertos de edificio como trabajo futuro.

**Brecha para AlohaMini2.** Fail2Progress repara **offline** un modelo simbólico de efectos después de observar un fallo. No aprende una política reactiva que, durante el mismo episodio, compare macroacciones como reobservar, renavegar, cambiar de cámara, repetir VLA o pedir ayuda. Tampoco estudia explícitamente la frontera navegación→VLA ni usa un progress/outcome model condicionado por la recuperación candidata.

**Implicación para la tesis.** No se debe reclamar «aprender de fallos móviles» como novedad. Sí puede reclamarse **recuperación reactiva de misión y selección de macroacciones**, comparándola contra la estrategia de reparar/replanificar el modelo.

---

### 3.2 MoMaStage — preprint 2026

**Referencia:** [MoMaStage: Skill-State Graph Guided Planning and Closed-Loop Execution for Long-Horizon Indoor Mobile Manipulation](https://arxiv.org/abs/2603.08383), marzo de 2026.

**Qué hace.** Restringe un VLM mediante una biblioteca jerárquica de skills y un Skill-State Graph con precondiciones/transiciones. Monitoriza feedback proprioceptivo, detecta desviaciones y activa replanning semántico limitado por el grafo. Emplea skills BC/RL para pick, place, open, close y navegación.

En simulación ejecuta 8 100 trayectorias sobre tres tareas de ManiSkill-HAB modificado y reporta 79–94% de éxito de planificación. En una evaluación física de diez tareas de 17 subtareas, alcanza 60% de éxito final, mientras las secuencias open-loop se degradan a cero.

**Lo fuerte.** Es probablemente el antecedente arquitectónico más cercano a «DimOS skills + VLM + monitor + replanificación móvil». Demuestra que representar explícitamente el estado de transición reduce planes inválidos y tokens.

**Limitaciones observadas.** El propio estudio muestra que incluso con planificación semántica correcta el éxito simulado cae casi a cero a horizontes de 20 pasos por fallos físicos de las policies. Los recoveries severos —por ejemplo, un objeto fuera del workspace— continúan siendo irrecuperables. La evaluación física principal tiene solo diez trayectorias de la tarea larga.

**Brecha para AlohaMini2.** El Skill-State Graph y sus transiciones son estructurados manualmente; la recuperación queda confinada a rutas anticipadas. No aprende de rollouts qué recuperación funciona mejor bajo evidencia visual multicámara ni calibra incertidumbre. Su monitor es principalmente ego-state/proprioceptivo, mientras AlohaMini2 puede explotar cámaras front/back/chest/wrists y estado de navegación de DimOS.

**Implicación para la tesis.** MoMaStage debe ser un baseline conceptual obligatorio. La novedad debe formularse como **ranking aprendido de recuperaciones y estados de transición**, no simplemente «grafo de skills con replanning».

---

### 3.3 REAL — ECCV 2026

**Referencia:** [Exploratory, Communicative, and Deployable: Vision-Driven Embodied Agents for Open-World Mobile Manipulation](https://arxiv.org/abs/2607.13653), aceptado en ECCV 2026.

**Qué hace.** REAL entrena un agente Qwen3-VL-8B de alto nivel para exploración visual, desambiguación con el usuario y tool calling. La interfaz de herramientas evita percepción oracle y se conserva entre simulación y robot. Usa SFT para alinear formato/skills y GSPO online para razonamiento, exploración y recuperación. En hardware, herramientas abstractas llaman navegación y una π0.5 especializada para open/close/pick/place.

REAL-Bench contiene 241 tareas. En 60 episodios físicos sobre ARX LIFT2 obtiene 78,3% end-to-end; las primitivas VLA alcanzan 85,3% sobre 600 llamadas. El costo acumulado de inferencia VLM es 68,4 s por episodio.

**Lo fuerte.** Ya implementa casi literalmente un high-level VLM entrenado que coordina navegación y VLA mediante herramientas, con memoria compacta, feedback y recuperación. Además usa una interfaz estilo MCP, muy cercana filosóficamente a DimOS.

**Limitaciones declaradas/medidas.** El espacio físico se concentra en rearrangement entre receptáculos; no cubre restricciones temporales o relaciones espaciales ricas, el usuario simulado está acotado y los receptáculos no tienen representación por partes. Su desglose físico atribuye la mayoría de fallos restantes a errores VLA, timeouts o no preguntar a tiempo. También depende de un VLM de 8B con SFT + RL online y posee latencia considerable.

**Brecha para AlohaMini2.** REAL aprende una política general de tool use; no presenta un modelo explícito, pequeño y calibrado que estime **progreso, recuperabilidad y riesgo de cada recuperación candidata**. Tampoco se enfoca en data efficiency para un único robot económico y una GPU de 32 GB.

**Implicación para la tesis.** «VLM planner + DimOS + VLA» ya está cubierto. La tesis debe enfocarse en el **mecanismo de decisión de recuperación**, su calibración, datos y evaluación, manteniendo el planner base congelado o ligero.

---

### 3.4 WANDA — preprint 2026

**Referencia:** [Worlds in One Demo: A Synthetic Data Engine for Learning Open-World Mobile Manipulation](https://arxiv.org/abs/2607.13154), julio de 2026.

**Qué hace.** Reconstruye una escena y las interacciones robot–objeto a partir de una demostración RGB-D; recompone segmentos de contacto mediante whole-body planning, genera nuevas escenas 3D y aplica **Corrective State Expansion**. Esta expansión perturba estados de objeto, base y articulaciones para que la VLA aprenda a corregir drift y desviaciones a lo largo de tareas móviles.

En cinco tareas físicas largas, WANDA reporta 54,8% de progreso medio contra 15,7% sin Corrective State Expansion. También muestra transferencia entre dos manipuladores móviles con morfologías distintas.

**Lo fuerte.** Ataca directamente el distribution shift de largo horizonte y demuestra que incluir estados correctivos en entrenamiento es decisivo. Es una alternativa moderna a DAgger generada sintéticamente.

**Limitaciones declaradas.** La reconstrucción o planning pueden propagar errores; cloth y fluidos no se modelan físicamente; el contacto rico sigue proviniendo de la demostración original. Además, el costo publicado es muy alto para el contexto de esta tesis: 765 GPU-h para generar 251,6 h de datos y fine-tuning full-parameter de π0.5 durante 12 h en 32 H100.

**Brecha para AlohaMini2.** WANDA entrena robustez implícita dentro de la VLA; no decide explícitamente entre recuperación por navegación, percepción, reintento, rollback o ayuda humana. Tampoco aprende online de los fallos específicos del robot con una restricción de cómputo modesta.

**Implicación para la tesis.** Corrective State Expansion sería un baseline o fuente de perturbaciones, no el aporte central. La alternativa AlohaMini2 puede investigar **active/selective failure collection** y un selector pequeño en lugar de una infraestructura de generación masiva.

---

### 3.5 Motion Planning-Augmented Hierarchical RL — Sensors 2026

**Referencia:** [Motion Planning-Augmented Hierarchical Reinforcement Learning for Long-Horizon Mobile Manipulation](https://www.mdpi.com/1424-8220/26/12/3845), Sensors 2026.

**Qué hace.** Descompone la misión como SMDP y usa trayectorias RRT* en el espacio articular completo para shaping del reward de cada subpolítica. Sustituye handoffs puntuales por regiones analíticas factibles según IK. Evalúa seis subtareas de ManiSkill-HAB sin teletransportes.

**Lo fuerte.** Identifica correctamente que muchos fallos de largo horizonte aparecen en el handoff entre navegación y manipulación, no dentro de una skill aislada.

**Limitaciones declaradas/inferidas.** Toda la evaluación es simulada; requiere IK, RRT*, estado geométrico y recompensas dependientes del planner. No razona sobre instrucciones abiertas, fallos visuales ni selección agéntica de recuperaciones.

**Brecha para AlohaMini2.** La tesis propuesta deliberadamente evita convertir IK/control en su eje. Puede abordar el mismo problema de handoff desde un enfoque robot-learning: evidencia visual/proprioceptiva, éxito futuro de la VLA y selección de macroacciones.

**Implicación para la tesis.** Debe incluirse para demostrar que se conoce la solución geométrica rival y justificar por qué se estudia una alternativa aprendida y perceptual.

---

### 3.6 VLLR — preprint 2026

**Referencia:** [Generalizable Dense Reward for Long-Horizon Robotic Tasks](https://arxiv.org/abs/2604.00055), marzo de 2026.

**Qué hace.** Usa un LLM para descomponer tareas, un VLM para estimar progreso e inicializar el value function durante una fase corta, y self-certainty de la propia policy como recompensa intrínseca durante PPO. Evalúa CHORES, que combina navegación, fetch y manipulación, y reporta mejoras absolutas de hasta 56 puntos sobre la policy inicial y hasta 10 puntos en tareas OOD.

**Lo fuerte.** Muestra que un progress model semántico y una señal interna de la policy son complementarios, y reduce el costo de consultar al VLM durante todo el entrenamiento.

**Limitaciones declaradas.** Solo evalúa CHORES/ProcTHOR con acciones discretas y deja continuous-action manipulation como futuro. El artículo también advierte que demasiado peso a self-certainty puede causar catastrophic forgetting.

**Brecha para AlohaMini2.** VLLR usa progreso como reward para fine-tuning de una policy end-to-end; no usa el modelo para comparar macroacciones de recuperación ni valida un robot móvil físico. La «certeza» de una policy tampoco equivale necesariamente a seguridad o progreso real.

**Implicación para la tesis.** Es un baseline fuerte para el componente de progreso. El modelo AlohaMini2 debería predecir **delta de progreso, outcome y riesgo por candidato**, no solo un escalar global.

## 4. Papers de recuperación de policies/manipulación que condicionan la novedad

### 4.1 RecoveryChaining — IROS 2025

**Referencia:** [RecoveryChaining: Learning Local Recovery Policies for Robust Manipulation](https://www.merl.com/publications/docs/TR2025-152.pdf), IROS 2025.

**Qué hace.** Aprende con PPO una recovery policy separada. Su acción híbrida contiene primitivas pequeñas del efector y opciones temporales que transfieren el control a controladores nominales. La policy aprende cómo recuperarse, cuándo abandonar recovery y a cuál skill nominal regresar, usando recompensa escasa.

Reporta mejoras de 70→90% en pick-place, 51→83% en shelf y 38→57% en cluttered shelf; entrena 200 000 pasos y transfiere de simulación a un brazo físico.

**Lo fuerte.** Es exactamente una «policy de recuperación» y descubre estrategias de contacto no programadas. Lazy RecoveryChaining reduce rollouts costosos mediante clasificadores conservadores de precondiciones.

**Limitaciones observables.** Los controladores nominales y los planes se diseñan manualmente; las acciones son desplazamientos discretos del efector; usa observaciones de estado/pose privilegiadas o detectores específicos; los fallos y dominios son tres; no incluye base móvil. El paper reconoce que no recupera grandes rotaciones in-hand sin observación de orientación y que el cluttered shelf necesitaría mejor acción/reward/entrenamiento.

**Brecha para AlohaMini2.** RecoveryChaining aprende recuperación motora local. La tesis puede aprender una policy **de orquestación** sobre skills heterogéneas DimOS, condicionada por video y estado de misión, sin aprender IK ni acciones cartesianas.

---

### 4.2 FLARE — CVPR 2026

**Referencia:** [FLARE: A Failure-Aware Framework for Autonomous Correction and Recovery in Visual-Language Robotic Manipulation](https://openaccess.thecvf.com/content/CVPR2026/html/Zhao_FLARE_A_Failure-Aware_Framework_for_Autonomous_Correction_and_Recovery_in_CVPR_2026_paper.html), CVPR 2026.

**Qué hace.** Divide los fallos en dos rutas:

- **Retry:** perturbation + bridging augmentation enseña a la VLA a corregir desviaciones de pose sin cambiar el estado del entorno;
- **Reset:** un MLLM analiza videos offline, identifica estados OOD y guía la colección de una pequeña biblioteca de skills que restauran el objeto/entorno.

Un MLLM online arbitra entre la policy nominal y resets. En RoboMimic reporta 84,0% promedio frente a 72,2% de π0.5. En Piper real, con diez demos humanas ampliadas a cincuenta por task/reset, mejora stacking 62,5→75% e inserción 45→55%.

**Lo fuerte.** Formaliza de manera útil la diferencia entre perturbaciones recuperables dentro de la policy y estados que requieren restaurar el entorno.

**Limitaciones observables.** Evalúa brazos fijos y una biblioteca de resets por objetos/tareas; algunos reset skills presentan tasas mucho menores para ciertos objetos. La decisión MLLM no es un ranker aprendido y calibrado con costo/riesgo. No estudia navegación, localization, docking visual ni recuperación de misión.

**Brecha para AlohaMini2.** Generalizar Retry/Reset a **Recover/Replan/Ask/Abort entre capas**, con opciones DimOS y un outcome model aprendido. FLARE sería un excelente baseline de arbitraje VLM puro.

---

### 4.3 FailSafe — IROS 2026

**Referencia:** [FailSafe: Reasoning and Recovery from Failures in Vision-Language-Action Models](https://arxiv.org/abs/2510.01642), IROS 2026.

**Qué hace.** Genera automáticamente fallos en simuladores con motion planning, los empareja con acciones de recuperación ejecutables y ajusta LLaVA-OneVision-7B como FailSafe-VLM. El monitor ayuda a π0-FAST, OpenVLA y OpenVLA-OFT y reporta hasta 22,6% de mejora media en ManiSkill, con generalización entre configuraciones, vistas, objetos y embodiments.

**Limitaciones declaradas.** El pipeline se centra en recuperación de movimiento y todavía no corrige errores a nivel del objeto. Los autores señalan que la integración VLA–VLM necesita mayor eficiencia y flexibilidad, por ejemplo mediante action chunking en tiempo real.

**Brecha para AlohaMini2.** Solo manipulación de brazo y simuladores con soporte de motion planning. No atribuye si el fallo proviene de navegación, visibilidad, activación prematura de la VLA o acción física; tampoco recupera la misión completa.

---

### 4.4 FAR — preprint 2026

**Referencia:** [FAR: Failure-Aware Retry for Test-Time Recovery and Continual Policy Improvement](https://arxiv.org/abs/2607.01111), julio de 2026.

**Qué hace.** Es el solapamiento más peligroso con la idea previa de «preferencias de recuperación». FAR identifica chunks que causaron una caída de value, muestrea alternativas de la diffusion policy, usa un critic IQL para construir pares preferido/no preferido y realiza 5–10 gradientes de preference adaptation durante el test. Agrega perturbaciones suaves para explorar y reutiliza las trayectorias recuperadas en continual improvement.

Evalúa nueve tareas simuladas y tres tareas reales xArm; reporta +17,6% sobre diffusion policy en simulación y +11,7% en real, usando una sola A5000.

**Lo fuerte.** Aprende de fallos sin demostrador humano, usa preferencias y es computacionalmente viable con una GPU similar a la disponible para la tesis.

**Limitaciones inferidas desde el setting.** Después de cada fallo conserva la escena pero devuelve el brazo a una pose inicial predefinida. Las acciones candidatas son chunks de la misma diffusion policy y se exploran localmente con ruido; necesita critic offline y feedback de éxito. Solo prueba manipulación de brazo, no navegación ni fallos cross-skill.

**Brecha para AlohaMini2.** La preferencia no puede ser el aporte por sí sola. La diferencia defendible es moverla al **nivel de misión**: comparar candidatos heterogéneos —renavegar, reobservar, reposicionar base, cambiar política, rollback, ask— usando clips multicámara y estado de ejecución. No se exige devolver el robot a una pose inicial fija.

---

### 4.5 RaC — preprint 2025

**Referencia:** [RaC: Robot Learning for Long-Horizon Tasks by Scaling Recovery and Correction](https://arxiv.org/abs/2509.07953), septiembre de 2025.

**Qué hace.** Después del preentrenamiento por imitación, humanos intervienen cuando anticipan un fallo: primero «rebobinan» el robot a un estado familiar y luego completan la subtarea con un segmento correctivo. La policy se afina con esta composición de datos. En tres tareas bimanuales reales largas reporta superar métodos anteriores con diez veces menos tiempo/muestras.

**Lo fuerte.** Es una versión pragmática y moderna de DAgger enfocada explícitamente en recovery; sostiene que el problema principal es la distribución de datos success-only.

**Limitaciones inferidas.** Requiere teleoperador que identifique el fallo, recupere físicamente el estado y termine la subtarea; estudia manipulación bimanual fija y policy-level recovery, no navegación ni selección autónoma entre alternativas.

**Brecha para AlohaMini2.** Sustituir intervención continua por **consulta selectiva en decisiones inciertas**. El humano etiqueta o elige una macroacción de recuperación; no teleopera todos los movimientos. Esto sería DAgger a nivel de skills, no DAgger motor.

---

### 4.6 RoboFailRing — ACL 2026

**Referencia:** [RoboFailRing: Retrieval-Augmented and Language Grounding Failure Detection for VLM-enabled Robotic Manipulation](https://aclanthology.org/2026.acl-long.602/), ACL 2026.

**Qué hace.** Construye una memoria de fallos recuperable por similitud para detectar fallos tempranamente; después entrega un reporte grounded al VLM para mejorar diagnóstico causal y estrategias de reparación. Evalúa más de 6 000 trayectorias y 81 tareas; reporta 80% de detección OOD, aproximadamente la mitad del tiempo de detección del baseline y +35% en accuracy de razonamiento VLM real.

**Lo fuerte.** Muestra que la memoria de fallos puede ser más rápida y fiable que consultar repetidamente un VLM grande, y separa detección rápida de razonamiento lento.

**Brecha para AlohaMini2.** La contribución evaluada es detección/razonamiento, no la ejecución y selección cerrada de recuperaciones ni mobile manipulation. Su memoria puede incorporarse como baseline o componente del monitor AlohaMini2.

## 5. Papers de progress/reward modeling relevantes para el modelo de recuperación

### 5.1 ARM — CVPR Workshop 2026

**Referencia:** [ARM: Advantage Reward Modeling for Long-Horizon Manipulation](https://arxiv.org/abs/2604.03037), 2026.

**Qué hace.** Reemplaza progreso absoluto por una clasificación relativa de tres estados: `Progressive`, `Regressive`, `Stagnant`. Puede anotar demostraciones completas y fragmentos tipo DAgger, y usar esas señales para reponderar datos en offline RL. Reporta 99,4% en folding de toalla.

**Lo fuerte.** Ataca exactamente el problema de recuperación no monótona: retroceder temporalmente puede ser correcto y una etiqueta de progreso basada solo en tiempo lo castigaría.

**Brecha para AlohaMini2.** Evalúa una tarea de manipulación, no navegación ni decisiones de recuperación. Estima ventaja/progreso observado, no el outcome contrafactual de varias macroacciones candidatas.

**Implicación.** La tesis debería adoptar o comparar etiquetas relativas de progreso. No debe presentar la idea `progreso/regresión/estancamiento` como nueva.

---

### 5.2 SARM — ICLR 2026

**Referencia:** [SARM: Stage-Aware Reward Modeling for Long Horizon Robot Manipulation](https://arxiv.org/abs/2509.25358), ICLR 2026.

**Qué hace.** Aprende desde video etapa de tarea y progreso fino, derivando labels de anotaciones de subtareas en lenguaje. Usa Reward-Aligned Behavior Cloning para filtrar/reponderar datos. Reporta 83% en camiseta plana y 67% en camiseta arrugada, frente a 8% y 0% de BC.

**Lo fuerte.** Demuestra que stage + progress es más estable que usar índice temporal, y que ejemplos con misgrasp, ida-vuelta y recovery son necesarios para evitar un reward model demasiado optimista.

**Brecha para AlohaMini2.** Es task-specific, se centra en folding deformable y usa reward para policy training; no selecciona acciones de recuperación de misión. Requiere anotaciones de subtareas y su señal puede no transferir directamente entre navegación y manipulación.

---

### 5.3 ARM vs SARM vs propuesta

| Modelo | Señal | Maneja retroceso | Condicionado por candidato | Mobile/real | Uso principal |
|---|---|---:|---:|---:|---|
| SARM | etapa + progreso absoluto | Parcial, mediante augmentations | No | No | reponderar BC |
| ARM | progreso relativo tri-state | Sí | No | No | offline RL / filtrado |
| VLLR | progreso VLM + self-certainty | Implícito | No | Benchmark sim | PPO de policy |
| Propuesta | etapa + delta + éxito futuro + riesgo | Sí | **Sí** | **Sí, AlohaMini2** | seleccionar recovery skill |

La contribución defendible no es crear «otro reward model», sino convertirlo en un **transition-outcome model accionable**:

\[
f(o_{t-k:t},\; m_t,\; a^R_i) \rightarrow
(p_{\text{éxito misión}},\; \Delta progreso,\; p_{\text{riesgo}},\; u)
\]

donde:

- `o` son clips front/chest/wrists y señales de navegación;
- `m_t` es memoria compacta: instrucción, etapa, última skill y resultado;
- `a^R_i` es una recuperación candidata;
- `u` es incertidumbre calibrada.

## 6. Matriz comparativa consolidada

| Trabajo | Mobile | Robot real | Aprende recovery | Nivel de acción | Usa progreso/valor | Humano online | Solapamiento |
|---|---:|---:|---:|---|---:|---:|---|
| Fail2Progress | Sí | Sí | Sí, actualiza modelo | skill/modelo simbólico | Información/uncertainty | No | Muy alto |
| MoMaStage | Sí | Sí | No, replanifica con grafo | skill | Estado/feedback | No | Muy alto |
| REAL | Sí | Sí | Sí, RL de agente | herramientas | Reward de entorno | Ask opcional | Muy alto |
| WANDA | Sí | Sí | Implícito en VLA | acciones VLA | No explícito | 1 demo | Alto |
| MP-HRL | Sí | No | Sí, subpolicies RL | continuo/joint space | Reward geométrico | No | Medio |
| VLLR | Benchmark mobile | No | Mejora policy | acción discreta | Sí | No | Alto en reward |
| RecoveryChaining | No | Sí | Sí, PPO | primitivas + options | Q/precondiciones | No | Alto en policy recovery |
| FLARE | No | Sí | Retry + reset skills | VLA/skill | Monitor MLLM | Demos de resets | Alto |
| FailSafe | No | No físico reportado | Sí vía datos | acción de recuperación | VLM monitor | No | Medio-alto |
| FAR | No | Sí | Sí, test-time preference | action chunks | Critic IQL | No | Muy alto en preferencias |
| RaC | No | Sí | Sí, imitación | acciones de policy | Intervención humana | Sí | Alto en DAgger |
| RoboFailRing | No | Parcial | Detecta/razona | reporte/estrategia | Similaridad | No | Medio |
| ARM | No | Sí | Mejora policy | muestras offline | Progreso relativo | Etiquetas ligeras | Alto en progress |
| SARM | No | Sí | Mejora policy | muestras BC | Etapa + progreso | Anotaciones | Alto en progress |

## 7. Qué partes de la idea original ya están ocupadas

| Reivindicación posible | Estado en 2026 | Veredicto |
|---|---|---|
| VLM de alto nivel llama navegación y VLA | REAL, OWMM-Agent, Hi Robot | No novedoso |
| Monitor visual detecta fallo y replantea | MoMaStage, FLARE, RoboFailRing, AHA | No novedoso |
| Biblioteca de skills con estados/transiciones | MoMaStage, RecoveryChaining | No novedoso |
| Policy aprende a volver a una skill nominal | RecoveryChaining | No novedoso |
| DAgger/intervenciones enseñan recovery | RaC y trabajos relacionados | No novedoso |
| Preferencias derivadas de fallos | FAR | No novedoso |
| Reward model de progreso no monótono | ARM/SARM | No novedoso |
| Datos sintéticos de estados correctivos móviles | WANDA | No novedoso |
| Aprender de un fallo real móvil mediante Real2Sim | Fail2Progress | No novedoso |
| Ranking aprendido y calibrado de recoveries **cross-layer** en navegación→VLA | No se encontró una demostración equivalente en estos trabajos | Candidato de aporte |
| Evaluación sistemática de recuperación de misión en robot móvil dual-SO101 de bajo costo | No se encontró equivalente exacto | Candidato de aporte |

## 8. Reformulación recomendada de la tesis

### Título recomendado

> **Aprendizaje de recuperación de misión consciente de transición para navegación y manipulación móvil en AlohaMini2**

Alternativa más explícita:

> **Selección multimodal e incierta de estrategias de recuperación para tareas de navegación–manipulación con políticas VLA**

### Pregunta científica

> ¿Un modelo temporal multicámara, entrenado para estimar el resultado de recuperaciones candidatas a nivel de skills, puede aumentar el éxito end-to-end y reducir intervenciones humanas frente a retry/reset por reglas y replanning directo de un VLM en tareas de manipulación móvil?

### Aporte técnico propuesto

1. **Taxonomía cross-layer de fallos** en un stack real:
   - navegación: bloqueo, goal no alcanzado, pose/localización degradada;
   - percepción/handoff: objeto no visible, observación ambigua, VLA activada fuera de su distribución;
   - manipulación: misgrasp, drop, contacto fallido, resultado parcial;
   - misión: objeto equivocado, memoria desactualizada, subtarea omitida.

2. **Transition-Outcome Model** compacto, condicionado por:
   - video antes/después desde head/chest/wrists;
   - estado de DimOS: odom, goal, resultado de navegación, skill activa;
   - instrucción y etapa;
   - recuperación candidata.

3. **Recovery policy a nivel de skills**, no de control:
   - `observe_again` / `scan_from_other_view`;
   - `navigate_again` / `reposition_base`;
   - `retry_vla`;
   - `rollback_to_stage`;
   - `switch_manipulation_policy` si existe;
   - `ask_human`;
   - `safe_abort`.

4. **Aprendizaje interactivo selectivo**:
   - el robot pide al humano elegir/validar recovery solo si la incertidumbre o el riesgo supera un umbral;
   - la etiqueta se convierte en pares de preferencia entre macroacciones;
   - el aprendizaje ocurre en el ranker de skills, no mediante teleoperación continua.

5. **Benchmark y protocolo reproducible** en MuJoCo + AlohaMini2 físico, con perturbaciones controladas y logs DimOS/Rerun.

### Distinción concreta frente a los cinco rivales más cercanos

| Rival | Qué hace | Diferencia que debe probar la tesis |
|---|---|---|
| Fail2Progress | repara offline el modelo de efectos con Real2Sim | recuperación reactiva en el mismo episodio, sin reconstruir un dataset por fallo |
| MoMaStage | replanning dentro de grafo diseñado | ranking aprendido y calibrado entre recoveries, incluidos estados no previstos |
| REAL | política VLM general de tool use entrenada con RL | módulo pequeño, explícito, interpretable y data-efficient centrado en fallo/transición |
| FAR | preferencias entre chunks de una diffusion policy | preferencias entre macroacciones heterogéneas de navegación/percepción/VLA |
| WANDA | entrena robustez VLA con datos sintéticos masivos | aprendizaje selectivo desde fallos del robot con una GPU de 32 GB |

## 9. Diseño experimental mínimo defendible

### Tareas

Tres tareas son suficientes si cubren transiciones distintas:

1. **Busca y trae:** localizar un libro/manzana, navegar, agarrar, volver y entregar.
2. **Rearrangement entre superficies:** recoger de mesa y colocar en estante/contenedor.
3. **Manipulación bimanual corta:** abrir/cerrar o estabilizar y depositar, si los SO101 lo permiten de forma fiable.

Cada tarea debe tener objetos y layouts vistos/no vistos.

### Perturbaciones

- obstáculo nuevo o ruta bloqueada;
- parada de base con error perceptual pequeño/mediano;
- objeto movido después de navegar;
- target o distractor ocluido;
- misgrasp y drop;
- subtarea declarada exitosa cuando no lo fue;
- memoria de objeto desactualizada;
- cámara parcial o temporalmente degradada.

### Baselines

1. sin recovery;
2. retry/reset por reglas;
3. VLM-only: observa fallo y genera siguiente skill;
4. Skill-State Graph estilo MoMaStage sin ranker aprendido;
5. progress model sin condicionamiento por recovery;
6. método completo: candidate-conditioned outcome + uncertainty + selective query.

### Métricas

- éxito end-to-end;
- éxito condicional de recuperación;
- porcentaje de episodios salvados después de un fallo;
- tiempo, distancia y número de skills extra;
- falsas activaciones de recovery;
- fallos peligrosos / safe aborts;
- tasa de intervención humana;
- data efficiency: éxito por número de fallos etiquetados;
- calibración: ECE/Brier/NLL del outcome model;
- generalización a objeto, layout y tipo de perturbación no visto.

### Ablations

- sin wrist cameras;
- sin historial temporal;
- sin estado de navegación;
- sin candidate conditioning;
- sin uncertainty gate;
- sin memoria de fallos;
- entrenamiento aleatorio frente a active/selective querying.

## 10. Viabilidad con una GPU de 32 GB

La propuesta es viable si se evita reproducir REAL o WANDA a escala completa.

**Configuración recomendada:**

- planner VLM congelado, vía API o modelo 3B/7B cuantizado;
- ACT o SmolVLA task-specific ya entrenada/afinada, sin foundation pretraining;
- encoder visual congelado como SigLIP/CLIP/DINOv2;
- temporal transformer de 4–8 capas o GRU pequeña para el Transition-Outcome Model;
- LoRA solo si se necesita ajustar el VLM/ranker;
- entrenamiento principal sobre embeddings y pares de recuperación, no video foundation-model end-to-end.

**Lo que no conviene intentar:**

- entrenar una VLA fundacional desde cero;
- RL online sobre un VLM de 8B al estilo REAL;
- reconstrucción/rendering de cientos de GPU-h al estilo WANDA;
- aprender whole-body control continuo si el eje es la recuperación de misión.

## 11. Riesgo científico y criterio honesto de go/no-go

La idea sigue siendo buena, pero solo si el experimento aísla una pregunta que los trabajos anteriores no contestan.

**Go:**

- el ranker condicionado por candidato supera consistentemente VLM-only y graph-only;
- la incertidumbre reduce intervenciones/fallos peligrosos sin destruir el éxito;
- la política generaliza al menos a un tipo de perturbación o layout no visto;
- el resultado se valida en AlohaMini2 físico, aunque sea con tres tareas acotadas.

**No-go o reformulación necesaria:**

- si la contribución termina siendo solo prompts y reglas de retry;
- si el modelo solo detecta éxito/fallo pero no cambia qué recovery se ejecuta;
- si se entrena y prueba en las mismas perturbaciones sin generalización;
- si no se compara con VLM-only, reglas y graph-only;
- si toda recuperación ocurre dentro del VLA y DimOS solo lanza el modelo.

## 12. Conclusión

La revisión no invalida el proyecto; lo hace más preciso. El campo ya resolvió muchas piezas aisladas y algunos sistemas de 2026 —REAL y MoMaStage— se acercan mucho a la arquitectura macro. FAR ocupa la idea de preferencias de recovery a nivel de action chunks; ARM/SARM ocupan el progreso relativo/por etapas; Fail2Progress ocupa aprendizaje desde fallos en mobile manipulation; WANDA ocupa expansión sintética de estados correctivos.

El aporte defendible consiste en estudiar una capa todavía fragmentada:

> **cómo elegir, con evidencia temporal multicámara e incertidumbre, la recuperación correcta entre navegación, percepción y VLA para salvar una misión móvil, aprendiendo con pocas consultas humanas y ejecutando las decisiones como skills observables de DimOS.**

La tesis no competiría con los grandes modelos por escala. Competiría por **formulación, integración experimental, eficiencia de datos, calibración y evidencia en un robot móvil dual-arm de bajo costo**.

## Referencias primarias principales

1. [Fail2Progress — CoRL 2025](https://proceedings.mlr.press/v305/huang25d.html)
2. [RecoveryChaining — IROS 2025](https://www.merl.com/publications/docs/TR2025-152.pdf)
3. [RaC — 2025](https://arxiv.org/abs/2509.07953)
4. [MoMaStage — 2026](https://arxiv.org/abs/2603.08383)
5. [REAL — ECCV 2026](https://arxiv.org/abs/2607.13653)
6. [WANDA — 2026](https://arxiv.org/abs/2607.13154)
7. [FLARE — CVPR 2026](https://openaccess.thecvf.com/content/CVPR2026/html/Zhao_FLARE_A_Failure-Aware_Framework_for_Autonomous_Correction_and_Recovery_in_CVPR_2026_paper.html)
8. [FailSafe — IROS 2026](https://arxiv.org/abs/2510.01642)
9. [FAR — 2026](https://arxiv.org/abs/2607.01111)
10. [RoboFailRing — ACL 2026](https://aclanthology.org/2026.acl-long.602/)
11. [VLLR — 2026](https://arxiv.org/abs/2604.00055)
12. [ARM — 2026](https://arxiv.org/abs/2604.03037)
13. [SARM — ICLR 2026](https://arxiv.org/abs/2509.25358)
14. [Motion Planning-Augmented HRL — Sensors 2026](https://www.mdpi.com/1424-8220/26/12/3845)
