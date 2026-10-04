"""The hierarchy of the transforms: an entity with a parent component is a CHILD, its Transform is relative to its parent, and its world pose is derived every frame (xlioncore_hierarchy.h).
A root's Transform is its world pose. What a child takes from its parent (the position axes, the rotation, the scale) is the Follow of its parent component.
GetWorldPose says the world pose of any entity; the editor draws every frame, so the derived pose settles a frame or two after a change.
"""
import math
import re
import time

import pytest


class node:
    """An entity of the Level: a Transform and a Primitive, optionally the child of another."""
    def __init__(self, level, entity, parent=None, position=(0, 0, 0), components="Transform,Primitive"):
        self.level, self.entity = level, entity
        cmd = f"CreateEntity -Scene {level.scene} -Id {entity} -Folder 0" + (f" -Parent {parent.entity}" if parent else "") + f" -Components {components}"
        level.ok(cmd)
        for axis, v in zip("XYZ", position):
            if v:
                self.set("Transform", f"Transform/Position/{axis}", v)

    def set(self, component, path, value):
        self.level.ok(f"SetProperty -Scene {self.level.scene} -Id {self.entity} -Component {component} -Path {path} -After {value}")

    def world(self, expect=None, timeout=15.0):
        """The world pose once it is what `expect` (a function of the pose) says, or after the timeout."""
        deadline = time.time() + timeout
        while True:
            reply = self.level.cmd(f"GetWorldPose -Scene {self.level.scene} -Id {self.entity}")
            pose = {"Child": int(re.search(r"Child=(\d)", reply)[1])}
            for key in ("Position", "Rotation", "Scale"):
                pose[key] = tuple(float(v) for v in re.search(rf"{key}=([-\d.,e]+)", reply)[1].split(","))
            if expect is None or expect(pose) or time.time() > deadline:
                return pose
            time.sleep(0.25)


def near(a, b, eps=1e-3):
    return all(abs(x - y) < eps for x, y in zip(a, b))


@pytest.fixture
def lv(level):
    yield level
    for _ in range(200):                                    # the entities and every property set on them: the Level is left as it was found (nothing was saved)
        if level.cmd("Undo") != "Undo: done":
            break


def test_a_root_is_where_its_transform_says(lv):
    p = node(lv, "7E7E0001", position=(3, 1, 2))
    w = p.world()
    assert w["Child"] == 0 and near(w["Position"], (3, 1, 2)) and near(w["Scale"], (1, 1, 1))


def test_a_child_is_where_its_parent_plus_its_own_offset_say(lv):
    p = node(lv, "7E7E0001", position=(3, 1, 0))
    c = node(lv, "7E7E0002", parent=p, position=(0, 2, 0))
    w = c.world(lambda w: w["Child"] == 1 and near(w["Position"], (3, 3, 0)))
    assert w["Child"] == 1 and near(w["Position"], (3, 3, 0)), w
    p.set("Transform", "Transform/Position/X", 10)                       # the parent moves: the child goes with it
    assert near(c.world(lambda w: near(w["Position"], (10, 3, 0)))["Position"], (10, 3, 0))


def test_a_child_turns_with_its_parent_and_its_offset_turns_with_it(lv):
    p = node(lv, "7E7E0001", position=(3, 0, 0))
    c = node(lv, "7E7E0002", parent=p, position=(1, 0, 0))
    p.set("Transform", "Transform/RotationDegrees/Y", 90)
    w = c.world(lambda w: abs(w["Position"][0] - 3) < 0.01)
    assert abs(w["Position"][0] - 3) < 1e-2 and abs(abs(w["Position"][2]) - 1) < 1e-2, f"the offset (1,0,0) is turned a quarter turn around the parent: {w}"
    c.set("Parent", "Parent/FollowRotation", "false")
    w = c.world(lambda w: abs(w["Position"][0] - 4) < 0.01)
    assert near(w["Position"], (4, 0, 0), 1e-2), f"without FollowRotation the offset stays along x: {w}"


def test_the_scale_of_the_parent_is_not_taken_unless_asked(lv):
    p = node(lv, "7E7E0001", position=(3, 0, 0))
    p.set("Transform", "Transform/Scale/X", 2); p.set("Transform", "Transform/Scale/Y", 2); p.set("Transform", "Transform/Scale/Z", 2)
    c = node(lv, "7E7E0002", parent=p, position=(1, 0, 0))
    w = c.world(lambda w: w["Child"] == 1 and near(w["Position"], (4, 0, 0)))
    assert near(w["Position"], (4, 0, 0)) and near(w["Scale"], (1, 1, 1)), f"the scale of a parent is its size, not its child's: {w}"
    c.set("Parent", "Parent/FollowScale", "true")
    w = c.world(lambda w: near(w["Position"], (5, 0, 0)))
    assert near(w["Position"], (5, 0, 0)) and near(w["Scale"], (2, 2, 2)), w


