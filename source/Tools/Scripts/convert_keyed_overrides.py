"""Material Instance descriptors: overrides addressed by place ("Overrides[G:0]/...") rewritten by parameter id ("Overrides[G:<id>]/...").

The same change UpgradeProject makes (xmaterial_instance::UpgradeKeyedOverrides), as a text edit: only the rows' paths change, every value stays,
and each file keeps its modification time - what the file means did not change, so nothing has to be compiled again.

    python convert_keyed_overrides.py <project>/Descriptors [--dry-run]

A file is converted when it has an "Overrides[G:0]/" row (0 is never a parameter id). Every "Overrides[G:i]/..." row is renamed by the id its own
"Overrides[G:i]/ID" row holds (a u64, "#hex"). A file whose entries do not all have an ID row is left as it is and listed.
"""
import os
import re
import sys
from pathlib import Path

ROW = re.compile(rb'"material_instance_descriptor/Overrides\[G:(\d+)\]/')
ID  = re.compile(rb'"material_instance_descriptor/Overrides\[G:(\d+)\]/ID"\s+;u64\s+#([0-9A-Fa-f]+)')


def convert(text: bytes):
    """The converted text, or None when there is nothing to convert (or it cannot be)."""
    if b'/Overrides[G:0]/' not in text:
        return None
    ids = {int(i): int(h, 16) for i, h in ID.findall(text)}
    used = {int(i) for i in ROW.findall(text)}
    if not used or used - ids.keys() or 0 in ids.values():
        return None
    return ROW.sub(lambda m: b'"material_instance_descriptor/Overrides[G:%d]/' % ids[int(m[1])], text)


def main():
    root = Path(sys.argv[1]) / "MaterialInstance"
    dry = "--dry-run" in sys.argv
    done, left = 0, []
    for f in sorted(root.rglob("Descriptor.txt")):
        text = f.read_bytes()
        if b'/Overrides[G:0]/' not in text:
            continue
        new = convert(text)
        if new is None:
            left.append(f)
            continue
        if not dry:
            st = f.stat()
            f.write_bytes(new)
            os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns))      # the same meaning: not changed for the compiler
        done += 1
    print(f"{'would convert' if dry else 'converted'} {done} file(s); {len(left)} left as they are")
    for f in left:
        print(f"  {f}")


if __name__ == "__main__":
    main()
