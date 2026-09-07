# Registro canónico de investigación

Fecha de corte: 2026-08-26
Pregunta: ¿cuál es el estado del arte y cuál sería una contribución defendible para un planificador VLM explícito y en lazo cerrado que coordine navegación semántica DimOS y políticas VLA, con verificación visual y recuperación?

## Dictamen

La arquitectura genérica ya no es novedosa. SayCan e Inner Monologue establecieron selección de skills y replanning con feedback; COME-robot y BUMBLE integraron navegación/manipulación, verificación y recuperación; Hi Robot estableció VLM alto + VLA bajo; Agentic Robot, VLA², HiMe y trabajos posteriores integran planner, executor, verifier y memoria; AnywhereVLA ya combina navegación modular, SmolVLA, SO-101 y compute de consumo; REAL usa incluso una interfaz MCP para tool use, entrenamiento jerárquico y despliegue móvil real.

La contribución recomendable es formular y evaluar el problema de **handoff consciente de competencia**: estimar si el estado perceptual alcanzado por la navegación está dentro de la distribución de éxito de una política VLA específica, bloquear activaciones inválidas, atribuir el fallo y seleccionar una recuperación discreta de DimOS.

## Libro mayor de afirmaciones y evidencia

| Afirmación | Evidencia primaria | Calidad / cautela |
|---|---|---|
| LLM seleccionando skills por utilidad y affordance no es nuevo | SayCan, https://arxiv.org/abs/2204.01691 | Conferencia/publicación consolidada |
| Feedback de escena/éxito y replanning no es nuevo | Inner Monologue, https://arxiv.org/abs/2207.05608 | Conferencia; algunos descriptores/verificadores no generalistas |
| Memoria semántica + navegación + manipulación modular no es nuevo | OK-Robot, https://ok-robot.github.io/ | Real, 10 hogares; pipeline parcialmente abierto/manual |
| VLM cerrado con verificación y recuperación móvil no es nuevo | COME-robot, https://come-robot.github.io/ | Real, dominio pequeño; primitivas programadas, no VLA |
| VLM central, skills, memoria y recuperación a escala de edificio no es nuevo | BUMBLE, https://robin-lab.cs.utexas.edu/BUMBLE/ | Real, 90+ horas; skills diseñadas |
| High-level VLM que entrega subtareas atómicas a VLA no es nuevo | Hi Robot, https://proceedings.mlr.press/v267/shi25d.html | ICML 2025; incluye robot móvil dual-arm |
| Navegación semántica jerárquica VLM + locomoción aprendida no es nuevo | NaVILA, https://navila-bot.github.io/ | RSS 2025; solo navegación |
| Planner–executor–verifier tampoco es nuevo | Agentic Robot, https://arxiv.org/abs/2505.23450 | Preprint; principalmente LIBERO |
| Verificación/fallo mediante VLM no es nuevo | AHA, https://aha-vlm.github.io/ | ICLR 2025; fuerte en detección/razonamiento, principalmente manipulación |
| Detección de fallos desde latentes VLA con calibración no es nueva | SAFE, https://vla-safe.github.io/ | NeurIPS 2025; detecta, no ejecuta recuperación completa |
| SO-101 + SmolVLA + navegación modular en compute consumidor no es nuevo | AnywhereVLA, https://arxiv.org/abs/2509.21006 | Preprint/sistema real; 46% global reportado |
| El docking/base pose condicionado a una policy ya está formulado | Mobi-pi, https://proceedings.mlr.press/v305/yang25b.html | CoRL 2025; 3DGS y score de pose |
| Orquestación Hi-VLA ya tiene un estudio sistemático | What Matters in Orchestrating Robot Policies, https://arxiv.org/abs/2606.10267 | Preprint 2026; tabletop ALOHA, muy cercano conceptualmente |
| Tool use MCP + agente entrenado + VLA móvil ya existe | REAL, https://internrobotics.github.io/REAL/ | Preprint/ECCV 2026; 78.3% en 60 episodios físicos reportados |
| Verifier, wrist confirmation y transition-aware memory ya existen | BATON, https://arxiv.org/abs/2608.16889 | Preprint muy reciente (17-08-2026); manipulación, no navegación móvil |
| Skill-State Graph con verificación proprioceptiva y replanning ya existe | MoMaStage, https://arxiv.org/abs/2603.08383 | Preprint 2026; parte del grafo es diseñado |
| Memoria, outcome verification y corrección con VLA ya existen | Goal2Skill, https://arxiv.org/abs/2604.13942 | Preprint 2026; manipulación, no navegación móvil |
| Escala end-to-end es un competidor fuerte pero inaccesible | Xiaomi-Robotics-1, https://arxiv.org/abs/2607.15330 | Preprint industrial 2026; escala incomparable con pregrado |

## Auditoría de DimOS/AlohaMini2

- `McpClient` descubre tools MCP y usa `create_agent`: `dimos/agents/mcp/mcp_client.py:149`, `:239`.
- `navigate_with_text` consulta ubicación etiquetada, objeto visible y mapa semántico: `dimos/agents/skills/navigation.py:121`.
- Existe un TODO relevante: la skill devuelve “Started navigating” y libera el recurso movimiento antes de confirmar llegada: `dimos/agents/skills/navigation.py:112`.
- `alohamini2_nav_manip_sim` ya compone navegación MuJoCo y manipulación SO101: `dimos/robot/alohamini2/blueprints/alohamini2_nav_sim.py:364`.
- En la configuración actual, color y depth están desactivados aunque existen cámaras: `dimos/robot/alohamini2/blueprints/alohamini2_nav_sim.py:213`.
- DimOS tiene pipeline de grabación y exportación LeRobot/HDF5: `dimos/imitation/README.md`.
- La memoria espacial asocia observaciones con posiciones: `dimos/perception/spatial_perception.py:69`.

## Hipótesis central

Un contrato de skills aprendido y condicionado por la política VLA, entrenado con resultados reales/simulados, aumentará el éxito end-to-end y reducirá las activaciones inválidas frente a: cadena fija, VLM plan-once, verificador VLM genérico y máquina de estados manual.

El contrato recibe instrucción/subtarea, identificador de policy, observaciones multicámara, estado del gripper/propriocepción, estado de navegación, memoria semántica e historial corto. Produce: probabilidad calibrada de éxito si se activa la VLA ahora; pre/postcondiciones; clase de fallo; y acción discreta de recuperación.

## Riesgo de novedad

Mobi-pi, SAFE, MoMaStage, REAL y el estudio de orquestación 2026 cercan el espacio. Evitar “primer sistema”. La reivindicación debe ser una intersección estrecha y evaluable: contrato policy-conditioned para transición navegación→VLA, hardware low-cost multicámara, evaluación sim-to-real y atribución causal de fallos. Si el modelo no supera reglas/verificador genérico, la tesis sigue aportando el benchmark y el resultado negativo bien medido.
