# Placing systems: constraints, connectors and the available systems

What runs in a game is exactly what is **placed** in its system graph: at the top level of the frame, or in a **connector** of another system (the Physics system has "Before Step" and
"After Step": the systems in them run once for every fixed step, right before the world takes it or right after). A system that is not placed is one of the **available systems**: it
does not run.

## Constraints

A system can only be placed where everything it needs is given. A constraint is an empty type that names itself (`xecs::system::constraint`):

```cpp
struct fixed_delta_time { static constexpr auto typedef_v = xecs::system::constraint::def{ .m_pName = "Fixed Delta Time", .m_pDescription = "..." }; };

struct players : xecs::system::instance
{
    using constraints = std::tuple<xlioncore::constraint::fixed_delta_time>;     // what the system needs of its place
    ...
};

// a connector says what it gives (xlioncore_physics_system.h)
static constexpr auto m_FixedStepGives = xecs::system::constraint::provides_v<xlioncore::constraint::fixed_delta_time>;
static constexpr std::array<xecs::system::connector, 2> connectors_v{ { { "Before Step", "...", m_FixedStepGives }, { "After Step", "...", m_FixedStepGives } } };
```

The constraint is **abstract**: `fixed_delta_time` says "every run of the system is one fixed step of the game's time (`game_time::m_FixedDeltaTime`)". It does not say *when* in the step: before it or
after it is where the person places the system, and both connectors of the Physics give it. A system that needs `fixed_delta_time` never counts the steps itself; it takes one step each time it runs
(and reads `kFixedDt`). The top level of the frame gives no constraint: a system that needs one cannot be placed there.

A system that needs nothing (most of them) can go anywhere, and starts out placed at the top level when no registry file says otherwise.

## The registry

`Project.config\SystemOrder.config.txt` has one entry per system of the game: its place (parent system and connector) and `Placed`. A system that is not in the file is new (a script module added it): it
waits as an available system until a person places it. A file written before systems had to be placed has no `Placed` field: every system in it was running, so every one is placed; the systems it does not
mention wait. When a placement cannot be made (the parent is gone, the place does not give what the system needs now) the system is an available system again.

## The System Registry panel

* the **tree** is what is placed; each system shows the constraints it needs as small tags after its name, each connector the ones it gives (hover: what each means);
* **Unused systems (N)** is the first part of the section below the tree (the parts of that section start closed): the systems that are not placed (the list shrinks as they are placed: what is left over is what does not run);
* drag a system from there into the tree to place it; drag a placed one onto the Unused header to take it out (what is connected under it goes with it); each drop runs one of the commands below;
* while a system is dragged, the places that do not give what it needs are dimmed and take nothing; hovering one says what is missing.

## Commands (undoable, the same for the panel and for an AI)

Every edit of the registry is a command, so it is in the undo history (Ctrl+Z / Ctrl+Y undo and redo it, a change that moves several systems is one step) and an AI can do everything the panel does:

| Command | What it does |
|---|---|
| `SetSystemParent -System s [-Parent p -Connector c]` | places a system at the top level of the frame, or last in a connector; refused (with the reason) when the place does not give what it needs |
| `UnplaceSystem -System s` | takes a system out of the graph; what is connected under it goes with it |
| `MoveSystem -System s -To t` | s takes the place of t: the same connector (or the top level) and the position t had |
| `SetSystemEnabled -System s -Enabled 0|1` | a disabled system is placed but does not run |

A system is named as `ListSystems` shows it, or by its guid in hex (the panel uses the guid: names can repeat). `ListSystems` shows what each system needs, NOT PLACED, the hierarchy and the available systems.

These are edits of the Level: it has unsaved changes after one, and Save, Save All and Play write the registry (`Project.config\SystemOrder.config.txt`) with it; a play session reverts them on Stop.
A refused command changes nothing and is not an undo step. Tests: `smoke/test_system_constraints.py`.

## The time of a fixed step

`game_time::m_FixedInterpolate` (0..1) is how far between the last two fixed states a frame is drawn (`m_FixedAccumulator / m_FixedDeltaTime`; 1 when there is nothing to blend). Drawing a body that the fixed steps move
by blending its previous and its current pose with it is `render_transform`:

- **Opt-in.** A body that carries a `RenderTransform` component (Basics category; Soccer's ball, players, referee and goalkeepers do) is drawn between its last two fixed steps; one without it is drawn at the pose of the last step, as before.
- **Smooth, not exact.** The physics keeps the pose before each step (`m_PrevPosition`, `m_PrevRotation`) - nothing else is stored. The render draws `lerp(previous, Transform, m_FixedInterpolate)` (slerp for the rotation), with the game's own `m_FixedInterpolate` and the live `Transform`, so an edit is always seen. The `Transform` is never touched: it is the pose of the last step, the one gameplay reads and writes. Only the render (`DrawnPoseOf` / `WorldOf(T, parent, render_transform*, interpolate)`, and `PropagateHierarchy` for the children of the body) reads the blended pose; the children of a blended body follow it.
- **Teleports are detected, not announced.** A body further than `render_transform::kSnapDistance` (2 m) from its previous pose was teleported or moves too fast for a step to be smoothed: there is nothing to smooth, so it is drawn at its `Transform`. So is a body with no previous pose yet (NaN until the physics has run). `GetTimeScale` shows the `fixed interpolate` of the frame.
- **Paused / single step.** A paused game draws the last frame's alpha; one fixed step (`m_FixedInterpolate` = 1) draws exactly the pose of the step.

Tests: `smoke/test_render_transform.py` (the previous pose, the game's fixed interpolate, a teleported body).
