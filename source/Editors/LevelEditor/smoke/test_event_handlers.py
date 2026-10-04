"""The event handlers: systems that run when something happens (the physics tells that a shape touched a sensor, ...), not every frame. ListEventHandlers lists the events of the world with what
each one tells and when, and the systems that handle each one - what the System Registry shows in its own section, apart from the update systems (which are in an order).
"""
import re


def events(level) -> dict:
    """{event name: (the text under it, [handler names])}"""
    out, current = {}, None
    for line in level.cmd("ListEventHandlers").splitlines():
        if m := re.match(r"(\S.*?)  \[(event|system events), \d+ handlers?\]", line):
            current = m[1]
            out[current] = ["", []]
        elif current and (m := re.match(r"    handler: (.*)", line)):
            out[current][1].append(m[1])
        elif current and line.startswith("    ") and not line.startswith("        "):
            out[current][0] += line.strip()
    return out


PHYSICS_EVENTS = ["Physics Sensor Begin", "Physics Sensor End", "Physics Contact Begin", "Physics Contact End", "Physics Contact Hit"]


def test_the_events_of_the_world_are_listed_with_what_they_tell(level):
    e = events(level)
    for name in PHYSICS_EVENTS:
        assert name in e, (name, list(e))
    assert "sensor_touch" in e["Physics Sensor Begin"][0] and "once per step" in e["Physics Sensor Begin"][0], e["Physics Sensor Begin"][0]
    assert "contact_hit" in e["Physics Contact Hit"][0] and "approach speed" in e["Physics Contact Hit"][0]


def test_the_handlers_are_not_in_the_list_of_update_systems(level):
    systems = level.cmd("ListSystems")
    update = [l for l in systems.splitlines() if "[update #" in l]
    handlers = {h for _, hs in events(level).values() for h in hs}
    assert handlers, "the engine's own loggers handle the physics events"
    assert not any(h in l for h in handlers for l in update), "a handler runs when its event is raised: it is not one of the update systems, which run in order every frame"


def test_the_game_of_a_level_shows_its_handlers(game_level):
    e = events(game_level)
    assert "Soccer Goal" in e["Physics Sensor Begin"][1], e["Physics Sensor Begin"]


def test_list_systems_says_which_systems_are_event_handlers_and_which_are_notifiers(level):
    text = level.cmd("ListSystems")
    assert re.search(r"Physics Destroy Notify  \[notifier\]", text), "a notifier runs when an entity is destroyed (or created, moved, changed)"
    assert re.search(r"Sensor Begin Logger  \[event handler\]", text), "an event handler runs when its event is raised: ListEventHandlers says which"
