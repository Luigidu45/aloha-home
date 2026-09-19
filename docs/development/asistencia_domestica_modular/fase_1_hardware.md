---
title: "F1: ficha de interfaces del AlohaMini1 y mediciones pendientes"
---

> Plataforma cambiada por el usuario al AlohaMini1 el 15/09/2026. Véase la [migración](/docs/development/asistencia_domestica_modular/migracion_alohamini1.md). Los datos de control y calibración anteriores no son transferibles.

# Hardware objetivo e interfaces

**Fuente de decisiones:** respuestas del usuario durante F1, 12 de septiembre de 2026. Esta ficha distingue elección de hardware de disponibilidad física y de interfaz validada. Los campos pendientes se completarán en F7/F8.

| Elemento | Confirmado por el usuario | Pendiente antes de habilitar hardware |
| --- | --- | --- |
| Plataforma | AlohaMini1, URDF y meshes suministrados | Versión de controlador y firmware, alimentación, interfaces y control de parada. |
| Base | Base de la plataforma original | Transporte/SDK, comando de velocidad, unidades y signos, odometría disponible, referencia temporal, watchdog y confirmación de parada. |
| Elevador | Elevador de la plataforma | Unidad y cero, homing, recorrido y velocidad permitidos, mando/lectura, movimiento relativo a sensores y confirmación de detención. |
| Brazos | Dos cadenas `left_joint1..6` / `right_joint1..6`; modelo comercial y función de cada eje pendientes | Nombres y orden de articulaciones, IDs, grados/radianes/unidades del SDK, modos de posición/velocidad, feedback, límites medidos y sincronización. |
| Pinzas | Una por brazo; transporte con objeto sujeto | Comando de apertura y calibración, carga admisible, corriente/fuerza si está disponible, detección de pérdida y comportamiento durante parada. |
| Cámaras de muñeca | Previstas anteriormente; montaje en AlohaMini1 pendiente de confirmar | Modelos y dispositivos estables, intrínsecos, resolución/FPS, tiempos y transformaciones que dependen de cada brazo. |
| LiDAR | Unitree L2 4D previsto; montaje en la nueva plataforma por confirmar | Driver real, nube e IMU, unidades y tiempos por punto, odometría compatible, calibración LiDAR–IMU y transformación a base. |
| RGB-D superior | RealSense D435i prevista; montaje en la nueva plataforma por confirmar | Dispositivo/serial, streams de color y profundidad alineados, escala de profundidad, intrínsecos, timestamps y transformación a base. |
| Postura de transporte | Regresar el brazo a home con la carga en la pinza | Validar `loaded_home` por objeto/brazo: ángulos, retorno libre de colisiones, espacio de botella/control, otro brazo, velocidad y retención. |
| Computadora | Beelink GTi15 Ultra prevista | Unidad recibida, CPU/RAM/almacenamiento, SO y conexión efectiva al robot; ninguna capacidad se presupone por el nombre comercial. |
| GPU | RTX de 24 GB de VRAM prevista; puede demorarse | Modelo concreto, disponibilidad, conexión, drivers y presupuesto de inferencia/entrenamiento medido. |

Brazo derecho seleccionado por el usuario para las pruebas artificiales de F4; la elección física sigue pendiente de alcance. Las políticas físicas deben declarar qué brazo y cámaras usan; no se supondrá que un checkpoint de un brazo se puede ejecutar en el otro.

## Marcos y sincronización

Documentar transformaciones entre mapa/localización, base, elevador, cámaras superiores, LiDAR y pinzas. «Montaje fijo» significa que el sensor no se mueve respecto de su soporte; aún hay que comprobar si ese soporte se mueve con el elevador. Nunca codificar una transformación constante respecto de la base sin medir esa relación. Las cámaras de muñeca necesitan cinemática actual.

La observación de F1 exige nombre de reloj y tiempo de captura. En hardware se debe registrar el origen de tiempo del sensor, conversión al reloj utilizado por la misión, latencia y tolerancia de asociación. Una marca de tiempo de recepción no se puede presentar silenciosamente como tiempo de captura.

## Modelos disponibles y sus límites

El modelo suministrado está en `/home/luigidu/AlohaMini/AlohaMini1/simulation/src/Aloha/urdf/Aloha.urdf`, con meshes en el directorio hermano `meshes`. Contiene 19 links, tres ruedas continuas, un elevador prismático y dos cadenas de seis articulaciones. Los 13 límites de brazos/elevador tienen mínimo, máximo, esfuerzo y velocidad en cero. No hay articulaciones adicionales llamadas pinza ni cámaras: hay que identificar qué eje corresponde al cierre y confirmar los montajes.

La conversión de navegación conserva la pose CAD y bloquea esos ejes; no copia homes, límites ni controles del modelo anterior. Las cinco vistas RGB son cámaras virtuales añadidas explícitamente. La base usa una aproximación de velocidad holonómica, no el controlador físico de las tres ruedas.

## Mediciones de tarea y acceso pendientes

| Medición o decisión | Cómo cerrarla | Dependencia |
| --- | --- | --- |
| Botella A | Elegir ejemplar y medir masa, dimensiones, contenido y superficie de agarre. | Disponibilidad de objeto y pinza. |
| Control B | Medir dimensiones/grosor, orientaciones sobre el suelo y posibilidad de cierre de pinza sin colisión. | Ensayo de alcance al suelo; no asumirlo a partir de un URDF. |
| Zona de recogida | Medir mesa y posiciones/orientaciones dentro del dominio entrenado. | Robot y calibración. |
| Región de entrega | Acordar lado, altura y alcance con un posible usuario; registrar región y márgenes sobre la mesa. | Persona disponible y medición del entorno. |
| Utilidad | Preguntar qué necesidad resuelve traer la botella/recuperar el control, y cómo quiere solicitar y supervisar la tarea. | Consulta aún no realizada; disponibilidad de participantes no confirmada. |
| Recorrido | Medir pasos libres y huella del robot con ambos brazos y objeto sujeto. | Postura con carga validada. |
| Parada | Comprobar base, elevador y brazos; definir retención del objeto y recuperación del estado tras cancelación. | Controlador físico; independiente de VLM/red/interfaz. |

Consultar a una persona sobre necesidad y región de entrega es trabajo de requisitos, no una prueba clínica. Si inicialmente se trabaja con supuestos del tesista o participantes que no representan al perfil objetivo, se debe declarar esa procedencia.

## Preparación ante el retraso de la GPU

F1 no depende de GPU. F2 puede empezar con la configuración ligera existente de simulación. Antes de F5/F7 se verificará cómputo disponible para decidir dónde ejecutar el VLM y entrenar ACT. La disponibilidad prevista de una RTX no se registra como recurso adquirido; tampoco se promete inferencia local en tiempo real antes de medirla.

Los endpoints, redes y rutas de dispositivos se configurarán mediante las interfaces de DimOS cuando existan adaptadores. Esta ficha no asigna puertos, IPs, frecuencias de control ni límites físicos inventados.

## Percepción y cómputo

Se mantiene la decisión de trabajar localmente en CPU y preparar el cambio a RTX. Los contratos de percepción y memoria siguen disponibles; la nueva geometría exige volver a comprobar extrínsecos, campo visual, alcance y datos de entrenamiento antes de conectar hardware. La [migración](/docs/development/asistencia_domestica_modular/migracion_alohamini1.md) registra las verificaciones nuevas por separado de los resultados históricos.
