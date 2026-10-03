"""What the physics tells the game it saw (xlioncore_physics.h: sensor_begin_event, sensor_end_event).

The Box3D body of an entity carries the entity's handle in its user data, so the two entities of a touch are known at once. The events are xECS global events of the world, sent right after the
fixed step that produced them. The core has two demo listeners (global event systems: xlioncore_demo_systems.h) that say what they were told in the log ("[System] Sensor begin sensor=<entity>
visitor=<entity>"), which is what these tests read: the whole way from Box3D to a system of the game.
"""
import re
import shutil
import tempfile
import time
from pathlib import Path

from script_project import PROJECT

MY_TEST_LEVEL_FOLDER = PROJECT / "Descriptors" / "Level" / "93" / "32" / "6162BB6775AC3293.desc"
PHYSICS_SCENE_FOLDER = PROJECT / "Descriptors" / "Scene" / "19" / "07" / "A1B2C3D4E5F60719.desc"
FLOAT, BOOL = "8CC78B69", "D739B4EF"                      # the type guids of the properties


class scene_backup:
    """Play saves the open level: the level and its scene are put back as they were."""
    def __init__(self):
        self.root = Path(tempfile.mkdtemp(prefix="xlion_physics_events_"))

    def __enter__(self):
        for n, folder in (("level", MY_TEST_LEVEL_FOLDER), ("scene", PHYSICS_SCENE_FOLDER)):
            shutil.copytree(folder, self.root / n)
        return self

    def __exit__(self, *_):
        for n, folder in (("level", MY_TEST_LEVEL_FOLDER), ("scene", PHYSICS_SCENE_FOLDER)):
            shutil.rmtree(folder, ignore_errors=True)
            shutil.copytree(self.root / n, folder)
        shutil.rmtree(self.root, ignore_errors=True)


def physics_lines(editor, kind):
    return [l for l in editor.log_text().splitlines() if l.startswith(f"[System] Sensor {kind} ")]


def make_ball_over_a_sensor(level):
    """A sensor box (a static body) and a ball dropped on it from 4 units up: the ball falls through the sensor (it has no collision response) and on."""
    editor, types = level.ed, level.ed.cmd(f"{level.name}\\ListComponentTypes")
    guid = lambda n: re.search(rf"^([0-9A-F]{{16}})\s+\S+\s+{n}\b", types, re.M)[1]
    sensor, ball = "7E570001", "7E570002"
    for entity, parts in ((sensor, ["Transform", "Physics", "PhysicsBodyProperties", "PhysicsColliderBox", "static"]), (ball, ["Transform", "Physics", "PhysicsBodyProperties", "PhysicsColliderSphere", "PhysicsDynamics"])):
        level.ok(f"CreateEntity -Scene {level.scene} -Id {entity} -Folder 0")
        for part in parts:
            level.ok(f"AddComponent -Scene {level.scene} -Id {entity} -Component {guid(part)}")
    # far from everything else in the scene (its own entities fall through the origin too)
    for entity, y in ((sensor, 0), (ball, 4)):
        for axis, value in (("X", 500), ("Y", y), ("Z", 500)):
            if value:
                level.ok(f"SetProperty -Scene {level.scene} -Id {entity} -Component {guid('Transform')} -Path Transform/Position/{axis} -TypeGuid {FLOAT} -Before 0 -After {value}")
    level.ok(f"SetProperty -Scene {level.scene} -Id {sensor} -Component {guid('PhysicsColliderBox')} -Path PhysicsColliderBox/Boxes[G:0]/IsSensor -TypeGuid {BOOL} -Before false -After true")


def test_a_ball_falling_through_a_sensor_is_reported_coming_in_and_going_out(level):
    editor = level.ed
    with scene_backup():
        begins, ends = len(physics_lines(editor, "begin")), len(physics_lines(editor, "end"))
        make_ball_over_a_sensor(level)
        assert "rror" not in level.cmd("Save", allow_disk=True), "the scene is saved (the harness plays only a clean document)"
        assert editor.cmd("Play", allow_disk=True).startswith("Play requested")
        editor.wait_play_state("Playing", timeout=120)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and len(physics_lines(editor, "end")) == ends:
            time.sleep(0.2)
        editor.cmd("Stop -Keep false")
        editor.wait_play_state("Stopped")
        editor.cmd("Close -Save 0")

    begin, end = physics_lines(editor, "begin")[begins:], physics_lines(editor, "end")[ends:]
    assert len(begin) == 1 and len(end) == 1, (begin, end)
    sensor, visitor = re.search(r"sensor=(\w+) visitor=(\w+)", begin[0]).groups()
    assert sensor != visitor, "two different entities: the sensor and the ball"
    assert re.search(rf"sensor={sensor} visitor={visitor}", end[0]), "the same pair that came in goes out"
    log = editor.log_text().splitlines()
    assert log.index(begin[0]) < log.index(end[0]) if begin[0] != end[0] else False, "in is before out"


def test_a_sensor_with_nothing_in_it_says_nothing(level):
    editor = level.ed
    with scene_backup():
        before = len(physics_lines(editor, "begin")) + len(physics_lines(editor, "end"))
        assert editor.cmd("Play", allow_disk=True).startswith("Play requested")
        editor.wait_play_state("Playing", timeout=120)
        time.sleep(2)
        editor.cmd("Stop -Keep false")
        editor.wait_play_state("Stopped")
        editor.cmd("Close -Save 0")
    assert len(physics_lines(editor, "begin")) + len(physics_lines(editor, "end")) == before, "a Level with no sensor reports no touch"
