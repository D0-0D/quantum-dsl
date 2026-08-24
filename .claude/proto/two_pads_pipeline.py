# -*- coding: utf-8 -*-
"""two_pads gmsh→Palace 原型 — 验证 v4 契约 N7 golden 可在本机复现。

变体 A (v3 逐字复刻): merge .geo → occ.dilate µm→m → SI 网格, Palace L0=1.0
变体 B (v4 候选简化): 模型保持 µm, 不 dilate, Palace L0=1e-6

用法: python two_pads_pipeline.py A|B [--mesh MAX MIN] [--order N] [--thickness T]
"""
import csv
import json
import math
import os
import subprocess
import sys
from pathlib import Path

import gmsh

GEO = Path("/home/administrator/quantum_dsl-v4/tests/fixtures/two_pads.geo")
GOLDEN = [[24.7288, -1.976], [-1.976, 24.7293]]

EPS_R = 11.45
SUB_TH = 100.0      # µm substrate thickness (down from z=0)
AIR_TOP = 120.0
AIR_BOT = 120.0
SIDE = 80.0
METAL_TH = 2.0      # µm (v3 layer_stack default that produced the golden)
FRAG_TOL_UM = 1.0   # v3 FRAGMENT_TOL_SI = 1e-6 m = 1 µm


