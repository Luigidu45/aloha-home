---
title: "F6: interfaz de asistencia y supervisión"
---

# F6: solicitud y supervisión desde la interfaz

**Cierre del hito previo al robot: 22/09/2026.** Se completó el flujo por texto con acceso desde un Android real, respuesta a una ambigüedad y cancelación con parada confirmada. La prueba del teléfono y la del VLM se realizaron el 19/09; la regresión final de pausa durante el recorrido, el 22/09. El [plan de trabajo](/docs/development/asistencia_domestica_modular/plan_trabajo.md) permite este cierre por texto y deja la validación de voz hasta F9.

## Qué quedó implementado

| Trabajo de F6 | Resultado |
| --- | --- |
| Solicitud, destino, estado, cámara y mapa | Ruta `/assistance` del cockpit React, adaptable a celular. Cámara MuJoCo con fecha de captura; mapa esquemático de la vivienda sintética con pose actual de la base. |
| Consultas y correcciones | Revisión y confirmación antes de iniciar; conversación conservada; elección de instancia con revisión de escena; aclaraciones durante la misión. |
| Pausa y cancelación | Se envían al gestor F4. La interfaz muestra «Deteniendo» hasta recibir evidencia de parada. Las decisiones VLM tardías quedan invalidadas. |
| Cambio de destino | Mesa del dormitorio o mesa de la sala. Requiere parada y confirmación; conserva el objeto sujeto y vuelve a comprobar las condiciones de transporte. |
| Reconexión y duplicados | Identificador estable de orden, recibos de reintentos, comprobación de sesión y versión. Reconectar o recargar no inicia otra misión. Avisos de conexión e imágenes obsoletas. |
| Voz | Adaptador de dictado local, indicador de escucha y transcripción editable, sin envío automático. Necesita HTTPS confiable y reconocimiento local compatible. Prueba real de micrófono/voz pendiente en F9. |
| Otro dispositivo | El usuario confirmó el ciclo completo desde Chrome en Android, viendo cámara y mapa. |

El formulario está acotado a la misión A: botella pequeña desde la mesa de la sala. El texto se revisa mediante reglas limitadas y el usuario confirma la misión normalizada y su destino. Esto no demuestra interpretación libre de cualquier solicitud. En modo VLM, F5 propone las siguientes acciones usando imágenes reales del simulador, percepción y memoria; F4 conserva la admisión y verificación. El control remoto desde el suelo sigue reservado para la ampliación.

La escena ofrece una botella dibujada. El escenario de ambigüedad introduce dos identidades **artificiales** para probar la interacción; no son dos detecciones visuales de la cámara. El brazo derecho es la referencia de los contratos; agarre, transporte y entrega usan los ejecutores artificiales F4. La base sí navega en MuJoCo. El mapa minimalista representa regiones conocidas y pose; **no es un mapa de ocupación ni prueba de SLAM**.

## Integración con DimOS

Se reutilizan el cockpit existente y el ciclo de vida HTTP/TLS de `FastAPIServer`. El relay WebTransport existente transporta visualizaciones, pero no proporciona este protocolo de órdenes de misión, y su acceso en una LAN requiere contexto seguro. La nueva ruta usa HTTP del mismo origen, estado consultado cada 500 ms e imágenes JPEG. El resto del cockpit conserva su ruta y transporte originales.

- [Servidor HTTP](/dimos/web/household_server.py): rutas limitadas de estado, órdenes e imagen; sirve el cockpit compilado.
- [Sesión e interacción](/dimos/experimental/household_assistant/web_session.py): borrador, confirmación, aclaraciones, selección, pausa, cancelación, cambio de destino, reintentos y registros.
- [Integración del VLM](/dimos/experimental/household_assistant/web_runtime.py): imágenes, percepción/memoria y supervisor F5. La inferencia queda fuera del bloqueo usado por las órdenes HTTP.
- [Interfaz](/web/cockpit/src/assistance/Assistance.tsx): estados, controles, historial, cámara, mapa y dictado.
- [Entrada de ejecución](/dimos/experimental/household_assistant/demo_web.py) y [prueba de navegador](/dimos/experimental/household_assistant/demo_web_browser.py).

Las órdenes llevan sesión, identificador y versión. Un reintento conserva exactamente su identificador y contenido; cambiarlo con el mismo identificador se rechaza. Las órdenes cuya respuesta se perdió se reenvían solo por acción explícita del usuario. Reiniciar el servidor invalida la sesión anterior. Pausa/cancelación siguen admitidas aunque haya cambiado la versión del formulario. El servidor limita el registro de órdenes a 2000 por sesión.

Cada cambio de conversación incrementa una generación. La última admisión VLM comprueba esa generación y que la misión siga habilitada bajo el mismo bloqueo que la cancelación. Así, una respuesta tardía no reinicia la tarea cancelada. No se informa parada física por el simple éxito de una petición HTTP.

La corrección final invalida la región anterior cuando la base navega o cancela entre mesas. Tras una pausa, la secuencia consulta evidencia reciente de la postura cargada: si está confirmada puede navegar; si se perdió, necesita prepararla otra vez. La entrega se verifica en el destino seleccionado, incluyendo el retorno a la sala.

## Reproducción

Desde la raíz del repositorio, con el entorno ya preparado:

```bash
source .venv/bin/activate
deno task --cwd web/cockpit build
MUJOCO_GL=egl python -m dimos.experimental.household_assistant.demo_web .ignore.f6/demo_texto --fixture --scenario ambiguous --host 0.0.0.0
```

