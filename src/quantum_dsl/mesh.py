# -*- coding: utf-8 -*-
"""静电网格 (契约 N5): 零厚度导体片 imprint 为边界面组。

配方 = .claude/physics-pipeline.md §3–§6 (golden 出处 = proto/two_pads_sheet.py
实测), v4 与 v3 的分道处:

* 金属**不 extrude、不布尔减** —— 2D 焊盘面直接 fragment (imprint) 进衬底/
  真空界面, Terminal 挂内部边界面 (Palace essential Dirichlet, §4 已实测可解)。
  共面是构造性精确 → ε-nudge / scale-ladder / 腔壁归位失效类结构性消失。
* 计算域由 meta 合成: 衬底 z∈[−thickness, 0], 真空 z∈[−bottom, +top],
  xy = 导体 bbox ± side (真空盒侧向再外扩 1 µm, 与 golden 配方一致)。
* 角色: metal → Terminal (按 component 命名, **labels = sorted(component)** 是
  C 矩阵行序的唯一真相源); ground → 接地导体面 (Boundaries.Ground);
  jj → 集总元件, **从几何中删除** (进 GDS 不进静电网格; 当导体桥会把两块
  焊盘短路, C 矩阵失去意义)。
* 网格: 导体边缘电场 ∝ r^(−1/2) 奇异 → Distance+Threshold 尺寸场对**所有**
  导体边缘曲线细化 (metal + ground, 电容缝隙两侧都要进细化源), 渐变
  10→130 µm (golden 配方常数); Delaunay 失败回退 HXT。
* 失效防线 (pipeline §8, 每条背后都有一次"无报错出错解"的实案):
  作者 Physical 组捕获后立即清除 (imprint 路径下作者面存活, 组保留 → 同一面
  两条边界元, Palace ReadMesh 拒收); fragment 后拓扑不变量 (衬底恰 1 体 /
  无负体积 / Σ体积 ≤ bbox×1.001); 导体面不得泄漏到外边界; 每条出口过空网格
  守卫 (gmsh 对失败可能静默返回空网格)。

单位: 全程 µm (网格文件坐标也是 µm), SI 换算只发生在 Palace config 的
``Model.L0 = 1e-6`` —— 不双重缩放。gmsh 惰性 import (N0)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .errors import QuantumDslError
from .geo import parse_physical_name

__all__ = ["Mesh", "build_mesh"]

_FRAG_TOL_UM = 1.0            # 真空盒相对导体 bbox+side 的再外扩 (golden 配方)
_REFINE_DIST_UM = (10.0, 130.0)  # Distance→Threshold 渐变区 (golden 配方)


@dataclass(frozen=True)
class Mesh:
    """已生成的 3D 静电网格 + Palace 绑定所需的组号。

    ``labels`` (= sorted metal component) 是 Terminal 顺序 = C 矩阵行序的
    唯一真相源, palace_config/parse_capacitance/solve_circuit_model 都以它对齐。
    """

    path: Path
    labels: tuple[str, ...]
    conductor_groups: dict[str, int]        # metal component → physical 组号
    domain_groups: dict[str, int]           # {"substrate": tag, "vacuum": tag}
    boundary_groups: dict[str, int]         # {"outer": tag[, "ground": tag]}
    num_cells: int                          # 全部网格单元 (含边界面单元)
    num_volume_cells: int                   # 3D 单元 (真空 + 衬底)
    conductor_bbox_um: dict[str, tuple] = field(default_factory=dict)


def _require(mapping: dict, key: str, where: str) -> float:
    if key not in mapping:
        raise QuantumDslError(f"build_mesh: meta.{where}.{key} is required")
    return float(mapping[key])


def build_mesh(geo_path, meta, out) -> Mesh:
    """``.geo`` (µm) + Meta → 3D 网格 (msh 2.2, 坐标 µm)。空网格 raise。"""
    geo_path = Path(geo_path)
    if not geo_path.is_file():
        raise QuantumDslError(f"build_mesh: no such file: {geo_path}")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)

    substrate = meta.materials.get("substrate") or {}
    sub_th = _require(substrate, "thickness_um", "materials.substrate")
    air_top = _require(meta.airbox, "top_um", "airbox")
    air_bot = _require(meta.airbox, "bottom_um", "airbox")
    side = _require(meta.airbox, "side_um", "airbox")
    mesh_max = _require(meta.mesh, "max_size_um", "mesh")
    mesh_min = _require(meta.mesh, "min_size_um", "mesh")

    from ._gmsh import geo_model

    with geo_model(geo_path) as gmsh:
        # --- 作者 Physical 组: role 分拣 -------------------------------------
        conductors: dict[str, list[int]] = {}   # metal component → 面 tags
        grounds: list[int] = []
        jj_faces: set[int] = set()
        claimed: set[int] = set()
        for dim, ptag in gmsh.model.getPhysicalGroups(2):
            phys = parse_physical_name(gmsh.model.getPhysicalName(dim, ptag))
            tags = [int(t) for t in
                    gmsh.model.getEntitiesForPhysicalGroup(dim, ptag)]
            claimed.update(tags)
            if phys.role == "metal":
                conductors.setdefault(phys.component, []).extend(tags)
            elif phys.role == "ground":
                grounds.extend(tags)
            elif phys.role == "jj":
                jj_faces.update(tags)   # 集总元件: 不进静电网格
            else:
                raise QuantumDslError(
                    f"build_mesh: role {phys.role!r} ({phys.name}) has no "
                    f"electrostatic-mesh semantics in v4 (supported: metal, "
                    f"ground, jj)")
        if not conductors:
            raise QuantumDslError(
                f"build_mesh: {geo_path} has no metal:: surfaces — nothing to "
                f"extract capacitance for")

        # 防线 §8.3: 捕获后立即清除作者组 —— imprint 路径下作者面**存活**到
        # 最终网格, 组保留会与实现组重叠 → 同一几何面两条边界元, Palace 拒收。
        gmsh.model.removePhysicalGroups()

        # jj 面与未被任何组认领的孤儿面 (分块过滤的残留几何) 一并删除。
        # recursive=True 会连边界点/线删掉 —— fixtures 的面互不共享低维实体
        # (OCC Rectangle / 布尔结果各自独立), 共享时 fragment 之前也无共享需求。
        drop = [(2, t) for _, t in gmsh.model.getEntities(2)
                if t in jj_faces or t not in claimed]
        if drop:
            gmsh.model.occ.remove(drop, recursive=True)
            gmsh.model.occ.synchronize()

        # --- 计算域: 导体 bbox ± side ----------------------------------------
        inf = float("inf")
        xmin, ymin, xmax, ymax = inf, inf, -inf, -inf
        cond_bbox: dict[str, tuple] = {}
        for comp, tags in conductors.items():
            cxmin, cymin, cxmax, cymax = inf, inf, -inf, -inf
            for t in tags:
                bb = gmsh.model.getBoundingBox(2, t)
                cxmin, cymin = min(cxmin, bb[0]), min(cymin, bb[1])
                cxmax, cymax = max(cxmax, bb[3]), max(cymax, bb[4])
            cond_bbox[comp] = (cxmin, cymin, cxmax, cymax)
            xmin, ymin = min(xmin, cxmin), min(ymin, cymin)
            xmax, ymax = max(xmax, cxmax), max(ymax, cymax)
        for t in grounds:
            bb = gmsh.model.getBoundingBox(2, t)
            xmin, ymin = min(xmin, bb[0]), min(ymin, bb[1])
            xmax, ymax = max(xmax, bb[3]), max(ymax, bb[4])
        xmin -= side; ymin -= side; xmax += side; ymax += side

        sub = gmsh.model.occ.addBox(xmin, ymin, 0, xmax - xmin, ymax - ymin,
                                    -sub_th)
        tol = _FRAG_TOL_UM
        vac = gmsh.model.occ.addBox(xmin - tol, ymin - tol, -air_bot,
                                    (xmax - xmin) + 2 * tol,
                                    (ymax - ymin) + 2 * tol, air_top + air_bot)

        # --- 一次 fragment: 体积互切 + 导体面 imprint 进 z=0 界面 -------------
        comp_order = sorted(conductors)
        tools = ([(3, sub)]
                 + [(2, t) for c in comp_order for t in conductors[c]]
                 + [(2, t) for t in grounds])
        _, out_map = gmsh.model.occ.fragment([(3, vac)], tools)
        gmsh.model.occ.synchronize()

        sub_vols = [t for d, t in out_map[1] if d == 3]
        vac_vols = sorted({t for d, t in out_map[0] if d == 3} - set(sub_vols))
        # 防线 §8.1: 拓扑不变量 (实案: OCC 静默复制衬底体 / 产负 mass 实体)
        if len(sub_vols) != 1:
            raise QuantumDslError(
                f"build_mesh: fragment produced {len(sub_vols)} substrate "
                f"volume(s), expected exactly 1 — OCC boolean corrupted the "
                f"topology")
        if not vac_vols:
            raise QuantumDslError("build_mesh: fragment consumed the vacuum box")
        vol_sum = 0.0
        for t in vac_vols + sub_vols:
            mass = gmsh.model.occ.getMass(3, t)
            if not mass > 0.0:
                raise QuantumDslError(
                    f"build_mesh: volume {t} has non-positive mass {mass} — "
                    f"OCC boolean corrupted the topology")
            vol_sum += mass
        bbox_vol = ((xmax - xmin) + 2 * tol) * ((ymax - ymin) + 2 * tol) \
            * (air_top + air_bot)
        if vol_sum > bbox_vol * 1.001:
            raise QuantumDslError(
                f"build_mesh: total volume {vol_sum:.6g} exceeds model bbox "
                f"volume {bbox_vol:.6g} — OCC duplicated material")

        # 防线 §8.4: 面归属用 fragment 的 out_map 直接映射, 不做 bbox 猜测。
        idx = 2
        cond_faces: dict[str, list[int]] = {}
        for c in comp_order:
            faces: list[int] = []
            for _ in conductors[c]:
                faces += [t for d, t in out_map[idx] if d == 2]
                idx += 1
            if not faces:
                raise QuantumDslError(
                    f"build_mesh: conductor {c!r} was not imprinted into the "
                    f"domain (fragment consumed it)")
            cond_faces[c] = faces
        ground_faces: list[int] = []
        for _ in grounds:
            ground_faces += [t for d, t in out_map[idx] if d == 2]
            idx += 1
        if grounds and not ground_faces:
            raise QuantumDslError(
                "build_mesh: ground sheet was not imprinted into the domain")

        boundary = gmsh.model.getBoundary(
            [(3, t) for t in vac_vols + sub_vols],
            combined=True, oriented=False, recursive=False)
        outer = [abs(t) for _, t in boundary]
        inner_faces = {t for faces in cond_faces.values() for t in faces}
        inner_faces.update(ground_faces)
        leaked = inner_faces & set(outer)
        if leaked:
            raise QuantumDslError(
                f"build_mesh: conductor face(s) {sorted(leaked)} leaked to the "
                f"outer boundary — the airbox does not enclose the conductors")

        # --- Physical 组 (Palace 整数 attribute) ------------------------------
        domain_groups = {
            "vacuum": gmsh.model.addPhysicalGroup(3, vac_vols, name="vacuum"),
            "substrate": gmsh.model.addPhysicalGroup(3, sub_vols,
                                                     name="substrate"),
        }
        boundary_groups = {
            "outer": gmsh.model.addPhysicalGroup(2, outer, name="outer"),
        }
        if ground_faces:
            boundary_groups["ground"] = gmsh.model.addPhysicalGroup(
                2, ground_faces, name="ground")
        conductor_groups = {
            c: gmsh.model.addPhysicalGroup(2, cond_faces[c], name=c)
            for c in comp_order}

        # --- 尺寸场: 所有导体边缘曲线细化 (metal + ground) --------------------
        curves = sorted({abs(cv) for f in sorted(inner_faces)
                         for _, cv in gmsh.model.getBoundary(
                             [(2, f)], combined=False, oriented=False)})
        df = gmsh.model.mesh.field.add("Distance")
        gmsh.model.mesh.field.setNumbers(df, "CurvesList", curves)
        gmsh.model.mesh.field.setNumber(df, "NumPointsPerCurve", 100)
        tf = gmsh.model.mesh.field.add("Threshold")
        gmsh.model.mesh.field.setNumber(tf, "InField", df)
        gmsh.model.mesh.field.setNumber(tf, "DistMin", _REFINE_DIST_UM[0])
        gmsh.model.mesh.field.setNumber(tf, "DistMax", _REFINE_DIST_UM[1])
        gmsh.model.mesh.field.setNumber(tf, "SizeMin", mesh_min)
        gmsh.model.mesh.field.setNumber(tf, "SizeMax", mesh_max)
        gmsh.model.mesh.field.setNumber(tf, "Sigmoid", 1)
        gmsh.model.mesh.field.setAsBackgroundMesh(tf)
        # gmsh.option 是全局的 (进程级共享 session) — 依赖的选项全部显式设,
        # 包括把上一次调用可能留下的 HXT 回退复位回 Delaunay。
        gmsh.option.setNumber("Mesh.Algorithm3D", 1)
        gmsh.option.setNumber("Mesh.ElementOrder", 1)
        gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
        gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
        gmsh.option.setNumber("Mesh.MeshSizeMin", mesh_min)
        gmsh.option.setNumber("Mesh.MeshSizeMax", mesh_max)

        # 防线 §8.2: 空网格守卫 + HXT 回退 (HXT 不能当全局默认, 部分几何反而败)
        try:
            gmsh.model.mesh.generate(3)
            _, etags3, _ = gmsh.model.mesh.getElements(3)
            empty = sum(len(t) for t in etags3) == 0
        except Exception:
            empty = True
        if empty:
            gmsh.model.mesh.clear()
            gmsh.option.setNumber("Mesh.Algorithm3D", 10)   # HXT
            gmsh.model.mesh.generate(3)
            _, etags3, _ = gmsh.model.mesh.getElements(3)
            if sum(len(t) for t in etags3) == 0:
                raise QuantumDslError(
                    f"build_mesh: empty 3D mesh for {geo_path} (Delaunay and "
                    f"HXT both failed) — gmsh can fail silently, refusing to "
                    f"write a useless mesh")
        num_volume_cells = sum(len(t) for t in etags3)
        _, etags_all, _ = gmsh.model.mesh.getElements()
        num_cells = sum(len(t) for t in etags_all)

        gmsh.option.setNumber("Mesh.MshFileVersion", 2.2)
        gmsh.write(str(out))

    return Mesh(path=out, labels=tuple(comp_order),
                conductor_groups=conductor_groups,
                domain_groups=domain_groups, boundary_groups=boundary_groups,
                num_cells=num_cells, num_volume_cells=num_volume_cells,
                conductor_bbox_um=cond_bbox)
