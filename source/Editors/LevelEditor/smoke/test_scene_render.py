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


def test_gi_bakes_the_surfels_of_the_meshes_and_holds_its_ray_budget(made):
    """An Environment with GI on: the Police Station's surfels (baked by its GeomStatic compiler, saved in the geometry) are loaded, and each
    frame traces at most the ray budget (a big mesh is updated in slices across frames)."""
    level = made
    e = entity(level, "5CE00021", "Transform,Mesh")
    level.ok(f'SetProperty -Scene {level.scene} -Id {e} -Component Mesh -Path Mesh/Geom -After "{POLICE_STATION}"')
    entity(level, "5CE00022", "Transform,LightSun")
    env = entity(level, "5CE00023", "Transform,Environment")
    level.ok(f"SetProperty -Scene {level.scene} -Id {env} -Component Environment -Path Environment/GI -After true")
    level.ok(f"SetProperty -Scene {level.scene} -Id {env} -Component Environment -Path Environment/GIRayBudget -After 4096")
    got = scene(level, lambda g: g.get("GIMeshes", 0) >= 1 and g.get("GIRays", 0) > 0, timeout=90)
    assert got.get("GIMeshes", 0) >= 1, got
    assert 0 < got["GIRays"] <= 4096, f"the GI holds its ray budget: {got}"


def test_a_mesh_is_picked_by_its_bounds(made):
    """A click on a Mesh selects it: the ray against the box of its geometry, placed by the entity (moved here, so nothing else is in the way)."""
    level = made
    e = entity(level, "5CE00031", "Transform,Mesh")
    level.ok(f'SetProperty -Scene {level.scene} -Id {e} -Component Mesh -Path Mesh/Geom -After "{POLICE_STATION}"')
    level.ok(f"SetProperty -Scene {level.scene} -Id {e} -Component Transform -Path Transform/Position/Y -After 1000")
    scene(level, lambda g: g.get("Drawn", 0) >= 1, timeout=60)       # the geometry is loaded
    deadline = time.time() + 20
    while True:
        hit = level.cmd("PickRay -Origin -26,995,-200 -Dir 0,0,1")
        if "hit" in hit or time.time() > deadline: break
        time.sleep(0.25)
    assert f"Id={e}" in hit, hit
    assert "nothing" in level.cmd("PickRay -Origin -26,995,-200 -Dir 0,0,-1"), "a ray pointing away hits nothing"
