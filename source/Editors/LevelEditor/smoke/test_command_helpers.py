"""The commands that spare the caller the bookkeeping: components by name, an entity made with its components in one command, a property set without saying its type and its old value, and a
property read without describing the whole entity.

The old forms (type guid in hex, -TypeGuid and -Before given) keep working: the other tests use them.
"""
import re

PHYSICS_PARTS = "Transform,Physics,PhysicsBodyProperties,PhysicsColliderSphere,PhysicsDynamics"


def prop(level, entity, component, path) -> str:
    return level.cmd(f"GetProperty -Scene {level.scene} -Id {entity} -Component {component} -Path {path}")


def test_an_entity_is_made_with_its_components_in_one_command_and_the_undo_takes_it_away(level):
    entity = "7E57C001"
    level.ok(f"CreateEntity -Scene {level.scene} -Id {entity} -Folder 0 -Components {PHYSICS_PARTS}")
    described = level.describe(entity)
    for part in PHYSICS_PARTS.split(","):
        assert re.search(rf"\] {part}\b", described), (part, described)
    level.cmd("Undo")
    assert entity not in level.entities(), "one undo removes the entity with everything it was given"


def test_a_component_that_is_not_known_is_refused_before_anything_is_made(level):
    entity = "7E57C002"
    assert "unknown component 'Nonsense'" in level.cmd(f"CreateEntity -Scene {level.scene} -Id {entity} -Folder 0 -Components Transform,Nonsense")
    assert entity not in level.entities(), "nothing was left behind"


def test_a_component_is_named_by_its_name_in_any_case_or_by_its_guid(level):
    entity = "7E57C003"
    level.ok(f"CreateEntity -Scene {level.scene} -Id {entity} -Folder 0 -Components transform")
    guid = re.search(r"^\[(\w{16})\] Transform\b", level.describe(entity), re.M)[1]
    level.ok(f"SetProperty -Scene {level.scene} -Id {entity} -Component TRANSFORM -Path Transform/Position/X -After 3")
    assert prop(level, entity, "Transform", "Transform/Position/X") == "3.000000"
    assert prop(level, entity, guid, "Transform/Position/X") == "3.000000", "the guid of the lists works as before"
    level.cmd("Undo"); level.cmd("Undo")


def test_a_property_is_set_without_its_type_and_its_old_value_and_the_undo_restores_the_old_value(level):
    entity = "7E57C004"
    level.ok(f"CreateEntity -Scene {level.scene} -Id {entity} -Folder 0 -Components {PHYSICS_PARTS}")
    sensor = "PhysicsColliderSphere/Spheres[G:0]/IsSensor"
    assert prop(level, entity, "PhysicsColliderSphere", sensor) == "false"
    level.ok(f"SetProperty -Scene {level.scene} -Id {entity} -Component PhysicsColliderSphere -Path {sensor} -After true")
    assert prop(level, entity, "PhysicsColliderSphere", sensor) == "true", "a bool, the editor knew"
    level.ok(f"SetProperty -Scene {level.scene} -Id {entity} -Component Transform -Path Transform/Position/Y -After 4.5")
    assert prop(level, entity, "Transform", "Transform/Position/Y") == "4.500000", "a float"
    level.cmd("Undo")
    assert prop(level, entity, "Transform", "Transform/Position/Y") == "0.000000", "the undo gave back the value the editor read before the change"
    level.cmd("Undo")
    assert prop(level, entity, "PhysicsColliderSphere", sensor) == "false"
    level.cmd("Undo")


def test_a_property_that_is_not_there_is_said_not_guessed(level):
    entity = "7E57C005"
    level.ok(f"CreateEntity -Scene {level.scene} -Id {entity} -Folder 0 -Components Transform")
    assert "no such property" in prop(level, entity, "Transform", "Transform/Nope")
    assert "no such property" in level.cmd(f"SetProperty -Scene {level.scene} -Id {entity} -Component Transform -Path Transform/Nope -After 1")
    assert "unknown component" in prop(level, entity, "NoSuchComponent", "Transform/Position/X")
    assert "target not found" in prop(level, "7E57FFFF", "Transform", "Transform/Position/X")
    level.cmd("Undo")


def test_the_forms_with_everything_given_still_work(level):
    entity = "7E57C006"
    level.ok(f"CreateEntity -Scene {level.scene} -Id {entity} -Folder 0 -Components Transform")
    guid = re.search(r"^\[(\w{16})\] Transform\b", level.describe(entity), re.M)[1]
    level.ok(f"SetProperty -Scene {level.scene} -Id {entity} -Component {guid} -Path Transform/Position/Z -TypeGuid 8CC78B69 -Before 0 -After 2")
    assert prop(level, entity, "Transform", "Transform/Position/Z") == "2.000000"
    level.cmd("Undo"); level.cmd("Undo")
