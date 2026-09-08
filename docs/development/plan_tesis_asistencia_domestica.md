---
title: "Plan de tesis de asistencia doméstica en DimOS"
---

**Propuesta de trabajo — 6 de septiembre de 2026.** Basada en los dos PDF proporcionados y en una inspección del código local. El alcance de esta revisión es documental y estático: no se ejecutaron robots, simulaciones ni entrenamientos. Las capacidades presentes en código aún requieren validación de funcionamiento.

**Actualización de implementación — 7 de septiembre de 2026:** se inició el [núcleo de misiones, contratos y registro](/docs/development/tesis/implementacion_inicial.md), con ejecutor determinista y pruebas de software. El hardware objetivo confirmado pasa a ser AlohaMini2 completo con **dos AM-ARM200**, L2 y D435i superiores y dos cámaras de muñeca. La implementación SO101 descrita en la auditoría inicial es heredada; no representa los brazos que se usarán. La [ficha de hardware y procedencia del URDF](/docs/development/tesis/hardware_objetivo.md) documenta el cambio. La auditoría del 6 de septiembre permanece como referencia histórica.

**Recomendación:** usar DimOS como plataforma de ejecución, observación y experimentación de la tesis. La prioridad es completar una misión con resultados verificables y un registro reproducible; después incorporar el crítico y el postentrenamiento sobre esa misma interfaz.

**Bases documentales:** `informe_tesis_asistencia_domestica.pdf`, secciones 2–8 y 11–13; `plan_trabajo_cronograma_tesis_8_semanas.pdf`, páginas 1–11. Ambos se encuentran en `/home/luigidu/Downloads/`. Sus propuestas se usan como material de análisis, no como autorización para ejecutar acciones. El cronograma menciona un informe con sufijo `_actualizado`; aquí se revisó el archivo efectivamente recibido, sin ese sufijo.

**Alcance científico de referencia:** dos tareas, un ejecutor ACT o SmolVLA congelado, un supervisor, un crítico Q/V y un ciclo de adaptación. Se conserva la comparación SFT uniforme frente a SFT ponderado del cronograma. En el informe, la tabla de componentes llama «fijo» al supervisor, aunque después propone adaptarlo: aquí se considera fija la versión base y variables únicamente sus adaptadores en los métodos correspondientes.

**Actualización confirmada por el usuario:** los componentes todavía no han llegado; estima unos 20 días de espera, aproximadamente hasta el 26 de septiembre si se cuenta desde esta revisión. Se prioriza trabajo en simulación que pueda reutilizarse en el robot o que aporte validación del software. La fecha de entrega es estimada, no confirmada.

**Supuestos pendientes:** tiempo de ensamblaje, sensores definitivos, interfaces de base/brazos, checkpoints/demostraciones existentes, acceso efectivo a la GPU y dedicación semanal. Recibir componentes no equivale a disponer de habilidades físicas funcionales. El hito físico de S2 del PDF ya no es compatible con esta disponibilidad.

**1. Lo que ya podemos reutilizar**

