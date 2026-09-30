"""Folder create/delete/move and undo/redo."""
from harness import b64


def test_create_folder(level):
    """CreateFolder creates a folder."""
    folder_id = "F0000001"
    level.ok(f"CreateFolder -Scene {level.scene} -Id {folder_id} -Parent 0 -Name {b64('TestFolder')}")
    
    folders = level.cmd(f"ListFolders -Scene {level.scene}")
    assert "TestFolder" in folders


def test_create_nested_folder(level):
    """CreateFolder with -Parent creates nested folder."""
    parent_id = "F0000001"
    child_id = "F0000002"
    level.ok(f"CreateFolder -Scene {level.scene} -Id {parent_id} -Parent 0 -Name {b64('Parent')}")
    level.ok(f"CreateFolder -Scene {level.scene} -Id {child_id} -Parent {parent_id} -Name {b64('Child')}")
    
    folders = level.cmd(f"ListFolders -Scene {level.scene}")
    assert "Parent" in folders
    assert "Child" in folders


def test_delete_folder_promotes_children(level):
    """DeleteFolder promotes entities and child folders to parent."""
    folder_id = "F0000001"
    level.ok(f"CreateFolder -Scene {level.scene} -Id {folder_id} -Parent 0 -Name {b64('Parent')}")
    entity = level.new_entity()
    
    # Move entity into folder
    level.ok(f"MoveToFolder -Scene {level.scene} -Id {entity} -Folder {folder_id}")
    
    # Create child folder
    child_id = "F0000002"
    level.ok(f"CreateFolder -Scene {level.scene} -Id {child_id} -Parent {folder_id} -Name {b64('Child')}")
    
    level.ok(f"DeleteFolder -Scene {level.scene} -Id {folder_id}")
    
    # Entity and child folder should be promoted to root
    folders = level.cmd(f"ListFolders -Scene {level.scene}")
    assert "Child" in folders
    assert f"{folder_id}" not in folders


def test_move_to_folder(level):
    """MoveToFolder moves entity into folder and out to root."""
    entity = level.new_entity()
    folder_id = "F0000001"
    level.ok(f"CreateFolder -Scene {level.scene} -Id {folder_id} -Parent 0 -Name {b64('TestFolder')}")

    assert "folder not found" in level.cmd(f"MoveToFolder -Scene {level.scene} -Id {entity} -Folder F00000EE")
    level.ok(f"MoveToFolder -Scene {level.scene} -Id {entity} -Folder {folder_id}")
    assert entity in level.entities()
    
    # Move out to root
    level.ok(f"MoveToFolder -Scene {level.scene} -Id {entity} -Folder 0")
    assert entity in level.entities()


def test_list_folders_reflects_changes(level):
    """ListFolders reflects every folder operation."""
    folder_id = "F0000001"
    level.ok(f"CreateFolder -Scene {level.scene} -Id {folder_id} -Parent 0 -Name {b64('TestFolder')}")
    assert "TestFolder" in level.cmd(f"ListFolders -Scene {level.scene}")
    
    level.ok(f"DeleteFolder -Scene {level.scene} -Id {folder_id}")
    assert "TestFolder" not in level.cmd(f"ListFolders -Scene {level.scene}")
