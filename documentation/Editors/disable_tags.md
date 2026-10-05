# disable, no_render, editor_disable, editor_no_render

Four tags (no data) that turn things off, in two pairs. The pairs never fight over a tag: the game's state is the game's, what the editor does while you work is the editor's.

| | where | kind | what it does |
|---|---|---|---|
| `disable` | Basics, `xlioncore_tags.h` | exclusive tag | The entity is out of the game: **every system skips it**. |
| `no_render` | Basics, `xlioncore_tags.h` | tag | The render leaves the entity out **in every view** (and it is not picked). It goes on existing and running: physics, scripts. |
| `editor_disable` | `xecs_editor.h` | exclusive tag | Like `disable`, but the state of the entity in the **editor**. |
| `editor_no_render` | `xecs_editor.h` | tag | The editor's **scene view** leaves the entity out. A game view still draws it. |

All four are saved with the scene like any tag. `disable` and `no_render` are authored state (the Add Component list, or scripts). The `editor_*` tags are the state the person left the scene in ("get this
out of my way while I work"): the Level Tree sets them, they are not in the Add Component list, the Inspector shows them like any component, and the scene/level compiler leaves them out of what the game
gets, with the rest of what the game does not need. Play saves the scenes and rebuilds the world from the save, so the state goes through Play and Stop with them.

## Why one of each pair is exclusive

An entity whose archetype has an *exclusive* tag only matches the queries that name that tag (xECS, `query::Compare` with the archetype's exclusive-tag bits). No system names `disable` or `editor_disable`,
so none of them (physics, the render, the scripts of a game, ...) sees such an entity, and not a line of code in any of them had to change. Disabling is adding the tag, enabling is removing it: nothing is
destroyed, the entity and all its components are as they were. The two render tags are regular tags the render systems exclude (`none_of`), because the entity must stay visible to everything else.

## Views

`xlionrender::view` (`xlionrender_view.h`) says which view asks: `Draw(..., view)` and `Pick(..., view)`. Every view leaves out `no_render` and what is exclusive-tagged; the **scene** view (the editor's
viewport) also leaves out `editor_no_render`; the **game** view shows the game as it is. This is the standard split (Unity's scene visibility, Unreal's hidden-in-editor flag). Today the only view is the
scene view; a game view only has to pass `view::game`. The render collects once per `Draw` for the view that asks (`system::Collect(view)`, `LeaveOut`).

## In the editor

The Level Tree has two columns to the right of the source control column, on every entity row:

- **Enabled** (the power icon): click adds or removes `editor_disable`. Red while the entity is disabled.
- **Visible** (the eye): click adds or removes `editor_no_render`. The eye has a slash while the entity is hidden.

A click acts on the entity **and everything under it**, as most editors do: the state the clicked entity is about to have is given to all its descendants (each gets the tag, or loses it), and the whole
change is one undo step (`xeditor::RunGroup` of the `AddComponent` / `RemoveComponent` commands).

**Headers.** The tree has a header row (it stays while the tree scrolls). The narrow columns show only their icon; hovering a header says what the column is and how many entities it is on ("3 of 52 entities
are disabled in the editor"). A right-click on a header opens the menu of the column: *Enabled*: Enable all, Disable selected, Enable selected; *Visible*: Show all, Hide selected, Show selected. Each is one
undo step, and "selected" is the tree's selection with everything under it.

**Amber says "something is switched off in here".** The header icon takes the amber while anything is disabled (or hidden) in the open scenes, and a row takes the same amber when it is not switched off itself
but something under it is (so a disabled child inside a collapsed parent is not lost). Red / slashed on a row means that entity itself.

## Limits (today)

- The tags are on the entities themselves, set when the toggle is clicked: an entity added later under a disabled parent is not disabled, and adding a tag by hand touches only that entity.
- A physics body that already exists is not touched by `disable` or `editor_disable`: its colliders are builder components, consumed when the entity is created in the game, so a body that is taken out could
  not be built again when the entity is enabled. Taking a body out of the physics world (and bringing it back) is the next step.

Tests: `test_disable_tags.py`.
