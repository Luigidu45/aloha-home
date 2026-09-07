# AlohaMini2 navigation meshes

These files are reduced visual derivatives of the STL meshes referenced by the
AlohaMini2 URDF. They preserve the URDF geometry and scale but are not used for
physics collisions.

Regenerate them from a local AlohaMini2 mesh directory with:

```bash
uv run python dimos/robot/alohamini2/tools/build_navigation_meshes.py \
  /path/to/alohamini2_meshes \
  dimos/robot/alohamini2/assets/meshes
```

The left/right arm meshes in the source package are identical. The MJCF reuses
the optimized `left_*` assets for both arms.
