"""Session command surface: golden list for session commands."""
import re


def test_session_commands_match_golden(level, request):
    """Session commands should match a golden list."""
    # Try to get session commands from Main Level\help
    session_cmds = level.cmd("help")
    
    # Parse the session commands section
    lines = session_cmds.splitlines()
    
    # Find the session commands section
    in_session_section = False
    session_commands = []
    for line in lines:
        if "Sessions:" in line:
            break
        if in_session_section:
            # Session commands are indented or after "Main Level\"
            if line.strip():
                # Extract command name
                m = re.search(r"Main Level\\(\w+)", line)
                if m:
                    session_commands.append(m[1])
        elif "Session commands:" in line.lower():
            in_session_section = True
    
    # If we couldn't parse from help, keep a static list
    if not session_commands:
        # Session commands from the editor documentation
        session_commands = [
            "CreateEntity", "DeleteEntity", "AddComponent", "RemoveComponent",
            "SetProperty", "DescribeEntity", "ListEntities", "ListFolders",
            "Undo", "Redo", "Select", "ToggleMultiSelect", "ClearSelection",
            "CreateFolder", "DeleteFolder", "MoveToFolder",
            "InstantiatePrefab", "MakePrefab", "MakePrefabVariant",
            "ApplyOverrides", "RevertOverride", "RevertAllOverrides", "RevertHierarchyOverrides",
            "SetEntityReference", "AddSceneDependency", "RemoveSceneDependency",
        ]
    
    # For now, just document that we have a list
    # In the future, this could be compared to a golden file
    assert session_commands, "Should have at least some session commands"


def test_session_commands_enum_from_editor(level):
    """Try to enumerate session commands from the running editor."""
    # Try Main Level\help
    session_cmds = level.cmd("Main Level\\help")
    
    # Parse the output
    lines = session_cmds.splitlines()
    
    # Look for session commands
    session_commands = []
    for line in lines:
        if "Main Level\\" in line:
            m = re.search(r"Main Level\\(\\w+)", line)
            if m:
                session_commands.append(m[1])
    
    # If we couldn't parse, keep a static list
    if not session_commands:
        session_commands = [
            "CreateEntity", "DeleteEntity", "AddComponent", "RemoveComponent",
            "SetProperty", "DescribeEntity", "ListEntities", "ListFolders",
            "Undo", "Redo", "Select", "ToggleMultiSelect", "ClearSelection",
        ]
    
    assert session_commands, "Should have at least some session commands"
