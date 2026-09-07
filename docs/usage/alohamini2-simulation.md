---
title: "AlohaMini2 Navigation Simulation"
---

# AlohaMini2 navigation simulation

`alohamini2-nav-sim` runs a reduced, navigation-only AlohaMini2 model in
MuJoCo. The base is holonomic and accepts body-frame `Twist` commands. Four
raycast cameras produce a world-frame point cloud for voxel mapping, costmap
generation, and A* replanning.

The default blueprint uses a lightweight primitive approximation of the Go2
office. It preserves a bounded room, desks, chairs, a column, navigation
obstacles, and the same default X/Y spawn, `(-1.0, 1.0)`, while avoiding the
thousand-plus mesh and convex-hull geometries of the original scene.

Use `alohamini2-nav-sim-full` when the exact `scene_office1.xml` environment,
textures, furniture, person, and higher sensor quality matter more than speed.

## Visual and collision models

MuJoCo renders an optimized CAD reconstruction of all 26 visual links from the
AlohaMini2 URDF, including the omni wheels, column, cameras, both arms, wrists,
and grippers. Identical left/right parts share mesh assets, and the optimized
set stays below 200,000 triangles for responsive simulation.

The CAD is visual only. Navigation physics still uses the conservative
primitive collision envelope, and the arm joints remain fixed at the URDF zero
pose. This keeps mapping and holonomic motion deterministic while presenting a
recognizable robot.

Only one DimOS coordinator can run on the same transport bus. Stop an existing
run before launching the simulation:

```bash
dimos stop
dimos run alohamini2-nav-sim
```

The fast profile keeps all five RGB streams at 256x144 and 2 FPS, uses a
40x12 raycast grid per navigation camera at 4 FPS, and omits detailed robot CAD
from the offscreen sensor renders. The native MuJoCo window still renders the
detailed AlohaMini2 model. To restore the previous full-quality profile, run:

```bash
dimos stop
dimos run alohamini2-nav-sim-full
```

The default command opens both MuJoCo's native window and DimOS Viewer. DimOS
Viewer shows five independent RGB feeds reconstructed from the URDF mounts:
`front_camera`, `back_camera`, `chest_camera`, `left_camera`, and
`right_camera`. Alongside them, the Rerun 3D view shows the accumulated
point-cloud map, global costmap, robot pose, navigation goal, and planned path.
The four `nav_*` cameras remain dedicated to raycast lidar, so enabling RGB
does not change the navigation scan geometry.

Run without either graphical viewer with:

```bash
dimos --viewer none run alohamini2-nav-sim
```

To keep Rerun active without opening its native window automatically, use:

```bash
dimos --rerun-open none run alohamini2-nav-sim
```

Inspect the main outputs in separate terminals:

```bash
dimos topic echo /odom
dimos topic echo /pointcloud
dimos topic echo /global_costmap
dimos topic echo /path
dimos topic echo /front_camera_image
dimos topic echo /back_camera_image
dimos topic echo /chest_camera_image
dimos topic echo /left_camera_image
dimos topic echo /right_camera_image
```

Send a navigation goal in the world frame:

```bash
dimos topic send /goal_request \
  'PoseStamped(frame_id="world", position=Vector3(1.5, 0.0, 0.0), orientation=Quaternion(0, 0, 0, 1))'
```

For a direct two-second motion check, open `dimos shell` and run:

```python
from dimos.msgs.geometry_msgs.Twist import Twist
from dimos.msgs.geometry_msgs.Vector3 import Vector3

app.AlohaMini2SimModule.move(
    Twist(linear=Vector3(0.25, 0.0, 0.0), angular=Vector3()),
    duration=2.0,
)
```

The driver limits planar speed and yaw rate and stops a streaming command if
no refresh arrives within 0.25 seconds.

## Acceptance checks

Run the repeatable simulation checks with:

```bash
uv run pytest dimos/robot/alohamini2/test_sim_module.py -v
```

They verify that:

- the MJCF compiles with one free root joint, four navigation cameras, five RGB
  cameras, and IMU sensors;
- the office scene and default X/Y spawn match the Go2 simulation;
- the default lite scene retains navigable obstacles with fewer than 60 total
  composed geometries;
- every camera produces raycast points that reach the room geometry;
- forward and lateral commands produce the expected planar displacement;
- yaw commands rotate the base without roll, pitch, or vertical drift; and
- velocity limits and the 0.25-second command watchdog stop unsafe or stale
  commands.

This first model intentionally keeps the arms rigid and uses primitive
collision geometry. It validates mapping and navigation behavior; wheel
dynamics and the physical hardware adapter are separate follow-up stages.

