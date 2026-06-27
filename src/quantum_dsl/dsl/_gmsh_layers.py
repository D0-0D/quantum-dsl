# -*- coding: utf-8 -*-
"""DSL → Gmsh adapter: layer stack / vacuum box / cut 阶段。

参见 plan §3.3-C / §3.3-D。symmetry 留到 M4, 这里只覆盖 ground + vacuum + cut。

允许 import:
- `gmsh`, `numpy`, 标准库
- `_gmsh_geometry.GeomTracker`
- `.errors.DesignDslError` (纯异常类型, 无依赖)

deny-list (硬性): `qiskit_metal.designs.*`, `qiskit_metal.qlibrary.*`,
`LayerStackHandler`, `BoundsForPathAndPolyTables`, `QGmshRenderer`, `renderer_base`。
"""

from __future__ import annotations

from ._gmsh_geometry import GeomTracker
from .errors import DesignDslError

try:
    import gmsh
except ImportError:  # pragma: no cover — exercised on lite installs
    gmsh = None


# fragment 1um (在 SI 即 1e-6) 兜底, 与 `gmsh_renderer.py:761` 同理: 避免
# 共面 substrate / vacuum 在 OCC fragment 时被切成两块独立 volume。
FRAGMENT_TOL_SI = 1e-6


def render_layer_grounds(bbox_si: tuple[float, float, float, float],
                         layer_stack_si: dict[int, dict],
                         tracker: GeomTracker) -> None:
    """每个 layer 画一个 Box (ground plane / substrate)。

    bbox_si = (xmin, ymin, xmax, ymax) 已含 side_buffer; layer_stack_si 中
    `thickness` 可正可负, 由 OCC ``addBox(dz=...)`` 自然处理 (负值 → 体积
    沿 -z 方向)。
    """
    if gmsh is None:
        raise ImportError("gmsh required for render_layer_grounds")
    xmin, ymin, xmax, ymax = bbox_si
    dx = xmax - xmin
    dy = ymax - ymin
    for layer, spec in layer_stack_si.items():
        z = float(spec["z"])
        dz = float(spec["thickness"])
        tag = gmsh.model.occ.addBox(xmin, ymin, z, dx, dy, dz)
        tracker.layer_ground.setdefault(layer, []).append(tag)


def render_vacuum_box(bbox_si: tuple[float, float, float, float],
                      airbox_si: dict,
                      tracker: GeomTracker) -> None:
    """画真空盒。

    airbox_si: ``{top, bottom, side_buffer}`` (米); ``side_buffer`` 这里
    不再用 (chip bbox 已经包含它), 只用 top / bottom。tol 加到外围避免
    OCC fragment 把真空切成两块。
    """
    if gmsh is None:
        raise ImportError("gmsh required for render_vacuum_box")
    top = float(airbox_si["top"])
    bottom = float(airbox_si["bottom"])
    if top <= 0 or bottom <= 0:
        raise ValueError(
            f"airbox top/bottom must be > 0 (got top={top}, bottom={bottom})")
    xmin, ymin, xmax, ymax = bbox_si
    tol = FRAGMENT_TOL_SI
    x = xmin - tol
    y = ymin - tol
    z = -bottom
    dx = (xmax - xmin) + 2 * tol
    dy = (ymax - ymin) + 2 * tol
    dz = top + bottom
    tracker.vacuum_box = gmsh.model.occ.addBox(x, y, z, dx, dy, dz)