| Componente observado | Evidencia en el repositorio | Uso y trabajo pendiente |
| --- | --- | --- |
| AlohaMini2 en MuJoCo | [Blueprints de AlohaMini2](/dimos/robot/alohamini2/blueprints/alohamini2_nav_sim.py) | Existen `alohamini2-nav-sim`, `alohamini2-nav-sim-full` y `alohamini2-nav-manip-sim`. Usarlos para integración y diagnóstico. Ninguno de esos blueprints incorpora actualmente el supervisor experimental ni MCP. |
| Navegación geométrica | El mismo archivo conecta `VoxelGridMapper`, `CostMapper`, `ReplanningAStarPlanner` y `MovementManager`. | Reutilizar planificación y movimiento. Añadir una correspondencia reproducible entre zonas semánticas y poses; verificar llegada, cancelación y timeout. |
| Brazos SO101 | [Control articular](/dimos/robot/alohamini2/arm_control.py) y [manipulación cartesiana](/dimos/robot/alohamini2/manipulation_module.py) | Hay movimientos, pinzas y planificación cartesiana. `so101_hardware()` configura `adapter_type="sim_mujoco"`; no demuestra integración física ni una policy ACT/SmolVLA de PICK/PLACE. |
| Sensores simulados | [Descripción de la simulación](/docs/usage/alohamini2-simulation.md) | Hay cinco vistas RGB y nube de puntos simulada. El perfil rápido usa RGB de 256×144 a 2 FPS: medir si sirve para observación; no asumir que coincide con las cámaras y entradas del ejecutor físico. |
| Skills semánticas | [Navegación por texto](/dimos/agents/skills/navigation.py) | Hay navegación por etiquetas, objetos y mapa semántico. Requiere dependencias de memoria/percepción y conexiones de streams que no están añadidas automáticamente al blueprint AlohaMini2. |
| Resultados estructurados | [SkillResult](/dimos/agents/skill_result.py) | Ya contiene éxito, código de error, duración y metadatos, con serialización para MCP. Reutilizarlo donde aplique; agregar una representación experimental explícita de SUCCESS, FAILED, TIMEOUT y UNKNOWN. |
| Agente y herramientas | [McpClient](/dimos/agents/mcp/mcp_client.py), [McpServer](/dimos/agents/mcp/mcp_server.py) | Infraestructura reutilizable. El cliente actual no constituye por sí solo un VLM local entrenable con LoRA; falta resolver el backend, entradas visuales y selección controlada de candidatos. |
| Grabación para imitación | [CollectionRecorder](/dimos/imitation/collection/recorder.py) y [flujo de datasets](/dimos/imitation/README.md) | Registra imágenes, articulaciones y límites de episodios; exporta LeRobot/HDF5. Adaptar cámaras/articulaciones a AlohaMini2. Añadir el dataset de decisiones semánticas: el actual no sustituye ese registro. |

En las rutas examinadas no se encontró un pipeline integrado de crítico por skill, cálculo de ventajas y SFT ponderado del supervisor. Ese es el principal desarrollo nuevo, junto con su instrumentación. La existencia de exportación LeRobot tampoco demuestra que esté implementada la inferencia ACT/SmolVLA.

**2. Arquitectura que propongo construir**

El flujo online será: misión → observación del estado → candidatos del supervisor → validación y selección → ejecución de una habilidad → verificación → registro de la transición → nueva decisión. El flujo offline leerá episodios cerrados para entrenar Q/V, calcular ventajas y producir los adaptadores del supervisor.

| Pieza propuesta | Responsabilidad | Criterio de terminado |
| --- | --- | --- |
| Contratos de misión y habilidad | Definir estado observado, acción con argumentos, resultado, evidencia y transición. | Esquemas versionados que rechazan acciones inválidas y representan incertidumbre sin inventar éxito. |
| Adaptadores de ejecución | Conectar NAVIGATE, SEARCH, VERIFY, PICK, PLACE, ASK y ABORT con módulos existentes o la policy motora. | Misma interfaz para ejecutor de prueba, simulación y robot real; procedencia de cada episodio identificada. |
| Ejecutor de misión | Administrar inicio, espera, finalización, cancelación, intentos y límites. | Una sola acción física activa; timeout cancela/detiene el ejecutor antes de permitir otra acción. |
| Constructor de observaciones | Unir objetivo, zona, objeto, visibilidad, objeto sostenido, historial y keyframes. | Estado anterior a la acción con timestamps y antigüedad de sensores; sin resultados futuros. |
| Verificadores | Confirmar llegada, búsqueda, agarre, colocación y misión completa. | Evidencia consultable y reglas idénticas para todos los métodos. |
| Registro de rollouts | Guardar decisiones y enlazarlas con sensores, versiones y resultado terminal. | Un episodio se puede reconstruir y auditar incluso si terminó en fallo o interrupción. |
| Supervisor experimental | Generar acciones válidas con un backend intercambiable y prompt AlohaMini2. | Entrada visual efectiva, JSON validado y catálogo cerrado; configuración común entre variantes. |
| Crítico y adaptación | Entrenar Q/V, puntuar candidatos, calcular pesos y ejecutar SFT. | Checkpoints recargables y evaluación sobre particiones independientes. |
| Evaluación | Programar escenarios y producir métricas/tablas desde los registros. | Resultados regenerables sin seleccionar manualmente las mejores demostraciones. |

