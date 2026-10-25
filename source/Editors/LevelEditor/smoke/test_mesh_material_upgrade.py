"""Old files' MeshMaterial: opened, it moves into the Mesh's own slots (Override Materials) and the MeshMaterial goes.

SliceLevel's scene (5E1CE0A11000000D) was saved with MeshMaterial: entity 5E1C0A02 swaps slot 0 to a material instance and overrides the
entity Tint with green. Its material marks the parameter "Tint" as the entity TINT field, so the green becomes an override of "Tint".
Nothing is saved: the Level is closed without saving, the files stay old (the next test run converts them again)."""

SLICE_LEVEL = "5E1CE0A11000000B"
SLICE_SCENE = "5E1CE0A11000000D"
TINTED      = "5E1C0A02"
MI_RED      = "5E1CE0A110000003"


def test_an_old_mesh_material_moves_into_the_mesh(editor):
    editor.cmd("Close -Save 0")
    try:
        assert editor.cmd(f"OpenLevel -Level {SLICE_LEVEL} -Save 0").startswith("Opened Level")
        name = dict(editor.levels())[SLICE_LEVEL]
        got = editor.wait_for(f"{name}\\DescribeEntity -Scene {SLICE_SCENE} -Id {TINTED}", r"Mesh/Override Materials = true", timeout=120)
        assert "MeshMaterial" not in got, "the MeshMaterial was removed once converted"
        assert f"Mesh/Slots[G:0]/Material = {MI_RED}" in got, "the MeshMaterial's slot swap is the Mesh slot's material"
        assert "Mesh/Slots[G:0]/Overrides[G:0]/Name = Tint" in got, "the old Tint overrides the parameter the material marks as the entity Tint"
        assert "Mesh/Slots[G:0]/Overrides[G:0]/Y = 1.000000" in got and "Mesh/Slots[G:0]/Overrides[G:0]/X = 0.000000" in got, "with the old value (green)"
        assert "Overrides[]" in got and "Mesh/Slots[G:0]/Overrides[] = 1" in got, "only the overridden value is kept"
    finally:
        editor.cmd("Close -Save 0")
