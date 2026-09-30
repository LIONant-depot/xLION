"""Robustness: commands with missing/malformed arguments."""
import pytest
from harness import b64


# Workspace commands from golden/commands.txt
# Note: Save, Close, and other disk writers are excluded - they require allow_disk=True
WORKSPACE_COMMANDS = [
    "Play", "Pause", "Step", "Undo", "Redo", "Close",
    "ListLevels", "ListScenes", "ListAssets", "ListProjectModuleReferences",
    "ListScriptSourceFiles", "CompileStatus", "CompilePause", "CompileAuto",
    "SourceControlStatus", "SourceControlDepotStatus", "SourceControlListLocks",
    "GetIdleTasks", "AuditComponentUsage",
]

# Session commands (from help output)
SESSION_COMMANDS = [
    "CreateEntity", "DeleteEntity", "AddComponent", "RemoveComponent",
    "SetProperty", "DescribeEntity", "ListEntities", "ListFolders",
    "Undo", "Redo", "Select", "ToggleMultiSelect", "RenameEntity",
]   # ClearSelection takes no arguments, so it answers with an empty success reply


def test_workspace_command_no_args(level):
    """Workspace commands with no arguments."""
    editor = level.ed
    
    for cmd in WORKSPACE_COMMANDS:
        reply = editor.cmd(cmd)
        # Should answer with a message (error or usage)
        assert reply.strip(), f"{cmd} should answer with a message"


def test_session_command_no_args(level):
    """Session commands with no arguments."""
    editor = level.ed
    
    for cmd in SESSION_COMMANDS:
        reply = editor.cmd(f"{level.name}\\{cmd}")
        # Should answer with a message (error or usage)
        assert reply.strip(), f"{level.name}\\{cmd} should answer with a message"


def test_command_with_malformed_guid(level):
    """Commands with malformed guid (ZZZ, empty, 40 hex digits)."""
    editor = level.ed
    
    # Malformed guids
    malformed = ["ZZZ", "", "A" * 40]
    
    for guid in malformed:
        reply = editor.cmd(f"ListAssets -Asset {guid}")
        # Should answer with a message
        assert reply.strip(), f"ListAssets with guid={guid!r} should answer with a message"


def test_command_with_huge_value(level):
    """Commands with a huge value (100 KB)."""
    editor = level.ed
    
    huge_value = "X" * 100000
    reply = editor.cmd(f"Say -Message {huge_value}")
    # Should answer with a message (either success or error about size)
    assert reply.strip(), "Command with huge value should answer with a message"


def test_command_with_bad_base64(level):
    """Commands with bad base64 value."""
    editor = level.ed
    
    reply = editor.cmd(f"Say -Message ZZZ!!!invalid_base64!!!")
    # Should answer with a message
    assert reply.strip(), "Command with bad base64 should answer with a message"


@pytest.mark.xfail(reason="known crash: SetProperty with unparseable -Before/-After", strict=False)
def test_set_property_with_unparseable_before_after(level):
    """SetProperty with unparseable -Before/-After crashes the editor."""
    editor = level.ed
    entity = level.new_entity()
    
    # This is known to crash - we mark it xfail
    editor.cmd(f"{level.name}\\SetProperty -Scene {level.scene} -Id {entity} -Component 0000000000000000"
               f" -Path {b64('Transform/Position/X')} -TypeGuid 0000000000000000"
               f" -Before {b64('not_a_number')} -After {b64('also_not_a_number')}")
    # If we get here, the crash didn't happen - the bug is fixed!
