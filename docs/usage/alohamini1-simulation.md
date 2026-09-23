---
title: "AlohaMini1 simulation"
---

# AlohaMini1 en MuJoCo

La plataforma activa es el AlohaMini1 suministrado por el usuario. La simulación usa sus 19 meshes y transformaciones URDF. Los brazos y el elevador permanecen en cero CAD porque sus límites están sin completar; no hay ejecutor articular físico ni simulación de agarre habilitados.

```bash
source .venv/bin/activate
dimos --simulation run alohamini1-nav-sim
# Escena de oficina completa:
dimos --simulation run alohamini1-nav-sim-full
# Vivienda de la tesis:
dimos --simulation run household-navigation-sim
# Gestor F4 con navegación y manipulación artificial:
dimos --simulation run household-mission-sim
```

El perfil completo necesita los datos de oficina de DimOS. Los perfiles ligero y doméstico usan los assets locales. Las cinco cámaras RGB y los rayos de navegación son sensores virtuales; no representan extrínsecos calibrados de una D435i ni un modelo exacto del L2.

Para repetir la misión A sin interfaz gráfica ni VLM:

```bash
MUJOCO_GL=egl python -m dimos.experimental.household_assistant.demo_mission --scenario nominal --output .ignore.alohamini1/nominal
```

El directorio de salida debe ser nuevo. Se necesita permitir transportes locales LCM/Zenoh. La misión usa el brazo derecho como referencia artificial y no mueve la malla de la botella ni acciona los brazos.

Para usar imágenes con un VLM local en CPU, véanse la [configuración, comandos y evaluación de F5](/docs/development/asistencia_domestica_modular/fase_5_vlm.md). El supervisor visual usa el mismo gestor con la secuencia automática de F4 deshabilitada; sus consultas y propuestas quedan registradas.

Se retiraron comandos y blueprints de control de prototipos anteriores porque no estaban validados para el AlohaMini1; esto no implica que las piezas SO101 locales sean incompatibles. Los identificadores `alohamini1-nav-sim`, `alohamini1-nav-sim-full` y `aloha-mini1-sim-module` sustituyen los anteriores; los dos nombres `household-…` se conservan.

Véanse la [migración y validación](/docs/development/asistencia_domestica_modular/migracion_alohamini1.md), la [configuración](/dimos/robot/alohamini1/config.py) y el [origen del modelo](/dimos/robot/alohamini1/assets/README.md).

Para solicitar y supervisar la misión desde un celular, véanse la [interfaz F6, comandos y grabaciones](/docs/development/asistencia_domestica_modular/fase_6_interfaz.md). El cockpit ofrece texto, elección de objeto, cambio de destino, pausa/cancelación, cámara y mapa esquemático. El modo `--fixture` usa la secuencia artificial F4; al omitirlo utiliza el VLM local F5. La validación de voz permanece pendiente para F9.

En F7 el usuario confirmó seguidores SO101 de 7,4 V sobre la base AlohaMini1. La simulación usa los meshes compuestos del URDF original y mantiene los brazos bloqueados. El directorio original `hardware/arms/stl` contiene piezas SO101; falta verificar su correspondencia con esos meshes y con el montaje real. El [pipeline ACT y protocolo de captura](/docs/development/asistencia_domestica_modular/fase_7_act.md) usa tres cámaras y un perfil artificial separado, sin actuadores.