def apply_symmetry_cuts(symmetry_specs,
                        tracker: GeomTracker,
                        bbox_si: tuple[float, float, float, float],
                        airbox_si: dict[str, float]) -> None:
    """Stage C': 按 ``simulation.gmsh.symmetry`` 切掉对称面外侧的半空间。

    每条 `{plane: x0|y0|z0, condition: pec|pmc}`:
    - 构造一个覆盖外侧半空间的 box (delta = 1um 容差);
    - 对 vacuum + 所有 layer_ground / poly / path 体上调 ``occ.cut``,
      留下半边;
    - 切完后切面留在 ground / vacuum 表面, 由 `_gmsh_physical` 阶段
      通过 "面中心在对称平面 z=0/y=0/x=0 上" 筛出, 命名 `symmetry_{plane}`;
    - 顺序约束 (plan §3.3-C): symmetry 必须在 stage D cut 之前做。

    LATENT GAP (M4-deferred): the conductors-as-voids tables ``conductor_solids`` /
    ``ground_solids`` (Approach A, geo path) are NOT in the cut targets / remap here.
    Today that is safe — symmetry is M4-deferred and never runs on the geo path, and
    even if it did, carve runs AFTER symmetry so a metal terminal/ground straddling a
    symmetry plane would simply be carved un-clipped. Before enabling symmetry on the
    geo path, add these tables to the targets + remap (mirror ``polys``/``paths``).
    """
    if gmsh is None:
        raise ImportError("gmsh required for apply_symmetry_cuts")
    if not symmetry_specs:
        return
    xmin, ymin, xmax, ymax = bbox_si
    top = float(airbox_si.get("top", 0.0))
    bottom = float(airbox_si.get("bottom", 0.0))
    pad = FRAGMENT_TOL_SI * 100  # 100um, 确保整个外侧被覆盖
    full_xmin = xmin - pad
    full_xmax = xmax + pad
    full_ymin = ymin - pad
    full_ymax = ymax + pad
    full_zmin = -(bottom + pad)
    full_zmax = top + pad

    for spec in symmetry_specs:
        plane = spec["plane"]
        if plane == "y0":
            x = (full_xmin, full_ymin, full_zmin)
            dxyz = (full_xmax - full_xmin, -full_ymin, full_zmax - full_zmin)
        elif plane == "x0":
            x = (full_xmin, full_ymin, full_zmin)
            dxyz = (-full_xmin, full_ymax - full_ymin, full_zmax - full_zmin)
        elif plane == "z0":
            x = (full_xmin, full_ymin, full_zmin)
            dxyz = (full_xmax - full_xmin, full_ymax - full_ymin, -full_zmin)
        else:
            raise ValueError(f"unsupported symmetry plane {plane!r}")
        halfspace = gmsh.model.occ.addBox(x[0], x[1], x[2],
                                          dxyz[0], dxyz[1], dxyz[2])

        targets: list[tuple[int, int]] = []
        for layer_tags in tracker.layer_ground.values():
            targets.extend((3, t) for t in layer_tags)
        for layer_dict in (tracker.polys, tracker.paths):
            for named in layer_dict.values():
                for tags in named.values():
                    targets.extend((3, t) for t in tags)
        # 注: endcap_subtracts 故意 *不* 参与 symmetry cut 目标。M5 实验显
        # 示把它们加入 targets 会让 OCC 把 ground/vacuum 当 fragment 切碎
        # 成多块 (target 间相互重叠拓扑被 OCC 当 cut 边界处理), 触发后续
        # fragment 失效。endcap box 跨对称面时由 OCC `cut(ground_half,
        # full_box)` 在 stage D 自动取交集, 不需要在 symmetry 阶段提前切。
        # (M4 r1 nit 4.3 = won't fix, 见 walkthrough §6 落字)
        # Include subtract bodies (CPW gap volumes) so they are clipped to
        # the kept half-space. endcap_subtracts are intentionally excluded
        # per the M5 note above.
        for layer_tags in tracker.subtracts.values():
            targets.extend((3, t) for t in layer_tags)
        if tracker.vacuum_box is not None:
            targets.append((3, tracker.vacuum_box))
        if not targets:
            gmsh.model.occ.remove([(3, halfspace)], recursive=True)
            continue

        out_dimtags, out_map = gmsh.model.occ.cut(
            targets, [(3, halfspace)], removeObject=True, removeTool=True)
        new_by_input: dict[tuple[int, int], list[int]] = {}
        for input_dimtag, mapping in zip(targets, out_map):
            new_by_input[input_dimtag] = [t for d, t in mapping if d == 3]

        def _remap_dict_of_dict(table):
            for layer in list(table.keys()):
                for key in list(table[layer].keys()):
                    new_tags: list[int] = []
                    for old_tag in table[layer][key]:
                        new_tags.extend(
                            new_by_input.get((3, old_tag), [old_tag]))
                    table[layer][key] = new_tags

        def _remap_dict_of_list(table):
            for layer in list(table.keys()):
                new_tags = []
                for old_tag in table[layer]:
                    new_tags.extend(new_by_input.get((3, old_tag), [old_tag]))
                table[layer] = new_tags

        _remap_dict_of_dict(tracker.polys)
        _remap_dict_of_dict(tracker.paths)
        _remap_dict_of_list(tracker.layer_ground)
        _remap_dict_of_list(tracker.subtracts)
        if tracker.vacuum_box is not None:
            mapped = new_by_input.get((3, tracker.vacuum_box), [])
            tracker.vacuum_box = mapped[0] if mapped else tracker.vacuum_box
        gmsh.model.occ.synchronize()


