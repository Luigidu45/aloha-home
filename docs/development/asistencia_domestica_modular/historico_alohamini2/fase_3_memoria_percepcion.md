---
title: "F3: memoria espacial y percepción local del objetivo"
---

> Actualización posterior: por petición del usuario se adelantó la [adaptación del AM-ARM200 original](/docs/development/asistencia_domestica_modular/adaptacion_am_arm200.md). Los blueprints de navegación y doméstico usan ahora ese modelo. Los resultados históricos de esta fase conservan su procedencia y fecha; los nuevos ensayos se registran por separado.


# F3: resultado y alcance

**Fecha:** 13 de septiembre de 2026. **Estado:** cerrada como piloto offline de memoria y percepción, con errores visuales documentados. **Decisión del usuario:** inferencia local en CPU, preparada para cambiar de dispositivo al disponer de RTX. No se usó la credencial de Google ni inferencia remota.

Se implementaron los seis puntos de F3 del [plan](/docs/development/asistencia_domestica_modular/plan_trabajo.md): catálogo semántico, recuperación con memoria de DimOS, separación temporal de evidencia, corpus visual, detector local y búsqueda acotada. El cierre acredita el circuito de búsqueda/percepción del piloto; no acredita agarres, localización física, identificación persistente de ejemplares ni navegación autónoma de una vivienda desconocida. La detección del control de B sigue siendo una limitación concreta que debe resolverse antes de su misión física.

## Las cuatro áreas de DimOS en esta tesis

