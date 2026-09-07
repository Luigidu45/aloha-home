---
title: "Hardware objetivo y procedencia del modelo AlohaMini2"
---

**Decisión del usuario, 7 de septiembre de 2026:** AlohaMini2 completo, incluidos dos brazos AM-ARM200. LiDAR Unitree L2 y RealSense D435i superiores, más una cámara de muñeca por brazo. Esta configuración sustituye la propuesta SO101.

**Identificación del URDF**

Se comparó `/home/luigidu/Downloads/alohamini2pro.urdf` con el [URDF oficial de AlohaMini2 Pro](https://github.com/liyiteng/AlohaMini/blob/17c6a98d79881a45ab869c1f392ed89c0723a298/AlohaMini2/urdf/alohamini2pro/urdf/alohamini2pro.urdf). Todos los elementos link y joint coinciden tras normalización XML: no hay enlaces ni articulaciones añadidos, eliminados o modificados. El [README oficial](https://github.com/liyiteng/AlohaMini/blob/17c6a98d79881a45ab869c1f392ed89c0723a298/README.md) identifica AM-ARM200 como el sistema de brazos de AlohaMini2.

| Identificador | Valor |
| --- | --- |
| Repositorio fuente | `liyiteng/AlohaMini` |
| Commit consultado | `17c6a98d79881a45ab869c1f392ed89c0723a298` |
| Nombre de robot del archivo local | `alohamini2pro_urdf` |
| SHA-256 del archivo local | `bd1b1e6d619d3160fcf1f7faa27a564f933128dc7d729ef87d6e170818389844` |
| Git blob del URDF Pro oficial | `ddfb01f9e91748c7aec17c638dc892eccdd6b603` |

Cada brazo contiene seis articulaciones de brazo y una articulación de pinza. Con prefijo `left_` o `right_`, sus nombres en el URDF son `shoulder_pan`, `shoulder_lift`, `elbow_flex`, `wrist_flex`, `wrist_yaw_joint`, `wrist_roll` y `gripper`. Las cámaras de muñeca tienen uniones fijas. Estos nombres son del modelo y no confirman IDs de motores ni orden de comandos del SDK.

También existe un [URDF oficial estándar](https://github.com/liyiteng/AlohaMini/blob/17c6a98d79881a45ab869c1f392ed89c0723a298/AlohaMini2/urdf/alohamini2/urdf/alohamini2.urdf). Identificar los brazos como AM-ARM200 no demuestra que toda la base, elevación y servoeléctrica de las variantes estándar/Pro sean intercambiables. Confirmar la variante comprada antes de fijar el adaptador físico.

**Limitaciones concretas de integración**

- En el URDF local, las articulaciones móviles de los brazos declaran `effort=0` y `velocity=0`, con límites angulares genéricos de aproximadamente ±3,14. No son límites de operación física validados.
- Las referencias de mallas mezclan rutas `package://` con rutas relativas. Hay que resolver el paquete y comprobar geometría, escala, inercia, colisiones y convenciones de ejes antes de importarlo a MuJoCo.
- La D435i y el L2 superiores son la configuración elegida por el usuario; no asumir que sus montajes y extrínsecos ya estén representados en ese URDF. Deben medirse o modelarse explícitamente.
- Los blueprints actuales de [simulación AlohaMini2](/dimos/robot/alohamini2/blueprints/alohamini2_nav_sim.py) incorporan SO101. Son una implementación heredada y todavía no simulan los AM-ARM200 objetivo. No se han renombrado para aparentar equivalencia.

**Ficha de preparación física**

| Componente | Confirmado | Pendiente |
| --- | --- | --- |
| Base y elevación | Plataforma AlohaMini2 completa | Variante, controlador, interfaz, odometría, homing, límites y parada verificable. |
| Brazos | Dos AM-ARM200 | SDK, transporte, IDs, unidades, signos, rangos y calibración de pinzas. |
| LiDAR | Unitree L2 superior | Driver y transporte disponibles, timestamps, frame y extrínsecos. |
| Cámara superior | RealSense D435i | Resolución/frecuencia, streams utilizados y calibración con LiDAR/base. |
| Cámaras de muñeca | Dos cámaras | Modelo, dispositivos estables, intrínsecos y montajes. |
| Operación | Beelink GTi15 Ultra prevista | CPU/RAM reales disponibles, latencias y dependencia de cómputo externo. |
| Entrenamiento | Objetivo de 24 GB VRAM | GPU y acceso efectivo, aún no confirmados. |

El núcleo de [misiones domésticas](/docs/development/tesis/implementacion_inicial.md) usa acciones semánticas y observaciones comunes. No depende del número de articulaciones: la migración del modelo y los drivers se realiza en adaptadores, no en el supervisor ni en el formato del dataset.