def fragment_everything(tracker: GeomTracker) -> None:
    """Stage E: OCC fragment 把所有 volume + JJ surface + vacuum 缝合一致。

    思路照 `gmsh_renderer.py:fragment_interfaces` (833-922):
    - 收集 (3, tag) 形式的所有 ground / poly / path / vacuum volume;
    - 收集 (2, tag) 形式的 JJ surface; ports / symmetry 留到 M4 时一并进来;
    - 任取一个 3D dimtag 作 ``object``, 其余作 ``tools`` 喂 ``occ.fragment``;
    - 解析返回的 ``outDimTags``(平铺) + ``outDimTagsMap``(按输入分组) 得到
      ``old_to_new``, 调 ``tracker.remap`` 更新所有 tag 表;
    - 最后 ``occ.synchronize()``。

    fragment 的副作用: 共面的体积 / 表面会被分割并共用边界 entity, 这正是
    后续 mesh 跨界面一致所需的。
    """
    if gmsh is None:
        raise ImportError("gmsh required for fragment_everything")

    inputs_3d: list[tuple[int, int]] = []
    for layer, tags in tracker.layer_ground.items():
        inputs_3d.extend((3, t) for t in tags)
    for layer_dict in tracker.polys.values():
        for tags in layer_dict.values():
            inputs_3d.extend((3, t) for t in tags)
    for layer_dict in tracker.paths.values():
        for tags in layer_dict.values():
            inputs_3d.extend((3, t) for t in tags)
    if tracker.vacuum_box is not None:
        inputs_3d.append((3, tracker.vacuum_box))
    inputs_3d.extend((3, t) for t in tracker.vacuum_extra)

    inputs_2d: list[tuple[int, int]] = []
    for layer_dict in tracker.juncs.values():
        for tags in layer_dict.values():
            inputs_2d.extend((2, t) for t in tags)
    # M4 r1 观察 #2 (M5): port face 也参与 fragment, 让 ground/port 的
    # 共享拓扑显式建立, remap 走正常路径而非 `mapped is None` 兜底 (后者
    # 在复杂 design 跨切割边界时会丢 tag)。
    seen_port_tags: set[int] = set()
    for port_tags in tracker.ports.values():
        for t in port_tags:
            if t in seen_port_tags:
                continue
            seen_port_tags.add(t)
            inputs_2d.append((2, t))

    all_inputs = inputs_3d + inputs_2d
    if len(all_inputs) < 2:
        # 没法 fragment (至少需要 object + 1 tool); 跳过, 退化到不缝合。
        gmsh.model.occ.synchronize()
        return

    object_dimtag = all_inputs[0]
    tools = all_inputs[1:]
    out_dimtags, out_map = gmsh.model.occ.fragment([object_dimtag], tools)
    # out_map[i] 对应 inputs[i] (object 在前, tools 顺序排其后)
    ordered_inputs = [object_dimtag] + tools
    old_to_new: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for old, mapping in zip(ordered_inputs, out_map):
        old_to_new[old] = list(mapping)
    tracker.remap(old_to_new)
    gmsh.model.occ.synchronize()


def _centroid_in_bbox(bb: tuple, c: tuple, tol: float = 1e-9) -> bool:
    """face 质心 ``c=(x,y,z)`` 是否落在 3D bbox ``bb=(x0,y0,z0,x1,y1,z1)`` 内 (含 tol)。"""
    x0, y0, z0, x1, y1, z1 = bb
    return (x0 - tol <= c[0] <= x1 + tol and
            y0 - tol <= c[1] <= y1 + tol and
            z0 - tol <= c[2] <= z1 + tol)


