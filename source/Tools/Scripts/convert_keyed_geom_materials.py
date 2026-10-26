"""GeomStatic descriptors: the materials addressed by place ("MaterialDetailsList[G:0]/...", their instances in a list beside them, "MaterialInstance[G:0]")
rewritten by the material's name ("MaterialDetailsList[G:<key>]/...", each with its "Instance"), key = FNV-1a 64 of the name's bytes
(xgeom_static::material_details::NameKey).

What xgeom_static::descriptor::Serialize writes for the same materials and instances, as a text edit: every value stays, and each file keeps its
modification time - what the file means did not change, so nothing has to be compiled again (the pipeline compiles a resource whose
descriptor is newer than it).

    python convert_keyed_geom_materials.py <project>/Descriptors [--dry-run]

A file is converted when it has a "MaterialInstance[G:" row. One whose materials and instances do not pair (or a name with an escape) is
left as it is and listed.
"""
import os
import re
import sys
from pathlib import Path

NAME = re.compile(rb'^(\s*)"GeomStatic/MaterialDetailsList\[G:(\d+)\]/Name"\s+;string\s+"([^"\\]*)"', re.M)
REF  = re.compile(rb'^\s*"GeomStatic/MaterialInstance\[G:(\d+)\]"\s+;full_guid\s+(#\S+\s+#\S+)', re.M)
ROW  = re.compile(rb'"GeomStatic/MaterialDetailsList\[G:(\d+)\]/')
HEAD = re.compile(rb'\[ xProperties : (\d+) \]')


def name_key(name: bytes) -> int:
    h = 14695981039346656037
    for c in name:
        h ^= c
        h = (h * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return h


def convert(text: bytes):
    """The converted text, or None when there is nothing to convert (or it cannot be)."""
    if b'"GeomStatic/MaterialInstance[G:' not in text and b'"GeomStatic/MaterialInstance[]"' not in text:
        return None
    eol = b"\r\n" if b"\r\n" in text else b"\n"
    names = {int(i): (ind, n) for ind, i, n in NAME.findall(text)}
    refs  = {int(i): v for i, v in REF.findall(text)}
    if set(refs) - set(names) or len({name_key(n) for _, n in names.values()}) != len(names):
        return None
    keys = {i: name_key(n) for i, (_, n) in names.items()}
    out, removed, added, first_row = [], 0, 0, None
    lines = text.split(eol)
    for line in lines:
        if b'"GeomStatic/MaterialInstance[' in line:
            removed += 1
            continue
        m = ROW.search(line)
        if m:
            i = int(m[1])
            if i not in keys:
                return None
            if first_row is None:
                first_row = len(out)
            line = ROW.sub(lambda r: b'"GeomStatic/MaterialDetailsList[G:%d]/' % keys[int(r[1])], line)
            out.append(line)
            if b'/RefCount"' in line:                                   # the last of an element's rows: its Instance after it
                ind = names[i][0]
                out.append(ind + b'"GeomStatic/MaterialDetailsList[G:%d]/Instance"  ;full_guid  ' % keys[i] + refs.get(i, b"#0 #B673C5DA4A4A70AD"))
                added += 1
            continue
        out.append(line)
    if added != len(names):
        return None
    # the block's row count
    for j in range(first_row if first_row is not None else len(out), -1, -1):
        if j < len(out) and HEAD.search(out[j]):
            out[j] = HEAD.sub(lambda h: b'[ xProperties : %d ]' % (int(h[1]) - removed + added), out[j])
            break
    return eol.join(out)


def main():
    root = Path(sys.argv[1]) / "GeomStatic"
    dry = "--dry-run" in sys.argv
    done, left = 0, []
    for f in sorted(root.rglob("Descriptor.txt")):
        text = f.read_bytes()
        if b'"GeomStatic/MaterialInstance[' not in text:
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