def build(variant: str, out_dir: Path, mesh_max=40.0, mesh_min=4.0,
          order=2, metal_th=METAL_TH):
    u = 1e-6 if variant == "A" else 1.0   # model unit per µm
    l0 = 1.0 if variant == "A" else 1e-6

    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("two_pads")
        gmsh.merge(str(GEO))
        gmsh.model.occ.synchronize()

        # authored physical surfaces -> {component: [surface tags]}
        pads = {}
        for dim, ptag in gmsh.model.getPhysicalGroups(2):
            name = gmsh.model.getPhysicalName(dim, ptag)
            comp = name.split("::")[2]
            pads[comp] = list(gmsh.model.getEntitiesForPhysicalGroup(dim, ptag))
        assert set(pads) == {"A", "B"}, pads

        if variant == "A":
            gmsh.model.occ.dilate(gmsh.model.getEntities(2), 0, 0, 0, u, u, u)
            gmsh.model.occ.synchronize()

        # chip bbox (from pad surfaces) + side buffer
        inf = float("inf")
        xmin, ymin, xmax, ymax = inf, inf, -inf, -inf
        for tags in pads.values():
            for t in tags:
                bb = gmsh.model.getBoundingBox(2, t)
                xmin, ymin = min(xmin, bb[0]), min(ymin, bb[1])
                xmax, ymax = max(xmax, bb[3]), max(ymax, bb[4])
        xmin -= SIDE * u; ymin -= SIDE * u; xmax += SIDE * u; ymax += SIDE * u

        # extrude pads -> conductor solids; record bbox for face re-keying
        solids, cond_bbox = {}, {}
        for comp, tags in pads.items():
            vols = []
            for t in tags:
                out = gmsh.model.occ.extrude([(2, t)], 0, 0, metal_th * u)
                vols += [tag for d, tag in out if d == 3]
            gmsh.model.occ.synchronize()
            mins, maxs = [inf] * 3, [-inf] * 3
            for v in vols:
                bb = gmsh.model.getBoundingBox(3, v)
                mins = [min(a, b) for a, b in zip(mins, bb[:3])]
                maxs = [max(a, b) for a, b in zip(maxs, bb[3:])]
            solids[comp] = vols
            cond_bbox[comp] = (*mins, *maxs)

        # substrate (z: -SUB_TH..0) + vacuum (z: -AIR_BOT..AIR_TOP)
        sub = gmsh.model.occ.addBox(xmin, ymin, 0, xmax - xmin, ymax - ymin,
                                    -SUB_TH * u)
        tol = FRAG_TOL_UM * u
        vac = gmsh.model.occ.addBox(xmin - tol, ymin - tol, -AIR_BOT * u,
                                    (xmax - xmin) + 2 * tol,
                                    (ymax - ymin) + 2 * tol,
                                    (AIR_TOP + AIR_BOT) * u)

        # Approach A: carve conductors OUT of the vacuum -> cavity walls become
        # exterior Terminal boundaries
        all_solids = [(3, v) for vols in solids.values() for v in vols]
        new_vac, _ = gmsh.model.occ.cut([(3, vac)], all_solids,
                                        removeObject=True, removeTool=True)
        gmsh.model.occ.synchronize()
        vac_tags = [t for d, t in new_vac if d == 3]
        assert vac_tags, "cut consumed the vacuum box"

        # fragment vacuum + substrate (conformal interface at z in [-SUB_TH, 0])
        out, out_map = gmsh.model.occ.fragment(
            [(3, vac_tags[0])], [(3, t) for t in vac_tags[1:]] + [(3, sub)])
        gmsh.model.occ.synchronize()
        # substrate volume(s) = last input's mapping; vacuum = the rest
        sub_vols = [t for d, t in out_map[-1] if d == 3]
        vac_vols = sorted({t for m in out_map[:-1] for d, t in m if d == 3}
                          - set(sub_vols))
        assert len(sub_vols) == 1, f"substrate split/duplicated: {sub_vols}"

        # classify combined-boundary faces: per-conductor cavity walls vs outer
        def in_bbox(bb, c, tol_):
            return all(bb[i] - tol_ <= c[i] <= bb[i + 3] + tol_ for i in range(3))

        def contains(outer_bb, inner_bb, tol_):
            return (all(inner_bb[i] >= outer_bb[i] - tol_ for i in range(3)) and
                    all(inner_bb[i + 3] <= outer_bb[i + 3] + tol_ for i in range(3)))

        boundary = gmsh.model.getBoundary(
            [(3, t) for t in vac_vols + sub_vols],
            combined=True, oriented=False, recursive=False)
        cond_faces = {c: [] for c in solids}
        outer = []
        geo_tol = 1e-3 * u
        for d, tag in boundary:
            f = abs(tag)
            c = gmsh.model.occ.getCenterOfMass(2, f)
            fbb = gmsh.model.getBoundingBox(2, f)
            for comp, bb in cond_bbox.items():
                if in_bbox(bb, c, geo_tol) and contains(bb, fbb, geo_tol):
                    cond_faces[comp].append(f)
                    break
            else:
                outer.append(f)
        for comp, faces in cond_faces.items():
            assert faces, f"terminal {comp} got no cavity walls"

        # physical groups (Palace integer attributes)
        attrs = {}
        attrs["vacuum"] = gmsh.model.addPhysicalGroup(3, vac_vols, name="vacuum")
        attrs["substrate"] = gmsh.model.addPhysicalGroup(3, sub_vols,
                                                         name="substrate")
        for comp, faces in sorted(cond_faces.items()):
            attrs[comp] = gmsh.model.addPhysicalGroup(2, faces, name=comp)
        attrs["vacuum_outer"] = gmsh.model.addPhysicalGroup(
            2, outer, name="vacuum_outer")

        # size fields: refine near conductor cavity-wall curves (v3 recipe)
        curves = sorted({abs(c) for f in sum(cond_faces.values(), [])
                         for d, c in gmsh.model.getBoundary(
                             [(2, f)], combined=False, oriented=False)})
        df = gmsh.model.mesh.field.add("Distance")
        gmsh.model.mesh.field.setNumbers(df, "CurvesList", curves)
        gmsh.model.mesh.field.setNumber(df, "NumPointsPerCurve", 100)
        tf = gmsh.model.mesh.field.add("Threshold")
        gmsh.model.mesh.field.setNumber(tf, "InField", df)
        gmsh.model.mesh.field.setNumber(tf, "DistMin", 10 * u)
        gmsh.model.mesh.field.setNumber(tf, "DistMax", 130 * u)
        gmsh.model.mesh.field.setNumber(tf, "SizeMin", mesh_min * u)
        gmsh.model.mesh.field.setNumber(tf, "SizeMax", mesh_max * u)
        gmsh.model.mesh.field.setNumber(tf, "Sigmoid", 1)
        gmsh.model.mesh.field.setAsBackgroundMesh(tf)
        gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
        gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
        gmsh.option.setNumber("Mesh.MeshSizeMin", mesh_min * u)
        gmsh.option.setNumber("Mesh.MeshSizeMax", mesh_max * u)

        try:
            gmsh.model.mesh.generate(3)
            _, etags, _ = gmsh.model.mesh.getElements(3)
            empty = sum(len(t) for t in etags) == 0
        except Exception:
            empty = True
        if empty:  # HXT fallback (v3 ladder)
            gmsh.model.mesh.clear()
            gmsh.option.setNumber("Mesh.Algorithm3D", 10)
            gmsh.model.mesh.generate(3)
            _, etags, _ = gmsh.model.mesh.getElements(3)
            assert sum(len(t) for t in etags) > 0, "empty 3D mesh"

        out_dir.mkdir(parents=True, exist_ok=True)
        gmsh.option.setNumber("Mesh.MshFileVersion", 2.2)
        gmsh.option.setNumber("Mesh.ScalingFactor", 1.0)
        msh = out_dir / "chip.msh"
        gmsh.write(str(msh))
        n_nodes = len(gmsh.model.mesh.getNodes()[0])
    finally:
        gmsh.finalize()

    cfg = {
        "Problem": {"Type": "Electrostatic", "Verbose": 2, "Output": "postpro"},
        "Model": {"L0": l0, "Mesh": msh.name},
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


def solve_and_check(cfg_path: Path):
    env = dict(os.environ, HWLOC_COMPONENTS="-gl")
    palace = env.get("PALACE_BIN",
                     "/home/administrator/spack/opt/spack/linux-skylake/"
                     "palace-0.16.0-jloea5mo2ggtwaccvf23xgqly3oxgi4b/bin/palace")
    r = subprocess.run([palace, "-np", "1", cfg_path.name],
                       cwd=cfg_path.parent, env=env,
                       capture_output=True, text=True, timeout=1800)
    if r.returncode != 0:
        print(r.stdout[-3000:], r.stderr[-3000:], sep="\n---stderr---\n")
        raise SystemExit(f"palace failed rc={r.returncode}")
    rows = list(csv.reader((cfg_path.parent / "postpro" / "terminal-C.csv")
                           .open(encoding="utf-8")))
    c_fF = [[float(v) * 1e15 for v in row[1:]] for row in rows[1:]]
    print("C (fF)  =", [[round(v, 4) for v in row] for row in c_fF])
    print("golden  =", GOLDEN)
    worst = 0.0
    for i in range(2):
        for j in range(2):
            rel = abs(c_fF[i][j] - GOLDEN[i][j]) / abs(GOLDEN[i][j])
            worst = max(worst, rel)
    print(f"worst rel err = {worst * 100:.3f}%  ({'PASS' if worst < 0.02 else 'FAIL'} @2%)")
    return c_fF, worst


if __name__ == "__main__":
    variant = sys.argv[1] if len(sys.argv) > 1 else "A"
    kw = {}
    if "--mesh" in sys.argv:
        i = sys.argv.index("--mesh")
        kw["mesh_max"], kw["mesh_min"] = float(sys.argv[i + 1]), float(sys.argv[i + 2])
    if "--order" in sys.argv:
        kw["order"] = int(sys.argv[sys.argv.index("--order") + 1])
    if "--thickness" in sys.argv:
        kw["metal_th"] = float(sys.argv[sys.argv.index("--thickness") + 1])
    tag = variant + "".join(f"_{k}{v}" for k, v in kw.items())
    out = Path(__file__).parent / f"run_{tag}"
    cfg, n_nodes = build(variant, out, **kw)
    print(f"variant {variant} kw={kw}: mesh nodes={n_nodes}, config={cfg}")
    solve_and_check(cfg)
