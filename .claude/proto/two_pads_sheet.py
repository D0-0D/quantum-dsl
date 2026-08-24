# -*- coding: utf-8 -*-
"""变体 C — 零厚度金属片: 2D 焊盘面直接 fragment 进衬底/真空界面 (z=0),
Terminal 挂在内部边界面上。无 extrude、无布尔减、无腔壁归位。

回答的架构问题: Palace 0.16 是否接受内部 Dirichlet (Terminal) 边界?
若接受, C 与 golden (2 µm 厚板挖空) 差多少 (= 膜厚敏感性)?

用法: python two_pads_sheet.py [--mesh MAX MIN] [--order N]
"""
import json
import sys
from pathlib import Path

import gmsh

sys.path.insert(0, str(Path(__file__).parent))
from two_pads_pipeline import (AIR_BOT, AIR_TOP, EPS_R, FRAG_TOL_UM, GEO,
                               SIDE, SUB_TH, solve_and_check)


def build_sheet(out_dir: Path, mesh_max=40.0, mesh_min=4.0, order=2):
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("two_pads_sheet")
        gmsh.merge(str(GEO))            # µm, 不 dilate; Palace L0=1e-6
        gmsh.model.occ.synchronize()

        pads = {}
        for dim, ptag in gmsh.model.getPhysicalGroups(2):
            comp = gmsh.model.getPhysicalName(dim, ptag).split("::")[2]
            pads[comp] = list(gmsh.model.getEntitiesForPhysicalGroup(dim, ptag))
        # 作者的 Physical 组必须清掉: sheet 路径下焊盘面存活到最终网格, 若保留
        # 会与我们的组重复 → 同一面两条边界元, Palace ReadMesh 拒收
        gmsh.model.removePhysicalGroups()

        inf = float("inf")
        xmin, ymin, xmax, ymax = inf, inf, -inf, -inf
        for tags in pads.values():
            for t in tags:
                bb = gmsh.model.getBoundingBox(2, t)
                xmin, ymin = min(xmin, bb[0]), min(ymin, bb[1])
                xmax, ymax = max(xmax, bb[3]), max(ymax, bb[4])
        xmin -= SIDE; ymin -= SIDE; xmax += SIDE; ymax += SIDE

        sub = gmsh.model.occ.addBox(xmin, ymin, 0, xmax - xmin, ymax - ymin,
                                    -SUB_TH)
        tol = FRAG_TOL_UM
        vac = gmsh.model.occ.addBox(xmin - tol, ymin - tol, -AIR_BOT,
                                    (xmax - xmin) + 2 * tol,
                                    (ymax - ymin) + 2 * tol, AIR_TOP + AIR_BOT)

        # 一次 fragment: 体积互切 + 焊盘面 imprint 进 z=0 界面
        comp_order = sorted(pads)
        pad_tools = [(2, t) for c in comp_order for t in pads[c]]
        out, out_map = gmsh.model.occ.fragment(
            [(3, vac)], [(3, sub)] + pad_tools)
        gmsh.model.occ.synchronize()

        sub_vols = [t for d, t in out_map[1] if d == 3]
        vac_vols = sorted({t for d, t in out_map[0] if d == 3}
                          - set(sub_vols))
        assert len(sub_vols) == 1, sub_vols
        pad_faces, idx = {}, 2
        for c in comp_order:
            faces = []
            for _ in pads[c]:
                faces += [t for d, t in out_map[idx] if d == 2]
                idx += 1
            assert faces, f"pad {c} not imprinted"
            pad_faces[c] = faces

        boundary = gmsh.model.getBoundary(
            [(3, t) for t in vac_vols + sub_vols],
            combined=True, oriented=False, recursive=False)
        outer = [abs(t) for d, t in boundary if d == 2]
        # sanity: 内部面 (含焊盘) 不得出现在 combined 外边界里
        for c, faces in pad_faces.items():
            assert not set(faces) & set(outer), f"pad {c} leaked to outer"

        attrs = {
            "vacuum": gmsh.model.addPhysicalGroup(3, vac_vols, name="vacuum"),
            "substrate": gmsh.model.addPhysicalGroup(3, sub_vols,
                                                     name="substrate"),
            "vacuum_outer": gmsh.model.addPhysicalGroup(2, outer,
                                                        name="vacuum_outer"),
        }
        for c in comp_order:
            attrs[c] = gmsh.model.addPhysicalGroup(2, pad_faces[c], name=c)

        curves = sorted({abs(cv) for c in comp_order for f in pad_faces[c]
                         for d, cv in gmsh.model.getBoundary(
                             [(2, f)], combined=False, oriented=False)})
        df = gmsh.model.mesh.field.add("Distance")
        gmsh.model.mesh.field.setNumbers(df, "CurvesList", curves)
        gmsh.model.mesh.field.setNumber(df, "NumPointsPerCurve", 100)
        tf = gmsh.model.mesh.field.add("Threshold")
        gmsh.model.mesh.field.setNumber(tf, "InField", df)
        gmsh.model.mesh.field.setNumber(tf, "DistMin", 10)
        gmsh.model.mesh.field.setNumber(tf, "DistMax", 130)
        gmsh.model.mesh.field.setNumber(tf, "SizeMin", mesh_min)
        gmsh.model.mesh.field.setNumber(tf, "SizeMax", mesh_max)
        gmsh.model.mesh.field.setNumber(tf, "Sigmoid", 1)
        gmsh.model.mesh.field.setAsBackgroundMesh(tf)
        gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
        gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
        gmsh.option.setNumber("Mesh.MeshSizeMin", mesh_min)
        gmsh.option.setNumber("Mesh.MeshSizeMax", mesh_max)

        try:
            gmsh.model.mesh.generate(3)
            _, etags, _ = gmsh.model.mesh.getElements(3)
            empty = sum(len(t) for t in etags) == 0
        except Exception:
            empty = True
        if empty:
            gmsh.model.mesh.clear()
            gmsh.option.setNumber("Mesh.Algorithm3D", 10)
            gmsh.model.mesh.generate(3)
            _, etags, _ = gmsh.model.mesh.getElements(3)
            assert sum(len(t) for t in etags) > 0, "empty 3D mesh"

        out_dir.mkdir(parents=True, exist_ok=True)
        gmsh.option.setNumber("Mesh.MshFileVersion", 2.2)
        msh = out_dir / "chip.msh"
        gmsh.write(str(msh))
        n_nodes = len(gmsh.model.mesh.getNodes()[0])
    finally:
        gmsh.finalize()

    cfg = {
        "Problem": {"Type": "Electrostatic", "Verbose": 2, "Output": "postpro"},
        "Model": {"L0": 1e-6, "Mesh": msh.name},
        "Domains": {"Materials": [
            {"Attributes": [attrs["substrate"]], "Permittivity": EPS_R},
            {"Attributes": [attrs["vacuum"]], "Permittivity": 1.0},
        ]},
        "Boundaries": {
            "Ground": {"Attributes": [attrs["vacuum_outer"]]},
            "Terminal": [
                {"Index": 1, "Attributes": [attrs["A"]]},
                {"Index": 2, "Attributes": [attrs["B"]]},
            ],
        },
        "Solver": {"Order": order, "Device": "CPU",
                   "Electrostatic": {"Save": 0},
                   "Linear": {"Type": "BoomerAMG", "KSPType": "CG",
                              "Tol": 1.0e-8, "MaxIts": 200}},
    }
    cfg_path = out_dir / "chip.json"
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return cfg_path, n_nodes


if __name__ == "__main__":
    kw = {}
    if "--mesh" in sys.argv:
        i = sys.argv.index("--mesh")
        kw["mesh_max"], kw["mesh_min"] = float(sys.argv[i + 1]), float(sys.argv[i + 2])
    if "--order" in sys.argv:
        kw["order"] = int(sys.argv[sys.argv.index("--order") + 1])
    tag = "C" + "".join(f"_{k}{v}" for k, v in kw.items())
    cfg, n_nodes = build_sheet(Path(__file__).parent / f"run_{tag}", **kw)
    print(f"variant C (zero-thickness sheet) kw={kw}: nodes={n_nodes}")
    solve_and_check(cfg)
