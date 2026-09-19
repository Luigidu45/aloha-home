---
title: "F1: misiones, catálogo y contratos de asistencia doméstica"
---

# Definición de F1

**Referencia:** [fase 1 del plan](/docs/development/asistencia_domestica_modular/plan_trabajo.md). **Fecha de decisiones:** 12 de septiembre de 2026. Implementación nueva en `dimos/experimental/household_assistant`, independiente del paquete descartado. Commit de partida: `e9fa5f63c8f590367d2a7ef0b286a27da4848a4a`; árbol inicialmente limpio.

F1 entrega una definición ejecutable de contratos y casos de escritorio. No incluye todavía gestor de misiones, adaptadores de movimiento, VLM, ACT entrenado, simulación integrada ni verificadores de imágenes. Los chequeos de hechos son funciones puras: comprueban coherencia, procedencia y vigencia de la evidencia suministrada, sin generar esa evidencia a partir de sensores.

## Decisiones confirmadas con el usuario

| Tema | Decisión |
| --- | --- |
| Misión A | Llevar una botella de plástico pequeña y cerrada desde una mesa de la sala hasta una mesa auxiliar junto al usuario en el dormitorio. |
| Transporte | El brazo recoge el objeto, vuelve a una postura home con el objeto en la pinza y se desplaza manteniéndolo sujeto. Se sustituye la propuesta inicial de bandeja fija. |
| Ampliación B | Recoger un control remoto caído desde el suelo y entregarlo sobre una superficie accesible. Se propone `suelo_sala` como primera zona registrada y la misma mesa de entrega. |
| Robot | AlohaMini1, cambio autorizado el 15/09/2026. Brazos/pinzas según el nuevo URDF, pendientes de identificar y calibrar; no reutilizar AM-ARM200. |
| Sensores superiores | Unitree L2 4D y RealSense D435i, ambos fijados a la estructura superior. Las transformaciones y el significado de «fijo» respecto de la base se medirán. |
| Cómputo | Beelink GTi15 Ultra y una RTX de 24 GB de VRAM previstos. El acceso efectivo no está confirmado y la GPU podría llegar después. |

`loaded_home` nombra la postura de transporte con carga, sin fijar aún sus ángulos. El home usado con la pinza vacía no se reutilizará automáticamente: hay que comprobar trayectoria, espacio ocupado por el objeto, retención y estabilidad. Llegar a esa postura no demuestra que el objeto siga sujeto. El brazo activo se deja pendiente; cada propuesta de manipulación exige indicar `left` o `right`. No se programa un intercambio de objeto entre brazos.

La misión de suelo es una ampliación obligatoria del repertorio elegida por el usuario y condicionada al alcance físico. Su novedad práctica está en una recogida con dominio de altura, geometría y postura diferente. No se declarará alcanzable por disponer de dos brazos. Si el control no se puede sujetar desde el suelo, se documentará el fallo y se revisará esa elección con el usuario antes de sustituirla.

## Misiones y regiones

La configuración canónica está en [pilot.json](/dimos/experimental/household_assistant/configs/pilot.json). Los lugares son identificadores semánticos, no coordenadas inventadas:

- `mesa_sala`: superficie inicial de la misión A.
- `suelo_sala`: zona inicial de la ampliación B; las posiciones del control variarán dentro del dominio que se valide.
- `mesa_dormitorio`: región concreta de entrega sobre la mesa auxiliar, no toda la habitación.

Las geometrías permanecen en `null` y la accesibilidad sin confirmar. La ficha física deberá registrar frame, centro y tamaño de la región, altura de la mesa, márgenes respecto de bordes y origen de la medición. Esta ausencia es válida para planificar F1, pero no para habilitar una colocación física.

El perfil de usuario se mantiene según el PDF: persona que puede utilizar brazos y manos y no puede desplazarse a buscar el objeto. «Consultar a un usuario» significa contrastar utilidad y posición de entrega con una persona que podría usar el asistente. Aún no se ha realizado esa consulta ni se ha confirmado disponibilidad de participantes. F1 registra como pendientes la necesidad prioritaria, altura, lado y distancia cómodos de alcance; no exige inventar esas respuestas para cerrar los contratos.