El directorio de salida debe ser nuevo. Abrir en el teléfono `http://<IP_LAN_DE_LA_PC>:<PUERTO>/assistance`, en la misma red. El puerto toma `GlobalConfig.household_web_port` (7781 por defecto); se puede cambiar con `--port`. El servidor escucha solo en loopback si no se pasa `--host`. Utilizar una red de prueba de confianza: esta sesión compartida no implementa autenticación de usuarios ni exposición a Internet.

Flujo de interacción:

1. Escribir «Lleva la botella pequeña de la sala al dormitorio», elegir destino y pulsar **Revisar solicitud**.
2. Comprobar el resumen y pulsar **Confirmar e iniciar**.
3. Cuando se solicite, elegir una botella. Las opciones se identifican como artificiales.
4. Probar **Pausar** o **Cancelar tarea** y esperar la confirmación real del gestor.
5. Para redirigir: elegir mesa de la sala, pulsar **Pausar y cambiar destino**, esperar y **Confirmar nuevo destino y continuar**.

Para F5 local real, ejecutar una sesión nueva omitiendo `--fixture`. Los valores predeterminados reutilizan Qwen2.5-VL-3B en `.ignore.f5/models/qwen`, CLIP en `.ignore.f3/models/clip` y YOLO en `.ignore.f3/models/yolo/yolo11n.pt`. La carga y las decisiones consumen CPU; el robot permanece detenido durante la planificación. Este cierre no cambia la selección provisional del modelo ni compara Qwen3.

```bash
MUJOCO_GL=egl python -m dimos.experimental.household_assistant.demo_web .ignore.f6/demo_vlm --host 0.0.0.0
```

Ejecutar **una sola** instancia de la simulación a la vez para evitar que sus transportes compartan estados. Detener con Ctrl-C; se guardan eventos y estado final.

Para la grabación automática, iniciar el servidor con `--fixture --scenario ambiguous` y, en otra terminal, ejecutar el navegador contra ese servidor. Requiere la herramienta opcional Playwright y Chromium instalados; no son dependencias de producción.

```bash
python -m dimos.experimental.household_assistant.demo_web_browser --url http://127.0.0.1:7781 .ignore.f6/nueva_grabacion
```

La prueba graba solo la interfaz y comprueba solicitud incompleta/corrección, elección de botella, pausa después de salir de la mesa, cambio de destino, entrega, recarga, desconexión y reconexión sin otra misión. El viewport móvil de Chromium **no sustituye** la prueba independiente en Android.

## Evidencia y comprobaciones

El [manifiesto F6](/docs/development/asistencia_domestica_modular/fase_6_validacion.json) conserva resultados y hashes de evidencia. Las grabaciones y trazas completas están en `.ignore.f6/` y no se incluyen en Git; para transferirlas a otra máquina hay que copiarlas o archivarlas explícitamente.

| Prueba | Evidencia y resultado |
| --- | --- |
| Android real, 19/09 | `.ignore.f6/browser_fixture/interaction.jsonl` registra Chrome Android, solicitud, selección, cancelación y parada. Confirmación directa del usuario: «Cancelada - parada confirmada»; cámara y mapa visibles. |
| Interacción completa, 19/09 | `.ignore.f6/browser_recording/`: grabación y capturas del flujo con destino modificado y reconexión. |
| Pausa durante el recorrido, 22/09 | `.ignore.f6/final_browser/report.json` y vídeo: pausa a 0,466 m del punto de recogida, retorno a la sala y entrega verificada; ningún error de página. |
| VLM real desde interfaz, 19/09 | `.ignore.f6/live_vlm/interaction.jsonl`: decisión `navigate_to(mesa_sala)` admitida, tensor visual `[180, 1176]`, inferencia de 30,16 s y navegación ejecutada. No es una misión completa dirigida por VLM. |
| Cancelación mientras planifica, 19/09 | `.ignore.f6/vlm_browser_final/report.json` y vídeo: estado final cancelado; 0,812 s desde pulsación hasta confirmación observada por el navegador, incluyendo consultas HTTP. No equivale a una medición de frenado físico. |
| Regresión Python, 22/09 | 131 pruebas del paquete aprobadas; incluye 13 de sesión web y casos de postura de transporte conservada/perdida. |
| Cockpit, 22/09 | 126 pruebas aprobadas y comprobación TypeScript correcta. |
| Tipos Python, 22/09 | Mypy correcto en 10 archivos de producción de F6. |

Pasaron los hooks aplicables de licencia, Ruff, formato, JSON, enlaces, LFS y formato Deno. El único fallo fue el control global de archivos mayores de 75 KB: señaló el cronograma Excel (132 KB), la propuesta PDF (116 KB) y el reporte visual HTML (88 KB), ya existentes y ajenos a F6. Se conservaron sin cambios; el detalle está en el manifiesto.

## Pendientes para las siguientes fases

- **F7–F8:** ejecutor ACT, dataset, control articular y validación física del AlohaMini1; no se infieren de esta demostración.
- **F9:** HTTPS con certificado confiable en Android, permiso de micrófono, disponibilidad del modelo de voz local en español y prueba real de escucha, corrección y notificación. No se recurre automáticamente a reconocimiento de voz remoto. La notificación actual es el estado visible y `aria-live` de la página.
- **F9–F10:** ensayo integrado y evaluación con usuarios. Las pruebas de ingeniería de F6 no equivalen a resultados de utilidad o autonomía doméstica.
