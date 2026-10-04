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

The `parent` component has five switches, all on its Inspector:

| FollowX / FollowY / FollowZ | the child takes that axis of its parent's position; off: its own value for that axis is a **world** value |
|---|---|
| FollowRotation | the child turns with its parent and its offset turns with it; off: its own rotation is a world rotation |
| FollowScale | the child is scaled by its parent (offset included); off (the default): its own scale is its world scale |

By default everything follows except the scale: in this engine the scale of an entity is also its size (a Primitive is as big as its Scale), and a name tag over a player must not be squashed by the player.

Examples (Soccer): a **name tag** is a child of the player at `(0, 1.45, 0)` with FollowRotation off (it floats straight up when the player leans); a **shadow** is a child at `(0, 0.012, 0)` with FollowY and FollowRotation off (it stays on the ground when the player jumps, and flat).

## Commands

- `CreateEntity -Parent id` makes a child. `GetWorldPose -Scene s -Id e` says `Child=0|1`, and the world Position, Rotation, Scale.
- `SetProperty ... -Component Parent -Path Parent/FollowY -After false`.

Tests: `smoke/test_hierarchy.py`.
