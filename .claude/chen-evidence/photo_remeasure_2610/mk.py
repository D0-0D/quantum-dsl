"""本机出网格 + Palace config。用法: mk.py <case> <d_um> <outdir> [max min]
case: si = 3×3 的 H01 块 (SI §D 孤立 QCQ, 6 terminal); siR = 同块 + Q11 读出爪 R11 (十字版图); cross = 十字整片 (19 导体)。"""
import sys, json, time, dataclasses
from pathlib import Path
from quantum_dsl import load_meta, compile_layout, build_mesh
from quantum_dsl.palace import palace_config
case, d, out = sys.argv[1], float(sys.argv[2]), Path(sys.argv[3])
mx, mn = (float(sys.argv[4]), float(sys.argv[5])) if len(sys.argv) > 5 else (100.0, 4.0)
SI = ["Q01_a", "Q01_b", "H01", "H01_pent", "Q11_a", "Q11_b"]
meta = {"si": "examples/chen_2025_3x3.meta.yaml"}.get(case, "examples/chen_2025_cross.meta.yaml")
comps = {"si": SI, "siR": SI + ["R11"], "cross": None}[case]
m = load_meta(meta)
m = dataclasses.replace(m, airbox={**m.airbox, "top_um": d}, mesh={**m.mesh, "max_size_um": mx, "min_size_um": mn})
lay = compile_layout(m)
out.mkdir(parents=True, exist_ok=True)
t = time.time()
mesh = build_mesh(lay.for_block(comps) if comps else lay, m, out / f"{case}.msh")
palace_config(mesh, m, out / f"{case}.json")
info = {"case": case, "d_um": d, "mesh": [mx, mn], "meta": meta, "labels": list(mesh.labels),
        "tets": mesh.num_volume_cells, "mesh_s": round(time.time() - t)}
(out / "info.json").write_text(json.dumps(info))
print(json.dumps(info))