def carve_conductors(tracker: GeomTracker) -> None:
    """Approach A: 把金属 terminal 实体 **从 vacuum_box 挖空** (occ.cut)。

    必须在 ``render_vacuum_box`` (vacuum_box 已建) 之后、``fragment_everything``
    之前调用。挖空后真空里出现导体形状的空腔, 其腔壁在 fragment 后成为 **外部**
    边界面 (≤1 相邻单元), 满足 Palace 的 Terminal 边界不变量。挖空前先记录每个
    terminal 的 3D bbox, 供 ``resolve_conductor_faces`` 按质心把腔壁归位。

    无金属 terminal (e.g. 纯 ground 设计) 或无 vacuum_box → no-op。
    """
    if gmsh is None:
        raise ImportError("gmsh required for carve_conductors")
    if tracker.vacuum_box is None or (
            not tracker.conductor_solids and not tracker.ground_solids):
        return

    cut_tools: list[tuple[int, int]] = []
    for layer, named in tracker.conductor_solids.items():
        for (component, primitive), tags in named.items():
            if not tags:
                continue
            # union bbox over this terminal's solid(s) (M1: 通常 1 个)
            mins = [float("inf")] * 3
            maxs = [float("-inf")] * 3
            for t in tags:
                bb = gmsh.model.getBoundingBox(3, t)
                for i in range(3):
                    mins[i] = min(mins[i], bb[i])
                    maxs[i] = max(maxs[i], bb[i + 3])
                cut_tools.append((3, t))
            tracker.conductor_bbox[(layer, component, primitive)] = (
                mins[0], mins[1], mins[2], maxs[0], maxs[1], maxs[2])

    # Approach A (M5a): carve the synthesized metal ground sheet too.  Same cut
    # as a terminal, but its cavity wall is later named ``gnd_layer{N}_sfs``
    # (Ground boundary), not a Terminal.  bbox keyed by layer (one chip-wide
    # ground per layer) so resolve_conductor_faces can re-key the walls.
    for layer, tags in tracker.ground_solids.items():
        if not tags:
            continue
        mins = [float("inf")] * 3
        maxs = [float("-inf")] * 3
        for t in tags:
            bb = gmsh.model.getBoundingBox(3, t)
            for i in range(3):
                mins[i] = min(mins[i], bb[i])
                maxs[i] = max(maxs[i], bb[i + 3])
            cut_tools.append((3, t))
        tracker.ground_bbox[layer] = (
            mins[0], mins[1], mins[2], maxs[0], maxs[1], maxs[2])

    if not cut_tools:
        return

    new_vac, _ = gmsh.model.occ.cut(
        [(3, tracker.vacuum_box)], cut_tools,
        removeObject=True, removeTool=True)
    gmsh.model.occ.synchronize()
    vac_tags = [t for (d, t) in new_vac if d == 3]
    if not vac_tags:
        # 0 volumes = the cut consumed the whole box. The carve tools must be a
        # strict subset of the vacuum interior; an empty result is a real error.
        raise DesignDslError(
            "carve_conductors: cutting the conductor/ground terminals consumed "
            "the entire vacuum box (0 volumes remain) — the carve tools must "
            "lie strictly inside the vacuum interior.")
    # Carving the conductors + ground sheet out of ONE box can SPLIT the vacuum
    # into several connected volumes: a ground-plane design pinches the thin
    # metal-layer vacuum into the pocket interior plus one sliver per lead
    # CPW-gap. Every result is still vacuum (the box MINUS metal) and the slivers
    # are conformal with the bulk after fragment_everything, so we KEEP them all
    # and tag them all 'vacuum' (vacuum_box = largest/primary, vacuum_extra =
    # rest). Each vacuum-domain stage (fragment / material / outer boundary /
    # face resolution) spans box + extra. (This previously raised on >1 volume,
    # which blocked every ground+lead design from solving — only vac_tags[0]
    # would have received a material attribute, leaving an incomplete domain.)
    vac_tags.sort(key=lambda t: gmsh.model.occ.getMass(3, t), reverse=True)
    tracker.vacuum_box = vac_tags[0]
    tracker.vacuum_extra = vac_tags[1:]
    tracker.conductor_solids.clear()  # consumed by the cut
    tracker.ground_solids.clear()     # consumed by the cut