`bottle_01`, `bottle_02` y `remote_01` son instancias para especificar el piloto y sus pruebas. La segunda botella sirve para el caso de ambigüedad; no equivale a haber inventariado objetos reales. F3 deberá asignar y mantener identidades a partir de percepción.

## Catálogo previsto

| Habilidad | Función | Ejecutor previsto |
| --- | --- | --- |
| `observe_at` | Obtener observaciones actuales de una estación. | `perception` |
| `navigate_to` | Llegar a una estación y confirmar parada. Si hay carga, conservar el agarre y la postura de transporte. | `navigation` |
| `align_at` | Ajustar base/elevador y terminar detenidos en una postura de interacción. | `alignment` |
| `pick_bottle_from_table` | Recoger la botella seleccionada desde la mesa. | `act_pick_table` |
| `prepare_transport` | Volver a `loaded_home` con el objeto aún sujeto. | `loaded_posture` |
| `place_on_table` | Colocar y liberar el objeto dentro de la región de entrega. | `act_place` |
| `pick_remote_from_floor` | Nueva recogida del control desde el suelo para B. | `act_pick_floor` |

Todos los ejecutores están **previstos, no implementados**. La configuración registra cámaras requeridas, escena compatible, precondiciones, resultados, timeout y cancelación. Los tiempos son presupuestos provisionales para el contrato, no frecuencias de control ni límites físicos validados. `active_wrist_rgb` es un alias a resolver a la cámara del brazo seleccionado; no es un stream instalado.

El retorno a home puede utilizar una trayectoria comprobada u otro ejecutor de postura; ACT queda previsto para las recogidas y la colocación. La implementación exacta se decide en F7/F8. La colocación está declarada para ambas categorías como objetivo de diseño: todavía no existe una política que demuestre esa compatibilidad. Cualquier adaptación necesaria para el control remoto se contabilizará en B.

## Contratos implementados

Los [modelos](/dimos/experimental/household_assistant/contracts.py) son tipados, inmutables y rechazan campos desconocidos. La [configuración](/dimos/experimental/household_assistant/configuration.py) valida identificadores, relaciones entre catálogos, regiones y correspondencia entre misión, objeto y habilidad.

| Contrato | Responsabilidad |
| --- | --- |
| `MissionDefinition`, `MissionRequest` | Misiones A/B y solicitud normalizada con instrucción original, origen, destino y posible objeto seleccionado. |
| `ObjectDefinition`, `Place`, `RegionGeometry` | Identidad/categoría, lugares y geometría medida cuando esté disponible. |
| `SkillDefinition`, `ActionProposal` | Dominio declarado, ejecutor previsto y parámetros de una acción propuesta. |
| `ExecutionReport` | Acción aceptada, en marcha, terminada, fallida, cancelación solicitada o cancelación confirmada. |
| `Evidence`, `FactKey`, `Observation` | Hechos observados con procedencia, tiempo de captura, reloj, frame y referencia al dato de origen. |
| `Verification`, `TargetResolution` | Éxito/fallo/incierto y objetivo seleccionado/ambiguo/no encontrado/incierto. |

La solicitud ya normalizada se comprueba con `validate_request`; interpretar lenguaje queda para F5. Su aceptación estructural no es ejecución. `validate_action` exige que el ejecutor figure entre los disponibles que le entrega el llamador. En F1 esa colección solo se suministra artificialmente en las pruebas; en F4 deberá derivarse de adaptadores realmente registrados y activos. Pasar un nombre no construye ni inicia un ejecutor.

La admisión estructural tampoco autoriza movimiento: F4 debe comprobar en ese instante precondiciones, sensores, calibración, brazo y ausencia de otra acción en curso. F1 no tiene endpoint, decorador `@skill` ni blueprint que exponga esas propuestas como movimientos.

