"""Prefab operations: instantiate, revert, hierarchy overrides."""
import re
import pytest
from harness import b64


def test_prefab_operations(level):
    """Prefab operations if prefabs exist in the project."""
    # Check if there are any prefabs in the project
    assets = level.cmd("ListAssets")
    
    # Look for Prefab type
    prefab_lines = [l for l in assets.splitlines() if "Prefab" in l]
    
    if not prefab_lines:
        pytest.skip("the example project has no prefabs to test")
    
    # Get the first prefab
    m = re.match(r"(\w{16})\s+(\w{16})\s+(.*)", prefab_lines[0])
    if not m:
        pytest.skip("could not parse prefab from ListAssets")
    
    prefab_guid = m[1]
    
    # Instantiate the prefab
    entity = f"7E57{next(iter([1])):04X}"
    level.ok(f"InstantiatePrefab -Scene {level.scene} -Id {entity} -Prefab {prefab_guid} -Folder 0")
    
    # Describe should show the instance component
    desc = level.describe(entity)
    assert "Instance" in desc or "prefab" in desc.lower()


def test_revert_override(level):
    """RevertOverride on a prefab instance."""
    # Check if there are any prefabs
    assets = level.cmd("ListAssets")
    prefab_lines = [l for l in assets.splitlines() if "Prefab" in l]
    
    if not prefab_lines:
        pytest.skip("the example project has no prefabs to test")
    
    m = re.match(r"(\w{16})\s+(\w{16})\s+(.*)", prefab_lines[0])
    if not m:
        pytest.skip("could not parse prefab from ListAssets")
    
    prefab_guid = m[1]
    
    # Instantiate the prefab
    entity = f"7E57{next(iter([1])):04X}"
    level.ok(f"InstantiatePrefab -Scene {level.scene} -Id {entity} -Prefab {prefab_guid} -Folder 0")
    
    # Get a property from the instance
    desc = level.describe(entity)
    # Find a property that can be modified
    m = re.search(r"(Transform/Position/X).*=\s*(\S+).*\(TypeGuid (\w+)\)", desc)
    if not m:
        pytest.skip("could not find a modifiable property on the prefab instance")
    
    path, value, type_guid = m[1], m[2], m[3]
    
    # Modify the property
    new_value = "999.000000"
    level.ok(f"SetProperty -Scene {level.scene} -Id {entity} -Component {m[0].split()[0]} -Path {b64(path)}"
             f" -TypeGuid {type_guid} -Before {b64(value)} -After {b64(new_value)}")
    
    # Revert the override
    level.ok(f"RevertOverride -Scene {level.scene} -Id {entity} -Component {m[0].split()[0]} -Path {b64(path)}"
             f" -TypeGuid {type_guid} -Before {b64(new_value)} -After {b64(value)}")


def test_revert_all_overrides(level):
    """RevertAllOverrides on a prefab instance."""
    # Check if there are any prefabs
    assets = level.cmd("ListAssets")
    prefab_lines = [l for l in assets.splitlines() if "Prefab" in l]
    
    if not prefab_lines:
        pytest.skip("the example project has no prefabs to test")
    
    m = re.match(r"(\w{16})\s+(\w{16})\s+(.*)", prefab_lines[0])
    if not m:
        pytest.skip("could not parse prefab from ListAssets")
    
    prefab_guid = m[1]
    
    # Instantiate the prefab
    entity = f"7E57{next(iter([1])):04X}"
    level.ok(f"InstantiatePrefab -Scene {level.scene} -Id {entity} -Prefab {prefab_guid} -Folder 0")
    
    # Try to revert all overrides
    level.ok(f"RevertAllOverrides -Scene {level.scene} -Id {entity}")


def test_revert_hierarchy_overrides(level):
    """RevertHierarchyOverrides on a prefab instance."""
    # Check if there are any prefabs
    assets = level.cmd("ListAssets")
    prefab_lines = [l for l in assets.splitlines() if "Prefab" in l]
    
    if not prefab_lines:
        pytest.skip("the example project has no prefabs to test")
    
    m = re.match(r"(\w{16})\s+(\w{16})\s+(.*)", prefab_lines[0])
    if not m:
        pytest.skip("could not parse prefab from ListAssets")
    
    prefab_guid = m[1]
    
    # Instantiate the prefab
    entity = f"7E57{next(iter([1])):04X}"
    level.ok(f"InstantiatePrefab -Scene {level.scene} -Id {entity} -Prefab {prefab_guid} -Folder 0")
    
    # Try to revert hierarchy overrides
    level.ok(f"RevertHierarchyOverrides -Scene {level.scene} -Id {entity}")


def test_delete_child_of_instance_and_undo(level):
    """Delete a child of a prefab instance and undo."""
    # Check if there are any prefabs
    assets = level.cmd("ListAssets")
    prefab_lines = [l for l in assets.splitlines() if "Prefab" in l]
    
    if not prefab_lines:
        pytest.skip("the example project has no prefabs to test")
    
    m = re.match(r"(\w{16})\s+(\w{16})\s+(.*)", prefab_lines[0])
    if not m:
        pytest.skip("could not parse prefab from ListAssets")
    
    prefab_guid = m[1]
    
    # Instantiate the prefab
    entity = f"7E57{next(iter([1])):04X}"
    level.ok(f"InstantiatePrefab -Scene {level.scene} -Id {entity} -Prefab {prefab_guid} -Folder 0")
    
    # Find a child of the instance
    desc = level.describe(entity)
    # Look for child entities in the description
    children = re.findall(r"(\w{8})\s+.*", desc)
    
    if len(children) > 1:  # At least one child
        child_id = children[1]
        level.ok(f"DeleteEntity -Scene {level.scene} -Id {child_id}")
        assert child_id not in level.entities()
        
        level.cmd("Undo")
        assert child_id in level.entities()
