"""AddComponent/RemoveComponent, undo/redo, and component list."""
import pytest
from harness import b64


def test_add_component_undo_redo(level):
    """Add a component, undo, verify values restored, redo."""
    entity = level.new_entity()
    _, _, transform = level.find_with_component("Transform")
    
    before_desc = level.describe(entity)
    level.ok(f"AddComponent -Scene {level.scene} -Id {entity} -Component {transform}")
    assert f"[{transform}] Transform" in level.describe(entity)
    
    level.cmd("Undo")
    assert level.describe(entity) == before_desc
    
    level.cmd("Redo")
    assert f"[{transform}] Transform" in level.describe(entity)


def test_remove_component_undo_redo(level):
    """Remove a component, undo restores it with prior values."""
    entity = level.new_entity()
    _, _, transform = level.find_with_component("Transform")
    level.ok(f"AddComponent -Scene {level.scene} -Id {entity} -Component {transform}")   # new entities are bare

    # Set a property before removing
    path = "Transform/Position/X"
    type_guid = level.property_type(entity, path)
    original = level.ed.property_value(level.name, level.scene, entity, path)
    level.ok(f"SetProperty -Scene {level.scene} -Id {entity} -Component {transform} -Path {b64(path)}"
             f" -TypeGuid {type_guid} -Before {b64(original)} -After {b64('5.000000')}")
    assert level.ed.property_value(level.name, level.scene, entity, path) == "5.000000"
    
    # Remove the component
    level.ok(f"RemoveComponent -Scene {level.scene} -Id {entity} -Component {transform}")
    assert f"[{transform}] Transform" not in level.describe(entity)
    
    # Undo restores the component with prior values
    level.cmd("Undo")
    assert f"[{transform}] Transform" in level.describe(entity)
    assert level.ed.property_value(level.name, level.scene, entity, path) == "5.000000"


@pytest.mark.xfail(reason="AddComponent does not refuse adding a component that already exists", strict=False)
def test_add_component_already_has_it_refused(level):
    """Adding a component that already exists is refused."""
    entity = level.new_entity()
    _, _, transform = level.find_with_component("Transform")
    
    # Add the component to the entity
    level.ok(f"AddComponent -Scene {level.scene} -Id {entity} -Component {transform}")
    
    # Try to add it again - should be refused (but currently not)
    assert "already has" in level.cmd(f"AddComponent -Scene {level.scene} -Id {entity} -Component {transform}")


def test_remove_component_does_not_have_refused(level):
    """Removing a component that doesn't exist is refused."""
    entity = level.new_entity()
    _, _, transform = level.find_with_component("Transform")

    # The new entity is empty, so it has no Transform to remove
    assert "does not have" in level.cmd(f"RemoveComponent -Scene {level.scene} -Id {entity} -Component {transform}")


def test_list_component_types(level):
    """ListComponentTypes lists Transform and Primitive."""
    types = level.cmd("ListComponentTypes")
    assert "Transform" in types
    assert "Primitive" in types


def test_describe_entity_format(level):
    """DescribeEntity output format: [guid] Name for components, path = value (TypeGuid xxxxxxxx) for properties."""
    entity = level.new_entity()
    _, _, transform = level.find_with_component("Transform")
    level.ok(f"AddComponent -Scene {level.scene} -Id {entity} -Component {transform}")   # new entities are bare

    desc = level.describe(entity)
    assert f"[{transform}] Transform" in desc
    
    path = "Transform/Position/X"
    type_guid = level.property_type(entity, path)
    assert f"{path} = " in desc
    assert f"(TypeGuid {type_guid})" in desc
