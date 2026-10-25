"""A Material Instance's overrides are addressed by the parameter's id ("Overrides[G:id]/..."), not by their place: a file of the old form ("Overrides[G:0]/...")
reads the same, and UpgradeProject writes it by id. The files it rewrites are put back when the run ends (project_guard: Descriptors/MaterialInstance)."""
import re

from harness import REPO

DESCRIPTORS = REPO / "example.lionprj" / "Descriptors"
OLD = DESCRIPTORS / "MaterialInstance" / "05" / "00" / "5E1CE0A110000005.desc" / "Descriptor.txt"      # one override of the old form


def _entries(text: str) -> dict:
    """Override key -> {property: value text} of a descriptor's text."""
    out = {}
    for key, prop, value in re.findall(r'"material_instance_descriptor/Overrides\[G:(\d+)\]/(\w+(?:/\w+)?)"\s+;\S+\s+(.*?)\s*$', text, re.M):
        out.setdefault(int(key), {})[prop] = value
    return out


def test_upgrade_project_writes_material_instance_overrides_by_parameter_id(level):
    before = OLD.read_text()
    old = _entries(before)
    assert 0 in old, "the file is of the old form (by place)"
    param_id = int(old[0]["ID"].lstrip("#"), 16)

    reply = level.cmd("UpgradeProject", allow_disk=True)
    m = re.search(r"UpgradeProject: (\d+) material instance\(s\) whose overrides were addressed by place, written by parameter id; 0 left", reply)
    assert m and int(m[1]) >= 1, reply

    new = _entries(OLD.read_text())
    assert 0 not in new and param_id in new, "written by the parameter's id"
    assert new[param_id] == old[0], "the same override: its id, type, value, texture and name hint"
    assert re.search(r"UpgradeProject: 0 material instance\(s\)", level.cmd("UpgradeProject", allow_disk=True)), "nothing left of the old form"