La primera navegación semántica puede usar dos o tres zonas etiquetadas con poses verificadas. Ampliar a búsqueda abierta o mapas semánticos completos solo cuando sea necesario para las dos tareas.

Un detalle que debe resolverse pronto: `NavigationSkillContainer._navigate_to()` devuelve un mensaje de «navegación iniciada». El registro científico debe esperar el resultado de llegada; aceptar una orden no significa completar la habilidad. De manera análoga, cerrar una pinza o terminar una trayectoria no prueba que el objeto esté sostenido.

RETRY reutilizará una acción con contador; RECOVER deberá nombrar una secuencia concreta. El supervisor recibirá únicamente habilidades semánticas: el servidor MCP descubre skills de los módulos y el código de brazos expone también comandos articulares. Una lista permitida validada en el despachador debe impedir que las variantes experimentales invoquen esos comandos directamente.

Usar `Spec` y RPC para dependencias internas. Si se elige MCP para la conexión del agente, componer el servidor y el cliente/adaptador experimental siguiendo el patrón del repositorio y comprobar que no existan dos agentes tomando decisiones sobre la misma misión.

**3. Organización propuesta del código y los artefactos**

Las siguientes rutas son propuestas; este documento no afirma que esos archivos ya estén implementados. Crear cada pieza cuando corresponda a su hito, evitando scaffolding sin comportamiento.

| Ruta propuesta | Contenido |
| --- | --- |
| `dimos/robot/alohamini2/` | Adaptadores específicos del robot, calibración e interfaz de la policy motora. |
| `dimos/robot/alohamini2/blueprints/alohamini2_domestic.py` | Composición de la misión doméstica; variantes de prueba/simulación/física con disponibilidad explícita. |
| `dimos/experimental/domestic_assistance/contracts.py` | Tipos de estado, acción, resultado y transición. |
| `dimos/experimental/domestic_assistance/runner.py` | Ciclo de misión y límites. |
| `dimos/experimental/domestic_assistance/observations.py` y `verification.py` | Estado observable y evidencia de resultados. |
| `dimos/experimental/domestic_assistance/rollouts.py` | Persistencia, cierre y validación del dataset. |
| `dimos/experimental/domestic_assistance/supervisor.py` | Backend del VLM y generación/selección de candidatos. |
| `dimos/experimental/domestic_assistance/learning/` | Dataset offline, embeddings, Q/V, ventajas y SFT uniforme/ponderado. |
| `dimos/experimental/domestic_assistance/evaluation/` | Matriz de escenarios, ejecución y métricas. |
| `dimos/experimental/domestic_assistance/configs/` | Tareas, zonas, límites, splits y variantes del experimento. |
| `docs/development/tesis/` | Protocolo, inventario/costo, bitácora, fichas de misiones y resultados. |

Mantener el entrenamiento como proceso offline con dependencias propias; el robot solo carga la inferencia necesaria. Si ACT/SmolVLA ya funciona en otro entorno, conectarlo mediante un adaptador y conservar su checkpoint/contrato de observaciones, evitando trasladar todo su entrenamiento a DimOS.

Versionar código, configuración y manifiestos. Guardar videos, rollouts grandes, embeddings y pesos en almacenamiento configurable fuera del código, con hashes y respaldos. Los blueprints incorporados al registro se generan mediante `dimos/robot/test_all_blueprints_generation.py`; no editar manualmente `all_blueprints.py`.

**4. Qué trabajo en simulación se trasladará al robot**

La portabilidad debe construirse mediante contratos comunes: el supervisor decide una habilidad semántica y el adaptador seleccionado por configuración la ejecuta. El estado, los resultados y el registro usan el mismo esquema. Así el cambio al robot afecta principalmente a sensores, actuadores y verificadores, sin reescribir el experimento.

