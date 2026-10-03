"""What the physics tells the game about solid contacts (xlioncore_physics.h: contact_begin_event, contact_end_event, contact_hit_event).

A shape reports its touches and hits only when its collider has ContactEvents on (off by default). The core's demo listeners say what they were told in the log ("[System] Contact begin a=<entity>
b=<entity>", "[System] Contact hit a=.. b=.. speed=<m/s> point=x,y,z normal=x,y,z"), which is what these tests read: the whole way from Box3D to a system of the game.
"""
import re
import time

from test_physics_events import FLOAT, BOOL, scene_backup


def contact_lines(editor, kind):
    return [l for l in editor.log_text().splitlines() if l.startswith(f"[System] Contact {kind} ")]


def make(level, entity, parts, position, size=None, events=False):
    editor, types = level.ed, level.ed.cmd(f"{level.name}\\ListComponentTypes")
    guid = lambda n: re.search(rf"^([0-9A-F]{{16}})\s+\S+\s+{n}\b", types, re.M)[1]
    level.ok(f"CreateEntity -Scene {level.scene} -Id {entity} -Folder 0")
    for part in parts:
        level.ok(f"AddComponent -Scene {level.scene} -Id {entity} -Component {guid(part)}")
    for axis, value in zip("XYZ", position):
        if value:
            level.ok(f"SetProperty -Scene {level.scene} -Id {entity} -Component {guid('Transform')} -Path Transform/Position/{axis} -TypeGuid {FLOAT} -Before 0 -After {value}")
    collider, path = ("PhysicsColliderSphere", "Spheres") if "PhysicsColliderSphere" in parts else ("PhysicsColliderBox", "Boxes")
    if size:
        for axis, value in zip("XYZ", size):
            level.ok(f"SetProperty -Scene {level.scene} -Id {entity} -Component {guid(collider)} -Path {collider}/{path}[G:0]/Size/{axis} -TypeGuid {FLOAT} -Before 1 -After {value}")
    if events:
        level.ok(f"SetProperty -Scene {level.scene} -Id {entity} -Component {guid(collider)} -Path {collider}/{path}[G:0]/ContactEvents -TypeGuid {BOOL} -Before false -After true")


BALL = ["Transform", "Physics", "PhysicsBodyProperties", "PhysicsColliderSphere", "PhysicsDynamics"]
FLOOR = ["Transform", "Physics", "PhysicsBodyProperties", "PhysicsColliderBox", "static"]


def play_for(level, seconds=None, until=None):
    editor = level.ed
    assert "rror" not in level.cmd("Save", allow_disk=True), "the scene is saved (the harness plays only a clean document)"
    assert editor.cmd("Play", allow_disk=True).startswith("Play requested")
    editor.wait_play_state("Playing", timeout=120)
    deadline = time.monotonic() + (seconds or 20)
    while time.monotonic() < deadline and not (until and until()):
        time.sleep(0.2)
    editor.cmd("Stop -Keep false")
    editor.wait_play_state("Stopped")
    editor.cmd("Close -Save 0")


def test_a_ball_that_falls_on_a_floor_is_reported_touching_and_hitting_with_its_speed(level):
    editor = level.ed
    with scene_backup():
        begins, hits = len(contact_lines(editor, "begin")), len(contact_lines(editor, "hit"))
        make(level, "7E570011", FLOOR, (500, 0, 500))
        make(level, "7E570012", BALL, (500, 4, 500), events=True)       # only the ball asks: a touch is reported when either shape of the pair asks
        play_for(level, until=lambda: len(contact_lines(editor, "hit")) > hits)
    begin, hit = contact_lines(editor, "begin")[begins:], contact_lines(editor, "hit")[hits:]
    assert len(begin) == 1, begin
    assert len(hit) >= 1, "it came down fast: a hit"
    a, b = re.search(r"a=(\w+) b=(\w+)", begin[0]).groups()
    assert a != b, "two different entities: the floor and the ball"
    speed = float(re.search(r"speed=([\d.]+)", hit[0])[1])
    assert 5.0 < speed < 10.0, f"3.5 units of free fall are about 8 meters per second, said {speed}"
    assert re.search(rf"a={a} b={b}", hit[0]), "the hit is of the pair that touched"
    point = [float(v) for v in re.search(r"point=([-\d.]+),([-\d.]+),([-\d.]+)", hit[0]).groups()]
    normal = [float(v) for v in re.search(r"normal=([-\d.]+),([-\d.]+),([-\d.]+)", hit[0]).groups()]
    assert abs(point[0] - 500) < 0.6 and abs(point[2] - 500) < 0.6 and 0.2 < point[1] < 0.8, f"on the floor, under the ball, at the top of the floor (y 0.5): {point}"
    assert abs(normal[1]) > 0.95 and abs(normal[0]) < 0.3 and abs(normal[2]) < 0.3, f"straight up or down, between the floor and the ball: {normal}"


def test_shapes_that_did_not_ask_for_contact_events_say_nothing(level):
    editor = level.ed
    with scene_backup():
        before = [len(contact_lines(editor, k)) for k in ("begin", "end", "hit")]
        make(level, "7E570021", FLOOR, (500, 0, 500))
        make(level, "7E570022", BALL, (500, 4, 500))
        play_for(level, seconds=6)
    assert [len(contact_lines(editor, k)) for k in ("begin", "end", "hit")] == before, "ContactEvents is off by default"


def test_a_ball_that_rolls_off_its_support_is_reported_leaving_it(level):
    editor = level.ed
    with scene_backup():
        ends = len(contact_lines(editor, "end"))
        make(level, "7E570031", FLOOR, (500, 0, 500), size=(0.2, 1, 0.2))          # a pillar the ball lands on the edge of, and slides off
        make(level, "7E570032", BALL, (500.2, 3, 500), events=True)
        play_for(level, until=lambda: len(contact_lines(editor, "end")) > ends)
    end = contact_lines(editor, "end")[ends:]
    assert len(end) >= 1, "it touched the pillar and left it"
    begin = contact_lines(editor, "begin")
    assert re.search(r"a=(\w+) b=(\w+)", end[0]).groups() in [re.search(r"a=(\w+) b=(\w+)", l).groups() for l in begin], "the pair that leaves is a pair that touched"
