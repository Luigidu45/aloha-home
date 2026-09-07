# Estado del arte y propuesta de contribución para AlohaMini2–DimOS

**Tema:** planificación VLM explícita y en lazo cerrado para coordinar navegación semántica y políticas VLA, con verificación visual y recuperación de fallos
**Plataforma objetivo:** AlohaMini2 con dos brazos SO-101 y DimOS
**Fecha de corte de la revisión:** 26 de agosto de 2026
**Tipo de documento:** informe para definir una tesis de pregrado y su protocolo experimental

## Respuesta ejecutiva

La idea es viable y encaja bien con DimOS, pero **la combinación general no es novedosa por sí sola**. Ya existen sistemas que:

- descomponen instrucciones con un LLM/VLM y seleccionan skills;
- coordinan navegación y manipulación;
- entregan subtareas de alto nivel a una VLA;
- verifican visualmente el resultado y replanifican;
- usan memoria, herramientas y recuperación de fallos;
- e incluso combinan navegación modular, SmolVLA y un brazo SO-101 en hardware de consumo.

Por tanto, una tesis titulada simplemente “Integración de un VLM y una VLA en DimOS” sería un buen proyecto de ingeniería, pero una contribución científica débil. La formulación que recomiendo es:

> **Aprender y evaluar un contrato de transición consciente de competencia entre navegación semántica y políticas VLA, con verificación multicámara y recuperación jerárquica de fallos en un manipulador móvil de bajo costo.**

La pregunta científica sería:

> **¿Puede un modelo aprendido, condicionado por la política VLA y por observaciones multicámara, determinar cuándo una escena alcanzada por navegación semántica es realmente manipulable, reducir activaciones inválidas de la VLA y seleccionar recuperaciones que aumenten el éxito end-to-end?**

La diferencia no estaría en “tener un planner”, sino en convertir el punto débil entre navegación y manipulación en un objeto explícito de aprendizaje, medición y comparación.

## 1. Cómo debe entenderse el estado del arte

No existe un único número que represente “el estado del arte” en navegación y manipulación móvil. Los trabajos usan robots, sensores, tareas, niveles de autonomía y protocolos distintos. Un 80% en tareas de mesa no es comparable con un 47% en recorridos de edificio de quince minutos. Por eso la revisión se organiza por capacidades y no como un ranking único.

Además, conviene separar tres niveles:

1. **Planificación semántica:** convertir “ve al estante y trae el libro rojo” en subtareas y skills.
2. **Ejecución aprendida:** transformar visión, lenguaje y estado del robot en acciones de manipulación mediante ACT, diffusion policy o VLA.
3. **Orquestación en lazo cerrado:** decidir cuándo empezar/terminar cada skill, verificar resultados, atribuir fallos y recuperarse.

La tesis propuesta se ubica principalmente en el tercer nivel y usa los otros dos como componentes reemplazables.

## 2. Evolución del campo

### 2.1 Del LLM como selector de skills al agente con feedback