| Trabajo durante la espera | Qué se reutiliza | Qué habrá que comprobar o reemplazar al llegar los componentes |
| --- | --- | --- |
| Contratos, ciclo de misión, límites y registro | Código y pruebas de software. | Integración de cancelación real, latencias, pérdida de comunicaciones y persistencia durante fallos. |
| Supervisor, catálogo permitido y variantes M0–M4 | Interfaz, lógica de candidatos y configuración del experimento. | Calidad de decisiones con imágenes reales; rendimiento de cómputo y latencia. |
| Pipeline de Q/V, ventajas, SFT y métricas | Código de entrenamiento, carga de checkpoints y generación de tablas. | Volver a entrenar/evaluar con experiencia física; un crítico entrenado solo en simulación no queda validado en el robot. |
| Navegación entre zonas | Planificador y contrato de objetivos, si se satisface su interfaz de odometría/nube de puntos/movimiento. | Driver de base, localización/SLAM real, TF, huella, límites, mapa y tolerancias. La pose exacta del simulador no reemplaza la localización real. |
| SEARCH y VERIFY | Lógica y formato de evidencia; pruebas con estados visibles, ausentes y ambiguos. | Intrínsecos/extrínsecos, iluminación, oclusiones y criterios observables de objeto sostenido o colocado. |
| PICK y PLACE con ejecutor de prueba | Secuenciación, precondiciones y manejo de éxito/fallo/timeout. | Adaptador ACT/SmolVLA, nombres/unidades articulares, cámara requerida, normalización, pinzas y demostraciones físicas. |
| Objetos y escenarios de MuJoCo | Ensayos repetibles de integración y fallos. | Contactos, fricción, geometría y dinámica; no asumir que un agarre simulado transfiere. |

Trabajar en tres niveles: (1) ejecutor de prueba determinista para probar contratos; (2) navegación y observación en MuJoCo; (3) manipulación simulada solo si el escenario ya permite validarla sin consumir semanas de desarrollo. No hace falta resolver agarres físicamente realistas en simulación para probar el ciclo de aprendizaje y los controles del experimento.

Los datos artificiales se etiquetan y sirven para comprobar que el pipeline funciona. Si se usan para preparar el supervisor, registrar esa preparación y compartirla entre todos los métodos comparados. El efecto atribuido a experiencia real debe medirse con datos y evaluación físicos separados. No proporcionar al supervisor información privilegiada del simulador que no tendrá en operación; reservarla, si se usa, para evaluar verificadores.

Antes de la llegada, preparar una ficha de adaptación con nombres/unidades de articulaciones, límites, tópicos, timestamps, marcos de referencia, cámaras, entrada/salida de la policy y procedimiento de cancelación. La simulación actual tiene cámaras de pecho/muñecas; el plan físico menciona D435i superior. Hay que decidir las cámaras realmente disponibles antes de fijar observaciones y entrenar manipulación.

**5. Calendario ajustado a unos 20 días sin componentes**

Fechas ilustrativas del PDF: 7 de septiembre–1 de noviembre de 2026. Cada semana conserva 28 h programadas y 4 h de contingencia. La programación aquí, la operación del robot, la auditoría y la escritura comparten ese presupuesto: no son horas adicionales ni trabajo de varias personas. Esta tabla propone un **piloto reducido y condicionado**, no promete el volumen físico original.

