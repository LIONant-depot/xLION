"""Editing in context (documentation/Editors/prefabs_plan.md, phase 7).

Two things are held here.

* The roles of the entities in an editing session (3.7): a Prefab Editor with context scenes draws the context first and fades it, and nothing of it is ever picked - not even to hide what is behind
  it. DescribeRoles says which scene is what, how many entities are context or hidden, and what the last draw did; PickRay answers what a click would select.
* Edit in Context: the prefab of an instance opens as the document of a Prefab Editor, placed where the instance is, with the Level's scenes around it as context and the instance itself left out of the
  draw and the pick. Saving the prefab brings every instance up to date (the one it was opened from too), and the placement is never saved into the prefab.

The Level has to be saved before: the context is the Level as it is saved.
"""
import re
import time

import pytest

from test_prefab_editor import PrefabEditor, _make, _prefab_files, game_level_files_restored, opened      # noqa: F401  (fixtures)
from test_prefab_live import _members, _x
from test_prefabs import _instantiate, _set_position_x, level_files_restored                # noqa: F401  (a fixture)

PARTS = ("Transform", "Primitive")


def _wall(level, x: float, size: float = 4.0) -> str:
    """A cube of the Level (a Transform and a Primitive), `size` wide, at x: what a ray from above meets before it meets the prefab's smaller cube."""
    entity = f"7E57{next(level._ids):04X}"
    level.ok(f"CreateEntity -Scene {level.scene} -Id {entity} -Folder 0 -Components Transform,Primitive")
    level.ok(f"SetProperty -Scene {level.scene} -Id {entity} -Component Transform -Path Transform/Position/X -After {x}")
    for axis in "XYZ":
        level.ok(f"SetProperty -Scene {level.scene} -Id {entity} -Component Transform -Path Transform/Scale/{axis} -After {size}")
    return entity


def _pick(session, x: float, y: float = 0.0):
    """What a click at (x, y) seen from above would select: (scene, id), or None."""
    reply = session.cmd(f"PickRay -Origin {x},{y},10 -Dir 0,0,-1")
    if "hit" not in reply:
        return None
    return re.search(r"Scene=(\w+)", reply)[1], re.search(r"Id=(\w+)", reply)[1]


def _roles(session) -> dict:
    return dict(re.findall(r"^(\w+)=(.*)$", session.cmd("DescribeRoles"), re.M))


def _drawn(session, ok, timeout: float = 30.0) -> dict:
    """The roles once the last draw says what `ok` wants (the editor draws every frame: the numbers follow a change by a frame or two)."""
    deadline = time.time() + timeout
    while True:
        roles = _roles(session)
        if ok(roles) or time.time() > deadline:
            return roles
        time.sleep(0.25)


@pytest.fixture
def closing(editor):
    """The Prefab Editors a test opened by EditInContext (the `opened` fixture only knows the ones it opened itself): closed, without saving, when the test ends."""
    made = []
    yield made
    for p in reversed(made):
        if editor.alive():
            if "Playing" in p.cmd("GetPlayState") or "Paused" in p.cmd("GetPlayState"):
                p.cmd("Stop -Keep false")
                editor.wait_for(f"{p.name}\\GetPlayState", r"PlayState=Stopped", timeout=60)
            p.close()


def _instance_of(level, name: str) -> str:
    """The entity MakePrefab turned into the instance of the prefab (it is named after it)."""
    return next(e for e, label in level.entities().items() if name in label)


def _edit_in_context(level, closing, prefab: str, name: str, instance: str) -> PrefabEditor:
    reply = level.cmd(f"EditInContext -Scene {level.scene} -Id {instance}", timeout=120)
    assert reply.startswith("EditInContext: ok"), reply
    level.ed.wait_for("GetPlayState", r"Building=false", timeout=240)
    closing.append(PrefabEditor(level.ed, prefab, name))
    return closing[-1]