## Navigation with articulated SO101 arms

`alohamini2-nav-manip-sim` preserves the optimized navigation environment and
sensor settings, but restores the five arm joints and gripper joint on each
SO101. Both arms share the same MuJoCo simulation while exposing independent
hardware views to the control coordinator.

```bash
dimos stop
dimos --simulation run alohamini2-nav-manip-sim
```

The saved pose in
`dimos/robot/alohamini2/assets/alohamini2_so101_home.json` initializes all 12
simulated joints on every launch and reset. Open `dimos shell` to exercise the
first joint-space manipulation API:

```python
# Inspect both arms and normalized gripper states.
app.AlohaMini2ArmControl.get_so101_joint_positions()

# Return both arms to the pose saved by the calibration tool.
app.AlohaMini2ArmControl.go_so101_home(side="both", duration=2.0)

# Move one arm; all angles are radians.
app.AlohaMini2ArmControl.move_so101_joints(
    side="left",
    shoulder_pan=0.0,
    shoulder_lift=-1.2,
    elbow_flex=1.2,
    wrist_flex=0.8,
    wrist_roll=0.0,
    duration=2.0,
)

# 0 is closed and 1 is fully open.
app.AlohaMini2ArmControl.set_so101_gripper(side="left", opening=1.0)

# Emergency stop affects the arm coordinator, not the navigation base.
app.AlohaMini2ArmControl.stop_so101_arms()
app.AlohaMini2ArmControl.clear_so101_estop()
```

Navigation goals and keyboard teleoperation continue to work while arm
trajectories execute. For a safe initial mobile-manipulation workflow, stop the
base before moving an arm outside the stowed envelope.

### Cartesian IK and collision-aware planning

The same blueprint also starts `AlohaMini2ManipulationModule` with a compact
SO101 URDF, Pink IK, and RoboPlan motion planning. The planning scene contains
both arms, their self/inter-arm collision geometry, and a lightweight envelope
for the AlohaMini2 lift column. The detailed STL geometry remains in MuJoCo, so
planning does not add significant rendering or physics cost.

All Cartesian coordinates are relative to the mobile robot's `base_link`, not
the fixed MuJoCo world: +X is forward, +Y is left, and +Z is up. This keeps a
target meaningful after the base navigates. Since SO101 has five arm degrees of
freedom, not every arbitrary 6D position and orientation is reachable; omit
roll/pitch/yaw to preserve the current gripper orientation when possible.

Use `dimos shell` to inspect FK and command a small Cartesian motion:

```python
# Current joints and tool pose in base_link coordinates.
app.AlohaMini2ManipulationModule.get_so101_cartesian_state(side="left")
app.AlohaMini2ManipulationModule.get_so101_cartesian_state(side="right")

# Move the left tool 1 cm forward from the saved home pose. The initial home
# tool positions are approximately (0.2412, +0.1873, 0.6001) on the left and
# (0.2412, -0.1873, 0.6001) on the right.
app.AlohaMini2ManipulationModule.move_so101_to_pose(
    side="left",
    x=0.2512,
    y=0.1873,
    z=0.6001,
)

# Return one arm through collision-checked joint-space planning.
app.AlohaMini2ManipulationModule.go_so101_planned_home(side="left")
```

The lower-level planner RPCs remain available for diagnostics. With two arms,
always pass `robot_name="left_arm"` or `robot_name="right_arm"`:

```python
from dimos.msgs.geometry_msgs.Pose import Pose

target = Pose(0.2512, 0.1873, 0.6001)
app.AlohaMini2ManipulationModule.solve_ik(
    target,
    robot_name="left_arm",
    check_collision=True,
)
app.AlohaMini2ManipulationModule.plan_to_pose(target, robot_name="left_arm")
app.AlohaMini2ManipulationModule.preview_plan(robot_name="left_arm")
app.AlohaMini2ManipulationModule.execute(robot_name="left_arm")
```

Joint-space commands in `AlohaMini2ArmControl` remain useful for calibration
and direct testing. Use `AlohaMini2ManipulationModule` for normal Cartesian
motion, because it validates reachability and plans around the other arm and
central column. Object perception, grasp selection, and autonomous pick/place
are the next layer on top of this validated motion-planning foundation.

Run the focused manipulation checks with:

```bash
uv run pytest dimos/robot/alohamini2/test_manipulation_config.py -v
```

They load the real compact URDF and verify the saved dual-arm home, FK mirror
placement, collision state, Pink IK, and a RoboPlan path for a Cartesian move.