| Semana | Trabajo en este repositorio y cómo avanzarlo | Trabajo físico/externo que habilita el avance | Entregable y puerta de salida |
| --- | --- | --- | --- |
| S1 · 7–13 sep. | Contratos, dos tareas y zonas, ejecutor de prueba, ciclo de misión y registro mínimo. Auditar conexiones de AlohaMini2. | Confirmar componentes pedidos, interfaces, cámaras y GPU; reunir documentación de montaje. | Episodio artificial auditable con éxito, fallo y timeout. |
| S2 · 14–20 sep. | Conectar navegación/observaciones en MuJoCo; instrumentar llegada y cancelación; integrar supervisor base y permitir solo skills semánticas. PICK/PLACE pueden ser de prueba y deben figurar como tales. | Preparar adaptadores de hardware a partir de interfaces conocidas; probar backend del VLM y guardado/carga de un adaptador. | Misión en simulación con procedencia de cada resultado explícita y sin datos futuros en el estado. |
| S3 · 21–27 sep. | Completar pipeline offline de Q/V, ventajas, SFT uniforme/ponderado y métricas con datos de prueba; ensayar reinicio y reproducción. | Recepción estimada hacia el 26; inventario y preparación de ensamblaje/calibración. | Ensayo completo del software y ficha de adaptación al robot. Aún no constituye evidencia científica física. |
| S4 · 28 sep.–4 oct. | Integrar drivers, streams, TF, localización real y ACT/SmolVLA; sustituir adaptadores de prueba; ajustar verificadores con evidencia real. | Ensamblaje, calibración y pilotos. Esta semana puede ser insuficiente si también hay que aprender agarres desde cero. | Puerta estricta del piloto de 8 semanas: navegación y PICK/PLACE físicos funcionales, misiones nominales y ejecutores congelados. Si no se cumple, extender el calendario. |
| S5 · 5–11 oct. | Auditar primero 10 episodios; cerrar un dataset piloto; entrenar Q/V y validar contra predictor constante. | Objetivo provisional: 60 misiones de desarrollo, aproximadamente 45 train/15 validación, agrupadas por escenario/sesión. | Dataset físico y crítico piloto. La cantidad reducida no garantiza aprender ventajas útiles. |
| S6 · 12–18 oct. | Obtener ventajas fuera de muestra; entrenar control uniforme y ponderado; integrar reranking y validar recarga en proceso nuevo. | Pilotos de validación acotados, GPU y congelación de configuraciones antes de test. | Cuatro variantes principales M0–M3 listas. M4 pasa a extensión. |
| S7 · 19–25 oct. | Ejecutar matriz piloto, registrar todas las salidas y generar tablas. | Propuesta reducida: 4 métodos × 2 tareas × 8 condiciones = 64 ensayos; orden aleatorizado y reset documentado. | Comparación física piloto, 16 ensayos por método, con incertidumbre explícita. |
| S8 · 26 oct.–1 nov. | Estadística, tablas/figuras regenerables, documentación de reproducción y empaquetado. | Redacción final, revisión académica, video y defensa. | Entrega técnica y memoria; sin incorporar nuevas funcionalidades. |

Las dos tareas actualizadas serán `recoger_ropa` y `preparar_bandeja`. La primera recoge tres prendas cercanas y verifica la relación `IN` respecto del cesto; su guion nominal tiene 18 decisiones. La segunda coloca una bandeja en la mesa, carga un vaso y un plato, traslada la bandeja y verifica las relaciones `ON` anidadas; su guion nominal tiene 19 decisiones. Se comienza con un vaso y un plato para respetar el límite de 20 decisiones; ampliar la vajilla exige reajustar y volver a congelar ese límite. La base se detiene para manipular y no se exige coordinación simultánea de ambos brazos.

Para S4, conservar como cribado las pruebas propuestas en el PDF: 9/10 navegaciones, al menos 8/10 por habilidad motora y 3 misiones completas por tarea. Son criterios de preparación, no estimaciones precisas de fiabilidad. Si no hay checkpoints de manipulación utilizables o la localización requiere desarrollo sustancial, no asumir que se podrá superar esta puerta en una semana.

**Opción recomendada para conservar el alcance completo:** mantener S1–S3 de simulación, reservar S4–S5 para integración y habilidades físicas según lo observado, y desplazar la recogida de datos y aprendizaje. Conservar entonces dos semanas de datos/crítico, dos de reranking/adaptación, una de evaluación y una de entrega. El horizonte estimado pasa a 10–11 semanas desde el inicio (aproximadamente hasta el 15–22 de noviembre), condicionado a la integración y al acceso al robot. La espera deja de ser tiempo perdido sin comprimir artificialmente la campaña física.

Escribir cada semana: S1 problema/objetivos; S2–S3 arquitectura y método; S4 integración; S5–S6 datos/aprendizaje; S7 resultados; S8 discusión y cierre en la ruta piloto. Registrar costo completo e incremental, RAM/VRAM, latencia mediana/p95 y horas de GPU durante las pruebas, no reconstruirlos al final.

**6. Registro mínimo que merece implementarse primero**