`resolve_target` usa evidencia de visibilidad de las instancias registradas de la categoría solicitada. Dos visibles producen ambigüedad; si faltan hechos o están obsoletos, conserva incertidumbre. No elige la primera entrada del catálogo. Una selección explícita del usuario restringe el objetivo y debe volver a comprobarse visualmente. Es un universo de prueba acotado; F3 debe producir los candidatos reales y confirmar además su ubicación.

## Evidencia y criterios de éxito

Cada evidencia exige origen (`test`, `simulation`, `external_recording` o `physical`), fuente, referencia, tiempo de captura, reloj y frame. No existe un origen único que oculte una mezcla de componentes. Los chequeos reciben los orígenes permitidos para cada experimento y conservan la procedencia en los resultados concluyentes. Una prueba artificial no puede convertirse en evidencia física mediante un indicador de éxito.

Los [chequeos de escritorio](/dimos/experimental/household_assistant/assessment.py) exigen datos recientes, no futuros y con el mismo reloj declarado. Comparar relojes de dispositivos distintos exige una conversión documentada fuera de estos contratos. Agregar una evidencia nueva a un hecho con evidencia antigua no renueva artificialmente el conjunto.

Una ejecución en estado `finished` solo acredita que el ejecutor terminó. `assess_completion` exige hechos posteriores a ese instante; ante datos faltantes, contradictorios o inconclusos devuelve `unknown`. Una cancelación solicitada tampoco se convierte en ejecución terminada aunque llegue otro hecho de parada. F4 comprobará la secuencia y la parada de todos los actuadores implicados antes de permitir otra acción.

Para la misión física, el verificador futuro deberá comprobar conjuntamente:

1. Identidad del objeto solicitado.
2. Durante el transporte: objeto sujeto por la pinza seleccionada, postura con carga adecuada y seguimiento de esas condiciones durante el recorrido. El otro brazo debe permanecer fuera del volumen de circulación.
3. Para entrega: pertenencia del objeto a la región medida de `mesa_dormitorio`, liberación de esa pinza, estabilidad y base detenida.
4. Evidencia suficiente y posterior a la acción relevante. Un fin de trayectoria, una pinza cerrada o la presencia del robot en el dormitorio no acreditan entrega.

La interpretación de píxeles, fuerza o corriente no está implementada en F1. Los textos de precondiciones del catálogo son especificaciones para F4/F7; no son expresiones que se ejecuten automáticamente. Los chequeos actuales evalúan claves de hechos que les pasa el caso de escritorio. Tampoco validan todavía la trayectoria, las dimensiones físicas ni la relación entre sucesivas acciones.

## Diez casos de escritorio obligatorios

Los casos están implementados en [test_desk_cases.py](/dimos/experimental/household_assistant/test_desk_cases.py), con evidencia artificial y sin modelos ni hardware.

| Caso | Situación | Resultado exigido |
| --- | --- | --- |
| C01 | Solicitud válida, un objetivo visible y ejecutor declarado por la prueba | Objetivo único y propuesta estructuralmente admisible; no se ejecuta. |
| C02 | Destino no registrado | Rechazo antes de despacho. |
| C03 | Habilidad conocida sin ejecutor disponible | Rechazo; figurar en el catálogo no habilita la habilidad. |
| C04 | Habilidad inventada | Rechazo. |
| C05 | Ausencia observada de las botellas candidatas | Ningún objetivo seleccionado; F4/F5 podrán buscar o consultar. |
| C06 | Dos botellas visibles | Ambigüedad hasta una selección explícita y comprobada. |
| C07 | Evidencia visual obsoleta | Estado incierto; hace falta otra observación. |
| C08 | Motores terminaron, agarre incierto | Resultado incierto; no declarar recogida. |
| C09 | Cancelación solicitada | No equivale a finalización ni autoriza continuar. |
| C10 | Objeto liberado fuera de la región de entrega | Fallo aunque haya llegado a la habitación. |

