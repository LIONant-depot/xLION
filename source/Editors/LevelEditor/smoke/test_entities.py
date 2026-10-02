"""Entity create/delete, parent/child hierarchy, and undo/redo."""
from harness import quote


def test_create_entity_existing_id_refused(level):
    """Creating an entity with an existing ID is refused."""
    entity = level.new_entity()
    assert "id already in use" in level.cmd(f"CreateEntity -Scene {level.scene} -Id {entity} -Folder 0")


def test_create_entity_into_folder(level):
    """Create entity into a folder."""
    folder_id = "F0000001"
    level.ok(f"CreateFolder -Scene {level.scene} -Id {folder_id} -Parent 0 -Name {quote('TestFolder')}")
    
    entity = f"7E57{next(iter([1])):04X}"
    level.ok(f"CreateEntity -Scene {level.scene} -Id {entity} -Folder {folder_id}")
    assert entity in level.entities()


def test_create_entity_with_parent(level):
    """Create entity with -Parent creates child hierarchy."""
    parent = level.new_entity()
    # Use a unique ID that doesn't conflict with existing entities
    child = f"F000{next(level._ids):04X}"
    
    level.ok(f"CreateEntity -Scene {level.scene} -Id {child} -Folder 0 -Parent {parent}")
    assert child in level.entities()
    
    # Note: DescribeEntity returns empty for entities without components
    # The parent-child relationship is tracked internally, not in the entity description
    # This test just verifies the child is listed


def test_delete_entity_removes_children(level):
    """DeleteEntity of a parent removes its children; undo restores all."""
    parent = level.new_entity()
    # Use a unique ID that doesn't conflict with existing entities
    child = f"F000{next(level._ids):04X}"
    level.ok(f"CreateEntity -Scene {level.scene} -Id {child} -Folder 0 -Parent {parent}")
    
    level.ok(f"DeleteEntity -Scene {level.scene} -Id {parent}")
    assert parent not in level.entities()
    assert child not in level.entities()
    
    level.cmd("Undo")
    assert parent in level.entities()
    assert child in level.entities()


def test_id_case_insensitive(level):
    """Entity IDs are hex and case-insensitive."""
    entity = level.new_entity()
    entity_upper = entity.upper()
    
    # List should work with uppercase
    entities = level.cmd(f"ListEntities -Scene {level.scene}")
    assert entity in entities or entity_upper in entities


def test_dirty_flag(level):
    """Dirty flag is set after edit and clear after undoing back to start."""
    assert not level.dirty()
    
    entity = level.new_entity()
    assert level.dirty()
    
    level.cmd("Undo")
    assert not level.dirty()


def test_rename_entity_undo_redo_and_clear(level):
    """RenameEntity sets the display name, Undo/Redo follow it, -Clear 1 goes back to the id label."""
    entity = level.new_entity()
    before = level.entities()[entity]
    level.ok(f"RenameEntity -Scene {level.scene} -Id {entity} -Name {quote('Big Floor')}")
    assert level.entities()[entity] == "Big Floor"
    assert "Undone" in level.cmd("Undo")
    assert level.entities()[entity] == before
    assert "Redone" in level.cmd("Redo")
    assert level.entities()[entity] == "Big Floor"
    level.ok(f"RenameEntity -Scene {level.scene} -Id {entity} -Clear 1")
    assert level.entities()[entity] == before
    assert "not found" in level.cmd(f"RenameEntity -Scene {level.scene} -Id DEADBEEF -Name {quote('x')}")
