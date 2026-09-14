# AlohaMini2 original: modelo AM-ARM200 para MuJoCo

Derivado del paquete `AlohaMini2/urdf/alohamini2` de [liyiteng/AlohaMini](https://github.com/liyiteng/AlohaMini), checkout local `17c6a98d79881a45ab869c1f392ed89c0723a298`, suministrado por el usuario. Licencia Apache-2.0; se conserva la [licencia del proveedor](/dimos/robot/alohamini2/assets/am_arm200/LICENSE). `source.urdf` conserva el XML del proveedor con espacios finales normalizados. El SHA-256 de los bytes originales está en [manifest.json](/dimos/robot/alohamini2/assets/am_arm200/manifest.json).

El [conversor](/dimos/robot/alohamini2/tools/build_am_arm200.py) produce `robot.xml` y meshes STL simplificados (objetivo de 5000 triángulos por pieza). Conserva frames, ejes, masas e inercias del URDF, y las dos cadenas originales de seis ejes más pinza. Cambios respecto del original:

- Las tres coordenadas virtuales de base se sustituyen por un freejoint y el controlador holonómico ya existente. Ruedas fijas como en el URDF; no se simulan motores/rodillos individuales.
- El marco CAD gira +90° en Z para expresar +X hacia delante y +Y hacia la izquierda. La altura inicial de base es 0,005 m.
- Se añaden 15 actuadores de posición: elevador, siete articulaciones izquierdas y siete derechas. Ganancias, amortiguación y límites de fuerza son parámetros de simulación; el URDF proporciona esfuerzo/velocidad cero para estos actuadores.
- Colisión convexa por pieza de los brazos; envolvente y patín de base aproximados. Se excluye la pareja alojamiento de muñeca–mandíbula móvil de cada pinza porque sus envolventes convexas se solapan en la referencia CAD. No se excluyen colisiones entre brazos ni con el entorno.
- Cámaras RGB en los cinco links CAD, con convenciones ópticas de simulación. Los rayos de navegación mantienen el sensor aproximado de cuatro vistas de F2; no son un modelo calibrado del Unitree L2. No se afirma que los montajes reales de D435i/L2 estén representados con medidas verificadas.

La postura inicial tiene todas las articulaciones a cero según el URDF. No es una calibración de home ni de `loaded_home` con carga. El sitio `left_tool`/`right_tool` marca el origen del link de mandíbula fija; no acredita un TCP físico calibrado.

Para regenerar en este checkout: `.venv/bin/python -m dimos.robot.alohamini2.tools.build_am_arm200 /home/luigidu/AlohaMini/AlohaMini2/urdf/alohamini2 dimos/robot/alohamini2/assets/am_arm200`. Los STL derivados se distribuyen mediante Git LFS; la ejecución usa estos assets locales y no depende de la ruta personal del proveedor. La copia de LICENSE se conserva junto al modelo.

Los ensayos y las instrucciones de uso están en la [nota de adaptación](/docs/development/asistencia_domestica_modular/adaptacion_am_arm200.md).