def test_an_axis_that_does_not_follow_is_a_world_value(lv):
    p = node(lv, "7E7E0001", position=(3, 5, 4))
    s = node(lv, "7E7E0002", parent=p, position=(0, 0.5, 0))
    s.set("Parent", "Parent/FollowY", "false")
    w = s.world(lambda w: w["Child"] == 1 and near(w["Position"], (3, 0.5, 4)))
    assert near(w["Position"], (3, 0.5, 4)), f"x and z follow, y is its own, in the world (a shadow stays on the ground): {w}"
    p.set("Transform", "Transform/Position/Y", 9)                        # the parent jumps
    w = s.world(lambda w: near(w["Position"], (3, 0.5, 4)))
    assert near(w["Position"], (3, 0.5, 4)), w


def test_a_hierarchy_goes_down_more_than_one_level(lv):
    a = node(lv, "7E7E0001", position=(1, 0, 0))
    b = node(lv, "7E7E0002", parent=a, position=(0, 1, 0))
    c = node(lv, "7E7E0003", parent=b, position=(0, 0, 1))
    w = c.world(lambda w: w["Child"] == 1 and near(w["Position"], (1, 1, 1)))
    assert near(w["Position"], (1, 1, 1)), w
    a.set("Transform", "Transform/Position/X", 4)
    assert near(c.world(lambda w: near(w["Position"], (4, 1, 1)))["Position"], (4, 1, 1))


def test_a_child_is_picked_where_it_is_drawn_not_where_its_transform_says(lv):
    p = node(lv, "7E7E0001", position=(20, 0, 0))
    c = node(lv, "7E7E0002", parent=p, position=(0, 0, 0))
    c.world(lambda w: w["Child"] == 1 and near(w["Position"], (20, 0, 0)))
    assert "7E7E0002" in lv.cmd("PickRay -Origin 20,0,5 -Dir 0,0,-1") or "7E7E0001" in lv.cmd("PickRay -Origin 20,0,5 -Dir 0,0,-1"), "something is there: the parent and the child share the spot"
    far = lv.cmd("PickRay -Origin 0,0,5 -Dir 0,0,-1")
    assert "7E7E0002" not in far, f"the child's Transform (0,0,0) is relative: it is not at the origin: {far}"


def test_a_child_survives_a_save_and_a_reload(lv):
    import pathlib
    import shutil
    import tempfile
    from script_project import PROJECT
    scene_dir = pathlib.Path(PROJECT) / "Descriptors" / "Scene" / lv.scene[-2:] / lv.scene[-4:-2] / f"{lv.scene}.desc"
    backup = pathlib.Path(tempfile.mkdtemp(prefix="xlion_hier_scene_")) / "scene"
    shutil.copytree(scene_dir, backup)
    try:
        p = node(lv, "7E7E0A01", position=(6, 0, 0))
        c = node(lv, "7E7E0A02", parent=p, position=(0, 2, 0))
        c.set("Parent", "Parent/FollowY", "false")
        c.set("Parent", "Parent/FollowRotation", "false")
        reply = lv.ed.cmd("Save", allow_disk=True)
        assert "rror" not in reply, reply
        lv.ed.cmd("Close -Save 0")
        lv.ed.cmd(f"OpenLevel -Level {lv.guid} -Save 0")
        lv.ed.wait_for("GetPlayState", r"Building=false", timeout=240)
        w = c.world(lambda w: w["Child"] == 1 and near(w["Position"], (6, 2, 0)))
        assert w["Child"] == 1 and near(w["Position"], (6, 2, 0)), w
        assert lv.cmd(f"GetProperty -Scene {lv.scene} -Id {c.entity} -Component Parent -Path Parent/FollowY") == "false"
        assert lv.cmd(f"GetProperty -Scene {lv.scene} -Id {c.entity} -Component Parent -Path Parent/FollowRotation") == "false"
        assert lv.cmd(f"GetProperty -Scene {lv.scene} -Id {c.entity} -Component Parent -Path Parent/FollowX") == "true"
    finally:
        lv.ed.cmd("Close -Save 0")
        shutil.rmtree(scene_dir, ignore_errors=True)
        shutil.copytree(backup, scene_dir)
        shutil.rmtree(backup.parent, ignore_errors=True)