# ---- the roles ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_a_context_scene_is_drawn_faded_and_never_picked_not_even_to_hide_what_is_behind_it(level, opened, level_files_restored):
    prefab, name = _make(level, parts=PARTS)
    _wall(level, 30.0)
    assert "rror" not in level.cmd("Save", allow_disk=True)

    p = opened(prefab, name)
    p.set_x(p.root(), "30.000000")                         # the prefab's cube is under the wall's face: a ray from above meets the wall first
    assert _pick(p, 30.0) == (prefab, p.root()), "without a context there is only the prefab"
    roles = _roles(p)
    assert roles["Document"] == prefab and roles["Context"] == "" and roles["ContextEntities"] == "0" and roles["InContext"] == "0", roles

    assert "ok" in p.cmd(f"AddContextScene -Scene {level.scene}")
    assert _pick(p, 30.0) == (prefab, p.root()), "the wall of the context is in front, and it is not there to be picked: the prefab behind it is"
    assert _pick(p, 30.0, y=1.5) is None, "a ray that meets only the wall selects nothing (the context has no entity ids)"

    roles = _roles(p)
    assert roles["Document"] == prefab and roles["Context"] == level.scene and int(roles["ContextEntities"]) > 1 and roles["HiddenEntities"] == "0", roles
    drawn = _drawn(p, lambda r: r.get("Faded") == "1")
    assert drawn.get("Faded") == "1" and int(drawn["DrawnContext"]) > 0 and int(drawn["DrawnDocument"]) >= 1, f"the context is drawn first and faded, then the document: {drawn}"

    assert "ok" in p.cmd(f"RemoveContextScene -Scene {level.scene}")
    after = _drawn(p, lambda r: r.get("Faded") == "0")
    assert after["Faded"] == "0" and after["ContextEntities"] == "0", f"no context: no fade: {after}"
    assert _pick(p, 30.0) == (prefab, p.root())


# ---- Edit in Context ------------------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_edit_in_context_places_the_prefab_at_the_instance_with_the_level_around_it(level, closing, opened, level_files_restored):
    prefab, name = _make(level, children=1, parts=PARTS)
    instance = _instance_of(level, name)
    _set_position_x(level, instance, "10.000000")
    second = _instantiate(level, prefab)
    _wall(level, 40.0)
    assert "rror" not in level.cmd("Save", allow_disk=True)

    # the context drawn when the prefab is open on its own with the Level as context: the instance is part of it
    plain = opened(prefab, name)
    assert "ok" in plain.cmd(f"AddContextScene -Scene {level.scene}")
    plain_drawn = int(_drawn(plain, lambda r: r.get("Faded") == "1")["DrawnContext"])
    plain.close()

    p = _edit_in_context(level, closing, prefab, name, instance)
    roles = _roles(p)
    assert roles["InContext"] == "1" and roles["Level"].lstrip("0") == level.guid.lstrip("0") and roles["Context"] == level.scene and roles["Instance"] == instance, roles
    assert roles["Placed"].startswith("10.000,"), roles
    assert roles["HiddenEntities"] == "2", f"the instance's root and its one member: {roles}"
    assert p.x(p.root()) == 10.0 and not p.dirty(), "the document's root is where the instance is, and nothing was edited"
    assert _pick(p, 10.0) == (prefab, p.root()), "the prefab is picked at the instance's place"
    assert _pick(p, 40.0) is None, "the Level around it is not"

    drawn = _drawn(p, lambda r: r.get("Faded") == "1")
    assert int(drawn["DrawnContext"]) == plain_drawn - 1, f"the instance is left out of the context (its root is the one Primitive of it): {drawn} against {plain_drawn}"

    # Play shows the Level with its own instance: refused here
    assert "refused" in p.cmd("Play", allow_disk=True)

    # an edit and a save: the prefab's own root stays where it was (the placement is the Level's), the change reaches the instance it was opened from and the other
    member = next(iter(_members(level, instance)))
    other_member = next(iter(_members(level, second)))
    child = next(e for e in p.entities() if e != p.root())
    p.set_x(child, "3.000000")
    assert p.cmd("Save", allow_disk=True) == "Saved" and not p.dirty()
    assert _x(level, member) == 3.0 and _x(level, other_member) == 3.0, "the change reaches the instance it was opened from, and the other"
    assert _x(level, instance) == 10.0, "the override of the instance (where it is) stays"
    after = _drawn(p, lambda r: r.get("Faded") == "1")
    assert after["HiddenEntities"] == "2" and int(after["DrawnContext"]) == plain_drawn - 1, f"the save spawned the instances of this editor's own context again: the instance is still left out: {after}"
    assert p.x(p.root()) == 10.0, "and the document is still where the instance is"
    p.close()

    again = opened(prefab, name)
    assert again.x(again.root()) != 10.0, "the placement was not written into the prefab"
    assert again.x(next(e for e in again.entities() if e != again.root())) == 3.0, "the edit was"