| Grupo | Campos y tratamiento |
| --- | --- |
| Identidad y procedencia | `episode_id`, `decision_id`, `scenario_id`, `task_id`, grupo de split, sesión, semilla y origen físico/simulado/prueba. Los identificadores sirven para trazabilidad, no como features del crítico. |
| Versiones | Commit y manifiesto de cambios locales, configuración, prompt, supervisor, ejecutores, verificador y hashes de checkpoints. |
| Observación anterior | Objetivo, zona, etapa, objeto visible/sostenido, intentos e historial previo; referencias a keyframes con timestamps. |
| Decisión | Candidatos con argumentos, elegida, política de comportamiento, exploración y scores cuando existan. Conservar la acción propuesta y la efectivamente ejecutada si difieren. |
| Ejecución | Inicio/fin, duración monotónica, resultado, causa de fallo, evidencia, ayuda humana y cancelación. |
| Observación posterior | Estado y evidencia después de finalizar la habilidad. Puede alimentar la decisión siguiente; no entra en Q para predecir la acción anterior. |
| Cierre de episodio | Éxito autónomo, razón de terminación, asistencia, validez experimental y motivo de exclusión si corresponde. El éxito terminal se agrega después; nunca es una entrada del modelo. |

Separar eventos de inicio, resultado y cierre mediante identificadores para detectar decisiones inconclusas. Una caída del proceso debe dejar evidencia recuperable; no convertir datos incompletos silenciosamente en éxitos o en fallos físicos etiquetados. Un timeout experimental válido sí cuenta como resultado.

Conservar fallos: el botón de descarte de demos de imitación no debe transformarse en un filtro de misiones fallidas del supervisor. Empezar con JSONL y referencias a imágenes; exportar Parquet offline cuando facilite entrenamiento y análisis.

**7. Reglas del experimento que debemos fijar desde el código**

| Método | Configuración |
| --- | --- |
| M0 | Supervisor inicial, sin crítico ni adaptación por experiencia. |
| M1 | M0 con reranking por Q. |
| M2 | Supervisor con SFT uniforme sobre los mismos ejemplos que M3, sin crítico. |
| M3 | Supervisor con SFT ponderado por ventaja, sin crítico. |
| M4 | M3 con el mismo crítico de M1. |

Todos comparten ejecutores, observaciones, precondiciones y reglas de terminación. Registrar generación de candidatos y su costo; donde haya reranking mantener el mismo procedimiento y número máximo fijado en S6. Reglas y SFT de interfaz son preparación/diagnóstico, sin añadir campañas físicas completas.

Usar éxito autónomo terminal binario y descuento 1 en el plan base. Así Q/V predicen éxito bajo las continuaciones observadas; no son valores óptimos ni efectos causales demostrados. Mantener tiempo y ayuda como métricas, sin introducir penalizaciones que cambien el significado del retorno. Para un mismo estado, V es común a los candidatos: ordenar por Q o por Q−V produce el mismo orden; la ventaja resulta especialmente relevante para ponderar decisiones entre estados durante el entrenamiento.

Calcular ventajas de train con predicciones fuera de muestra, por ejemplo tres particiones agrupadas por escenario/sesión dentro de train. El crítico de inferencia se entrena luego con todo train. Reservar validación para decisiones de ajuste y test para la campaña final. No dividir frames o decisiones del mismo episodio entre conjuntos.

