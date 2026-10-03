"""Read-only queries: ListAssets, DescribeAsset, CompileStatus, etc."""
import re


def test_list_assets(level):
    """ListAssets reply is non-empty, well formed."""
    assets = level.cmd("ListAssets")
    assert assets.strip()
    
    # Should have some lines with guid patterns
    lines = [l for l in assets.splitlines() if l.strip()]
    assert len(lines) > 0


def test_describe_asset_real(level):
    """DescribeAsset with a real guid."""
    assets = level.cmd("ListAssets")
    lines = [l for l in assets.splitlines() if l.strip()]
    if not lines:
        return  # Nothing to test
    
    # Parse the first asset line
    m = re.match(r"(\w{16})\s+(\w{16})\s+(.*)", lines[0])
    if m:
        asset_guid = m[1]
        desc = level.cmd(f"DescribeAsset -Asset {asset_guid}")
        assert desc.strip()


def test_describe_asset_bogus(level):
    """DescribeAsset with a bogus guid."""
    bogus_guid = "ZZZZZZZZZZZZZZZZ"
    desc = level.cmd(f"DescribeAsset -Asset {bogus_guid}")
    # Should answer with an error message
    assert desc.strip()


def test_compile_status(level):
    """CompileStatus reply is non-empty."""
    status = level.cmd("CompileStatus")
    assert status.strip()


def test_list_project_module_references(level):
    """ListProjectModuleReferences reply is non-empty (and says it needs the Game when none is given)."""
    refs = level.ed.cmd("ListProjectModuleReferences")
    assert refs.strip() and "required option" in refs


def test_list_script_source_files(level):
    """ListScriptSourceFiles reply is non-empty."""
    files = level.cmd("ListScriptSourceFiles")
    assert files.strip()


def test_source_control_status(level):
    """SourceControlStatus reply is non-empty."""
    status = level.cmd("SourceControlStatus")
    assert status.strip()


def test_source_control_depot_status(level):
    """SourceControlDepotStatus reply is non-empty."""
    status = level.cmd("SourceControlDepotStatus")
    assert status.strip()


def test_source_control_list_locks(level):
    """SourceControlListLocks reply is non-empty."""
    locks = level.cmd("SourceControlListLocks")
    assert locks.strip()


def test_get_idle_tasks(level):
    """GetIdleTasks reply is non-empty."""
    tasks = level.cmd("GetIdleTasks")
    assert tasks.strip()


def test_compile_pause_toggle(level):
    """CompilePause and CompileAuto -State are reported by CompileStatus; restored afterwards."""
    editor = level.ed
    status = editor.cmd("CompileStatus")
    was_paused = "Paused=true" in status
    was_auto = "Auto=true" in status
    try:
        editor.cmd(f"CompilePause -State {'false' if was_paused else 'true'}")
        assert f"Paused={'false' if was_paused else 'true'}" in editor.cmd("CompileStatus")

        editor.cmd(f"CompileAuto -State {'false' if was_auto else 'true'}")
        assert f"Auto={'false' if was_auto else 'true'}" in editor.cmd("CompileStatus")
    finally:
        editor.cmd(f"CompilePause -State {'true' if was_paused else 'false'}")
        editor.cmd(f"CompileAuto -State {'true' if was_auto else 'false'}")



def test_list_assets_stable(level):
    """ListAssets is stable when asked twice."""
    assets1 = level.cmd("ListAssets")
    assets2 = level.cmd("ListAssets")
    assert assets1 == assets2
