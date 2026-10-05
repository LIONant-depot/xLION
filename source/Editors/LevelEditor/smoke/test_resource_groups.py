"""Every resource plugin says which group its resource type belongs to (and what it is, in a sentence), like every component has a category: the "+" of the resource view lists the types by group, with
a search and a hint on each one, the look of the Add Component popup. A plugin without a group is still loaded (under "Other") but it is an error, and this is where it is caught.
"""
import re

from harness import REPO

PLUGINS = REPO / "plugins"
CONFIGS = sorted(PLUGINS.glob("*/Plugin.config/resource_pipeline.config.txt"))


def field(text: str, name: str) -> str:
    m = re.search(rf'"PipelinePlugin/{name}"\s*;string\s*"([^"]*)"', text)
    return m[1] if m else ""


def test_there_are_plugins_to_check():
    assert len(CONFIGS) >= 15, [c.parent.parent.name for c in CONFIGS]


def test_every_resource_plugin_has_a_group_and_a_description():
    missing = []
    for cfg in CONFIGS:
        text = cfg.read_text(encoding="utf-8-sig")
        name = field(text, "TypeName")
        if not field(text, "Group"):
            missing.append(f"{name}: no Group")
        if not field(text, "Description"):
            missing.append(f"{name}: no Description")
        if field(text, "Group") == "Other":
            missing.append(f"{name}: is in Other (give it a real group)")
    assert not missing, "\n".join(missing)


def test_the_property_count_of_every_plugin_config_matches_its_rows():
    """A config whose [ xProperties : N ] says another number than the rows it has is read wrong (or not at all)."""
    wrong = []
    for cfg in CONFIGS:
        text = cfg.read_text(encoding="utf-8-sig")
        declared = int(re.search(r"\[ xProperties : (\d+) \]", text)[1])
        rows = len(re.findall(r'^\s*"PipelinePlugin/', text, re.M))
        if declared != rows:
            wrong.append(f"{cfg.parent.parent.name}: says {declared}, has {rows}")
    assert not wrong, "\n".join(wrong)
