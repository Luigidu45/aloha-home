# Modelo AlohaMini1 para navegación

Origen: `AlohaMini1/simulation/src/Aloha/urdf/Aloha.urdf` y `AlohaMini1/simulation/src/Aloha/meshes` del repositorio AlohaMini proporcionado por el usuario. La licencia Apache 2.0 del repositorio de origen se conserva en `LICENSE`.

`source.urdf` conserva el export CAD con espacios finales normalizados. `robot.xml` es la conversión portable para MuJoCo; `manifest.json` identifica hashes del origen y de los meshes reducidos (hasta 5000 triángulos por pieza), decisiones y articulaciones bloqueadas.

El URDF no proporciona límites utilizables de brazos/elevador: todos son cero. La simulación mantiene la pose CAD sin actuadores. Las ruedas también se fijan para usar la aproximación de base holonómica existente. Las cámaras e IMU son añadidos virtuales, sin calibración física. La correspondencia entre los seis ejes de cada cadena y la pinza queda pendiente; no se afirma que existan seis ejes independientes más pinza.

Regeneración desde la raíz del repositorio:

```bash
python -m dimos.robot.alohamini1.tools.build_model /ruta/AlohaMini1/simulation/src/Aloha dimos/robot/alohamini1/assets
```

La rotación CAD → DimOS es +90° en Z: +X hacia delante y +Y hacia la izquierda. La pose CAD no es home ni loaded_home. El manifiesto y las pruebas comparan las transformaciones originales, sin atribuir calibración física al modelo.
