"""Meshes, lights and the Environment of a Level through the forward renderer (xlionrender::instance: shadows, probes, GI), DescribeScene says what the last render had.

The geometry is the Police Station of the example project (Police folder: a GeomStatic with 55 material instances, 99 textures). Its resources load the first time they are asked for,
so the numbers settle a few frames after a change.
"""
import re
import time

import pytest

pytestmark = pytest.mark.needs_window          # needs a window: the viewport renders (skipped for a headless editor, see conftest.py)

POLICE_STATION = "1B2E7050C4FC9D73, E5359948C52D26D1"


def scene(level, until, timeout: float = 60.0) -> dict:
    """The numbers of the last render, once `until` holds for them (or the timeout)."""
    deadline = time.time() + timeout
    while True:
        got = {k: int(v) for k, v in re.findall(r"(\w+)=(\d+)", level.cmd("DescribeScene"))}
        if until(got) or time.time() > deadline:
            return got
        time.sleep(0.25)


@pytest.fixture
def made(level):
    """The entities a test makes, undone after: the Level is left as it was found, nothing was saved."""
    yield level
    for _ in range(200):
        if level.cmd("Undo") != "Undo: done":
            break


def entity(level, eid: str, components: str) -> str:
    level.ok(f"CreateEntity -Scene {level.scene} -Id {eid} -Folder 0 -Components {components}")
    return eid


def test_a_mesh_its_materials_and_the_lights_are_rendered(made):
    level = made
    before = scene(level, lambda g: "Meshes" in g, timeout=20)
    assert "Meshes" in before, level.cmd("DescribeScene")

    e = entity(level, "5CE00001", "Transform,Mesh")
    level.ok(f'SetProperty -Scene {level.scene} -Id {e} -Component Mesh -Path Mesh/Geom -After "{POLICE_STATION}"')
    entity(level, "5CE00002", "Transform,LightSun")
    entity(level, "5CE00003", "Transform,LightPoint")
    entity(level, "5CE00004", "Transform,LightSpot")

    got = scene(level, lambda g: g.get("Drawn") == before["Drawn"] + 1 and g.get("ConstantSlots") == before["ConstantSlots"])
    assert got["Meshes"] == before["Meshes"] + 1 and got["Drawn"] == before["Drawn"] + 1, got
    assert got["ConstantSlots"] == before["ConstantSlots"], f"every material slot of the Police Station resolves to its material instance: {got}"
    assert got["Sun"] >= 1 and got["Lights"] == before["Lights"] + 2, got
    assert got["DrawsRendered"] >= 1, got


def test_a_mesh_without_a_geometry_is_not_drawn_and_nothing_breaks(made):
    level = made
    before = scene(level, lambda g: "Meshes" in g, timeout=20)
    entity(level, "5CE00011", "Transform,Mesh")
    got = scene(level, lambda g: g.get("Meshes") == before["Meshes"] + 1, timeout=20)
    assert got["Meshes"] == before["Meshes"] + 1 and got["Drawn"] == before["Drawn"] and got["Waiting"] == before["Waiting"] + 1, got