[SayCan](https://say-can.github.io/) estableció una arquitectura influyente: el LLM puntúa qué skill es útil para la orden y una función de valor aprendida estima qué skill es factible en el estado actual. Reportó 84% de éxito de planificación y 74% de ejecución sobre 101 instrucciones. Su contribución fundamental fue separar razonamiento lingüístico de affordance física. En consecuencia, seleccionar herramientas robóticas con un LLM ya no es una novedad.

[Inner Monologue](https://arxiv.org/abs/2207.05608) cerró el lazo al reinyectar descripciones de escena, detección de éxito y feedback humano al planner. Mostró que el LLM puede reintentar y replanificar, pero también que un success detector imperfecto produce falsos finales y planes equivocados. De aquí se desprende otra conclusión: agregar feedback visual a un LLM tampoco basta como contribución nueva.

[PaLM-E](https://palm-e.github.io/) integró directamente imágenes y estado continuo como entradas de un modelo multimodal embodied y demostró planificación de subtareas con observación actualizada. [RT-2](https://robotics-transformer2.github.io/) llevó conocimiento vision-language a acciones robóticas tokenizadas. Estos trabajos consolidaron la división entre razonamiento semántico y control aprendido, así como la alternativa de entrenarlos dentro de un modelo grande.

### 2.2 Manipulación móvil modular y de mundo abierto

[OK-Robot](https://ok-robot.github.io/) combinó memoria semántica RGB-D, recuperación open-vocabulary, A*, navegación y grasping en diez hogares reales. Logró 58,5% end-to-end zero-shot y 82,4% en escenarios más limpios. Su análisis es especialmente útil: los fallos se distribuyeron entre recuperación semántica, pose de manipulación y hardware. La lección es que el éxito de cada módulo por separado no garantiza éxito de la cadena.

[COME-robot](https://come-robot.github.io/) es uno de los antecedentes más cercanos a la frase original de la tesis. GPT-4V genera código que llama APIs de percepción, exploración, navegación y manipulación; cada llamada devuelve imágenes o resultados y el modelo verifica progreso, analiza causas y replantea. En tareas reales reportó una mejora aproximada de 25–35% frente a su referencia, dependiendo de la versión del reporte. La diferencia con la propuesta AlohaMini2 es que sus primitivas de manipulación son programadas, no una VLA SO-101 aprendida.

[BUMBLE](https://robin-lab.cs.utexas.edu/BUMBLE/) extendió esta línea a tareas de edificios: VLM central, percepción RGB-D, skills parametrizadas, mapa topológico, memoria del episodio y memoria de fallos. Evaluó más de 90 horas y 70 pruebas, con hasta 12 skills y 15 minutos por tarea, y obtuvo 47,1% de éxito. Es evidencia contundente de que VLM + skills + memoria + recuperación ya constituye una familia establecida, aunque todavía lejos de ser infalible.

### 2.3 VLM de alto nivel y VLA de bajo nivel

[Hi Robot](https://proceedings.mlr.press/v267/shi25d.html) coincide casi literalmente con la arquitectura “VLM planner → instrucción atómica → VLA”. Un VLM de alto nivel genera la siguiente subtarea y una política π0 la ejecuta; ambos observan el mundo y el sistema acepta correcciones humanas situadas. Se evaluó en brazo único, dual-arm y robot móvil dual-arm. Por ello, no sería defendible presentar como novedad la simple conexión de un VLM con una VLA.

[HAMSTER](https://hamster-robot.github.io/) muestra otra jerarquía: un VLM produce trayectorias visuales 2D gruesas y una política 3D ejecuta control preciso. Aunque se centra en tabletop, confirma que las representaciones intermedias entre VLM y policy son una línea de investigación madura.

[Agentic Robot](https://arxiv.org/abs/2505.23450) formaliza planner–VLA–temporal verifier y reporta 79,6% promedio en LIBERO. [VLA²](https://vla-2.github.io/) rodea una VLA con planificación, memoria/web retrieval, grounding y verificación de resultados. Ambos refuerzan que “planner, executor y verifier” ya no es una arquitectura inédita; el espacio abierto está en diseñar y demostrar una interfaz mejor para un contexto particular.

Los trabajos más recientes aumentan aún más la presión sobre una afirmación genérica de novedad. [What Matters in Orchestrating Robot Policies](https://arxiv.org/abs/2606.10267), preprint de 2026, estudia sistemáticamente planner, controlador, switching, terminación, observaciones y memoria en jerarquías VLA. [HiMe](https://happywaterxp.github.io/), también de 2026, usa una VLA rápida, un sentry VLM que detecta transiciones y un planner lento con memoria editable. Deben tratarse como evidencia reciente —no como consenso consolidado—, pero hacen insuficiente una tesis que solo compare plan-once contra closed-loop.

### 2.4 Navegación semántica aprendida

[NaVILA](https://navila-bot.github.io/) usa un VLM para producir comandos espaciales intermedios en lenguaje y una política visual RL de locomoción para ejecutarlos en Go2, H1 y T1. Esto valida la separación que DimOS ya favorece: el modelo semántico decide “hacia dónde” y un subsistema especializado ejecuta “cómo moverse”. NaVILA, sin embargo, se limita a navegación y no resuelve el traspaso a manipulación.

[Mobility VLA](https://arxiv.org/abs/2407.07775) usa un VLM de contexto largo para seleccionar un goal frame de un video-tour y un planner topológico para llegar. Reportó que pedir al VLM waypoints directos fue mucho peor que delegar la ejecución espacial a navegación especializada. Esto respalda mantener A*, costmap y control de base en DimOS, sin convertir la tesis en control geométrico.

### 2.5 Aprendizaje de manipulación móvil y el problema del “docking”

[Mobile ALOHA](https://mobile-aloha.github.io/) demostró behavior cloning bimanual de cuerpo completo en una plataforma de bajo costo, con 20–50 demostraciones por tarea y mejoras relativas de hasta 90% mediante co-training con datos estáticos. Es el antecedente natural del hardware AlohaMini2, aunque no ofrece planificación lingüística abierta ni recuperación agéntica.

[MoManipVLA](https://openaccess.thecvf.com/content/CVPR2025/html/Wu_MoManipVLA_Transferring_Vision-language-action_Models_for_General_Mobile_Manipulation_CVPR_2025_paper.html) transfiere una VLA de brazo fijo a mobile manipulation haciendo que produzca waypoints y optimizando base y brazo. Es un enfoque geométrico fuerte, pero reconoce que no estudia planificación larga. No coincide con la preferencia de esta tesis por robot learning, aunque constituye una referencia que debe superarse o excluirse explícitamente del alcance.

[Mobi-π](https://proceedings.mlr.press/v305/yang25b.html) es el antecedente más importante para el handoff. Formula “policy mobilization”: encontrar una pose de base en un entorno nuevo que se parezca a las vistas en las que fue entrenada la política de manipulación. Usa 3D Gaussian Splatting, síntesis de vistas, un score de idoneidad y optimización por muestreo, y supera al mejor baseline por 7,65× en simulación y 2,38× en el mundo real. Esto significa que ni siquiera “detener la base donde la policy pueda actuar” es completamente nuevo. La tesis debe diferenciarse por aprender un contrato **semántico, temporal y multimodal**, no solo optimizar una pose geométrica.

[AnywhereVLA](https://arxiv.org/abs/2509.21006) cierra otra posibilidad de novedad demasiado amplia: usa un grafo de tareas, SLAM LiDAR/cámara, semantic mapping, frontier exploration, approach planning y una SmolVLA afinada en una plataforma móvil con SO-101, RealSense, Jetson Orin NX y NUC. Reporta 46% end-to-end en 50 episodios reales. Por tanto, “SO-101 + SmolVLA + navegación clásica + compute consumidor” ya existe.

### 2.6 Verificación y recuperación de fallos

[VLMs as Success Detectors](https://proceedings.mlr.press/v232/du23b.html) mostró tempranamente que un VLM puede actuar como detector de éxito con cierta generalización open-vocabulary. Sin embargo, la transferencia a videos y condiciones realmente nuevas sigue siendo difícil.

[AHA](https://aha-vlm.github.io/) estudia detección y razonamiento de fallos mediante VLM y construye FailGen para generar fallos diversos. Reporta mejoras tanto en detección como en éxito de tarea al integrar el razonador. Su foco está principalmente en manipulación; no resuelve la frontera semántica navegación→VLA.

[SAFE](https://vla-safe.github.io/) usa características latentes de la propia VLA para detectar fallos, incluidos casos no vistos, y calibra umbrales mediante conformal prediction. Es una referencia muy cercana para incertidumbre y seguridad: enseña que un judge VLM externo no es la única opción y que las señales internas de la policy pueden ser más informativas. SAFE detecta fallos, pero no constituye por sí solo una política completa de recuperación móvil.

[REAL](https://internrobotics.github.io/REAL/), preprint reciente de 2026, es un competidor especialmente cercano. Emplea un high-level policy visual, herramientas con interfaz consistente entre simulación y robot, entrenamiento supervisado más RL online, exploración, recuperación y preguntas al usuario. Incluso usa MCP como esquema de herramientas. Reporta 78,3% de éxito en 60 episodios físicos de un robot móvil dual-arm. La consecuencia es clara: ni MCP, ni tool use, ni sim-to-real, ni RL de recuperación pueden reivindicarse aisladamente como novedad.

[BATON](https://arxiv.org/abs/2608.16889), preprint del 17 de agosto de 2026, estrecha todavía más el espacio: introduce un agente verificador, confirmación desde wrist camera antes de invocar una VLA, lookahead de transición y memoria consciente de transiciones. Reporta mejoras de 11,6 puntos de éxito y 14,9 de reward acumulado en RoboMemArena. Su evaluación se concentra en manipulación y primitivas analíticas de espacio libre, sin navegación móvil ni estudio sim-to-real low-cost. Aun así, impide afirmar que “verificación del handoff” o “memoria de transición” sean nuevas por sí solas.

También son relevantes [DoReMi](https://arxiv.org/abs/2307.00329), que verifica constraints visuales durante una skill y puede abortar/replanificar, y [REFLECT](https://arxiv.org/abs/2306.15724), que combina RGB-D, audio y propriocepción para localizar, explicar y corregir fallos. Ambos confirman que monitorización visual y diagnóstico multimodal son antecedentes sólidos, aunque se centran principalmente en manipulación y no en la frontera navegación–VLA.

[MoMaStage](https://arxiv.org/abs/2603.08383), preprint de marzo de 2026, restringe al VLM mediante una biblioteca jerárquica de skills y un Skill-State Graph; verifica estado propio con propriocepción y replantea sin depender de un mapa explícito. Su estructura hace la ejecución auditable, pero parte del grafo y la biblioteca son diseñados y la recuperación queda limitada a estados anticipados. [Goal2Skill](https://arxiv.org/abs/2604.13942) combina memoria de tarea, descomposición, outcome verification, corrección y una diffusion/VLA de bajo nivel; reporta 32,4% promedio en RMBench frente a 9,8% del mejor baseline citado. Ambos se concentran sobre todo en manipulación, no en el handoff móvil.

[FailSafe](https://arxiv.org/abs/2510.01642) y [FLARE](https://openaccess.thecvf.com/content/CVPR2026/html/Zhao_FLARE_A_Failure-Aware_Framework_for_Autonomous_Correction_and_Recovery_in_CVPR_2026_paper.html) muestran que la recuperación de policies ya es un subcampo propio. FailSafe monitoriza periódicamente e inyecta correcciones; FLARE separa errores recuperables por reintento de estados OOD que requieren reset. Sus evaluaciones se centran en manipulación, pero obligan a que el aporte AlohaMini2 cubra fallos entre niveles y no se presente simplemente como “recovery para VLA”.

## 3. Matriz comparativa

La siguiente tabla no compara porcentajes entre benchmarks; compara capacidades publicadas.

| Sistema | Navegación móvil | VLM/LLM de alto nivel | Policy/VLA aprendida | Verificación cerrada | Recuperación | Brecha respecto a la tesis propuesta |
|---|---:|---:|---:|---:|---:|---|
| SayCan | Sí | Sí | Skills/value functions | Parcial | Re-selección limitada | No handoff VLA multicámara |
| Inner Monologue | Parcial | Sí | Skills | Sí | Sí | Verificador genérico y dominio acotado |
| OK-Robot | Sí | Parcial | Grasp model | Limitada | Máquina de estados | Pipeline abierto y sin policy-conditioned gate |
| COME-robot | Sí | Sí | No VLA general | Sí | Sí | Primitivas programadas |
| BUMBLE | Sí | Sí | Skills diseñadas | Sí | Sí | No contrato aprendido para una VLA concreta |
| Hi Robot | Sí | Sí | Sí | Feedback situado | Parcial | No estudio sistemático del handoff móvil |
| NaVILA | Sí | Sí | RL locomoción | Sí | Parcial | Sin manipulación |
| Agentic Robot / VLA² | No o limitada | Sí | Sí | Sí | Sí | Principalmente manipulación simulada/tabletop |
| Mobi-π | Sí | No necesariamente | Sí | Score pre-ejecución | Reposicionamiento | Foco geométrico y reconstrucción 3D por entorno |
| AnywhereVLA | Sí | Grafo de tareas | SmolVLA/SO-101 | Limitada | Limitada | La integración base ya existe |
| REAL | Sí | Sí, entrenado | Sí | Sí | Sí, aprendida | Muy cercano; gran escala y otra pregunta experimental |
| BATON | No | Sí | Sí | Wrist + transición | Sí | Manipulación; sin handoff desde navegación móvil |
| Propuesta | DimOS | Plan estructurado | SmolVLA/ACT | Pre y post, multicámara | Skills discretas DimOS | Contrato calibrado, policy-conditioned y evaluación causal del handoff |

## 4. El hueco defendible

Los trabajos anteriores dejan una tensión que sigue siendo relevante:

- El navegador declara que llegó a un destino geométrico o semántico.
- La VLA solo funciona bien dentro de una distribución perceptual estrecha: distancia, escala del objeto, oclusión, fondo, iluminación, pose del brazo, estado del gripper y cámaras.
- Un VLM genérico puede decir “parece listo”, pero no necesariamente conoce la frontera real de competencia de esa policy.
- Si el sistema activa la VLA demasiado pronto, desperdicia intentos, puede golpear el entorno o atribuir el fallo al componente equivocado.
- Si es demasiado conservador, navega/reobserva indefinidamente y eleva latencia y costo.

El hueco puede formularse como **estimación aprendida de readiness y outcome para una policy específica, en la frontera entre skills heterogéneas**.

### Definición propuesta: contrato de skill aprendido

Para una skill de manipulación \(\pi_i\), el contrato estima:

\[
q_{ready} = P(\text{éxito de } \pi_i \mid o_{t-k:t},\; s_{nav},\; s_{robot},\; g,\; i)
\]

donde:

- \(o_{t-k:t}\): historial corto de cámaras frontal/chest/wrists y, si se usa, profundidad;
- \(s_{nav}\): destino, llegada, distancia restante, bloqueo y orientación disponible;
- \(s_{robot}\): articulaciones, apertura del gripper, contacto/estado y E-STOP;
- \(g\): subtarea semántica estructurada;
- \(i\): identidad o embedding de la policy VLA que se pretende activar.

Además del score, el modelo devuelve:

1. validez de precondiciones;
2. validez de postcondiciones;
3. clase de fallo estructurada;
4. recuperación discreta recomendada.

Taxonomía inicial de fallos:

- `OBJECT_NOT_FOUND`
- `WRONG_OBJECT`
- `TOO_FAR_OR_BAD_VIEW`
- `OCCLUDED`
- `GRIPPER_NOT_READY`
- `NAVIGATION_FAILED`
- `GRASP_FAILED`
- `OBJECT_DROPPED`
- `PLACE_FAILED`
- `UNKNOWN_OR_UNCERTAIN`

Acciones de recuperación:

- reobservar desde otra cámara;
- girar o reposicionar localmente la base mediante una skill de DimOS;
- volver a navegación semántica;
- reintentar la VLA desde una condición aceptada;
- cambiar de policy;
- pedir aclaración al usuario;
- abortar de forma segura.

El VLM sigue produciendo un plan semántico, pero un coordinador determinista aplica el contrato y los límites. La VLA conserva el control de la manipulación; DimOS conserva navegación, coordinación, observabilidad y seguridad. No se requiere investigar IK ni control articular.

## 5. Contribuciones de tesis propuestas

### C1. Formulación del problema

Formalizar el handoff navegación→VLA como una decisión de competencia condicionada por policy, no como una simple condición `goal_reached`. Esta formulación integra preparación perceptual, estado del robot y resultados reales de la policy.

### C2. Modelo de contrato aprendido y calibrado

Entrenar un modelo pequeño o VLM adaptado para precondiciones, postcondiciones, readiness y fallo. La calibración importa: un score de 0,8 debería corresponder aproximadamente a un 80% de éxito bajo la distribución evaluada. Se medirían ECE, Brier score y curvas riesgo–cobertura, no solo accuracy.

### C3. Política jerárquica de recuperación sobre skills de DimOS

El modelo no genera velocidades ni ángulos. Selecciona acciones discretas seguras y observables. Esto mantiene la investigación dentro de robot learning y planificación agéntica, a la vez que aprovecha la arquitectura modular de DimOS.

### C4. Benchmark de fallos sim-to-real para AlohaMini2-SO101

Crear tareas, perturbaciones, etiquetas de transición y protocolos reproducibles. El dataset incluiría episodios exitosos y fallidos, no solo demostraciones perfectas. Esta parte es valiosa porque los modelos de fallo necesitan ejemplos negativos que rara vez contienen los datasets de imitación.

### C5. Evidencia causal mediante baselines y ablaciones

Demostrar qué aporta cada componente: multicámara, condicionamiento por policy, calibración, memoria corta y recovery. Esta es la diferencia entre una integración y una investigación.

### C6. Contribución de sistema abierta

Publicar blueprint, drivers, modelo MuJoCo, herramientas de recolección, checkpoints permitidos, logs Rerun y protocolo experimental. Es una contribución de ingeniería importante, pero debe acompañar —no sustituir— C1–C5.

## 6. Qué tendría de mejor el método

Las siguientes son **hipótesis a validar**, no ventajas que puedan afirmarse antes de experimentar.

### Frente al agente actual de DimOS

El agente actual descubre herramientas MCP y las entrega a un agente LangChain. La navegación semántica intenta ubicación etiquetada, objeto visible y mapa semántico. Sin embargo, la propia implementación reconoce una brecha: `navigate_with_text` puede retornar “Started navigating” y liberar la capacidad de movimiento antes de confirmar que la navegación terminó. Véanse [navigation.py](/home/luigidu/dimos/dimos/agents/skills/navigation.py:112) y [mcp_client.py](/home/luigidu/dimos/dimos/agents/mcp/mcp_client.py:239).

La propuesta mejoraría esto con estado explícito, eventos de terminación y pre/postcondiciones. El LLM dejaría de interpretar un mensaje de inicio como éxito físico.

### Frente a un VLM judge genérico

Un judge genérico reconoce semántica, pero puede no saber que SmolVLA falla cuando el objeto ocupa cierta escala, que ACT necesita una configuración inicial específica o que una muñeca está ocluida. El contrato aprende de los resultados de la policy real y está condicionado por su identidad. La mejora esperada es reducir falsos positivos de readiness.

### Frente a Mobi-π

Mobi-π optimiza una pose de base compatible con la distribución visual usando una reconstrucción 3D por entorno. La propuesta:

- no exige construir un Gaussian Splat de cada entorno;
- incorpora semántica, historial, gripper y outcome, no solo pose/vista;
- cubre precondiciones y postcondiciones;
- decide entre múltiples recuperaciones y no únicamente reposicionamiento.

No obstante, Mobi-π debe ser baseline conceptual; no sería honesto afirmar que el problema de transición se descubre por primera vez.

### Frente a SAFE, AHA y BATON

SAFE y AHA detectan o razonan fallos durante/tras manipulación. El contrato propuesto también actúa **antes** de entregar el control a la VLA y atribuye fallos entre navegación, observación y manipulación. Puede combinar señales externas multicámara con señales internas de la policy.

BATON ya verifica una transición antes de activar la VLA, por lo que la diferencia debe medirse con precisión: navegación móvil semántica real, readiness condicionado por la policy y calibrado con sus resultados, recovery que cruza niveles —reobservación, reposicionamiento de base, nueva navegación, reintento o consulta al usuario— y transferencia MuJoCo→AlohaMini2 físico.

### Frente a BUMBLE y COME-robot

Estos sistemas usan razonamiento VLM alrededor de skills. La propuesta sustituye parte del juicio libre por un predictor calibrado con salidas estructuradas y mide explícitamente sus errores. Se espera menor costo de inferencia, más auditabilidad y menos recovery improvisado.

### Frente a AnywhereVLA

AnywhereVLA prueba que la integración SO-101/SmolVLA/navegación es posible. La tesis añadiría una pregunta científica que aquel sistema no aísla: cómo se decide el handoff, cómo se calibra contra el éxito real y cuánto aporta cada recuperación bajo fallos controlados.

### Frente a REAL

REAL entrena un high-level policy con tool use, RL y recuperación a mayor escala. La propuesta no competiría en apertura de mundo o volumen de datos; competiría en **interpretabilidad del contrato, calibración, atribución de fallos y eficiencia de datos/cómputo** en una plataforma low-cost. Si se usa RL, conviene limitarlo a seleccionar recuperaciones discretas sobre un estado aprendido, no intentar entrenar el robot completo end-to-end.

### Frente a una VLA monolítica de gran escala

Modelos industriales recientes pueden internalizar navegación, razonamiento y acción con enormes datasets. Una tesis de pregrado no debe intentar vencerlos por escala. Su ventaja potencial es modularidad, reemplazo independiente de policies, explicación de fallos, ejecución local y recolección de datos asequible.

## 7. Arquitectura experimental recomendada

```text
Orden del usuario
       │
       ▼
VLM planner ──► plan JSON con subtareas, precondiciones y criterio de éxito
       │
       ▼
Coordinador de DimOS / máquina de estados observable
       │
       ├──► navegación semántica DimOS ─► evento real de llegada/fallo
       │                                      │
       │                                      ▼
       │                            contrato aprendido de readiness
       │                              │ aceptar       │ rechazar
       │                              ▼               ▼
       │                          VLA/ACT       recovery DimOS
       │                              │               │
       │                              ▼               └──► reobservar/reubicar
       └──────────────────── verificador de outcome
                                      │
                           éxito / fallo tipado / replanning
```

### Plan semántico estructurado

El VLM no debería devolver prosa libre. Un esquema mínimo:

```json
{
  "goal": "entregar el libro rojo al usuario",
  "steps": [
    {
      "id": "navigate_shelf",
      "skill": "navigate_semantic",
      "target": "estante de libros",
      "success": "shelf_reached_and_book_visible"
    },
    {
      "id": "pick_book",
      "skill": "vla_pick",
      "object": "libro rojo",
      "policy": "smolvla_pick_v1",
      "requires": ["manipulation_ready", "gripper_empty"]
    }
  ]
}
```

El coordinador valida el esquema, registra cada transición y solo ejecuta skills permitidas. La prosa del VLM nunca debe interpretarse como una orden motora directa.

### Modelo del contrato

Para pregrado recomiendo comenzar con tres alternativas de complejidad creciente:

1. **Baseline supervisado liviano:** embeddings de un VLM congelado + MLP/transformer temporal pequeño.
2. **Adaptación eficiente:** LoRA sobre SmolVLM/Qwen-VL pequeño para clasificación estructurada.
3. **Extensión opcional:** señales internas de SmolVLA más imágenes para failure detection tipo SAFE.

El output puede ser multitarea: `ready`, `success`, `failure_class`, `recovery_action`. El entrenamiento usa cross-entropy/focal loss y una pérdida de calibración. La selección de recovery puede iniciarse por behavioral cloning de reglas/teleoperación y, como extensión, offline RL o contextual bandit.

### VLA de manipulación

[SmolVLA](https://arxiv.org/abs/2506.01844) es una elección razonable por tamaño, apertura y soporte en el ecosistema LeRobot/SO-100/SO-101. ACT también sirve como baseline específico por tarea. No conviene entrenar una VLA fundacional desde cero; el objetivo es estudiar la orquestación y el contrato.

## 8. Encaje con la implementación actual de AlohaMini2

La base existente es útil:

- [alohamini2_nav_sim.py](/home/luigidu/dimos/dimos/robot/alohamini2/blueprints/alohamini2_nav_sim.py:364) ya compone navegación MuJoCo y control/manipulación dual SO-101;
- el stack incluye voxel map, costmap, replanning A* y MovementManager;
- las cámaras del modelo se publican y Rerun aporta observabilidad;
- DimOS ya posee grabación y exportación a LeRobot/HDF5 en [imitation/README.md](/home/luigidu/dimos/dimos/imitation/README.md:1);
- SpatialMemory asocia información con posiciones en [spatial_perception.py](/home/luigidu/dimos/dimos/perception/spatial_perception.py:69).

Hay cuatro brechas concretas que deben resolverse antes del experimento:

1. **Evento de finalización real:** la skill de navegación debe ser background/async y emitir `reached`, `failed`, `cancelled` o `timeout`, no solo “started”.
2. **Percepción para learning:** en la configuración actual `enable_color=False` y `enable_depth=False` en [alohamini2_nav_sim.py](/home/luigidu/dimos/dimos/robot/alohamini2/blueprints/alohamini2_nav_sim.py:213). Para entrenar/verificar habrá que habilitar las cámaras necesarias y controlar resolución/FPS para no degradar la simulación.
3. **VLA real:** el blueprint actual controla articulaciones y planifica, pero todavía necesita un módulo que consuma observación/estado/lenguaje y produzca action chunks para SO-101.
4. **Blueprint agéntico:** crear `alohamini2-agentic-vla-sim` con `McpServer`, `McpClient`, prompt específico, coordinador de tareas, contrato, recorder y Rerun; después un gemelo `alohamini2-agentic-vla` para hardware.

## 9. Diseño experimental

### 9.1 Alcance aconsejado

Para que sea terminable y publicable como pregrado:

- un entorno indoor conocido con cambios de objetos;
- tres clases de objeto: libro, manzana y botella/caja;
- dos fuentes: estante y mesa;
- un destino de entrega;
- un solo brazo en la primera evaluación; dual-arm como extensión;
- dos policies como máximo: SmolVLA y ACT, o dos checkpoints de SmolVLA;
- tres tareas largas.

Tareas sugeridas:

1. “Ve al estante, toma el libro rojo y tráemelo”.
2. “Ve a la mesa, recoge la manzana y déjala en la bandeja”.
3. “Busca la botella solicitada; si hay ambigüedad, pregunta antes de traerla”.

### 9.2 Perturbaciones

- objeto ausente, cambiado de posición o distractor similar;
- navegación termina demasiado lejos o con mala vista;
- oclusión de chest o wrist camera;
- iluminación/textura alterada en simulación;
- gripper inicialmente ocupado o fuera de home;
- grasp fallido;
- objeto deslizado/caído después del agarre;
- obstáculo que obliga a replanificar;
- corrección del usuario a mitad de tarea.

Estas perturbaciones deben aplicarse con semillas y niveles de dificultad documentados.

### 9.3 Baselines mínimos

- **B0 — cadena fija:** navegar, lanzar VLA y volver, sin verifier.
- **B1 — agente DimOS libre:** LLM llama tools según mensajes actuales.
- **B2 — VLM plan-once:** plan estructurado al inicio, sin replanning.
- **B3 — VLM judge:** verificación visual genérica después de cada skill.
- **B4 — reglas:** máquina de estados con umbrales y recovery manual.
- **B5 — contrato propuesto:** predictor policy-conditioned, calibrado y multicámara.

Si el tiempo alcanza, añadir un baseline inspirado en Mobi-π —score de similitud con vistas exitosas o nearest-neighbor— sin tener que reproducir toda la reconstrucción 3DGS.

### 9.4 Métricas

**Métrica primaria**

- éxito end-to-end de la orden completa.

**Handoff**

- \(P(\text{manipulable}\mid\text{navegación reportó llegada})\);
- \(P(\text{éxito VLA}\mid\text{handoff aceptado})\);
- tasa de lanzamientos inválidos de la VLA;
- cobertura: fracción de estados que el sistema se atreve a aceptar.

**Verificación**

- precision, recall, F1 y AUROC por clase de fallo;
- ECE y Brier score del readiness;
- latencia de detección;
- falsos “éxito” y falsos “no listo”.

**Recuperación**

- éxito por tipo de recovery;
- éxito después de 1, 2 y 3 intentos;
- porcentaje de fallos correctamente atribuidos a navegación, percepción o VLA.

**Costo operativo**

- duración, distancia y energía aproximada;
- número de llamadas VLM, tokens/costo y latencia;
- cantidad de ejecuciones VLA desperdiciadas;
- intervenciones humanas y eventos inseguros.

**Sim-to-real**

- brecha absoluta de éxito;
- degradación de calibración;
- clases de fallo nuevas en hardware.

### 9.5 Ablaciones

- chest solamente frente a chest + wrist frente a todas las cámaras;
- sin profundidad frente a RGB-D;
- sin historial temporal;
- sin estado del gripper/propriocepción;
- modelo genérico frente a condicionado por policy;
- sin calibración;
- sin memoria semántica;
- sin recovery, recovery por reglas y recovery aprendido;
- plan VLM libre frente a JSON validado.

### 9.6 Estadística

Usar muchas ejecuciones simuladas y un conjunto físico más pequeño pero balanceado. Para hardware, 10–20 episodios por método y condición ya representan bastante trabajo; si son menos, debe reconocerse como limitación. Reportar intervalos de Wilson para éxito binario, bootstrap para diferencias y las mismas semillas/escenas entre métodos cuando sea posible. No reportar solo el “mejor intento”.

## 10. Fases de ejecución

### Fase 1 — Base reproducible en simulación

- corregir eventos de navegación;
- definir task-state schema y logs;
- integrar una policy ACT/SmolVLA de una sola tarea;
- construir B0–B4;
- generar fallos controlados y recorder.

**Criterio de salida:** una orden completa se ejecuta, cada transición queda registrada y el fallo puede reproducirse por semilla.

### Fase 2 — Dataset de contratos

- recolectar estados antes/durante/después de la VLA;
- balancear positivos y fallos difíciles;
- etiquetar readiness, outcome, failure y recovery;
- separar escenas/objetos/semillas entre train, validation y test.

**Criterio de salida:** dataset versionado, inspeccionable y sin leakage obvio.

### Fase 3 — Modelo y evaluación en simulación

- entrenar predictor liviano;
- calibrar umbral según riesgo;
- comparar B0–B5;
- ejecutar ablaciones multicámara y policy-conditioned.

**Criterio de salida:** mejora estadísticamente defendible o resultado negativo claro con análisis de fallos.

### Fase 4 — Construcción y transferencia al robot

- drivers reales de base, brazos, cámaras y E-STOP;
- calibración extrínseca y sincronización;
- shadow mode: el contrato predice sin controlar;
- pruebas progresivas con objetos blandos y límites conservadores;
- fine-tuning/recalibración con pocos episodios reales.

**Criterio de salida:** evaluación física pre-registrada, no una demostración seleccionada.

### Fase 5 — Escritura y liberación

- failure taxonomy y evidencia cualitativa en Rerun;
- tablas con intervalos de confianza;
- repositorio reproducible y guía de despliegue;
- discusión honesta de condiciones donde las reglas ganan al modelo.

## 11. Formulación de tesis recomendada

### Título principal

> **Contratos de skills aprendidos para el traspaso consciente de competencia entre navegación semántica y políticas VLA en un manipulador móvil de bajo costo**

### Título que conserva el énfasis agéntico

> **Planificación VLM en lazo cerrado con traspaso consciente de competencia para navegación y manipulación móvil en AlohaMini2-SO101**

### Título conservador y muy defendible

> **Diseño y evaluación de un protocolo perceptualmente verificado de transición entre navegación semántica y manipulación VLA en AlohaMini2-SO101**

### Objetivo general

Diseñar y evaluar una arquitectura jerárquica en DimOS que interprete instrucciones de lenguaje, coordine navegación semántica y políticas VLA, y aprenda a validar y recuperar la transición entre ambas mediante observaciones multicámara y estado del robot.

### Objetivos específicos

1. Implementar una interfaz estructurada y observable entre planner, navegación y VLA.
2. Construir un dataset sim-to-real de estados de handoff, resultados y fallos.
3. Entrenar y calibrar un modelo policy-conditioned de readiness/outcome.
4. Implementar recuperaciones discretas sobre skills seguras de DimOS.
5. Comparar el método contra cadena fija, VLM judge y reglas manuales.
6. Medir éxito, calibración, costo, recovery y transferencia al robot físico.

## 12. Qué no conviene afirmar

Evitar estas frases:

- “primer robot que combina VLM y VLA”;
- “primer agente con navegación y manipulación”;
- “primera recuperación visual de fallos”;
- “primer uso de MCP para robótica”;
- “primera integración de SmolVLA con SO-101 móvil”;
- “primer sistema VLM–VLA en lazo cerrado”;
- “primer sistema que verifica el handoff o usa memoria de transición”;
- “supera el estado del arte” sin un benchmark común.

Una afirmación prudente sería:

> Proponemos y evaluamos un contrato aprendido, condicionado por la política de manipulación, para validar y recuperar la transición entre navegación semántica y ejecución VLA en una plataforma móvil SO-101 de bajo costo.

Incluso “primer contrato” debe reservarse hasta realizar una búsqueda bibliográfica final antes de enviar la tesis. La contribución no necesita ser la primera absoluta; necesita ser nueva respecto a antecedentes definidos, técnicamente razonable y respaldada por evidencia.

## 13. Riesgos y decisiones de alcance

### Riesgo: terminar haciendo solo integración

Mitigación: predefinir hipótesis, baselines, métricas y ablaciones antes de implementar el modelo final.

### Riesgo: la policy VLA domina todos los fallos

Mitigación: comenzar con una tarea en la que la VLA alcance un éxito razonable desde condiciones válidas. Si falla incluso en distribución, no se podrá medir el handoff.

### Riesgo: muy pocos datos físicos

Mitigación: simulación con domain randomization moderado, shadow mode, calibración con pocos datos y énfasis en el cambio de distribución, no en entrenar todo desde cero.

### Riesgo: un VLM grande es lento/costoso

Mitigación: usar el VLM en cambios de subtask y fallos, no a frecuencia de control. El contrato pequeño opera con mayor frecuencia.

### Riesgo: reglas simples ganan

Ese resultado no invalida la tesis si el protocolo es correcto. Puede mostrar que, bajo un entorno muy acotado, las reglas son más eficientes, mientras el modelo gana al introducir objetos, vistas o policies nuevas. La publicación debe incluir ambos regímenes.

## 14. Conclusión

DimOS es una base apropiada porque ya separa módulos, streams, skills, navegación, visualización, MCP y ejecución de hardware. AlohaMini2 aporta una plataforma low-cost poco explorada y el SO-101 ofrece un ecosistema de imitation learning accesible. Sin embargo, esos elementos son infraestructura.

El aporte científico más fuerte es estudiar la frontera donde la navegación deja al robot y la VLA toma el control. Esa frontera concentra errores de distribución, percepción y atribución que los sistemas actuales suelen resolver con reglas, geometría específica o juicio VLM no calibrado. Un contrato policy-conditioned, multicámara y medido causalmente puede aportar:

- una formulación clara del problema;
- un modelo de readiness/outcome con incertidumbre;
- una estrategia de recuperación auditable;
- un benchmark sim-to-real de fallos;
- evidencia de cuándo el aprendizaje supera —o no— al VLM genérico y a las reglas.

Esta formulación mantiene la tesis dentro de robot learning, aprovecha realmente la navegación agéntica de DimOS y es suficientemente acotada para una tesis de pregrado sin renunciar a una posible publicación.

## Referencias primarias seleccionadas

- [SayCan — Ahn et al., 2022](https://arxiv.org/abs/2204.01691)
- [Inner Monologue — Huang et al., 2022](https://arxiv.org/abs/2207.05608)
- [PaLM-E — Driess et al., 2023](https://arxiv.org/abs/2303.03378)
- [VLMs as Success Detectors — Du et al., 2023](https://proceedings.mlr.press/v232/du23b.html)
- [OK-Robot — Liu et al., 2024](https://ok-robot.github.io/)
- [Mobile ALOHA — Fu et al., 2024](https://mobile-aloha.github.io/)
- [COME-robot — Zhi et al., ICRA 2025](https://come-robot.github.io/)
- [BUMBLE — Shah et al., ICRA 2025](https://robin-lab.cs.utexas.edu/BUMBLE/)
- [NaVILA — Cheng et al., RSS 2025](https://navila-bot.github.io/)
- [HAMSTER — Li et al., ICLR 2025](https://hamster-robot.github.io/)
- [Hi Robot — Shi et al., ICML 2025](https://proceedings.mlr.press/v267/shi25d.html)
- [MoManipVLA — Wu et al., CVPR 2025](https://openaccess.thecvf.com/content/CVPR2025/html/Wu_MoManipVLA_Transferring_Vision-language-action_Models_for_General_Mobile_Manipulation_CVPR_2025_paper.html)
- [Mobi-π — Yang et al., CoRL 2025](https://proceedings.mlr.press/v305/yang25b.html)
- [AHA — failure detection and reasoning, ICLR 2025](https://aha-vlm.github.io/)
- [SAFE — failure detection for VLAs, NeurIPS 2025](https://vla-safe.github.io/)
- [SmolVLA — Shukor et al., 2025](https://arxiv.org/abs/2506.01844)
- [AnywhereVLA — Gubernatorov et al., 2025](https://arxiv.org/abs/2509.21006)
- [Agentic Robot — Yang et al., 2025](https://arxiv.org/abs/2505.23450)
- [VLA² — Zhao et al., 2025](https://vla-2.github.io/)
- [What Matters in Orchestrating Robot Policies — Hu et al., preprint 2026](https://arxiv.org/abs/2606.10267)
- [HiMe — Ji et al., ICML 2026](https://happywaterxp.github.io/)
- [REAL — Mi et al., preprint/ECCV 2026](https://internrobotics.github.io/REAL/)
- [BATON — Xu et al., preprint 2026](https://arxiv.org/abs/2608.16889)
- [MoMaStage — Li et al., preprint 2026](https://arxiv.org/abs/2603.08383)
- [Goal2Skill — Liu et al., preprint 2026](https://arxiv.org/abs/2604.13942)
- [FailSafe — Lin et al., preprint 2025](https://arxiv.org/abs/2510.01642)
- [FLARE — Zhao et al., CVPR 2026](https://openaccess.thecvf.com/content/CVPR2026/html/Zhao_FLARE_A_Failure-Aware_Framework_for_Autonomous_Correction_and_Recovery_in_CVPR_2026_paper.html)
- [DoReMi — Guo et al., 2023/2024](https://arxiv.org/abs/2307.00329)
- [REFLECT — Liu et al., CoRL 2023](https://arxiv.org/abs/2306.15724)
- [Xiaomi-Robotics-1 — preprint 2026](https://arxiv.org/abs/2607.15330)
