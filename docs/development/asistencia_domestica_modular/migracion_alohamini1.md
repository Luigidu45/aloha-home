# Migración de la tesis al AlohaMini1

Cambio solicitado por el usuario el 15/09/2026. **Aclaración posterior:** `AlohaMini1/hardware/arms/stl` ya incluye piezas SO101; los meshes compuestos del URDF aún no se han comparado con ellas. La retirada de prototipos de control SO101 previos no demuestra una diferencia geométrica entre los brazos físicos. La plataforma activa de software es **AlohaMini1**. Se conserva el trabajo F1–F4 de contratos, percepción/memoria, navegación semántica y gestor, con nuevas comprobaciones de integración para esta geometría. Las misiones A (botella sala → dormitorio) y B (control caído, ampliación pendiente) y el brazo derecho de pruebas no cambian.

## Cambios en el repositorio

- Paquete activo: [dimos/robot/alohamini1](/dimos/robot/alohamini1). Modelos, imports, configuración, blueprints, demos y pruebas apuntan a este robot.
- URDF aportado: `/home/luigidu/AlohaMini/AlohaMini1/simulation/src/Aloha/urdf/Aloha.urdf`; meshes del directorio hermano `meshes`. Conversión local reproducible, con licencia de origen, hashes y 19 meshes reducidos.
- Blueprints públicos: `alohamini1-nav-sim`, `alohamini1-nav-sim-full`, `household-navigation-sim` y `household-mission-sim`. Registro regenerado mediante su prueba oficial.
- Retirados los módulos, assets y comandos de control de prototipos SO101/AM-ARM200 anteriores, no validados para este montaje. Esto no se refiere a los STL SO101 del repositorio AlohaMini1. No se ofrecen aliases que carguen silenciosamente otro robot.
- Guía de uso, ficha de hardware y plan actualizados. Los documentos y resultados anteriores están en [el archivo histórico](/docs/development/asistencia_domestica_modular/historico_alohamini2). Sus hashes, métricas y nombres de robot no se reasignan al nuevo modelo. El Excel y las fuentes externas no se modifican.

## Qué permite el URDF y qué queda pendiente

| Parte | Situación actual |
| --- | --- |
| Geometría | 19 links/meshes, transformaciones e inercias conservadas; CAD girado +90° en Z para la convención DimOS. |
| Ruedas | Tres articulaciones continuas; bloqueadas en cero CAD para usar la aproximación holonómica de navegación. No se valida dinámica de ruedas ni odometría física. |
| Brazos y elevador | 12 articulaciones de brazos y un elevador; todos los límites, esfuerzos y velocidades del URDF son cero. Permanecen bloqueados; no se inventan rangos operativos. |
| Pinzas | No hay articulaciones adicionales etiquetadas como pinza. Confirmar la función de los ejes terminales y su correspondencia con el controlador. |
| Sensores | Cinco cámaras RGB virtuales, cuatro vistas de rayos e IMU virtual. No existen cámaras en el URDF. El L2, D435i y cámaras de muñeca previstos requieren confirmar montaje y calibración en esta plataforma. |
| Manipulación F4 | Artificial y etiquetada `origin=test`; no mueve la botella ni demuestra agarre, retención física o retorno articular cargado. |

Antes de habilitar articulación, ACT o hardware hacen falta límites, homes, relación SDK–articulaciones, pinzas y extrínsecos reales. La pregunta al usuario sobre esos archivos y sensores queda pendiente; los sensores virtuales son un supuesto de simulación explícito.

## Navegación y criterio de llegada

Los meshes en cero CAD ocupan aproximadamente 0,459 × 0,425 × 1,090 m, con radio horizontal máximo de 0,346 m respecto de la base. Se adopta ancho de planificación 0,50 m, diámetro de giro 0,80 m y altura 1,15 m, con márgenes sobre esa pose. No sirven para un brazo extendido ni para loaded_home físico.

El primer ensayo nominal quedó fuera de la estación al terminar el navegador y fue rechazado por el gestor. Se expuso `goal_tolerance_m` en el navegador DimOS, manteniendo su valor por defecto de 0,20 m para otros robots y usando 0,10 m en este stack. El ensayo con tolerancia más estricta también mostró que el control de avance frontal podía girar alrededor de una meta cercana. Se añadió seguimiento holonómico opcional: permite velocidad lateral y desacelera proporcionalmente al aproximarse. Se habilita solo en el nuevo stack; los demás robots mantienen su controlador por defecto. Se conserva la tolerancia independiente de llegada de la misión; no se amplía para aceptar el fallo. Los ensayos fallidos se conservan junto con los posteriores.

## Reproducción y evidencia

Los comandos vigentes están en [la guía de simulación](/docs/usage/alohamini1-simulation.md). Para inspeccionar el modelo y cámaras:

```bash
MUJOCO_GL=egl python -m dimos.robot.alohamini1.demo_model .ignore.alohamini1/modelo
```

Las trazas locales están en `.ignore.migration_alohamini1/`. El [registro de validación](/docs/development/asistencia_domestica_modular/migracion_alohamini1_validacion.json) recoge resultados, hashes y limitaciones. Las pruebas mecánicas comparan todas las transformaciones de links, la masa y la envolvente; las de integración comprueban navegación, cancelación y el gestor F4.

Este cambio no valida alcance al suelo, agarre físico, trayectorias bimanuales ni políticas ACT. Esas capacidades continúan en F7–F9 y deben prepararse específicamente para AlohaMini1.

## Resultados de la migración

- 142 pruebas aprobadas: modelo y sensores MuJoCo, controlador holonómico, contratos/gestor F1–F4, registro y CLI.
- 14 escenarios controlados F4 con el resultado esperado.
- Misión A en MuJoCo completada; cancelación durante transporte confirmada en 0,441 s; paso bloqueado termina como fallo con parada confirmada.
- Mypy sin errores en 15 archivos de producción. Los tres ensayos nativos finales corresponden a los mismos hashes de implementación.
- Dos intentos nominales iniciales fueron rechazados por llegada fuera de estación; se conservan en la evidencia y motivaron el ajuste de seguimiento holonómico.

En la suite ampliada del navegador, 116 pruebas pasaron y ocho no pudieron preparar sus datos: necesitan `occupancy_simple.npy`/`three_paths.npy` del servidor LFS privado de DimOS y faltan credenciales. La suite seleccionada de la migración pasó completa. El control global de tamaño sigue señalando el Excel preexistente (132 KB, límite 75 KB), que permanece idéntico al original. Estas limitaciones del entorno no se presentan como pruebas aprobadas.
