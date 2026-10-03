"""The saved order of the systems (Project.config/SystemOrder.config.txt) is shared by the Games of the project: a Save writes the systems that are registered now and keeps the entries of the ones that are not
(a Game that is not the one loaded now), each right after the entry that came before it.
"""
import re

from script_project import PROJECT

ORDER = PROJECT / "Project.config" / "SystemOrder.config.txt"
GHOST = "DEAD0000DEAD0001"
PHYSICS = "11ED5FB0C5668F79"


def _entries(text: str):
    """The header lines, and the lines of each entry (by index)."""
    lines = text.splitlines()
    first = next(i for i, l in enumerate(lines) if "UpdateOrder[]" in l)
    groups: dict[int, list[str]] = {}
    for l in lines[first + 1:]:
        if m := re.search(r"\[G:(\d+)\]", l):
            groups.setdefault(int(m[1]), []).append(l)
    return lines[:first], lines[first], [groups[k] for k in sorted(groups)]


def _guids(text: str) -> list[str]:
    return re.findall(r'UpdateOrder\[G:\d+\]/Guid"\s+;u64\s+#([0-9A-Fa-f]+)', text)


def _with_a_system_nobody_registers(text: str) -> str:
    """The file with one more entry, of a guid no loaded Game registers, right after Physics."""
    head, count, groups = _entries(text)
    at = next(i for i, g in enumerate(groups) if PHYSICS in g[0].upper()) + 1

    def ghosted(line: str) -> str:
        if "/Guid" in line:
            return re.sub(r"#[0-9A-Fa-f]+", f"#{GHOST}", line, count=1)
        if "/Name" in line:
            return re.sub(r'(;string\s+)"[^"]*"', r'\1"Ghost System"', line)
        return line

    groups.insert(at, [ghosted(l) for l in groups[at - 1]])
    body = [re.sub(r"\[G:\d+\]", f"[G:{i}]", l) for i, g in enumerate(groups) for l in g]
    count = re.sub(r"s64\s+\d+", f"s64    {len(groups)}", count)
    head = [re.sub(r"\[ xProperties : \d+ \]", f"[ xProperties : {1 + len(body)} ]", l) for l in head]
    return "\r\n".join(head + [count] + body) + "\r\n"


def test_saving_the_system_order_keeps_the_entries_of_systems_that_are_not_loaded(editor, level):
    original = ORDER.read_bytes()
    try:
        ORDER.write_bytes(_with_a_system_nobody_registers(original.decode()).encode())
        before = _guids(ORDER.read_text())
        assert GHOST in before and before[before.index(GHOST) - 1].upper() == PHYSICS, "the test file has it after Physics"

        assert level.cmd("SaveSystemOrder", allow_disk=True) == "SaveSystemOrder: saved"
        after = [g.upper() for g in _guids(ORDER.read_text())]
        assert GHOST in after, "the entry of a system that is not registered is still in the file"
        assert after[after.index(GHOST) - 1] == PHYSICS, "and still right after the entry that came before it"
        assert len(after) == len(before), "nothing else was added or lost"
    finally:
        ORDER.write_bytes(original)