Las cuatro áreas de la imagen coinciden con el [README público de DimOS](https://github.com/dimensionalOS/dimos), consultado el 13 de septiembre de 2026. Son capacidades disponibles en el framework; instalarlo no conecta automáticamente todas a nuestro blueprint.

| Área | Uso comprobado al terminar F3 | Qué falta para la tesis |
| --- | --- | --- |
| Navigation and Mapping | F2 compone `VoxelGridMapper`, `CostMapper`, `ReplanningAStarPlanner`, `MovementManager` y el adaptador de estaciones. Construye mapa desde nube y comprueba llegada/parada. | Localización de la base en hardware, calibración L2 y sensores. La localización de F2 es ground truth de MuJoCo: no equivale a SLAM real validado. Exploración de una casa arbitraria no forma parte del piloto. |
| Perception | F3 usa `Yolo2DDetector` de DimOS con YOLO11n, imágenes RGB y resultados con cajas, procedencia y tiempo. | Mejorar evidencia para el control, validar las cámaras reales y añadir profundidad/proyección cuando haya intrínsecos y profundidad alineada. El VLM supervisor corresponde a F5. |
| Agentive Control, MCP | La arquitectura lo contempla para F4–F5; todavía no está activo en el asistente. Los RPC de F2 no son una integración MCP. | Gestor de acciones único en F4, supervisor visual en F5 y exposición de habilidades que pasen por el gestor. Si se usa la composición MCP de DimOS, incluir `McpServer` y `McpClient` con un prompt doméstico. |
| Spatial Memory | F3 reutiliza `SpatialVectorDB`, `VisualMemory`, Chroma y el `CLIPModel` existente de DimOS; recupera vistas con su pose observada. | Alimentación continua desde el robot, reconciliación durante las misiones y evaluación física. No se afirma permanencia exhaustiva de todos los objetos. |

**Estamos aprovechando tres áreas en componentes ensayados y tenemos la cuarta programada.** No se marca control agentivo como realizado por disponer de decoradores o por ejecutar una secuencia Python. El blueprint de navegación (`dimos/robot/alohamini2/blueprints/household_navigation_sim.py`, ruta histórica) mantiene su composición de F2; F3 entrega adaptadores y un ejecutor offline, sin añadir otro controlador de movimiento.

## Qué era la navegación semántica de F2

F2 implementa navegación a estaciones con nombres: `mesa_sala` resuelve una pose de observación registrada. Es una forma básica de navegación semántica a lugares etiquetados, pero no implica que el robot haya reconocido la mesa, localizado una botella o aprendido el significado de «dormitorio» recorriendo la casa. La descripción anterior necesitaba esta precisión.

DimOS permite una alternativa basada en observaciones. Su [NavigationSkillContainer](/dimos/agents/skills/navigation.py) incluye `tag_location` y `navigate_with_text`: puede usar lugares etiquetados, percepción actual y recuperación de memoria espacial. En la ruta de memoria, la descripción se compara con imágenes guardadas y se recupera la pose desde la que se observó una escena. No es necesario escribir de antemano una coordenada para cada objeto.

Las coordenadas siguen existiendo: el planificador necesita una meta métrica. Lo que cambia es su origen. En la búsqueda por memoria proceden de la localización asociada a una imagen, no de una tabla escrita manualmente. Además:

- Una pose de observación es la posición del observador, **no la posición 3D del objeto** ni una pose de agarre.
- «Aquí se vio una botella» propone dónde volver a mirar; no demuestra que siga allí.
- Un lugar nunca observado requiere exploración, información del usuario u otra fuente. La memoria no inventa habitaciones no visitadas.
- Las estaciones medidas siguen siendo útiles para manipular y entregar en una región accesible. Buscar libremente por semántica y conservar estaciones de interacción son compatibles.

F3 comprobó esta alternativa con las grabaciones reales de la ejecución simulada de F2: se indexaron ambas imágenes **sin `place_id`**, se consultó `a bottle on a table` y se recuperó primero la vista de sala. La pose recuperada fue aproximadamente `(-2.331, 0.520, 1.897 rad)`, procedente de la localización grabada, sin llamar al catálogo de coordenadas de estaciones. La distancia coseno fue aproximadamente 0,734 frente a 0,768 para la vista de dormitorio. Es un orden de candidatos, no una probabilidad de presencia.

Esta prueba recupera una meta candidata. Todavía no hace que el asistente ejecute por sí solo búsqueda → navegación a esa pose → nueva observación: F4 será quien despache y verifique ese ciclo. No se activó directamente el contenedor genérico de navegación porque introduciría otro camino de despacho fuera del gestor previsto.

## Componentes entregados

| Archivo | Responsabilidad |
| --- | --- |
| [semantic_catalog.json](/dimos/experimental/household_assistant/configs/semantic_catalog.json) | Alias de estaciones y región de entrega, categorías y lugares habituales. Valida correspondencia con F1. «Dormitorio» solo no selecciona silenciosamente una superficie concreta. |
| [semantic_memory.py](/dimos/experimental/household_assistant/semantic_memory.py) | Adapta memoria de DimOS; separa pistas habituales, observaciones históricas, confirmación reciente y colocación verificada. Propone búsqueda acotada. |
| [visual.py](/dimos/experimental/household_assistant/visual.py) | Contratos RGB, evidencia, cajas y candidatos por imagen; comprueba hash, timestamp y frame antes de inferir. |
| [local_models.py](/dimos/experimental/household_assistant/local_models.py) | Conecta el CLIP de DimOS al adaptador de memoria, sin crear un segundo índice vectorial. |
| [perception_bridge.py](/dimos/experimental/household_assistant/perception_bridge.py) | Convierte un snapshot de F2 en una vista con pose/evidencia conservadas; sirve para captura actual o replay sin refrescar tiempos. |
| [demo_visual_corpus.py](/dimos/experimental/household_assistant/demo_visual_corpus.py) | Renderiza diez casos MuJoCo y guarda RGB, escenas, hashes y anotaciones para evaluación. |
| [demo_perception.py](/dimos/experimental/household_assistant/demo_perception.py) | Ejecuta modelos locales, recuperación, métricas por imagen y registro de evidencia. |

Se corrigió [SpatialVectorDB](/dimos/perception/spatial_vector_db.py): las listas anidadas devueltas por una consulta Chroma perdían vecinos y mezclaban metadatos. Ahora cada candidato conserva sus propios datos y distancia, manteniendo las consultas por ubicación. Una prueba con Chroma real comprueba los dos resultados.

En [Yolo2DDetector](/dimos/perception/detection/detectors/yolo.py) se añadió `tracking=False` para imágenes independientes; el comportamiento anterior sigue siendo el predeterminado. Así, fotos de escenas distintas no comparten estado del tracker. El adaptador doméstico asigna identificadores como `two_bottles_candidate_0`, ordenados horizontalmente en esa imagen: no los presenta como `bottle_01`/`bottle_02` reconocidas persistentemente.

Se reutiliza el CLIP actual de DimOS porque su implementación permite propagar fallos. El proveedor legado `ImageEmbeddingProvider` devuelve vectores aleatorios en algunas rutas de error; eso no es adecuado para evidencia reproducible. Se reutiliza la misma infraestructura de memoria, con el proveedor moderno, sin instanciar `SpatialMemory` con sus rutas/defaults globales.

## Memoria, incertidumbre y búsqueda

`remember(image, view)` indexa una captura inmutable con pose del observador, mapa, origen, reloj y hash RGB. `candidates(...)` recupera vistas del contexto solicitado. Los lugares habituales proceden del catálogo; no se convierten en observaciones. `last_observed(...)` consulta detecciones históricas utilizables. `current(...)` considera la última observación y su antigüedad, incluso si esa imagen no produjo detecciones: una detección antigua no sustituye una vista reciente incierta.

El detector solo devuelve `candidate`, `ambiguous` o `unknown`. Un score de YOLO tampoco se trata como probabilidad calibrada. Una detección de categoría no confirma identidad, botella cerrada, masa, estabilidad ni aptitud para el agarre. RGB no produce coordenadas 3D; la nube de F2 no se usa como si fuese profundidad alineada de la cámara.

Para invalidar una ubicación se exige una `AbsenceReview` explícita de la región visible, vinculada a los píxeles de esa vista. **YOLO sin detecciones no genera esa revisión.** En el ensayo, la revisión la realizó Codex inspeccionando el PNG de la mesa vacía; quedó registrada como `codex_visual_inspection`. Es una comprobación visual asistida e independiente de las anotaciones del render, no una capacidad autónoma nueva del detector ni un juicio de un participante humano. La invalidación afecta a esa región y a capturas anteriores o iguales; no borra vistas posteriores ni registros de otro mapa/origen/reloj.

`verify_placement(...)` reutiliza el evaluador de F1: requiere ejecución terminada y evidencia posterior/fresca de objeto dentro de la región, liberación y base detenida. Solo entonces escribe la ubicación verificada del ejemplar. La prueba es artificial; los verificadores físicos y el control de estabilidad se completan en F4/F8. Un movimiento de pinza terminado, un timeout o un resultado incierto no actualizan esa ubicación.

`BoundedSearch` propone como máximo tres lugares y dos vistas por lugar. Una observación incierta solicita otra vista; la ambigüedad exige elegir entre candidatos; agotado el presupuesto pide ayuda. Son propuestas para el futuro gestor, no llamadas a motores. Las poses de cámaras estáticas del corpus están etiquetadas como tales y no deben enviarse a la base como si fueran odometría del robot.

Los embeddings/metadatos se guardan en la colección Chroma propia de cada ejecución. `journal.json` conserva observaciones, revisiones y colocaciones; `restore_journal(...)` restaura explícitamente ese estado sin rejuvenecer evidencias. El integrador debe restaurarlo antes de servir consultas de una sesión retomada. Cambiar pesos o preprocesamiento de embeddings requiere una colección nueva; el ejecutor identifica ambos por hashes. Las imágenes originales se conservan en el corpus/grabación, con referencias y hashes, y `VisualMemory` sirve como almacén visual de la sesión.

## Evaluación visual y criterio de cierre

Se usó [YOLO11n](https://docs.ultralytics.com/models/yolo11/) para cajas y [CLIP ViT-B/16](https://huggingface.co/openai/clip-vit-base-patch16) para recuperación texto–imagen, ambos a través de implementaciones de DimOS. No se incorporó segmentador ni VLM generativo: F3 admite un detector y esta combinación cumple el piloto en CPU. El supervisor VLM que interpreta peticiones y propone acciones sigue correspondiendo a F5.

Las diez imágenes son renders RGB de 640×480, derivados de la vivienda sintética de F2 con fixtures de botella más detallados. Son datos de desarrollo propios, no fotografías reales. La segmentación de MuJoCo genera las anotaciones y solo entra en el evaluador **después** de inferir. El reconocedor recibe la imagen, la categoría solicitada y su procedencia; no recibe conteos, nombres de geoms ni coordenadas de objetos. Tres variaciones de vista se marcaron como reservadas; no se modificaron pesos ni umbrales a partir de sus resultados. Su pequeño tamaño no permite afirmar generalización.

| Caso | Resultado del detector | Evaluación a IoU ≥ 0,5 |
| --- | --- | --- |
| Una botella | Un candidato | 1 detección correcta. |
| Dos botellas | Dos candidatos, ambiguo | 2 detecciones correctas. |
| Botella y vaso distractor | Un candidato de botella | 1 detección correcta. |
| Mesa vacía | Incierto | Sin falsos positivos; revisión visual explícita permite invalidar historia anterior. |
| Solo vaso | Incierto | Sin falsos positivos de botella. |
| Botella ocluida | Incierto | 1 omisión sobre la parte aún visible. No se declaró ausencia. |
| Control en suelo | Incierto | 1 omisión. Percepción de B todavía no resuelta con este modelo/escena. |
| Suelo vacío, otra vista | Incierto | Sin falsos positivos. |
| Dos botellas, otra vista | Dos candidatos, ambiguo | 2 detecciones correctas. |
| Una botella, otra vista | Un candidato | 1 detección correcta. |

Total: **7 detecciones correctas, 0 falsos positivos y 2 omisiones**, respecto de 9 cajas anotadas de objetivos visibles al menos parcialmente. Se informa el fallo por oclusión aunque conservar incertidumbre sea el comportamiento correcto del sistema. Los dos resultados no se confunden: calidad del detector y tratamiento de la incertidumbre se evalúan por separado.

En las dos imágenes originales de F2, de 256×144, YOLO no produjo candidatos de botella. Se reporta ese resultado sin calcular accuracy porque esas imágenes no tienen cajas anotadas en este corpus. CLIP sí recuperó primero la vista pertinente. Antes de F9 hay que validar la configuración real de cámara, el tamaño aparente del objeto y el control remoto; cambiar a GPU acelera inferencia, pero por sí solo no corrige omisiones.

La ejecución de aceptación usó cuatro hilos de PyTorch en CPU. Las inferencias individuales de YOLO estuvieron en el orden de decenas de milisegundos; el JSON conserva cada tiempo. El pico del proceso fue aproximadamente 1,73 GiB de RSS. Estos tiempos no incluyen arranque de Python, importaciones ni toda la carga inicial de modelos, y no constituyen una medida del sistema robótico completo. Las versiones y resultados exactos están en el [registro de validación](/docs/development/asistencia_domestica_modular/historico_alohamini2/fase_3_validacion.json).

| Criterio de F3 | Evidencia |
| --- | --- |
| Localizar candidato | Detección en renders y recuperación CLIP de la vista de sala de F2 sin coordenadas de estación consultadas. |
| Distinguir dos compatibles | Dos cajas e identificadores por imagen; salida `ambiguous`, sin elegir arbitrariamente. |
| Mantener incertidumbre ante oclusión | Caso ocluido devuelve `unknown`; historia y confirmación actual permanecen separadas. |
| Descartar ubicación histórica contradicha | Revisión del PNG vacío invalida vistas anteriores; prueba adicional conserva una observación posterior. |
| Reportar errores visuales | Omisión de botella ocluida, control no detectado y falta de detecciones sobre los originales F2 registradas. |

La fase aporta evidencia parcial a O2/O3/O5 y a la integración C1. No cierra esos objetivos científicos completos ni la extensibilidad física C2.

## Reproducción y migración a RTX

Desde la raíz del repositorio, los modelos ya preparados están en `.ignore.f3/models/clip/` y `.ignore.f3/models/yolo/yolo11n.pt`. El ensayo final usa `.ignore.f3/corpus_01/`, `.ignore.f3/acceptance/` y el log `/tmp/household_f3_acceptance.log`. Los binarios quedan fuera de Git; se versionan código, [manifiesto del corpus](/docs/development/asistencia_domestica_modular/historico_alohamini2/fase_3_corpus.json), hashes y resultados. No se necesita una API key.

Para regenerar imágenes en un directorio nuevo: `MUJOCO_GL=glfw xvfb-run -a .venv/bin/python -m dimos.experimental.household_assistant.demo_visual_corpus .ignore.f3/corpus_nuevo`.

Para repetir la evaluación sobre el corpus ya revisado: `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/python -m dimos.experimental.household_assistant.demo_perception .ignore.f3/corpus_01 .ignore.f3/ensayo_nuevo --clip-path .ignore.f3/models/clip --yolo-path .ignore.f3/models/yolo/yolo11n.pt --device cpu --f2-recording .ignore.f2/route_final --reviews .ignore.f3/corpus_01/absence_reviews.json`.

Los directorios de salida deben ser nuevos para no mezclar evidencia. Si se regeneran imágenes, omitir inicialmente `--reviews`: sus timestamps cambian y se necesita revisar de nuevo la captura correspondiente. El archivo de revisión contiene `view_id`, hash de píxeles RGB, categoría, revisor, declaración de región visible/ausencia, instante de revisión y nota. No reutilizar una etiqueta antigua para otra captura. `--f2-recording` también es opcional; para obtener esa grabación seguir [F2](/docs/development/asistencia_domestica_modular/fase_2_simulacion.md).

En otro equipo, preparar un directorio CLIP completo con pesos y archivos de procesador/tokenizador. La revisión de pesos utilizada fue `5ef227a78de3f75873f373246dac80def63b0003` de `openai/clip-vit-base-patch16`; puede descargarse con `.venv/bin/hf download openai/clip-vit-base-patch16 --revision 5ef227a78de3f75873f373246dac80def63b0003 --local-dir .ignore.f3/models/clip --include '*.json' '*.txt' model.safetensors`. El checkpoint YOLO se obtuvo de los [assets oficiales de Ultralytics, v8.3.0](https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n.pt). Comparar hashes con el registro; estas descargas requieren red, la inferencia posterior es local.

Al disponer de RTX, usar `--device cuda:0` con los mismos modelos y repetir el corpus. `--yolo-path` admite otro checkpoint compatible; `--clip-path` otro CLIP completo. El adaptador de percepción consume el protocolo del detector y no conoce su dispositivo. Un VLM futuro puede producir el mismo contrato mediante otro adaptador; F3 no supone que un modelo generativo exponga automáticamente la API de cajas de YOLO. Registrar de nuevo latencia, memoria y errores antes de elegirlo.

Validación de código: **67 pruebas rápidas aprobadas** en `.venv/bin/python -m pytest -p no:launch_pytest dimos/experimental/household_assistant dimos/perception/test_spatial_vector_db.py -q --tb=short`. Incluyen 22 pruebas nuevas de F3/regresión y las anteriores del paquete. Mypy sin incidencias en ocho archivos de implementación; Ruff correcto. El plugin ROS se desactiva por la dependencia ausente `lark`, como en F1/F2; no se utilizó ROS en el ensayo. No se añadieron blueprints, por lo que no hubo regeneración del registro.

## URDF original y pendientes concretos

La ruta nueva suministrada sí contiene el AlohaMini2 original: `/home/luigidu/AlohaMini/AlohaMini2/urdf/alohamini2/urdf/alohamini2.urdf`, nombre interno `alohamini2_urdf`. Se inspeccionó sin modificar esos archivos. El [inventario con hashes](/docs/development/asistencia_domestica_modular/historico_alohamini2/fase_3_urdf_original.json) registra 18 articulaciones no fijas: tres coordenadas virtuales de base, elevador y seis ejes más pinza por brazo; las 26 referencias a meshes se resuelven dentro del paquete suministrado.

Hay dos referencias a meshes de base con un formato de ruta distinto; los límites de esfuerzo/velocidad de elevador y brazos figuran en cero. Preparar las rutas de importación y contrastar límites, signos, ceros y orden SDK con el equipo antes de F7/F8. La identificación AM-ARM200 procede de la elección del usuario; disponer del XML no prueba calibración ni correspondencia con el SDK.

F2 conserva el modelo de navegación existente. La adaptación cinemática del original, transforms de D435i/L2/muñecas, alcance al suelo y trayectoria `loaded_home` con carga siguen pendientes. También siguen pendientes el gestor F4, supervisor VLM F5 y todo ensayo físico.
