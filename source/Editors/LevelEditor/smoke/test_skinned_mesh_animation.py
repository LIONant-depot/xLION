"""The Skinned Mesh and the Animation (xlionrender_scene_components.h; the pose in xlionrender_scene_renderer.h AddSkinnedMesh, the clock in xlionrender_system.h
animation_system): Lily - a GeomSkin with her own skeleton and animations - stands in the Police level as it is saved. She is drawn with her geometry's 9 material slots;
the Animation system is placed before Render and moves her clip's time while the game runs (outside Play the pose stays where Time says)."""
import re
import time

POLICE_LEVEL = "EF31687D49834DD9"
LEVEL        = "Police Level"
SCENE        = "EF19AB610AD85421"
LILY         = "11F1E001"
LILY_GEOM    = "28B760D85FD80001"


def _time(editor) -> float:
    return float(re.search(r"Animation/Time = (\S+)", editor.describe(LEVEL, SCENE, LILY))[1])


def test_lily_is_drawn_and_her_animation_plays(editor):
    assert editor.cmd(f"OpenLevel -Level {POLICE_LEVEL} -Save 0", timeout=300).startswith("Opened Level")
    text = editor.describe(LEVEL, SCENE, LILY)
    assert f"SkinnedMesh/Geom = {LILY_GEOM}" in text and "Animation/Playing = true" in text, text[:800]
    editor.wait_for(rf"{LEVEL}\DescribeEntity -Scene {SCENE} -Id {LILY}", r"SkinnedMesh/Slots\[\] = 9\b", timeout=120)     # (her geometry loaded: its slots)

    systems = editor.cmd(rf"{LEVEL}\ListSystems")
    order = {m[1]: int(m[2]) for m in re.finditer(r"^(Animation|Render)  \[update #(\d+)\]", systems, re.M)}
    assert "Animation  [update" in systems and "NOT PLACED" not in systems.split("Animation  [update", 1)[1].split("\n", 1)[0], systems
    assert order["Animation"] < order["Render"], "the pose is drawn after the clock moved"
    editor.wait_for(rf"{LEVEL}\DescribeScene", r"Waiting=0\b", timeout=120)

    before = _time(editor)
    time.sleep(1.0)
    assert _time(editor) == before, "outside Play the time stays"
    try:
        editor.cmd("Play", timeout=300)
        editor.wait_play_state("Playing", timeout=300)
        time.sleep(2.0)
        assert _time(editor) > before + 0.5, "while the game runs the clip's time moves"
    finally:
        if editor.play_state() != "Stopped":
            editor.cmd("Stop -Keep false", timeout=120)
            editor.wait_play_state("Stopped", timeout=120)
