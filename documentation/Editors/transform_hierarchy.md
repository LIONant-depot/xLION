# The hierarchy of the transforms

An entity can be the child of another: it has a `parent` component (the entity it belongs to) and its parent has a `children` component (the list of its children). Both are xECS's own.

## Roots and children

| | Transform | World pose |
|---|---|---|
| **root** (no `parent` component) | the world pose | the Transform |
| **child** (has a `parent` component) | **relative to the parent** | derived every frame, kept in the `parent` component (`m_WorldPosition`, `m_WorldRotation`, `m_WorldScale`; never saved) |

- Physics ignores children (`none_of<parent>`): only roots are bodies. A child of a body follows it.
- The world pose is derived by `xlioncore::PropagateHierarchy` (`dependencies/xLIONCore/src/transform/xlioncore_hierarchy.h`), which the render system runs at the start of every frame (edit mode too), after everything that moves things and before anything is drawn. A system that runs before it sees the pose of the last frame.
- Anything that needs the world pose of an entity that may be a child asks `xlioncore::WorldOf(transform, parent*)`: the stored pose when the entity has a `parent`, the Transform when not (`parent*` is a pointer parameter of the Foreach: optional). It never reads `Transform::m_Position` as a world position.
- The gizmo sits at the world pose of what is selected and writes back a relative value (`xlioncore::LocalFromWorld`).

## What a child takes from its parent: `Follow`

The `parent` component has switches, all on its Inspector (`FollowPosition` and `FollowScale` are one row of three checkboxes each, X Y Z, like the physics Constraints):

| FollowPosition X / Y / Z | the child takes that axis of its parent's position; off: its own value for that axis is a **world** value |
|---|---|
| FollowRotation | the child turns with its parent and its offset turns with it; off: its own rotation is a world rotation |
| FollowHeading | only when FollowRotation is off: the child takes the turn of its parent around the vertical axis (where it faces), not its lean or roll |
| FollowScale X / Y / Z | the child is scaled by that axis of its parent's scale (its offset along it too); off (the default): its own scale is its world scale |

A rotation has no X, Y and Z to switch off one by one (rotations do not combine axis by axis, and Euler angles depend on an order and jump at some angles), so it is followed whole, only by its heading (the swing-twist split around the vertical axis), or not at all.

By default everything follows except the scale: in this engine the scale of an entity is also its size (a Primitive is as big as its Scale), and a name tag over a player must not be squashed by the player.

Examples (Soccer): a **name tag** is a child of the player at `(0, 1.45, 0)` with FollowRotation off (it floats straight up when the player leans); a **shadow** is a child at `(0, 0.012, 0)` with FollowPosition Y and FollowRotation off (it stays on the ground when the player jumps, and flat).

## Commands

- `CreateEntity -Parent id` makes a child. `GetWorldPose -Scene s -Id e` says `Child=0|1`, and the world Position, Rotation, Scale.
- `SetProperty ... -Component Parent -Path Parent/FollowPosition/Y -After false`.

Tests: `smoke/test_hierarchy.py`.