Se incluyen además casos de pérdida del objeto en home, dominio de recogida del suelo y chequeos de relojes, procedencia mixta, referencias, selección del usuario y coherencia temporal en [test_contracts.py](/dimos/experimental/household_assistant/test_contracts.py).

## Reserva y protocolo de ampliación B

Antes de incorporar B, se congelarán la configuración de A, sus checkpoints y el núcleo que coordina la misión. Se registrará un ensayo de referencia de A. Después:

1. Comprobar alcance al suelo y agarre del control; medir dimensiones y orientar el dominio de entrenamiento.
2. Registrar horas de preparación de escena/teleoperación, demostraciones aceptadas y descartadas y tiempo de anotación.
3. Registrar entrenamiento: configuración, dataset, cómputo efectivo, tiempo, intentos y checkpoint.
4. Integrar `pick_remote_from_floor`; comprobar compatibilidad de su estado final con `prepare_transport` y `place_on_table`.
5. Registrar por separado las adaptaciones de transporte o colocación que haga falta entrenar/implementar. Conservar diffs y tiempo de integración, pruebas y validación; no atribuir todo el costo al registro de una skill.
6. Evaluar B y repetir A después de la ampliación, bajo condiciones registradas. Informar éxito, intervenciones y cambios en el núcleo. El esfuerzo reducido es una hipótesis a medir, no un resultado de F1.

El criterio de extensibilidad exige la nueva manipulación física compuesta con las anteriores. Una nueva configuración, un nombre distinto o una prueba con acciones artificiales solo acreditan integración de software.

## Pendientes declarados de F1

La [ficha de interfaces y pendientes físicos](/docs/development/asistencia_domestica_modular/fase_1_hardware.md) concentra lo que depende del robot y del posible usuario. Dejarlo pendiente es parte del alcance previsto de F1: no se necesitan medidas ficticias para redactar contratos.

El siguiente trabajo es F2: llevar estaciones y observaciones a la simulación conservada, manteniendo explícitos los límites del modelo AlohaMini1. No se instala un VLM ni se inicia entrenamiento por completar F1.

## Cierre y reproducción

**Estado:** F1 completada el 12 de septiembre de 2026. Se cumplieron sus siete tareas: misión y transporte definidos, modelos tipados, catálogo, separación de ejecución y resultado, procedencia de evidencia, ampliación B con protocolo y ficha de hardware. Las medidas físicas y la consulta a posibles usuarios permanecen declaradas como pendientes, conforme al alcance de la fase.

Desde la raíz del repositorio y con el entorno `.venv` disponible:

- Pruebas: `CI=1 .venv/bin/python -m pytest -p no:launch_pytest dimos/experimental/household_assistant dimos/robot/test_all_blueprints_generation.py -q --tb=short`. Resultado: **31 aprobadas** (30 del paquete, incluida la batería C01–C10, y una de consistencia del registro). Se desactiva el complemento ROS `launch_pytest` porque este entorno no dispone de su dependencia `lark`; estas pruebas no utilizan ROS. El complemento de reintentos de pytest necesita un socket local.
- Estilo: `.venv/bin/ruff check dimos/experimental/household_assistant` y `.venv/bin/ruff format --check dimos/experimental/household_assistant`.
- Tipos: `.venv/bin/mypy --follow-imports=silent dimos/experimental/household_assistant`. Resultado: sin incidencias en los tres archivos de implementación; las pruebas siguen las exclusiones de mypy del repositorio.
- Enlaces: `.venv/bin/doclinks --check docs/development/asistencia_domestica_modular/plan_trabajo.md docs/development/asistencia_domestica_modular/fase_1_definicion.md docs/development/asistencia_domestica_modular/fase_1_hardware.md`.

La entrada de los ensayos es `configs/pilot.json`, solicitudes normalizadas y hechos artificiales definidos en las pruebas; no se descargan modelos ni se accionan dispositivos. El registro de blueprints no cambia. Estos resultados acreditan contratos y reglas de escritorio, sin acreditar navegación, percepción, cancelación física o éxito de manipulación.
