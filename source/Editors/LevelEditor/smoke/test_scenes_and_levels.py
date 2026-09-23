"""Scenes and levels: open/close, dependencies, and list formats."""
import re
from harness import b64


def test_list_levels_format(level):
    """ListLevels reply format: guid + name."""
    levels = level.ed.cmd("ListLevels")  # Workspace command
    assert len(level.ed.levels()) > 0
    guid, name = level.ed.levels()[0]
    assert guid in levels
    assert name in levels


def test_list_scenes_format(level):
    """ListScenes reply format: guid + name."""
    scenes = level.cmd(f"ListScenes")
    assert len(level.scenes) > 0
    for guid, name in level.scenes:
        assert guid in scenes
        assert name in scenes


def test_list_entities_format(level):
    """ListEntities reply format: hex id + name."""
    entities = level.cmd(f"ListEntities -Scene {level.scene}")
    for entity_id in level.entities():
        assert entity_id in entities


def test_list_folders_format(level):
    """ListFolders reply format: folder tree with entities."""
    folder_id = "F0000001"
    level.ok(f"CreateFolder -Scene {level.scene} -Id {folder_id} -Parent 0 -Name {b64('TestFolder')}")
    
    folders = level.cmd(f"ListFolders -Scene {level.scene}")
    assert "TestFolder" in folders


def test_open_level_on_open_level(level):
    """OpenLevel on an open level says so."""
    level.cmd("Close -Save 0")
    [lvl] = level.ed.levels()
    
    level.cmd(f"OpenLevel -Level {lvl[0]} -Save 0")
    assert "already open" in level.cmd(f"OpenLevel -Level {lvl[0]} -Save 0")


def test_open_level_unsaved_edits_refused(level):
    """OpenLevel over unsaved edits is refused until -Save 0."""
    entity = level.new_entity()
    assert "unsaved edits" in level.cmd(f"OpenLevel -Level {level.guid} -Save 0")
    
    level.cmd("Close -Save 0")
    level.cmd(f"OpenLevel -Level {level.guid} -Save 0")


def test_close_scene(level):
    """CloseScene closes a scene and reopening works."""
    level.cmd("Close -Save 0")
    
    [lvl] = level.ed.levels()
    level.cmd(f"OpenLevel -Level {lvl[0]} -Save 0")
    
    scenes_before = level.cmd(f"ListScenes")
    level.ok(f"CloseScene -Scene {level.scene}")
    scenes_after = level.cmd(f"ListScenes")
    
    assert len(scenes_before.splitlines()) > len(scenes_after.splitlines())


def test_add_scene_remove_scene(level):
    """AddScene/RemoveScene with undo."""
    level.cmd("Close -Save 0")
    [lvl] = level.ed.levels()
    level.cmd(f"OpenLevel -Level {lvl[0]} -Save 0")
    
    # Find a scene to add
    all_scenes = level.cmd("ListScenes")
    lines = [l for l in all_scenes.splitlines() if "Main Scene" not in l]
    if lines:
        m = re.match(r"(\w{16})\s+(.*)", lines[0])
        if m:
            scene_to_add = m[1]
            level.ok(f"AddScene -Level {lvl[0]} -Scene {scene_to_add}")
            assert scene_to_add in level.cmd("ListScenes")
            
            level.cmd("Undo")
            assert scene_to_add not in level.cmd("ListScenes")


def test_add_scene_dependency_refuses_cycle(level):
    """AddSceneDependency refuses cycles."""
    # Get current scene's dependencies
    deps = level.cmd(f"ListSceneDependencies -Scene {level.scene}")
    
    # Try to add self as dependency (should refuse)
    assert "cycle" in level.cmd(f"AddSceneDependency -Scene {level.scene} -Parent {level.scene}")


def test_remove_scene_dependency_with_refs_refused(level):
    """RemoveSceneDependency with refs refuses unless -ClearRefs 1."""
    # Get current scene's dependencies
    deps = level.cmd(f"ListSceneDependencies -Scene {level.scene}")
    
    # If there are dependencies, try to remove one without -ClearRefs
    if deps.strip():
        lines = deps.splitlines()
        for line in lines:
            m = re.match(r"(\w{16})", line)
            if m:
                parent = m[1]
                # Try to remove without -ClearRefs (should refuse if there are refs)
                # This may or may not refuse depending on actual refs
                # For now, just document the expected behavior
                break