def test_an_instance_that_is_not_saved_yet_is_not_hidden_in_the_context(level, closing, level_files_restored):
    prefab, name = _make(level, parts=PARTS)
    instance = _instance_of(level, name)                              # made in memory: the Level has not been saved with it
    reply = level.cmd(f"EditInContext -Scene {level.scene} -Id {instance}", timeout=120)
    assert reply.startswith("EditInContext: ok") and "not in the saved scene yet" in reply, reply
    closing.append(PrefabEditor(level.ed, prefab, name))
    assert _roles(closing[-1])["HiddenEntities"] == "0"


def test_edit_in_context_refuses_what_is_not_the_root_of_an_instance_and_a_prefab_already_open(level, closing, opened, level_files_restored):
    prefab, name = _make(level, children=1, parts=PARTS)
    instance = _instance_of(level, name)
    member = next(iter(_members(level, instance)))
    plain = level.new_entity()
    assert "not the root of a prefab instance" in level.cmd(f"EditInContext -Scene {level.scene} -Id {member}")
    assert "not the root of a prefab instance" in level.cmd(f"EditInContext -Scene {level.scene} -Id {plain}")
    assert "was not found" in level.cmd(f"EditInContext -Scene {level.scene} -Id 7E5799FF")

    p = opened(prefab, name)
    assert "already open" in level.cmd(f"EditInContext -Scene {level.scene} -Id {instance}")
    assert "not edited in context yet" in p.cmd(f"EditInContext -Scene {level.scene} -Id {instance}"), "an editor of a prefab does not open another in context (yet)"


def test_get_prefab_game_says_the_prefabs_own_game_while_an_editor_in_context_works_under_the_levels(game_level, closing, game_level_files_restored):
    """The editor opened in context works under the Level's Game (an in-memory override): GetPrefabGame still says what the prefab names (ContextGame is the other), and SetPrefabGame is seen at once."""
    lv = game_level
    level_game = re.search(r"^Game=(\S+)", lv.ed.cmd(f"GetLevelGame -Level {lv.guid}"), re.M)[1]
    prefab, name = _make(lv, parts=PARTS)
    instance = _instance_of(lv, name)
    assert lv.ed.cmd(f"SetPrefabGame -Prefab {prefab}", allow_disk=True) == ""
    assert "rror" not in lv.cmd("Save", allow_disk=True)
    p = _edit_in_context(lv, closing, prefab, name, instance)
    got = lv.ed.cmd(f"GetPrefabGame -Prefab {prefab}")
    assert "Source=none" in got and f"ContextGame={level_game}" in got, got
    assert lv.ed.cmd(f"SetPrefabGame -Prefab {prefab} -Game {level_game}", allow_disk=True) == ""
    got = lv.ed.cmd(f"GetPrefabGame -Prefab {prefab}")
    assert "Source=set" in got and re.search(r"^Game=(\S+)", got, re.M)[1] == level_game, got
    p.close()
    assert "ContextGame" not in lv.ed.cmd(f"GetPrefabGame -Prefab {prefab}"), "the override is gone with the editor"


def test_an_edit_in_context_that_cannot_be_entered_leaves_no_editor_behind(level, level_files_restored):
    """The prefab's editor opens, then the context cannot be entered (the instance has no Transform to place the prefab at): that editor is closed again, with the Level's Game dropped."""
    prefab, name = _make(level, parts=())                      # a root with no component at all
    instance = _instance_of(level, name)
    reply = level.cmd(f"EditInContext -Scene {level.scene} -Id {instance}", timeout=120)
    assert reply.startswith("EditInContext:") and "no Transform" in reply, reply
    deadline = time.time() + 15
    while name in [s.name for s in level.ed.sessions()] and time.time() < deadline:
        time.sleep(0.2)
    assert name not in [s.name for s in level.ed.sessions()], "no plain Prefab Editor is left open"
    assert "ContextGame" not in level.ed.cmd(f"GetPrefabGame -Prefab {prefab}")