El SFT ponderado usará pesos exponenciales de ventaja, recortados y normalizados, y pérdida sobre tokens de acción/argumentos. M2 y M3 tendrán iguales datos, pasos y presupuesto de ajuste. Se trata de una adaptación a decisiones semánticas inspirada en la regresión ponderada de [AWR](https://arxiv.org/abs/1910.00177), no de una reproducción exacta del algoritmo. La implementación de adaptadores puede apoyarse en [LoRA de PEFT](https://huggingface.co/docs/peft/main/package_reference/lora); comprobar compatibilidad y consumo con el modelo elegido antes de comprometerlo.

La campaña completa del PDF tiene 5 métodos × 2 tareas × 12 condiciones = 120 ensayos, 24 por método. Cada tarea incluye 4 condiciones nominales, 4 con desplazamiento/ocultación y 4 con fallo recuperable controlado. En la ruta reducida de 8 semanas se proponen M0–M3 y 8 condiciones por tarea: por ejemplo, 2 nominales, 3 con desplazamiento/ocultación y 3 con fallo recuperable; son 64 ensayos, 16 por método. Fijar esa distribución antes de evaluar, no según los resultados. En ambas rutas usar los mismos escenarios iniciales y perturbaciones entre métodos, con reset y orden aleatorizado por bloques.

La unidad de análisis es la misión, con comparación emparejada por escenario. Reportar éxito autónomo, recuperación, ayuda, tiempo, reintentos y latencia; Brier para Q/V y comparación constante. Medir ranking accuracy únicamente con alternativas realmente ensayadas en contextos comparables. Incluso 24 ensayos por método dan evidencia piloto; 16 por método amplían la incertidumbre. Ninguna de estas cantidades promete detectar mejoras pequeñas ni demostrar generalización a otras viviendas.

**8. Primer bloque de implementación propuesto**

Estas tareas están pendientes y constituyen el siguiente incremento dentro de S1–S2. Podemos avanzar las primeras sin tener encendido el robot.

| Orden | Tarea | Evidencia concreta al terminar |
| --- | --- | --- |
| 1 | Fijar contratos, tareas y catálogo de skills. | Dos fichas de misión y esquemas con ejemplos válidos/inválidos; estados desconocidos explícitos. |
| 2 | Crear ejecutor de prueba con éxito, fallo, timeout y evidencia insuficiente configurables. | Misma misión reproducible con cada desenlace; ningún movimiento físico. |
| 3 | Implementar ciclo de misión y persistencia. | Episodio completo con transiciones, límite de intentos, cancelación y cierre verificable. |
| 4 | Añadir un reporte de auditoría. | Detecta decisiones abiertas, imágenes ausentes, desorden temporal, versiones y etiquetas faltantes. |
| 5 | Conectar NAVIGATE al stack existente. | Comprobar en simulación llegada frente a simple aceptación de objetivo, parada y timeout. |
| 6 | Conectar observaciones y VERIFY; después PICK/PLACE de prueba o simulados. | Evidencia y procedencia explícitas de objeto visible/sostenido/colocado; definición del verificador físico pendiente hasta tener sensores. |
| 7 | Sustituir la decisión de prueba por el VLM base. | Acciones validadas, mismas transiciones y límites, medición de latencia y formato. |

El primer entregable será una misión instrumentada que deje un episodio legible y auditado. Los episodios artificiales sirven para probar software; no se mezclarán con la evidencia física ni se presentarán como aprendizaje demostrado en el robot.

Al implementar, probar contratos, cancelación sin acciones solapadas, cierre de episodios, ausencia de fuga de etiquetas y cálculo de pesos. Después hacer integración en simulación y pilotos físicos. Para este documento se verifican referencias, sin ejecutar una campaña de tests de robot.

**9. Condiciones para mantener el plazo**

La puerta decisiva pasa a S4 para el piloto reducido. La simulación permite llegar a la recepción con el software preparado, pero no sustituye ensamblaje, calibración ni aprendizaje motor. Si las misiones físicas no funcionan al cierre de S4, ampliar el plazo o reformular explícitamente el alcance; no sustituir datos reales por artificiales conservando las afirmaciones originales de la tesis.

El presupuesto original es 120 misiones de desarrollo + 24 pilotos como máximo + 120 ensayos finales = 264 misiones. A 8 minutos de ejecución más reset son 35,2 h, sin auditoría ni preparación. A 12 minutos serían 52,8 h. La ruta reducida propone 60 de desarrollo + hasta 24 pilotos + 64 finales = hasta 148 misiones: unas 19,7 h a 8 minutos o 29,6 h a 12 minutos. Estas horas tampoco incluyen ensamblaje, calibración ni demostraciones motoras. Medir duración y disponibilidad en S4 antes de cerrar el volumen definitivo.

La ruta reducida ya retira tercera tarea, nuevas familias de objetos, más rondas de aprendizaje y M4. Si hay más retrasos, reducir tareas/escenarios declarando la pérdida de evidencia o ampliar el plazo, protegiendo la comparación uniforme/ponderada. Si no llega a completarse el postentrenamiento, crítico + reranking sigue siendo un resultado acotado, pero ya no evalúa la mejora persistente del supervisor planteada en el alcance completo.

Cerrar cada semana con horas reales, hito, episodios válidos, bloqueo principal y siguiente tarea. Separar en la bitácora cuatro niveles de evidencia: presente en código, probado sin robot, probado en simulación y validado físicamente. La tesis puede ser válida con un resultado negativo si el protocolo y la evidencia son sólidos.
