"""The reflection test's sphere grid (documentation/reflections_strategy.md, milestone B; Tomas 2026-10-28): two rows of six spheres -
dielectric (front) and metal (back) - roughness 0, 0.2 .. 1 across, written as an OBJ with an MTL whose PBR keys (Pr roughness, Pm
metallic) the geometry's material import reads (xraw3d's RoughnessFactor / MetallicFactor). Centred on the origin, on y = 0.
    python make_sphere_grid.py <folder>"""
import math, sys
from pathlib import Path

R, SPACING, ROW, RINGS, SEGS = 0.25, 0.7, 0.8, 32, 48
ROUGH = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
KINDS = [("dielectric", (0.8, 0.8, 0.8), 0.0), ("metal", (0.95, 0.93, 0.88), 1.0)]

out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
obj = ["mtllib sphere_grid.mtl"]
mtl = []
nv = 0
for row, (kind, color, metal) in enumerate(KINDS):
    for col, r in enumerate(ROUGH):
        name = f"{kind}_r{int(r * 100):03d}"
        mtl += [f"newmtl {name}", f"Kd {color[0]} {color[1]} {color[2]}", f"Pr {r}", f"Pm {metal}", "Ks 0 0 0", ""]
        cx, cy, cz = (col - (len(ROUGH) - 1) / 2) * SPACING, R, (row - 0.5) * ROW
        obj += [f"o sphere_{name}", f"usemtl {name}"]
        for j in range(RINGS + 1):
            th = math.pi * j / RINGS
            for i in range(SEGS + 1):
                ph = 2 * math.pi * i / SEGS
                n = (math.sin(th) * math.cos(ph), math.cos(th), math.sin(th) * math.sin(ph))
                obj.append(f"v {cx + R * n[0]:.6f} {cy + R * n[1]:.6f} {cz + R * n[2]:.6f}")
                obj.append(f"vn {n[0]:.6f} {n[1]:.6f} {n[2]:.6f}")
                obj.append(f"vt {i / SEGS:.6f} {1 - j / RINGS:.6f}")
        for j in range(RINGS):
            for i in range(SEGS):
                a = nv + j * (SEGS + 1) + i + 1
                b, c, d = a + 1, a + SEGS + 1, a + SEGS + 2
                obj.append(f"f {a}/{a}/{a} {c}/{c}/{c} {b}/{b}/{b}")
                obj.append(f"f {b}/{b}/{b} {c}/{c}/{c} {d}/{d}/{d}")
        nv += (RINGS + 1) * (SEGS + 1)
(out / "sphere_grid.obj").write_text("\n".join(obj) + "\n")
(out / "sphere_grid.mtl").write_text("\n".join(mtl) + "\n")
print("wrote", out / "sphere_grid.obj", nv, "vertices")
