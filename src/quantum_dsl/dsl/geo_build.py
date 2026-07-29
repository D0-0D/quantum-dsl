# -*- coding: utf-8 -*-
"""Native ``.geo`` + ``*.meta.yaml`` → GDS + Palace orchestrator (M1 pivot).

一个原生 Gmsh ``.geo`` (Layer 2 几何, 微米) + 一个独立的 ``*.meta.yaml``
sidecar (Layer 1 物理元数据) 分叉成两条后端:

    Layer 1 (*.meta.yaml)  ─┐
    Layer 2 (chip.geo)     ─┤
                            ├─► GDS backend  (gdstk)            → chip.gds
                            └─► Mesh backend (Gmsh → Palace)    → chip.msh + chip.json

GDS 与 mesh 两条分支在 M1 各自 **独立加载** ``.geo`` (load twice — 简单解耦);
单位契约见各 adapter docstring (GDS 保留微米; mesh dilate µm→m, Palace L0=1.0)。

**M8 / P0 —— 分块提取 + 拼装 (sidecar 带 ``extract:`` 时)**::

    Layer 2 (完整芯片几何, 单一真值源)
        ├─► GDS fork      —— 完整图, 一行不改
        └─► Mesh fork     —— 每个 extract.block 派生一份 block_<name>.geo (G1)
                              → 独立 mesh → 独立 Palace → 一份 C 矩阵 (= 一个 Cell)
                              → assemble(累加 + Schur 消元)  ← 纯数据层
                              → circuit_model (transmon + tl_resonator + χ)
                              → chip.results.yaml (系统级)

三条设计理念硬约束 (spec §3.0), 本编排逐条遵守:

* **G1** 块几何 **落盘**为 ``out_dir/block_<name>.geo`` (可用 gmsh GUI 打开检视、可
  归档、进 manifest 带 sha256), **不是**运行时的内存过滤。``emit_block_geo`` 严格在
  ``load_geo`` **上游** —— 下游 (``carve_conductors`` / ``fragment`` /
  ``assign_physical_groups``) 一行不改, 故 Palace 的 physical group 名保持
  byte-identical (与 M5a 的 ``emit_geo`` 同一契约)。
* **G2** 命令行 / 环境变量 **不得改动几何参数**。``--no-solve`` 只关求解, 不碰几何;
  几何与其参数的真值源永远是 ``.geo`` + ``meta.yaml``。
* **G3** 一次 build = 一份确定几何 (扫参是 N 次独立 build, 不在本函数内变形几何)。

没有 ``extract:`` 时走原来的整片路径, **输出逐字节不变**。

公开 API:
    build_geo(geo_path=None, meta_path, out_dir, *, run_palace=False, dry_run=True,
              num_procs=1, no_solve=False) -> dict

CLI:
    python -m quantum_dsl.dsl.geo_build <meta.yaml> --out-dir build/
        [--run-palace --dry-run] [--np N] [--no-solve]
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Union

from .errors import DesignDslError
from .parsers.simulation import parse_geo_meta_sidecar


__all__ = ["build_geo", "main"]


def _sha256_file(path: Optional[Union[str, Path]]) -> Optional[str]:
    """文件内容 SHA-256 (十六进制); 路径为 None 或不存在则返回 None。

    用于结果产物的溯源/失效检测: 消费端重算输入哈希与产物记录比对, 不符即 stale。
    """
    if path is None:
        return None
    p = Path(path)
    if not p.is_file():
        return None
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _file_record(path: Optional[Union[str, Path]],
                 *, role: str) -> Optional[dict[str, Any]]:
    """单文件的指纹+时间记录 (sha256 / 字节数 / mtime); 文件不存在返回 None。

    用于 ``chip.manifest.yaml`` 的文件夹级清单 — 每条登记 ``out_dir`` 内一个文件的
    内容 SHA-256 与修改时间, 便于脱离源仓库后自证产物来源 / 做失效检测。
    """
    if path is None:
        return None
    p = Path(path)
    if not p.is_file():
        return None
    st = p.stat()
    return {
        "name": p.name,
        "role": role,
        "sha256": _sha256_file(p),
        "bytes": st.st_size,
        "modified_utc": datetime.fromtimestamp(st.st_mtime, timezone.utc)
        .isoformat(timespec="seconds"),
    }


# ---------------------------------------------------------------------------
# M8 / P0-B — extract.blocks 的节点名解析 (rename → 全局节点空间)
# ---------------------------------------------------------------------------
#
# New LOM 的连通机制只有一条: **共享节点名** (``node_rename``, 4.05)。sidecar 的
# ``nodes:`` 就是它。作者可以用两种键指一个 terminal —— 结构化 geo 名
# ``role::layer::comp::prim`` 或已 sanitize 的 group 名 ``{comp}_{prim}_sfs`` ——
# 因为前者是他在 ``.geo`` 里亲手写的、后者是 Palace 矩阵行的标签, 两个他都会看到。
# 解析在这里做 (parser 层刻意只当字符串保留, 见 ``_parse_extract`` docstring)。
#
# rename **先**生效; ``junctions[].between`` / ``assemble.ground_node`` /
# ``nodes_force_keep`` / ``subsystems[].node`` 全部指 rename **之后**的名字, 没被
# rename 的名字原样通过 —— 与 4.05 的写法一致 (它只 rename 耦合爪子, ``jj_dict``
# 仍用原名)。

def _terminal_aliases(geo_surfaces: list[Any],
                      components: Sequence[str]) -> dict[str, str]:
    """``{已 sanitize 的 terminal group 名: 结构化 geo 名}`` —— 块内导体面反查表。

    只收 ``metal::`` —— ``jj::`` 是**集总元件**, ``populate_tracker_from_geo`` 会把它
    移出网格, 所以它永远不是一个电容矩阵的 Terminal (见 CLAUDE.md 的 JJ 约定)。
    """
    from ._gmsh_physical import PHYSICAL_GROUP_NAMING, _sanitize

    keep = set(components)
    out: dict[str, str] = {}
    for s in geo_surfaces:
        if s.role != "metal" or s.component not in keep:
            continue
        group = _sanitize(PHYSICAL_GROUP_NAMING["component_surface"].format(
            component=s.component, primitive=s.primitive))
        out[group] = f"{s.role}::{s.layer}::{s.component}::{s.primitive}"
    return out


def _cell_from_block(blk: Mapping[str, Any], cap: Any,
                     aliases: Mapping[str, str]) -> tuple[Any, dict[str, str]]:
    """一份 C 矩阵 + 一个 ``extract.blocks`` 条目 → ``(ExtractedCell, 解析表)``。

    解析表把「作者可能写出的任何一种节点写法」映射到最终的全局节点名, 供
    ``between`` / ``ground_node`` / ``nodes_force_keep`` / ``subsystems[].node``
    复用: group 名 / 结构化 geo 名 / 最终名 三者都是合法键。

    Raises:
        DesignDslError: ``nodes:`` 里有键不对应本块的任何 Terminal (拼错的节点名会
            静默丢掉耦合 —— 风险 R2, 所以宁可报错); 或一个块内两个 Terminal 被
            rename 成同一个名字 (块内导体是不同的物理导体, 撞名必是笔误)。
    """
    from .assemble import CellJunction, ExtractedCell

    rename = dict(blk.get("nodes") or {})
    group_of_structured = {v: k for k, v in aliases.items()}

    finals: list[str] = []
    resolve: dict[str, str] = {}
    used: set[str] = set()
    claimed: dict[str, str] = {}
    for b in cap.terminals:
        group = b.group
        structured = aliases.get(group)
        key = (group if group in rename
               else structured if structured in rename else None)
        if key is not None:
            used.add(key)
        final = rename[key] if key is not None else group
        if final in claimed:
            raise DesignDslError(
                f"extract block {blk['name']!r}: terminals {claimed[final]!r} and "
                f"{group!r} both map to node {final!r} — two conductors inside ONE "
                f"block are distinct physical nodes; sharing a name is only how "
                f"you connect ACROSS blocks")
        claimed[final] = group
        finals.append(final)
        for alias in (group, structured, final):
            if alias:
                resolve[alias] = final

    unused = sorted(set(rename) - used)
    if unused:
        known = ", ".join(sorted(set(aliases) | set(group_of_structured))) or "<none>"
        raise DesignDslError(
            f"extract block {blk['name']!r}: nodes: key(s) {unused} match no "
            f"capacitance terminal of this block — a mistyped node name silently "
            f"drops or invents coupling. Addressable terminals: {known}")

    junctions = []
    for j in blk.get("junctions") or ():
        between = tuple(
            _resolve_node(n, resolve,
                          where=f"extract block {blk['name']!r} junction "
                                f"{j['name']!r} 'between'")
            for n in j["between"])
        junctions.append(CellJunction(
            name=j["name"], between=between,
            L_J=j.get("L_J"), E_J=j.get("E_J"),
            E_J1=j.get("E_J1"), E_J2=j.get("E_J2"),
            flux=j.get("flux") or 0.0, C_j=j.get("C_j") or 0.0))

    cell = ExtractedCell(
        name=blk["name"],
        terminals=tuple(finals),
        maxwell=tuple(tuple(row) for row in cap.maxwell),
        junctions=tuple(junctions),
        source=getattr(cap, "source", "solved"),
        sha256=getattr(cap, "sha256", None),
    )
    return cell, resolve


def _resolve_node(name: str, resolve: Mapping[str, str], *, where: str) -> str:
    """把一个作者写的节点名解析成最终的全局节点名 (见 ``_cell_from_block``)。"""
    if name in resolve:
        return resolve[name]
    raise DesignDslError(
        f"{where}: unknown node {name!r} — expected a capacitance terminal "
        f"(group name or 'role::layer::comp::prim') or a name introduced by a "
        f"'nodes:' rename. Known: {', '.join(sorted(set(resolve)))}")


# ---------------------------------------------------------------------------
# M8 / P0-D/F — subsystems: → circuit_model 的输入 (transmon / tl_resonator)
# ---------------------------------------------------------------------------

_UM_PER_M = 1.0e-6   # µm → m; cpw_analytic 的接口是 SI 米, 仓库内部是 µm。只乘一次。


def _cpw_stack_defaults(layer_stack: Mapping[int, Mapping[str, Any]]
                        ) -> dict[str, float]:
    """从 sidecar 的 ``layer_stack`` 推 CPW 解析所需的层参数 (µm / 无量纲)。

    只在层栈**无歧义**时给值 (恰好一个 dielectric / 恰好一个 metal); 有歧义就不给,
    让作者在 ``cpw:`` 子块里显式写 —— 猜错一个衬底厚度会静默移动 ``f_res``。
    """
    out: dict[str, float] = {}
    dielectric = [s for s in layer_stack.values() if s.get("kind") == "dielectric"]
    metal = [s for s in layer_stack.values() if s.get("kind") == "metal"]
    if len(dielectric) == 1:
        if dielectric[0].get("thickness") is not None:
            out["substrate_thickness"] = float(dielectric[0]["thickness"])
        if dielectric[0].get("eps_r") is not None:
            out["eps_r"] = float(dielectric[0]["eps_r"])
    if len(metal) == 1 and metal[0].get("thickness") is not None:
        out["film_thickness"] = float(metal[0]["thickness"])
    return out


def _cpw_f_res_hz(cpw: Mapping[str, Any], mode: str,
                  layer_stack: Mapping[int, Mapping[str, Any]], *,
                  where: str) -> float:
    """从 ``cpw: {line_width, line_gap, length}`` 解析算裸谐振频率 (Hz)。

    ``λ_g(f) = (c0/f)/√ε_eff`` 随 f 只经 ε_eff **弱**依赖, 故用不动点迭代
    ``f ← f·λ_g(f)/λ_target`` 求 ``λ_g(f*) = λ_target``; λ/2 谐振器
    ``λ_target = 2L``, λ/4 谐振器 ``λ_target = 4L``。3~4 步即收敛。

    ⚠ 长度参数在 sidecar 里是 **µm** (仓库内部单位), ``cpw_analytic`` 的接口是
    **SI 米** —— 换算只在这里做一次 (``_UM_PER_M``)。
    """
    from .cpw_analytic import guided_wavelength

    merged = {**_cpw_stack_defaults(layer_stack), **dict(cpw)}
    missing = [k for k in ("line_width", "line_gap", "length",
                           "substrate_thickness", "film_thickness")
               if merged.get(k) is None]
    if missing:
        raise DesignDslError(
            f"{where}: cpw: is missing {missing} (µm) and they are not derivable "
            f"from simulation.gmsh.layer_stack — author them explicitly in the "
            f"cpw: block (guessing a substrate thickness silently moves f_res)")
    for key in ("line_width", "line_gap", "length", "substrate_thickness",
                "film_thickness"):
        if float(merged[key]) <= 0:
            raise DesignDslError(f"{where}: cpw.{key} must be > 0, "
                                 f"got {merged[key]}")

    lam_target = (2.0 if mode == "half_wave" else 4.0) * \
        float(merged["length"]) * _UM_PER_M
    kwargs = dict(
        line_width=float(merged["line_width"]) * _UM_PER_M,
        line_gap=float(merged["line_gap"]) * _UM_PER_M,
        substrate_thickness=float(merged["substrate_thickness"]) * _UM_PER_M,
        film_thickness=float(merged["film_thickness"]) * _UM_PER_M,
    )
    if merged.get("eps_r") is not None:
        kwargs["eps_r"] = float(merged["eps_r"])

    freq = 5.0e9
    for _ in range(50):
        lam = guided_wavelength(freq, **kwargs).lambda_g
        nxt = freq * lam / lam_target
        if abs(nxt - freq) <= 1e-12 * nxt:
            return nxt
        freq = nxt
    return freq   # pragma: no cover — 弱依赖, 50 步不收敛在物理上不可能


def _subsystem_inputs(subsystems: Sequence[Mapping[str, Any]],
                      assembled: Any,
                      resolve: Mapping[str, str],
                      layer_stack: Mapping[int, Mapping[str, Any]]
                      ) -> tuple[list[Any], list[Any]]:
    """``subsystems:`` → ``(qubits, resonators)``, 并守卫「每个保留节点都被认领」。

    最后那条守卫是 ``status.md`` 缺口 ⑥ / issue #20 的收尾: ``solve_circuit_model``
    把**未被引用**的 Terminal 当接地电极。Schur 消元之后剩下的节点全都是真正的动力学
    自由度或作者点名 ``nodes_force_keep`` 的节点 —— 任何一个没被 subsystem 认领, 都会
    在下游被**静默接地**, 杀掉它中介的耦合。所以这里 **raise**, 不 warn。
    """
    from .circuit_model import JunctionInput, ResonatorInput

    by_junction = {j.name: j for j in assembled.junctions}
    qubits: list[Any] = []
    resonators: list[Any] = []
    claimed: set[str] = set()

    for sub in subsystems:
        where = f"subsystem {sub['name']!r}"
        if sub["type"] == "transmon":
            jname = sub["junction"]
            if jname not in by_junction:
                raise DesignDslError(
                    f"{where}: junction {jname!r} is not declared in any "
                    f"extract.blocks[].junctions (have: "
                    f"{', '.join(sorted(by_junction)) or '<none>'})")
            j = by_junction[jname]
            qubits.append(JunctionInput(
                name=sub["name"], islands=j.between,
                L_J=j.L_J, E_J=j.E_J, E_J1=j.E_J1, E_J2=j.E_J2,
                flux=j.flux, C_j=j.C_j))
            claimed.update(j.between)
        else:  # tl_resonator (schema 已把 type 限制在 SUBSYSTEM_TYPES 内)
            node = _resolve_node(sub["node"], resolve, where=f"{where} 'node'")
            f_res = sub.get("f_res")
            if f_res is None:
                f_res = _cpw_f_res_hz(sub["cpw"], sub["mode"], layer_stack,
                                      where=where)
            resonators.append(ResonatorInput(
                name=sub["name"], node=node, f_res=float(f_res),
                Z0=float(sub["Z0"]), mode=sub["mode"]))
            claimed.add(node)

    unclaimed = [n for n in assembled.nodes if n not in claimed]
    if unclaimed:
        raise DesignDslError(
            f"assembled node(s) {unclaimed} are not claimed by any subsystem — "
            f"they would be SILENTLY GROUNDED by the circuit-model solve, killing "
            f"whatever coupling they mediate (this is exactly issue #20). Either "
            f"declare a subsystem on them, or drop them from "
            f"assemble.nodes_force_keep so Schur elimination integrates them out "
            f"properly. Kept nodes: {list(assembled.nodes)}")
    return qubits, resonators


def build_geo(geo_path: Optional[Union[str, Path]] = None,
              meta_path: Optional[Union[str, Path]] = None,
              out_dir: Union[str, Path] = "build",
              *,
              run_palace: bool = False,
              dry_run: bool = True,
              num_procs: int = 1,
              no_solve: bool = False) -> dict[str, Any]:
    """从 sidecar (+ 配套 ``.geo``) 分叉构建 GDS + mesh + Palace 配置。

    Args:
        geo_path: 可选, 显式覆盖 sidecar 里 ``geo`` 指向的 ``.geo`` 路径。
            ``None`` 时用 sidecar 解析出的 ``geo`` (相对 sidecar 解析为绝对路径)。
        meta_path: ``*.meta.yaml`` sidecar 路径 (必填)。
        out_dir: 输出目录 (chip.gds / chip.msh / chip.json 写到这里)。
        run_palace: True 时调 ``run_palace`` (受 ``dry_run`` 控制)。
        dry_run: 传给 ``run_palace`` (``--dry-run``: 只校验/划分, 不求解)。
        num_procs: Palace 的 MPI rank 数 (透传给 ``run_palace``); 仅在
            ``run_palace and not dry_run`` 时有意义。必须 >= 1。
        no_solve: 只做几何 + 拼装 + 电路模型, **完全不碰 FEM** (P0-C 的「零成本回归」)。
            带 ``extract:`` 时: ``from: solve`` 的块仍然**派生并落盘**
            ``block_<name>.geo`` (供 gmsh GUI 目视检视), 但不划网格、不跑 Palace;
            ``from: file``/``inline`` 的块照常注入矩阵 → 若**全部**块都有矩阵, 拼装与
            电路模型照常跑并写出 ``chip.results.yaml``。
            ⚠ 这是求解开关, **不是**几何开关 —— 遵守 G2 (命令行不得改动几何参数)。

    Returns:
        ``{"gds": Path|None, "msh": Path|None, "palace_json": Path|None,
           "physical_groups": [sorted names], "results": Path|None,
           "manifest": Path, "blocks": [per-block dict]}``。
        ``results`` 指向 ``out_dir/chip.results.yaml`` (OUTPUT-ONLY 结果产物) —— 整片
        路径下仅在 ``run_palace and not dry_run`` 且 Palace 真写出电容 CSV 时; 分块路径
        下在**每个** block 都拿到 C 矩阵时 (实解或注入)。否则 None。
        ``blocks`` 仅在 sidecar 带 ``extract:`` 时非空, 每块一条
        ``{name, source, geo?, msh?, palace_json?, physical_groups?, solved}``;
        整片路径下 ``msh``/``palace_json`` 保持原语义, 分块路径下二者为 None
        (它们是**每块**的, 见 ``blocks``)。
        ``manifest`` 总是指向 ``out_dir/chip.manifest.yaml`` (输入副本 + 全部产物的
        sha256 指纹与时间戳清单, 含每个 ``block_<name>.geo``); 输入的 meta.yaml / .geo
        也被复制进 ``out_dir``。

    Raises:
        DesignDslError: sidecar / geo 缺失或非法, ``num_procs < 1``, 分块路径下节点名
            解析失败 / 有保留节点没被任何 subsystem 认领, 或下游 adapter 报错。
    """
    if meta_path is None:
        raise DesignDslError("build_geo requires meta_path (the *.meta.yaml).")
    # 在这里校验 (而非 argparse): 直接调 API 的调用方也要被挡住。
    if num_procs < 1:
        raise DesignDslError(
            f"num_procs must be >= 1 (MPI rank count), got {num_procs}.")

    # Lazy import of the optional gmsh/gdstk-backed adapters — keep the package
    # importable without gmsh/gdstk; only this orchestrator needs them.
    from .gmsh_adapter import build_mesh_from_geo
    from .palace_adapter import (
        build_palace_config,
        validate_config,
        write_palace_config,
    )

    meta = parse_geo_meta_sidecar(meta_path)

    sim_gmsh = (meta.get("simulation") or {}).get("gmsh") or {}
    if not sim_gmsh:
        raise DesignDslError(
            f"sidecar {meta_path} has no simulation.gmsh block — cannot build "
            f"mesh / Palace config.")
    layer_stack = sim_gmsh.get("layer_stack") or {}
    solver = sim_gmsh.get("solver") or {}

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ---- resolve the geometry source (M5a) ------------------------------
    # Precedence: explicit geo_path arg > generated from a ``cells:`` block
    # (emit_geo bridge → out_dir/<stem>.elaborated.geo) > the sidecar's ``geo``.
    # The elaborated path is substituted here so BOTH the GDS and mesh forks
    # below consume it unchanged (nothing under load_geo knows the difference).
    if geo_path is not None:
        geo = Path(geo_path).resolve()
    elif meta.get("cells"):
        from .geo_emit import elaborate_cells
        # Strip the full ``.meta.yaml`` / ``.meta.yml`` suffix (NOT just the first
        # dot — a sidecar like ``chip.layout.meta.yaml`` must give stem
        # ``chip.layout``, else two such sidecars collide on ``chip.elaborated.geo``).
        name = Path(meta_path).name
        if name.endswith(".meta.yaml"):
            stem = name[: -len(".meta.yaml")]
        elif name.endswith(".meta.yml"):
            stem = name[: -len(".meta.yml")]
        else:
            stem = Path(name).stem
        geo = out_dir / f"{stem}.elaborated.geo"
        elaborate_cells(meta["cells"], geo, emit_ports=False)
    else:
        geo = meta.get("geo")
    if geo is None or not Path(geo).is_file():
        raise DesignDslError(f"geo file not found: {geo}")

    result: dict[str, Any] = {
        "gds": None,
        "msh": None,
        "palace_json": None,
        "physical_groups": [],
        "results": None,
        "manifest": None,
        "blocks": [],
    }

    # Palace solver口径 —— 提到 session 之前算, 整片与每个 block 共用同一组设置。
    l0 = float(solver.get("l0", 1.0))
    order = int(solver.get("order", 2))
    # outer_boundary: "ground" (default, grounded enclosure) | "open" (natural
    # Neumann ≈ free-space FarField, matches qiskit-metal/Elmer).
    ground_outer = str(solver.get("outer_boundary", "ground")).lower() != "open"

    # M8 / P0-A: 带 ``extract:`` 时 mesh fork 改走分块 —— GDS fork 一行不改 (完整图)。
    extract = meta.get("extract")
    side_buffer_um = float(
        (sim_gmsh.get("airbox") or {}).get("side_buffer", 200.0))
    cells: list[Any] = []
    resolve_all: dict[str, str] = {}
    mesh_result = None

    # SESSION OWNERSHIP (critical): the GDS and mesh branches each call
    # load_geo, which Includes qlib.geo.  qlib.geo's macros (PAD/CPW/...) live in
    # a PROCESS-GLOBAL parser table that survives gmsh.finalize()+initialize(),
    # but its ``_QLIB_INCLUDED`` include-guard CONSTANT does NOT — so if each
    # branch owned (and finalized) its OWN session, the 2nd merge would re-Include
    # qlib.geo with the guard gone and hit "Redefinition of function PAD".
    # Fix: build_geo owns ONE gmsh session spanning both branches.  Each branch's
    # _did_initialize guard then sees gmsh already-initialized → it does NOT
    # finalize → the guard constant survives → the 2nd Include is correctly
    # skipped.  load_geo still switches to a fresh, uniquely-named model per
    # call, so the two branches stay decoupled at the model level.
    import gmsh  # lazy: optional gmsh dependency
    _did_initialize = not gmsh.isInitialized()
    if _did_initialize:
        gmsh.initialize()
        gmsh.option.setNumber("General.Terminal", 0)
    try:
        # ---- GDS branch (gdstk) — microns verbatim, bypasses the 3D mesh ----
        from .gds_adapter import build_gds  # lazy: optional gdstk dependency
        gds_path = out_dir / "chip.gds"
        gds_result = build_gds(
            geo, output_path=gds_path, layer_map=sim_gmsh.get("gds"))
        result["gds"] = gds_result.gds_path

        if extract:
            # ---- MESH fork, 分块 (M8 / P0-A+C) ----------------------------
            # 每个 block 一次独立提取 = New LOM 的一个 Cell。块几何 **落盘** (G1),
            # 其下游 (load_geo / carve / fragment / assign_physical_groups) 一行不改
            # → Palace 的 physical group 名与整片解 byte-identical。
            # 顺序执行: gmsh 是进程级全局状态, 块的并行求解需要进程隔离 (spec §6)。
            from ._gmsh_geo_source import load_geo
            from .geo_emit import emit_block_geo
            from .palace_adapter import (
                capacitance_from_file,
                capacitance_from_inline,
                parse_capacitance_matrix,
                terminal_bindings,
            )

            # 一次加载源几何, 只为拿 {group 名: 结构化 geo 名} 反查表 (节点名解析用)。
            src_surfaces = load_geo(geo, scale_to_si=False)
            groups_seen: set[str] = set()

            for blk in extract["blocks"]:
                bname = blk["name"]
                # 每块一条形状**固定**的记录 (缺席的键为 None, 不是不存在) ——
                # 消费端不必对每个键做 .get() 兜底。
                binfo: dict[str, Any] = {"name": bname,
                                         "source": blk["source"],
                                         "solved": False,
                                         "geo": None,
                                         "msh": None,
                                         "palace_json": None,
                                         "physical_groups": []}
                cap = None
                aliases: dict[str, str] = {}

                if blk["source"] == "file":
                    cap = capacitance_from_file(
                        blk["path"], units=blk["units"])
                    binfo["path"] = str(blk["path"])
                    binfo["solved"] = True
                elif blk["source"] == "inline":
                    cap = capacitance_from_inline(
                        blk["matrix"], units=blk["units"], label=bname)
                    binfo["solved"] = True
                else:
                    # G1: 派生并落盘一份确定的块几何, 再走完全不变的下游管线。
                    blk_geo = emit_block_geo(
                        geo, components=blk["components"],
                        out_path=out_dir / f"block_{bname}.geo",
                        side_buffer_um=side_buffer_um)
                    binfo["geo"] = blk_geo
                    aliases = _terminal_aliases(src_surfaces, blk["components"])
                    if not no_solve:
                        bdir = out_dir / f"block_{bname}"
                        bdir.mkdir(parents=True, exist_ok=True)
                        bmesh = build_mesh_from_geo(
                            blk_geo, sim_gmsh, output_path=bdir / "chip.msh",
                            generate=True)
                        bcfg = build_palace_config(
                            bmesh.physical_attributes, layer_stack,
                            sim_gmsh.get("ports", ()), l0=l0, order=order,
                            ground_outer=ground_outer,
                            mesh_path=(Path(bmesh.mesh_path).name
                                       if bmesh.mesh_path else None))
                        validate_config(bcfg, bmesh.physical_attributes)
                        bjson = write_palace_config(bcfg, bdir / "chip.json")
                        binfo["msh"] = bmesh.mesh_path
                        binfo["palace_json"] = bjson
                        binfo["physical_groups"] = sorted(bmesh.physical_groups)
                        groups_seen.update(bmesh.physical_groups)
                        if run_palace:
                            from .palace_adapter import (
                                run_palace as _run_palace)
                            _run_palace(bjson, dry_run=dry_run,
                                        num_procs=num_procs)
                            if not dry_run:
                                cap = parse_capacitance_matrix(
                                    bdir / bcfg["Problem"].get(
                                        "Output", "postpro"),
                                    terminals=terminal_bindings(
                                        bmesh.physical_attributes))
                                if not cap.available:
                                    raise DesignDslError(
                                        f"extract block {bname!r}: Palace wrote "
                                        f"no capacitance CSV in "
                                        f"{bdir / 'postpro'} — cannot assemble")
                                binfo["solved"] = True

                if cap is not None:
                    cell, resolve = _cell_from_block(blk, cap, aliases)
                    cells.append(cell)
                    for key, final in resolve.items():
                        prev = resolve_all.get(key)
                        if prev is not None and prev != final:
                            raise DesignDslError(
                                f"node name {key!r} resolves to {prev!r} in one "
                                f"block and {final!r} in block {bname!r} — a name "
                                f"must mean the same node everywhere")
                        resolve_all[key] = final
                result["blocks"].append(binfo)

            result["physical_groups"] = sorted(groups_seen)
        else:
            # ---- MESH branch (Gmsh) — µm→m dilate, msh2.2 for Palace --------
            msh_path = out_dir / "chip.msh"
            mesh_result = build_mesh_from_geo(
                geo, sim_gmsh, output_path=msh_path, generate=True)
            result["msh"] = mesh_result.mesh_path
            result["physical_groups"] = sorted(mesh_result.physical_groups)
    finally:
        if _did_initialize and gmsh.isInitialized():
            gmsh.finalize()

    if mesh_result is not None:
        # ---- PALACE — Electrostatic config from geo-derived attributes ------
        # run_palace cd's into the config's directory before invoking Palace, so
        # Model.Mesh must be RELATIVE to that dir. chip.json and chip.msh share
        # out_dir, so the mesh reference is just its basename.
        mesh_rel = (Path(mesh_result.mesh_path).name
                    if mesh_result.mesh_path else None)
        cfg = build_palace_config(
            mesh_result.physical_attributes,
            layer_stack,
            sim_gmsh.get("ports", ()),
            l0=l0,
            order=order,
            ground_outer=ground_outer,
            mesh_path=mesh_rel,
        )
        validate_config(cfg, mesh_result.physical_attributes)
        palace_json = out_dir / "chip.json"
        write_palace_config(cfg, palace_json)
        result["palace_json"] = palace_json

    if run_palace and mesh_result is not None:
        from .palace_adapter import run_palace as _run_palace
        _run_palace(palace_json, dry_run=dry_run, num_procs=num_procs)

        # ---- RESULTS write-back (M3): OUTPUT-ONLY chip.results.yaml --------
        # Only a real solve (not --dry-run) produces capacitance CSVs.  Derive
        # the postpro dir from the config's Problem.Output (NOT a hardcoded
        # literal) and reuse build_palace_config's terminal binding as the
        # single source of truth for the matrix row/col labels.
        if not dry_run:
            from .palace_adapter import (
                parse_capacitance_matrix,
                terminal_bindings,
                write_results_sidecar,
            )
            postpro = out_dir / cfg["Problem"].get("Output", "postpro")
            bindings = terminal_bindings(mesh_result.physical_attributes)
            cap = parse_capacitance_matrix(postpro, terminals=bindings)
            if cap.available:
                provenance = {
                    "generated_utc": datetime.now(timezone.utc)
                    .isoformat(timespec="seconds"),
                    "solver": {"type": "Electrostatic", "order": order, "l0": l0},
                    "out_dir": str(out_dir),
                    "label_index_map": {b.group: b.index for b in bindings},
                    "inputs": {
                        "geo": Path(geo).name,
                        "geo_sha256": _sha256_file(geo),
                        "mesh": (Path(mesh_result.mesh_path).name
                                 if mesh_result.mesh_path else None),
                        "mesh_sha256": _sha256_file(mesh_result.mesh_path),
                        "palace_json": palace_json.name,
                        "config_sha256": _sha256_file(palace_json),
                    },
                }

                # ---- CIRCUIT MODEL (M6): C-matrix → transmon Hamiltonian ----
                # Optional: only when the sidecar authored a `circuit_model`
                # block.  Derives E_C/E_J/f01/anharmonicity per qubit + pairwise
                # couplings, written to the SAME results artifact at tier 2.
                circuit_model = None
                cm_block = meta.get("circuit_model")
                if cm_block and cm_block.get("qubits"):
                    from .circuit_model import (
                        JunctionInput,
                        solve_circuit_model,
                    )
                    junctions = [
                        JunctionInput(
                            name=q["name"],
                            islands=tuple(q["islands"]),
                            L_J=q.get("L_J"),
                            E_J=q.get("E_J"),
                            # SQUID (flux-tunable, possibly asymmetric); flux is
                            # Phi/Phi0 and defaults to 0.0 (zero flux, max E_J).
                            E_J1=q.get("E_J1"),
                            E_J2=q.get("E_J2"),
                            flux=q.get("flux") or 0.0,
                            # 结电容 (P0-E); 默认 0 → 既有数值逐位不动。
                            C_j=q.get("C_j") or 0.0,
                        )
                        for q in cm_block["qubits"]
                    ]
                    circuit_model = solve_circuit_model(cap, junctions)
                    provenance["circuit_model_inputs"] = {
                        "qubits": [
                            {
                                "name": q["name"],
                                "islands": list(q["islands"]),
                                **({"L_J_H": q["L_J"]} if q.get("L_J") is not None
                                   else {"E_J_J": q["E_J"]}
                                   if q.get("E_J") is not None
                                   else {"squid": {"E_J1_J": q["E_J1"],
                                                   "E_J2_J": q["E_J2"],
                                                   "flux_Phi0": q["flux"]}}),
                            }
                            for q in cm_block["qubits"]
                        ],
                    }

                result["results"] = write_results_sidecar(
                    cap, out_dir / "chip.results.yaml",
                    provenance=provenance, circuit_model=circuit_model)

    # ---- ASSEMBLE + system-level results (M8 / P0-B+D+E) ------------------
    # 拼装层是**纯数据层**: 只消费 {C_k} + Layer-1 的节点/结/子系统声明, 完全不碰几何,
    # 所以它天然符合 G1–G3。只有当**每个** block 都拿到矩阵 (实解或注入) 时才跑 ——
    # 缺一个块就少一段电容图, 拼出来的系统是错的, 宁可不写结果。
    if extract:
        n_blocks = len(extract["blocks"])
        if len(cells) != n_blocks:
            missing = [b["name"] for b in result["blocks"] if not b["solved"]]
            print(f"note: {len(cells)}/{n_blocks} extract block(s) have a "
                  f"capacitance matrix — skipping assembly (no matrix for "
                  f"{missing}). Run with --run-palace (without --dry-run), or "
                  f"author those blocks as 'from: file'/'inline'.",
                  file=sys.stderr)
        else:
            from .assemble import assemble
            from .palace_adapter import write_results_sidecar

            asm = meta.get("assemble") or {}
            ground_node = asm.get("ground_node")
            # 参考地通常是金属地 (``ground::``), 而金属地**不是**一个 Terminal
            # (``_conductor_groups`` 排除 ``gnd_``) —— 所以它解析不到任何节点是
            # 正常的, 原样透传给 assemble (它按名字缺席处理)。
            ground_resolved = (resolve_all.get(ground_node, ground_node)
                               if ground_node else None)
            force_keep = tuple(
                _resolve_node(n, resolve_all,
                              where="assemble.nodes_force_keep")
                for n in (asm.get("nodes_force_keep") or ()))
            assembled = assemble(cells, ground_node=ground_resolved,
                                 nodes_force_keep=force_keep)
            # 溯源 (风险 R4): 拼装后的矩阵不是任何单一来源的产物, 而
            # ``as_capacitance_result()`` 会留下默认的 ``source="solved"`` —— 一份
            # 全靠注入矩阵拼出来的结果会自称实解。这里改写成 ``assembled:<来源集合>``,
            # 逐 cell 的 source/sha256 另见 provenance.assembly.cells。
            asm_cap = dataclasses.replace(
                assembled.as_capacitance_result(),
                source="assembled:" + "+".join(
                    sorted({c.source for c in cells})))

            circuit_model = None
            subsystems = meta.get("subsystems")
            if subsystems:
                from .circuit_model import solve_circuit_model
                qubits, resonators = _subsystem_inputs(
                    subsystems, assembled, resolve_all, layer_stack)
                circuit_model = solve_circuit_model(
                    asm_cap, qubits, resonators=resonators)

            provenance = {
                "generated_utc": datetime.now(timezone.utc)
                .isoformat(timespec="seconds"),
                "solver": {"type": "Electrostatic", "order": order, "l0": l0},
                "out_dir": str(out_dir),
                "label_index_map": {b.group: b.index for b in asm_cap.terminals},
                "inputs": {
                    "geo": Path(geo).name,
                    "geo_sha256": _sha256_file(geo),
                },
                # 溯源必须能区分实解与文件注入 (风险 R4), 且必须记下哪些节点被消掉
                # (风险 R2/R3) —— 否则拼装层成了一个新的 silent-wrong-result 面。
                "assembly": {
                    "method": "capacitance-graph accumulation (shared node names) "
                              "+ Schur elimination of non-dynamical nodes "
                              "(New LOM / arXiv:2103.10344 eq 7b), node basis",
                    "ground_node": assembled.ground_node,
                    "nodes": list(assembled.nodes),
                    "nodes_force_keep": list(force_keep),
                    "eliminated": list(assembled.eliminated),
                    "cells": [
                        {"name": c.name, "source": c.source,
                         "sha256": c.sha256, "terminals": list(c.terminals),
                         "junctions": [j.name for j in c.junctions]}
                        for c in cells
                    ],
                    "audit": assembled.audit,
                },
            }
            result["results"] = write_results_sidecar(
                asm_cap, out_dir / "chip.results.yaml",
                provenance=provenance, circuit_model=circuit_model)

    # ---- ARCHIVE inputs + write file manifest (every build) ---------------
    # Copy the meta.yaml + .geo into out_dir (keep original names) so a build
    # folder is self-contained, then record sha256 + mtime of inputs AND every
    # produced artifact in chip.manifest.yaml (folder-level fingerprint list;
    # distinct from results.yaml's own provenance block).
    import yaml  # core dep, lazy-imported to keep the bare import path light

    meta_dst = out_dir / Path(meta_path).name
    if Path(meta_path).resolve() != meta_dst.resolve():
        shutil.copy2(meta_path, meta_dst)
    geo_dst = out_dir / Path(geo).name
    if Path(geo).resolve() != geo_dst.resolve():
        shutil.copy2(geo, geo_dst)

    files = [
        _file_record(meta_dst, role="input"),
        _file_record(geo_dst, role="input"),
        _file_record(result["gds"], role="output"),
        _file_record(result["msh"], role="output"),
        _file_record(result["palace_json"], role="output"),
        _file_record(result["results"], role="output"),
    ]
    # G1: 每个派生的块几何逐块登记 —— block_<name>.geo 是可归档、可 diff、可用 gmsh
    # GUI 打开检视的确定产物, 所以它进清单带 sha256, 与源 .geo 同等待遇。
    for binfo in result["blocks"]:
        files.append(_file_record(binfo.get("geo"), role="block-geo"))
        files.append(_file_record(binfo.get("msh"), role="block-output"))
        files.append(_file_record(binfo.get("palace_json"), role="block-output"))
    manifest = {
        "schema": "quantum-dsl/build-manifest/1",
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "out_dir": str(out_dir),
        "files": [f for f in files if f is not None],
    }
    manifest_path = out_dir / "chip.manifest.yaml"
    with manifest_path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(manifest, fh, sort_keys=False, allow_unicode=True,
                       default_flow_style=False)
    result["manifest"] = manifest_path

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m quantum_dsl.dsl.geo_build",
        description="Fork a native Gmsh .geo + *.meta.yaml sidecar into a GDS "
                    "(gdstk) layout and a Palace Electrostatic mesh+config.",
    )
    parser.add_argument(
        "meta", help="path to the *.meta.yaml sidecar (its 'geo' key names "
                     "the companion .geo).")
    parser.add_argument(
        "--geo", default=None,
        help="optional explicit .geo path (overrides the sidecar's 'geo').")
    parser.add_argument(
        "--out-dir", default="build", help="output directory (default: build).")
    parser.add_argument(
        "--run-palace", action="store_true",
        help="also invoke Palace on the generated config.")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="pass --dry-run to Palace (validate/partition only).")
    parser.add_argument(
        "--np", type=int, default=1, metavar="N",
        help="number of MPI ranks for Palace (default: 1); only meaningful "
             "with --run-palace and without --dry-run.")
    parser.add_argument(
        "--no-solve", action="store_true",
        help="skip all FEM: still derive/write every block_<name>.geo (so they "
             "can be inspected in the gmsh GUI), but do not mesh or run Palace. "
             "With every extract block authored as 'from: file'/'inline' this is "
             "a zero-cost assembly + circuit-model run. Solve switch only — it "
             "never changes geometry parameters (G2).")
    parser.add_argument(
        "--png", nargs="?", const="chip.png", default=None,
        help="render the produced chip.gds to a PNG preview (M7; gdsfactory if "
             "installed, else matplotlib). Optional PATH relative to --out-dir "
             "(default: chip.png).")
    args = parser.parse_args(argv)

    try:
        result = build_geo(
            geo_path=args.geo,
            meta_path=args.meta,
            out_dir=args.out_dir,
            run_palace=args.run_palace,
            dry_run=args.dry_run,
            num_procs=args.np,
            no_solve=args.no_solve,
        )
    except DesignDslError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"GDS         : {result['gds']}")
    print(f"MSH         : {result['msh']}")
    print(f"Palace JSON : {result['palace_json']}")
    for binfo in result.get("blocks") or ():
        print(f"Block       : {binfo['name']} (from={binfo['source']}, "
              f"matrix={'yes' if binfo['solved'] else 'no'})"
              + (f" geo={binfo['geo']}" if binfo.get("geo") else ""))
    if result.get("results"):
        print(f"Results     : {result['results']}")
    if result.get("manifest"):
        print(f"Manifest    : {result['manifest']}")
    print(f"physical_groups ({len(result['physical_groups'])}): "
          f"{result['physical_groups']}")

    # ---- optional GDS preview (M7) — visualization only, additive ----------
    if args.png is not None and result.get("gds"):
        try:
            from .gds_viz import preview_gds
            prev = preview_gds(result["gds"], out_png=Path(args.out_dir) / args.png)
            print(f"Preview     : {prev.png_path} (backend={prev.backend}, "
                  f"layers={prev.layers})")
        except DesignDslError as exc:
            print(f"warning: --png preview failed: {exc}", file=sys.stderr)

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
