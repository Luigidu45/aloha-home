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

Se retiraron los comandos de calibración/diseño SO101 y el blueprint antiguo de manipulación porque pertenecían a otra mecánica. Los identificadores `alohamini1-nav-sim`, `alohamini1-nav-sim-full` y `aloha-mini1-sim-module` sustituyen los anteriores; los dos nombres `household-…` se conservan.

Véanse la [migración y validación](/docs/development/asistencia_domestica_modular/migracion_alohamini1.md), la [configuración](/dimos/robot/alohamini1/config.py) y el [origen del modelo](/dimos/robot/alohamini1/assets/README.md).