def resolve_conductor_faces(tracker: GeomTracker,
                            layer_stack_si: dict[int, dict]) -> None:
    """carve + fragment 之后, 把空腔壁 face 归位到各 terminal (Terminal 出表面)。

    思路同 ``resolve_port_surfaces`` (fragment 后按几何解析): 取 (vacuum +
    dielectric substrate) 域的 **combined** 边界 (丢掉内部 substrate/vacuum 界面,
    保留外部面 + 空腔壁), 用挖空前记录的 ``conductor_bbox`` 把每个 face 按质心
    归到 ``(component, primitive)``; 落在任一 terminal bbox 内 → ``conductor_faces``,
    其余 → ``vacuum_outer_faces`` (carve 版真空外边界)。
    """
    if gmsh is None:
        raise ImportError("gmsh required for resolve_conductor_faces")
    if not tracker.conductor_bbox and not tracker.ground_bbox:
        return

    domain: list[tuple[int, int]] = []
    if tracker.vacuum_box is not None:
        domain.append((3, tracker.vacuum_box))
    domain.extend((3, t) for t in tracker.vacuum_extra)
    for layer, spec in layer_stack_si.items():
        if spec.get("kind") == "dielectric":
            domain.extend((3, t) for t in tracker.layer_ground.get(layer, []))
    if not domain:
        return

    boundary = gmsh.model.getBoundary(
        domain, combined=True, oriented=False, recursive=False)
    outer: list[int] = []
    for dim, tag in boundary:
        if dim != 2:
            continue
        face = abs(int(tag))
        c = gmsh.model.occ.getCenterOfMass(2, face)
        # Terminal bboxes are checked FIRST: they are small and specific, and a
        # chip-wide ground bbox (M5a) spatially CONTAINS every terminal (the
        # ground's xy bbox ignores its holes), so terminals must win the centroid
        # test before the ground claims their cavity walls.
        hit = None
        for (layer, component, primitive), bb in tracker.conductor_bbox.items():
            if _centroid_in_bbox(bb, c):
                hit = (layer, component, primitive)
                break
        if hit is not None:
            layer, component, primitive = hit
            tracker.conductor_faces.setdefault(layer, {}).setdefault(
                (component, primitive), []).append(face)
            continue
        # then the metal ground frame (its cavity walls live outside every
        # terminal bbox because the metals sit inside the ground's holes).
        gnd_layer = None
        for layer, bb in tracker.ground_bbox.items():
            if _centroid_in_bbox(bb, c):
                gnd_layer = layer
                break
        if gnd_layer is not None:
            tracker.ground_faces.setdefault(gnd_layer, []).append(face)
        else:
            outer.append(face)
    tracker.vacuum_outer_faces = outer


def apply_cuts(tracker: GeomTracker,
               layer_stack_si: dict[int, dict] | None = None) -> None:
    """把 `tracker.subtracts + endcap_subtracts` 从对应 layer ground 里 cut 出去。

    cut 之后 ground volume 的 tag 会变, tracker.layer_ground[layer] 更新到
    返回的新 dimtag。subtracts/endcap_subtracts 在 cut 中消失, 之后从
    tracker 里清掉。

    layer_stack_si: 可选; 若提供, dielectric layers 的 subtract 被跳过并
    警告, 避免在 substrate 上打洞。当前调用方传 None 保持原有行为; 传入
    resolved_options.layer_stack 后可启用保护。
    """
    if gmsh is None:
        raise ImportError("gmsh required for apply_cuts")
    for layer in list(tracker.layer_ground.keys()):
        if layer_stack_si is not None:
            layer_kind = layer_stack_si.get(layer, {}).get("kind")
            if layer_kind == "dielectric":
                import warnings
                warnings.warn(
                    f"Layer {layer} is dielectric but has subtract primitives; "
                    "skipping cuts to avoid holes in substrate.", stacklevel=2)
                continue
        ground_tags = tracker.layer_ground.get(layer, [])
        subtract_tags = (
            tracker.subtracts.get(layer, []) +
            tracker.endcap_subtracts.get(layer, [])
        )
        if not subtract_tags:
            continue
        if not ground_tags:
            import warnings
            warnings.warn(
                f"Layer {layer} has subtract primitives but no ground body "
                "(possibly consumed by symmetry cut); cuts skipped and "
                "subtracts discarded.", stacklevel=2)
            tracker.subtracts.pop(layer, None)
            tracker.endcap_subtracts.pop(layer, None)
            continue
        cut_input = [(3, t) for t in ground_tags]
        cut_tools = [(3, t) for t in subtract_tags]
        new_ground, _ = gmsh.model.occ.cut(cut_input, cut_tools)
        tracker.layer_ground[layer] = [tag for dim, tag in new_ground if dim == 3]
        tracker.subtracts.pop(layer, None)
        tracker.endcap_subtracts.pop(layer, None)
    gmsh.model.occ.synchronize()
