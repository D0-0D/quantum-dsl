# -*- coding: utf-8 -*-
"""DSL → Palace adapter: Electrostatic (capacitance) config builder.

把 fragment 之后的 physical-group **名称 → 整数 attribute** 映射 (即
``GmshMeshResult.physical_attributes``) 翻译成 Palace 的 Electrostatic JSON
输入。本模块是 **纯 Python**: 不 import gmsh, 只按名字查 attribute, 因此可在
任何环境 (含 metal-env-old) 下单测。

单位 / L0 约定 (cross-cutting, 与其它 agent 严格一致):
    mesh 分支在 ``gmsh.merge`` 之后把整个模型 microns→meters dilate 过, 因此
    写出的 ``.msh`` 已经是 **SI 米**。Palace 的 ``Model.L0`` 表示 "1 mesh unit =
    L0 米", 故 ``L0 = 1.0`` (mesh 即米)。GDS 分支才保留 micron, 与本模块无关。

name → attribute 绑定 (THE binding contract 的下游消费端):
    导体面 (Terminal)      : ``{component}_{primitive}_sfs``  (metal:: feature 的出表面)
    金属地 (Ground)        : ``gnd_layer{N}_sfs``
    真空外边界 (Ground)    : ``vacuum_outer``
    介质材料 (Material)    : ``substrate_layer{N}``  → Permittivity = layer_stack[N].eps_r
    真空材料 (Material)    : ``vacuum``              → Permittivity = 1.0

注意: physical-group 名字经过 ``_gmsh_physical._sanitize`` (非
``[A-Za-z0-9_]`` → ``_``), 因此 ``Q1.pad_left`` 之类会变成 ``Q1_pad_left``。
本模块按 *已 sanitize* 的名字工作; 导体集合的识别完全基于 ``_sfs`` 后缀 +
排除 ``gnd_*`` / ``vacuum_*`` 前缀, 不依赖原始 component 名。

公开 API:
    build_palace_config(physical_attributes, layer_stack, ports=(), *, l0=1.0) -> dict
    terminal_bindings(physical_attributes, *, geo_names=None) -> list[TerminalBinding]
    validate_config(config, physical_attributes) -> None
    write_palace_config(config, path) -> Path
    run_palace(config_path, *, dry_run=True, num_procs=1) -> None
    _to_wsl_path(win_path) -> str
    parse_capacitance_matrix(postpro_dir, terminals=()) -> CapacitanceResult
    capacitance_from_file(path, *, terminals=None, units="fF") -> CapacitanceResult
    capacitance_from_inline(matrix, *, terminals=None, units="fF",
                            label="inline") -> CapacitanceResult
    write_results_sidecar(result, out_path, *, provenance=None,
                          circuit_model=None, tier=None) -> Path
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
from typing import Any, Iterable, Mapping, Sequence

import yaml

from .errors import DesignDslError


__all__ = [
    "build_palace_config",
    "terminal_bindings",
    "TerminalBinding",
    "validate_config",
    "write_palace_config",
    "run_palace",
    "parse_capacitance_matrix",
    "capacitance_from_file",
    "capacitance_from_inline",
    "CapacitanceResult",
    "write_results_sidecar",
]


# ---------------------------------------------------------------------------
# name → attribute helpers
# ---------------------------------------------------------------------------

def _attr_of(physical_attributes: Mapping[str, int], name: str) -> int:
    """查 ``physical_attributes[name]``; 缺失则 ``DesignDslError``。"""
    try:
        return int(physical_attributes[name])
    except KeyError as exc:
        available = ", ".join(sorted(physical_attributes)) or "<none>"
        raise DesignDslError(
            f"Palace config needs physical group {name!r} but it is not in "
            f"physical_attributes (have: {available})"
        ) from exc


def _conductor_groups(physical_attributes: Mapping[str, int]) -> list[str]:
    """挑出所有「导体面」physical-group 名 (Terminal 候选)。

    规则: 名字以 ``_sfs`` 结尾, 且 **不是** 金属地 (``gnd_``) 或真空
    (``vacuum``) 的出表面。结果按名字排序, 保证 Terminal Index 稳定。
    """
    out: list[str] = []
    for name in physical_attributes:
        if not name.endswith("_sfs"):
            continue
        if name.startswith("gnd_") or name.startswith("vacuum"):
            continue
        out.append(name)
    return sorted(out)


def _ground_groups(physical_attributes: Mapping[str, int]) -> list[str]:
    """金属地出表面 (``gnd_*_sfs``) — Ground 边界候选, 按名字排序。"""
    return sorted(
        name for name in physical_attributes
        if name.startswith("gnd_") and name.endswith("_sfs")
    )


def _dielectric_volume_groups(physical_attributes: Mapping[str, int]) -> list[str]:
    """介质体 (``substrate_layer{N}``) — Material 候选, 按名字排序。"""
    return sorted(
        name for name in physical_attributes
        if name.startswith("substrate_layer")
    )


def _layer_of_substrate(name: str) -> int | None:
    """从 ``substrate_layer3`` 提取层号 3 (失败返回 None)。"""
    prefix = "substrate_layer"
    if not name.startswith(prefix):
        return None
    suffix = name[len(prefix):]
    try:
        return int(suffix)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# terminal binding — THE single source of truth for capacitance row/col order
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TerminalBinding:
    """一个 Palace Terminal 的绑定 (电容矩阵行/列的自描述标签)。

    Fields:
        index:     Palace ``Boundaries.Terminal`` 的 1-based Index (= 矩阵行列号)。
        group:     已 sanitize 的 physical-group 名 (导体出表面, ``{C}_{P}_sfs``)。
        attribute: ``physical_attributes[group]`` 整数 attribute。
        terminal:  可选结构化绑定名 ``role::layer::component::primitive`` (若可得)。
    """

    index: int
    group: str
    attribute: int
    terminal: str | None = None


def terminal_bindings(
    physical_attributes: Mapping[str, int],
    *,
    geo_names: Mapping[str, str] | None = None,
) -> list[TerminalBinding]:
    """导体面 → 有序 ``TerminalBinding`` 列表 (电容矩阵行列绑定的 **单一真相源**)。

    顺序 = ``enumerate(_conductor_groups(...), start=1)``, 与
    ``build_palace_config`` 写 ``Boundaries.Terminal`` 的 Index 顺序 **逐字一致**
    (二者共用 ``_conductor_groups``), 故 CSV 第 i 行 ↔ ``Terminal[i]`` ↔
    ``terminal_bindings()[i-1]`` 不会错位 —— 即便日后 ``_sfs`` 规则或排序改变,
    config 与结果写出端仍同步。

    Args:
        physical_attributes: ``{group_name: int_attribute}`` (post-fragment)。
        geo_names: 可选 ``{group_name: "role::layer::comp::prim"}`` 反查表, 用于
            回填 ``terminal`` 字段; 缺省时该字段为 ``None``。
    """
    names = (geo_names or {})
    return [
        TerminalBinding(
            index=index,
            group=name,
            attribute=_attr_of(physical_attributes, name),
            terminal=names.get(name),
        )
        for index, name in enumerate(_conductor_groups(physical_attributes),
                                     start=1)
    ]


# ---------------------------------------------------------------------------
# Electrostatic config builder
# ---------------------------------------------------------------------------

def build_palace_config(
    physical_attributes: Mapping[str, int],
    layer_stack: Mapping[int, Mapping[str, Any]],
    ports: Sequence[Any] = (),
    *,
    l0: float = 1.0,
    order: int = 2,
    ground_outer: bool = True,
    mesh_path: str | os.PathLike[str] | None = None,
) -> dict:
    """构建 Palace **Electrostatic** (电容) JSON 配置 (dict)。

    Args:
        physical_attributes: ``{physical_group_name: int_attribute}``, 来自
            ``GmshMeshResult.physical_attributes`` (fragment 后从 GeomTracker
            重注册得到, 名字与 legacy 路径字节一致)。
        layer_stack: ``{N: {"kind": "dielectric"|"metal", "eps_r": ..., ...}}``;
            介质层 (``kind == "dielectric"``, 或带 ``eps_r``) 提供 Permittivity。
        ports: 预留 (M1 电容求解的 terminal 即导体面, 不消费 ports)。
        l0: ``Model.L0`` — 1 mesh unit = l0 米。mesh 已是 SI 米故缺省 1.0。
        order: 有限元阶数 (``Solver.Order``), 缺省 2。
        mesh_path: 可选 ``Model.Mesh`` 路径 (相对/绝对均可); orchestrator 写入。

    要求至少 **1 个 Terminal**, 否则 ``DesignDslError``。

    ⚠ 这条曾经是「至少 **2** 个」(M1: 电容矩阵总得有两个导体才有互电容)。M8 的分块
    提取 (``extract.blocks``) 打破了这个前提: 一个块**完全可以只含一个导体**, 此时
    1×1 的 Maxwell 矩阵就是该导体对接地边界 (``gnd_*_sfs`` 或被接地的 ``vacuum_outer``)
    的自电容 —— 这正是拼装层要的量, Palace 也照常做一次 terminal 激励求解。
    ``two_pads`` 分块成 A/B 两个单导体块就是这个情形 (spec §7 第一行的 A/B 对照)。
    0 个 Terminal 仍然 raise —— 那才是「作者忘了给导体打 ``metal::`` 标注」的症状,
    而那个保护是这条守卫真正的价值所在。
    """
    bindings = terminal_bindings(physical_attributes)
    if not bindings:
        raise DesignDslError(
            "Electrostatic capacitance needs >=1 conductor terminal (found none). "
            "Each conductor must author a metal::N::C::P surface so that a "
            "'{C}_{P}_sfs' physical group exists."
        )

    # --- Domains.Materials: 每个介质层 + 真空 ----------------------------
    materials: list[dict] = []
    energy_attrs: list[int] = []

    for sub_name in _dielectric_volume_groups(physical_attributes):
        attr = _attr_of(physical_attributes, sub_name)
        layer = _layer_of_substrate(sub_name)
        spec = layer_stack.get(layer, {}) if layer is not None else {}
        eps_r = spec.get("eps_r")
        if eps_r is None:
            raise DesignDslError(
                f"dielectric group {sub_name!r} (layer {layer}) has no "
                f"'eps_r' in layer_stack"
            )
        materials.append({
            "Attributes": [attr],
            "Permittivity": float(eps_r),
        })
        energy_attrs.append(attr)

    # 真空: 必有 (vacuum box 总会注册)。
    vacuum_attr = _attr_of(physical_attributes, "vacuum")
    materials.append({
        "Attributes": [vacuum_attr],
        "Permittivity": 1.0,
    })
    energy_attrs.append(vacuum_attr)

    # --- Boundaries.Ground: 金属地出表面 + 真空外边界 --------------------
    ground_attrs: list[int] = [
        _attr_of(physical_attributes, name)
        for name in _ground_groups(physical_attributes)
    ]
    # The vacuum_box outer wall: grounded (V=0, default) models a grounded
    # enclosure; leaving it open (natural Neumann) is the closest Palace analog
    # of an open / free-space FarField boundary, which is what qiskit-metal's
    # Elmer reference uses. Open is only honoured when a metal ground sheet
    # already provides the V=0 reference — otherwise the electrostatic problem
    # would be singular, so we force-ground the outer wall.
    if ground_outer or not ground_attrs:
        ground_attrs.append(_attr_of(physical_attributes, "vacuum_outer"))

    # --- Boundaries.Terminal: 每个导体面一个, Index 从 1 起 -------------
    # 复用 terminal_bindings 计算出的 (index, group, attr) —— 与结果写出端
    # 共用同一顺序, 杜绝电容矩阵行/列错配。
    terminals: list[dict] = []
    surface_flux: list[dict] = []
    for b in bindings:
        terminals.append({"Index": b.index, "Attributes": [b.attribute]})
        surface_flux.append({
            "Index": b.index,
            "Attributes": [b.attribute],
            "Type": "Electric",
        })

    config: dict = {
        "Problem": {
            "Type": "Electrostatic",
            "Verbose": 2,
            "Output": "postpro",
            "OutputFormats": {
                "Paraview": True,
                "GridFunction": True,
            },
        },
        "Model": {
            "L0": float(l0),
        },
        "Domains": {
            "Materials": materials,
            "Postprocessing": {
                "Energy": [
                    {"Index": i, "Attributes": [attr]}
                    for i, attr in enumerate(energy_attrs, start=1)
                ],
            },
        },
        "Boundaries": {
            "Ground": {
                "Attributes": ground_attrs,
            },
            "Terminal": terminals,
            "Postprocessing": {
                "SurfaceFlux": surface_flux,
            },
        },
        "Solver": {
            "Order": int(order),
            "Device": "CPU",
            "Electrostatic": {
                "Save": 2,
            },
            "Linear": {
                "Type": "BoomerAMG",
                "KSPType": "CG",
                "Tol": 1.0e-8,
                "MaxIts": 200,
            },
        },
    }

    if mesh_path is not None:
        config["Model"]["Mesh"] = Path(mesh_path).as_posix()

    return config


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------

def _iter_referenced_attrs(node: Any) -> Iterable[int]:
    """递归收集 config 中所有 ``"Attributes": [...]`` 里的整数 attribute。"""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "Attributes" and isinstance(value, (list, tuple)):
                for item in value:
                    if isinstance(item, int):
                        yield item
            else:
                yield from _iter_referenced_attrs(value)
    elif isinstance(node, (list, tuple)):
        for item in node:
            yield from _iter_referenced_attrs(item)


def validate_config(config: Mapping[str, Any],
                    physical_attributes: Mapping[str, int]) -> None:
    """校验 config 引用的每个整数 attribute 都存在于 physical_attributes 值集。

    任一缺失即抛 ``DesignDslError``, 列出全部缺失的 attribute。
    """
    known = set(int(v) for v in physical_attributes.values())
    referenced = set(_iter_referenced_attrs(config))
    missing = sorted(referenced - known)
    if missing:
        raise DesignDslError(
            f"Palace config references unknown physical attribute(s) {missing}; "
            f"known attributes are {sorted(known)}"
        )


# ---------------------------------------------------------------------------
# IO
# ---------------------------------------------------------------------------

def write_palace_config(config: Mapping[str, Any],
                        path: str | os.PathLike[str]) -> Path:
    """把 config 以 ``json.dump(indent=2)`` 写到 ``path``, 返回 Path。"""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        json.dump(dict(config), fh, indent=2)
        fh.write("\n")
    return out


# ---------------------------------------------------------------------------
# Palace runner (lifted from the two_spheres PoC)
# ---------------------------------------------------------------------------

_WSL_PALACE = (
    "/home/administrator/spack/opt/spack/linux-skylake/"
    "palace-0.16.0-jloea5mo2ggtwaccvf23xgqly3oxgi4b/bin/palace"
)


def _to_wsl_path(win_path: str | os.PathLike[str]) -> str:
    """把 Windows 绝对路径转成 WSL ``/mnt/<drive>/...`` 路径。

    跨平台实现 (用 ``PureWindowsPath`` 解析盘符, 不依赖宿主 OS 的 pathlib
    flavour, 故在 Linux/WSL 内跑测试也成立)。已经是 POSIX 绝对路径 (``/...``,
    即在 WSL 内 native 运行的情形) 则原样返回, 不做 ``/mnt`` 映射。
    """
    s = os.fspath(win_path)
    if s.startswith("/"):  # already a POSIX/WSL path — nothing to map
        return s
    pure = PureWindowsPath(s)
    posix = pure.as_posix()
    drive = pure.drive.rstrip(":").lower()
    if not drive:  # no drive letter — best-effort separator normalisation
        return posix
    return f"/mnt/{drive}{posix[len(pure.drive):]}"


def run_palace(config_path: str | os.PathLike[str], *,
               dry_run: bool = True, num_procs: int = 1) -> None:
    """运行 Palace: 优先 native PATH (``palace`` / ``$PALACE_BIN``), 否则 WSL spack。

    Args:
        config_path: Palace JSON 输入路径 (Palace cwd = 其所在目录)。
        dry_run: True → 加 ``--dry-run`` (只校验/划分, 不求解)。
        num_procs: 非 dry-run 时的 MPI 进程数 (native ``-np`` / WSL mpirun)。

    native palace 通过 ``$PALACE_BIN`` 覆盖或 ``shutil.which('palace')`` 定位;
    都没有则回退 WSL spack 安装 (Windows 专用)。
    """
    config_path = Path(config_path).resolve()

    palace = os.environ.get("PALACE_BIN") or shutil.which("palace")

    if palace is not None:
        # Native palace on PATH (or PALACE_BIN override)
        command = [palace]
        if dry_run:
            command.append("--dry-run")
        else:
            command.extend(["-np", str(num_procs)])
        command.append(config_path.name)
        subprocess.run(command, cwd=config_path.parent, check=True)
        return

    # Fall back to WSL spack installation (Windows-specific)
    wsl = shutil.which("wsl")
    if wsl is None:
        raise DesignDslError(
            "Palace was not found on PATH (set $PALACE_BIN or install palace) "
            "and WSL is not available."
        )

    wsl_dir = _to_wsl_path(config_path.parent)

    palace_args = [_WSL_PALACE]
    if dry_run:
        palace_args.append("--dry-run")
    elif num_procs > 1:
        palace_args = ["mpirun", "-np", str(num_procs)] + palace_args
    palace_args.append(config_path.name)

    command = [wsl, "bash", "-c", f"cd {wsl_dir!r} && {' '.join(palace_args)}"]
    subprocess.run(command, check=True)


# ---------------------------------------------------------------------------
# results — Palace Electrostatic capacitance matrices (M3)
# ---------------------------------------------------------------------------
#
# Palace 在 <Problem.Output>/ (缺省 'postpro') 写两张电容 CSV:
#   terminal-C.csv   — MAXWELL 电容矩阵 C: 对称, +对角 / -非对角
#                      (C[i][i]=节点 i 自/总电容; C[i][j]=-互容)。circuit-QED /
#                      LOM 约化消费的就是这一张。
#   terminal-Cm.csv  — 互/集总(SPICE)矩阵 Cm: 全正
#                      (Cm[i][i]=节点 i 对地电容=Σ_j C[i][j]; Cm[i][j]=-C[i][j]
#                       =导体 i 与 j 之间的物理电容)。
# 两张都是 N×N (N=#terminals), 单位 SI 法拉, 带表头行:
#     "        i,   C[i][1] (F),   C[i][2] (F), ..."
# 数据行: "<i as float>, <+val>, <+val>, ..."。我们用表头校验列数 + 断言方阵,
# 按列序解析 (列 j = C[i][j]), 并把 F → fF 存储。

_F_TO_FF = 1.0e15  # 1 F = 1e15 fF

CAP_MAXWELL_CSV = "terminal-C.csv"
CAP_MUTUAL_CSV = "terminal-Cm.csv"


@dataclass(frozen=True)
class CapacitanceResult:
    """Palace Electrostatic 电容结果 (M3: 真实解析两张矩阵)。

    Fields:
        postpro_dir: 被读取的 postpro 目录。
        available:   是否至少读到一张电容矩阵。
        units:       矩阵元素单位 (恒 ``"fF"``; CSV 原文是 F, 解析时 ×1e15)。
        terminals:   行/列绑定 (index↔group↔attribute), 来自 ``terminal_bindings``。
        maxwell:     Maxwell 矩阵 C (terminal-C.csv): 对称, +对角 -非对角, fF。
        mutual:      互/集总矩阵 Cm (terminal-Cm.csv): 全正, fF。
        csv_paths:   实际读到的 CSV ``{kind: Path}`` (kind ∈ maxwell/mutual)。
        raw:         CSV 原文 ``{kind: text}`` (取证回退)。
        source:      矩阵**来源** — ``"solved"`` (Palace 实解) / ``"file"``
                     (``capacitance_from_file`` 注入) / ``"inline"``
                     (``capacitance_from_inline`` 注入)。溯源必须能区分实解与注入
                     (spec §11 R4), 否则注入就成了新的 silent-wrong-result 面。
        sha256:      ``source == "file"`` 时是**文件内容**的 SHA-256 (hexdigest);
                     其余情形 ``None``。
    """

    postpro_dir: Path
    available: bool = False
    units: str = "fF"
    terminals: tuple[TerminalBinding, ...] = ()
    maxwell: list[list[float]] = field(default_factory=list)
    mutual: list[list[float]] = field(default_factory=list)
    csv_paths: dict[str, Path] = field(default_factory=dict)
    raw: dict[str, str] = field(default_factory=dict)
    source: str = "solved"
    sha256: str | None = None

    @property
    def matrix(self) -> list[list[float]]:
        """主电容矩阵 (Maxwell C 优先, 否则 mutual, 否则空)。向后兼容别名。"""
        return self.maxwell or self.mutual


def _parse_palace_cap_csv(text: str) -> list[list[float]]:
    """把一张 Palace 电容 CSV 文本解析成 N×N 稠密矩阵 (单位 F→fF)。

    格式 (用表头校验列数, 不依赖具体单位标签):
        header: ``i, X[i][1] (F), X[i][2] (F), ...`` (X = C 或 C_m)
        data:   ``<i>, <v1>, <v2>, ...`` (i 为 1-based 浮点, 须升序; v 带 ± 号)
    校验: ≥1 行数据; 行 i 与序号一致; 每行值列数 == 行数 (方阵)。
    解析失败 → ``DesignDslError``。
    """
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        raise DesignDslError(
            "Palace capacitance CSV needs a header row + >=1 data row.")
    header = [c.strip() for c in lines[0].split(",")]
    n_cols = len(header) - 1  # 第一列是行号 'i'
    if n_cols < 1:
        raise DesignDslError(
            f"Palace capacitance CSV header has no value columns: {lines[0]!r}")

    matrix: list[list[float]] = []
    for row_no, line in enumerate(lines[1:], start=1):
        cells = [c.strip() for c in line.split(",")]
        if len(cells) != len(header):
            raise DesignDslError(
                f"Palace capacitance CSV row {row_no} has {len(cells)} cells "
                f"but the header has {len(header)}: {line!r}")
        try:
            row_index = int(round(float(cells[0])))
            values = [float(c) * _F_TO_FF for c in cells[1:]]
        except ValueError as exc:
            raise DesignDslError(
                f"Palace capacitance CSV row {row_no} has a non-numeric "
                f"value: {line!r}") from exc
        # float() happily accepts 'nan'/'inf'/overflow; a non-finite entry would
        # propagate silently into the inverse-cap / transmon math and into
        # chip.results.yaml. Reject it here (a diverged/partial Palace solve).
        if not all(math.isfinite(v) for v in values):
            raise DesignDslError(
                f"Palace capacitance CSV row {row_no} has a non-finite value "
                f"(nan/inf): {line!r} — the Palace solve likely diverged or is "
                f"incomplete.")
        if row_index != row_no:
            raise DesignDslError(
                f"Palace capacitance CSV rows out of order: expected index "
                f"{row_no}, got {row_index} in {line!r}")
        matrix.append(values)

    if len(matrix) != n_cols:
        raise DesignDslError(
            f"Palace capacitance matrix is not square: {len(matrix)} rows × "
            f"{n_cols} columns.")
    return matrix


def parse_capacitance_matrix(
    postpro_dir: str | os.PathLike[str],
    terminals: Sequence[TerminalBinding] = (),
) -> CapacitanceResult:
    """读取 ``<postpro_dir>`` 下的 Palace 电容矩阵 (terminal-C.csv / terminal-Cm.csv)。

    两张 CSV 都可缺失 (dry-run / 未求解): 缺则跳过, 不报错; 都缺 → ``available=False``。
    存在则解析成 N×N 矩阵 (F→fF)。若给了 ``terminals`` (来自
    ``terminal_bindings``), 额外断言矩阵阶数 == 导体数 (行/列绑定一致性)。

    Raises:
        DesignDslError: CSV 存在但格式非法 / 非方阵 / 阶数与 ``terminals`` 不符。
    """
    base = Path(postpro_dir)
    matrices: dict[str, list[list[float]]] = {"maxwell": [], "mutual": []}
    csv_paths: dict[str, Path] = {}
    raw: dict[str, str] = {}

    for kind, fname in (("maxwell", CAP_MAXWELL_CSV), ("mutual", CAP_MUTUAL_CSV)):
        path = base / fname
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        matrices[kind] = _parse_palace_cap_csv(text)
        csv_paths[kind] = path
        raw[kind] = text

    available = bool(matrices["maxwell"] or matrices["mutual"])

    if available and terminals:
        n = len(terminals)
        for kind, mat in matrices.items():
            if mat and len(mat) != n:
                raise DesignDslError(
                    f"Palace {kind} capacitance matrix is {len(mat)}×{len(mat)} "
                    f"but there are {n} terminals — row/col binding mismatch.")

    return CapacitanceResult(
        postpro_dir=base,
        available=available,
        terminals=tuple(terminals),
        maxwell=matrices["maxwell"],
        mutual=matrices["mutual"],
        csv_paths=csv_paths,
        raw=raw,
        source="solved",
    )


# ---------------------------------------------------------------------------
# P0-C — 从文件 / inline 读电容矩阵 (拼装层的**正常输入方式**, 不是调试旁路)
# ---------------------------------------------------------------------------
#
# tutorial 4.05 的标准入口就是从文件读两份矩阵 (``load_q3d_capacitance_matrix``),
# 所以「注入」是一等公民; 但 ``source``/``sha256`` 必须把注入与实解区分开
# (spec §11 R4)。
#
# 三种输入, 格式按 **内容** 识别 (读头几行), 不看扩展名:
#   1. **Palace CSV** (本仓库自产的 ``terminal-C.csv`` / ``terminal-Cm.csv``) ——
#      复用 ``_parse_palace_cap_csv`` (不重写)。它按「文件是 F」硬换算成 fF, 故此处
#      再按表头自述单位 ``C[i][1] (F)`` 修正; 表头就是 (F) 时修正因子恰为 1.0 且
#      **短路跳过** → 与 ``parse_capacitance_matrix`` 逐位相同。
#   2. **Ansys Q3D ``.txt``** (Q3D "save as type: data table" 导出, 即 4.05 的输入)。
#   3. **inline** ``{"terminals": [...], "maxwell": [[...]]}`` 或直接一个二维列表。
#
# Q3D 格式的实际结论 (读 tutorial 4.05 的 ``Q1_TwoTransmon_CapMatrix.txt`` 得到):
#   * CRLF + **制表符** 分隔; 头部若干 ``key:value`` 行, 其中单位自述在
#     ``C Units:fF, G Units:mSie``; 之后是 ``Capacitance Matrix`` 段 (行、列都带
#     terminal 名, 且 **ground 也是一个 terminal 行**), 再接 ``Conductance Matrix`` 段。
#   * 该样本已是 **Maxwell** 矩阵 (+对角 −非对角) —— Ansys 的 "Maxwell matrix" 导出;
#     但 Q3D 也能导互容 (全正), 故下面显式判定 (``_as_maxwell``), 不假设。
#
# 与参考实现 ``qiskit_metal.analyses.quantization.lumped_capacitive``
# (Apache-2.0) 的对照:
#   * ``readin_q3d_matrix``: 同样 ``split("Capacitance Matrix")`` → 空白分隔表
#     (``sep=r"\s+"``, index_col=0) → 从 ``C Units:(.*?),`` 取单位。**我们逐条照抄这个
#     解析契约** (含「terminal 名不能含空白」这一同样的限制)。
#   * ``load_q3d_capacitance_matrix(path, user_units="fF")``: 用 pint 把文件自述单位
#     换算到用户单位。我们的等价物是 ``_UNIT_TO_FF`` 小表, 且内部单位恒为 **fF**
#     (``CapacitanceResult.units``), 因此 ``units=`` 参数只是**文件没自述单位时的兜底**
#     —— 文件自述优先 (与参考实现同序: 它也是先读 ``Cunits`` 再换算)。
#   * 我们**多做**三件事: (a) 方阵/对称/有限性校验, (b) 互容 vs Maxwell 显式判定,
#     (c) 行标签必须与列标签同序。我们**不读** Conductance 段 (静电电容用不到)。
#   * ⚠ **不复用上游的 Maxwell 转换代码**: ``lumped_oscillator_model``
#     ``_get_capacitance_matrix`` 用 pandas 链式赋值设 Maxwell 对角, 在 pandas ≥2 下
#     **静默失效** (session log 2607280204:76-80 的实测坑)。这里按定义自己算。

# 内部单位恒 fF; 键小写以便大小写不敏感查表。'mF' = **毫**法拉 (Q3D 不导兆法拉)。
_UNIT_TO_FF: dict[str, float] = {
    "f": 1.0e15, "farad": 1.0e15, "farads": 1.0e15,
    "mf": 1.0e12, "uf": 1.0e9, "µf": 1.0e9, "nf": 1.0e6,
    "pf": 1.0e3, "ff": 1.0, "af": 1.0e-3,
}

# 对称性容差: |C[i][j]−C[j][i]| 相对 max|C|。松到不会被 FEM 求解器的正常不对称
# (~1e-6) 误伤, 紧到能抓住行列错位 (那会给 O(1) 的不对称)。
_SYM_RTOL = 1.0e-3
# 符号判定的零阈值 (相对 max|C|): 严格的 0 与浮点噪声都不参与 互容/Maxwell 判定。
_SIGN_RTOL = 1.0e-9

_Q3D_CAP_HEADING = "Capacitance Matrix"
_Q3D_COND_HEADING = "Conductance Matrix"


def _unit_to_ff(unit: str) -> float:
    """单位名 → 「×该因子 = fF」的换算系数; 未知单位 → ``DesignDslError``。"""
    key = str(unit).strip().lower()
    if key not in _UNIT_TO_FF:
        raise DesignDslError(
            f"unknown capacitance unit {unit!r}; supported (case-insensitive): "
            f"{', '.join(sorted(_UNIT_TO_FF))} — note 'mF' means milli-farad")
    return _UNIT_TO_FF[key]


def _scaled(matrix: Sequence[Sequence[float]], scale: float) -> list[list[float]]:
    """整矩阵 ×scale; ``scale == 1.0`` 时只拷贝 (不引入任何浮点运算 → 逐位不变)。"""
    if scale == 1.0:
        return [list(row) for row in matrix]
    return [[v * scale for v in row] for row in matrix]


def _check_matrix(matrix: Sequence[Sequence[float]], label: str) -> None:
    """校验方阵 + 元素有限 + 对称 (相对容差 ``_SYM_RTOL``); 否则 ``DesignDslError``。

    非有限值必须在这里挡住: ``nan <= 0`` 是 False, 会一路静默算出 nan
    (与 ``_parse_palace_cap_csv`` 同一理由)。
    """
    n = len(matrix)
    if n == 0:
        raise DesignDslError(f"{label}: capacitance matrix is empty")
    for i, row in enumerate(matrix, start=1):
        if len(row) != n:
            raise DesignDslError(
                f"{label}: capacitance matrix is not square — row {i} has "
                f"{len(row)} columns but there are {n} rows")
        for j, v in enumerate(row, start=1):
            if not math.isfinite(v):
                raise DesignDslError(
                    f"{label}: capacitance matrix entry [{i}][{j}] is not "
                    f"finite ({v!r}) — a nan/inf would propagate silently "
                    f"through the inverse-cap math (nan <= 0 is False)")

    biggest = max(abs(v) for row in matrix for v in row)
    worst, at = 0.0, (1, 1)
    for i in range(n):
        for j in range(i + 1, n):
            delta = abs(matrix[i][j] - matrix[j][i])
            if delta > worst:
                worst, at = delta, (i + 1, j + 1)
    tol = _SYM_RTOL * biggest
    if worst > tol:
        raise DesignDslError(
            f"{label}: capacitance matrix is not symmetric — max "
            f"|C[i][j]-C[j][i]| = {worst:.6g} at [{at[0]}][{at[1]}] "
            f"(tolerance {tol:.6g} = {_SYM_RTOL:g} x max|C| = {biggest:.6g}); "
            f"row/col order is probably wrong")


def _as_maxwell(matrix: Sequence[Sequence[float]],
                label: str) -> tuple[list[list[float]], list[list[float]] | None]:
    """判定输入是 **Maxwell** 还是 **互容(mutual)** 矩阵, 统一返回 Maxwell。

    本仓库内部一律 Maxwell: **+对角、−非对角、对称、fF** (见
    ``CapacitanceResult`` docstring)。判定显式且可测:

    * 非对角全 ≤0 (含全零/1×1 的无信息情形) 且对角 >0 → **已是 Maxwell**, 原样返回。
    * 非对角全 ≥0 且至少一个 >0 → **互容矩阵** (Cm[i][i]=对地电容,
      Cm[i][j]=导体 i↔j 的物理电容), 按定义换算::

          C[i][i] = Σ_j Cm[i][j]   (含 j==i 的对地项)
          C[i][j] = −Cm[i][j]      (i≠j)

      这正是 ``parse_capacitance_matrix`` 那段注释里 Cm↔C 关系的逆。
    * 非对角**混杂**正负 → ``DesignDslError`` (**拒绝猜**)。

    Returns:
        ``(maxwell, mutual_or_None)`` —— 输入本来就是 Maxwell 时第二项为 None。
    """
    n = len(matrix)
    zero = _SIGN_RTOL * max(abs(v) for row in matrix for v in row)
    pos = [(i + 1, j + 1) for i in range(n) for j in range(n)
           if i != j and matrix[i][j] > zero]
    neg = [(i + 1, j + 1) for i in range(n) for j in range(n)
           if i != j and matrix[i][j] < -zero]

    if pos and neg:
        raise DesignDslError(
            f"{label}: off-diagonal signs are mixed ({len(pos)} positive, e.g. "
            f"{pos[0]}, and {len(neg)} negative, e.g. {neg[0]}) — that is "
            f"neither a Maxwell matrix (+diagonal, -offdiagonal) nor a mutual "
            f"matrix (all positive); refusing to guess the convention")

    if not pos:  # Maxwell (或无非对角信息)
        bad = [i + 1 for i in range(n) if matrix[i][i] <= 0.0]
        if bad:
            raise DesignDslError(
                f"{label}: Maxwell capacitance matrix must have a positive "
                f"diagonal, but row(s) {bad} have C[i][i] <= 0")
        return [list(row) for row in matrix], None

    # 互容 → Maxwell
    bad = [i + 1 for i in range(n) if matrix[i][i] < 0.0]
    if bad:
        raise DesignDslError(
            f"{label}: mutual (all-positive) capacitance matrix must have a "
            f"non-negative diagonal (= capacitance to ground), but row(s) "
            f"{bad} are negative")
    maxwell = [
        [math.fsum(matrix[i]) if i == j else -matrix[i][j] for j in range(n)]
        for i in range(n)
    ]
    return maxwell, [list(row) for row in matrix]


def _bind_terminals(names: Sequence[str] | None, n: int,
                    label: str) -> tuple[TerminalBinding, ...]:
    """终端名 → ``TerminalBinding`` 元组 (``index`` 从 1 起, ``attribute=0``)。

    ``attribute=0`` 是**注入矩阵没有 gmsh attribute** 的诚实表达 (消费端
    ``assemble`` / ``circuit_model`` 只用 ``index`` 与 ``group``)。``names`` 为 None
    时生成 ``t1..tN``。
    """
    if names is None:
        return tuple(TerminalBinding(index=i + 1, group=f"t{i + 1}", attribute=0)
                     for i in range(n))
    labels = [str(x) for x in names]
    if len(labels) != n:
        raise DesignDslError(
            f"{label}: {len(labels)} terminal name(s) given ({labels}) but the "
            f"capacitance matrix is {n}x{n}")
    return tuple(TerminalBinding(index=i + 1, group=name, attribute=0)
                 for i, name in enumerate(labels))


def _q3d_cap_matrix(
    text: str, label: str,
) -> tuple[list[list[float]], list[str], str | None]:
    """解析 Q3D 导出的 ``Capacitance Matrix`` 段 → ``(matrix, names, unit|None)``。

    契约与参考实现 ``readin_q3d_matrix`` 一致: ``split("Capacitance Matrix")`` 后按
    **空白** 分隔 (制表符/空格皆可), 第一行是列名, 之后每行 ``<行名> <N 个数>``,
    单位取自 ``C Units:<u>,``。**terminal 名不得含空白** (上游同限制)。
    """
    parts = text.split(_Q3D_CAP_HEADING)
    if len(parts) != 2:
        raise DesignDslError(
            f"{label}: expected exactly one {_Q3D_CAP_HEADING!r} section in the "
            f"Q3D export, found {len(parts) - 1}")
    body = parts[1].split(_Q3D_COND_HEADING)[0]
    rows = [line.split() for line in body.splitlines() if line.strip()]
    if len(rows) < 2:
        raise DesignDslError(
            f"{label}: the Q3D {_Q3D_CAP_HEADING!r} section has a header row "
            f"but no data rows")

    names = rows[0]
    matrix: list[list[float]] = []
    row_names: list[str] = []
    for cells in rows[1:]:
        if len(cells) != len(names) + 1:
            raise DesignDslError(
                f"{label}: Q3D matrix row {cells[0]!r} has {len(cells) - 1} "
                f"value(s) but the header lists {len(names)} terminal(s) — "
                f"terminal names must not contain whitespace")
        row_names.append(cells[0])
        try:
            matrix.append([float(c) for c in cells[1:]])
        except ValueError as exc:
            raise DesignDslError(
                f"{label}: Q3D matrix row {cells[0]!r} has a non-numeric "
                f"value: {cells[1:]}") from exc

    if row_names != names:
        raise DesignDslError(
            f"{label}: Q3D matrix row labels {row_names} differ from the column "
            f"labels {names} — refusing to guess the row/col correspondence")

    found = re.search(r"C\s*Units\s*:\s*([^,\n\r]+)", text)
    return matrix, names, (found.group(1).strip() if found else None)


def _palace_csv_header(text: str) -> tuple[bool, str | None]:
    """嗅探 Palace 电容 CSV: 返回 ``(是不是, 表头自述单位|None)``。

    识别依据是**内容**: 第一行逗号分隔且首列为 ``i`` (``_parse_palace_cap_csv``
    的表头契约); 单位取自表头里第一个括号, 如 ``C[i][1] (F)`` → ``"F"``。
    """
    first = next((ln for ln in text.splitlines() if ln.strip()), "")
    cells = [c.strip() for c in first.split(",")]
    if len(cells) < 2 or cells[0] != "i":
        return False, None
    found = re.search(r"\(([^)]+)\)", first)
    return True, (found.group(1).strip() if found else None)


def capacitance_from_file(
    path: str | os.PathLike[str],
    *,
    terminals: Sequence[str] | None = None,
    units: str = "fF",
) -> CapacitanceResult:
    """从**文件**读一份电容矩阵 (Palace CSV 或 Q3D ``.txt``) → ``CapacitanceResult``。

    这是 New LOM (tutorial 4.05) 的标准入口的等价物 —— 那里两个 qubit 各自一份
    ``*_CapMatrix.txt``, 靠共享节点名拼装。格式按**内容**识别 (见本节顶部注释)。
    返回值恒为内部约定: **Maxwell 矩阵, +对角 −非对角, 对称, fF**; 文件若是互容
    (全正) 矩阵则按定义换算 (``_as_maxwell``), 原始互容矩阵保留在 ``mutual``。

    Args:
        path:      矩阵文件路径。
        terminals: 可选行/列名 (长度须 == 矩阵阶数)。缺省时用文件表头里的 terminal
                   名 (Q3D 有); 表头也没有 (Palace CSV) 则生成 ``t1..tN``。
        units:     **兜底**单位 —— 只在文件没有自述单位时使用 (实际只对 Q3D 生效)。
                   文件自述 (Q3D 的 ``C Units:``, Palace 表头的 ``(F)``) 一律优先, 与
                   参考实现 ``load_q3d_capacitance_matrix`` 同序。⚠ Palace CSV 的单位
                   契约恒为 **F**, 表头漏写单位标签时也按 F 处理 (不用 ``units`` 兜底,
                   否则缺省 "fF" 会把一张 F 的矩阵静默缩掉 1e15 倍)。

    Raises:
        DesignDslError: 文件不存在/空/格式无法识别; 非方阵/不对称/含 nan-inf;
            非对角符号混杂; ``terminals`` 长度与矩阵不符; 单位名未知。
    """
    src = Path(path)
    if not src.is_file():
        raise DesignDslError(f"capacitance matrix file not found: {src}")
    try:
        data = src.read_bytes()
    except OSError as exc:
        raise DesignDslError(
            f"cannot read capacitance matrix file {src}: {exc}") from exc
    text = data.decode("utf-8", errors="replace")
    if not text.strip():
        raise DesignDslError(f"capacitance matrix file is empty: {src}")

    label = str(src)
    is_palace, palace_unit = _palace_csv_header(text)
    if _Q3D_CAP_HEADING in text:
        matrix, names, file_unit = _q3d_cap_matrix(text, label)
        scale = _unit_to_ff(file_unit or units)
    elif is_palace:
        # 复用既有解析器 (它已按「文件是 F」×1e15), 再按表头自述单位修正 ——
        # 表头是 (F) 时 scale 恰好 == 1.0 → _scaled 短路, 逐位等于实解路径。
        # ⚠ 表头没写单位时兜底 **"F"** (Palace 的格式契约), 不是 units= —— 否则
        # 一张少了标签的 terminal-C.csv 会被 units 缺省值 "fF" 静默缩掉 1e15 倍。
        matrix = _parse_palace_cap_csv(text)
        names = None
        scale = _unit_to_ff(palace_unit or "F") / _F_TO_FF
    else:
        first = next((ln for ln in text.splitlines() if ln.strip()), "")
        raise DesignDslError(
            f"{label}: unrecognised capacitance matrix format. Supported: "
            f"(a) a Palace terminal-C.csv / terminal-Cm.csv (comma separated, "
            f"first header cell 'i'), (b) an Ansys Q3D data-table export "
            f"(contains a {_Q3D_CAP_HEADING!r} section). "
            f"First non-blank line seen: {first[:120]!r}")

    _check_matrix(matrix, label)
    maxwell, mutual = _as_maxwell(matrix, label)
    kind = "mutual" if mutual is not None else "maxwell"
    return CapacitanceResult(
        postpro_dir=src.parent,
        available=True,
        terminals=_bind_terminals(
            terminals if terminals is not None else names, len(maxwell), label),
        maxwell=_scaled(maxwell, scale),
        mutual=_scaled(mutual, scale) if mutual is not None else [],
        csv_paths={kind: src},
        raw={kind: text},
        source="file",
        sha256=hashlib.sha256(data).hexdigest(),
    )


_INLINE_KEYS = ("terminals", "maxwell", "matrix", "units")


def capacitance_from_inline(
    matrix: Mapping[str, Any] | Sequence[Sequence[float]],
    *,
    terminals: Sequence[str] | None = None,
    units: str = "fF",
    label: str = "inline",
) -> CapacitanceResult:
    """从 sidecar 里 **inline** 写的矩阵造 ``CapacitanceResult`` (校验同文件路径)。

    Args:
        matrix: ``{"terminals": [...], "maxwell": [[...], ...]}`` (``"matrix"`` 是
                ``"maxwell"`` 的别名), 或直接一个二维列表。dict 里的 ``terminals``/
                ``units`` 优先于同名参数 (它离数据更近, 且免得静默忽略)。
                互容 (全正) 矩阵同样接受, 按 ``_as_maxwell`` 换算。
        terminals: 可选行/列名; 都没给则生成 ``t1..tN``。
        units:  矩阵元素单位 (``fF``/``pF``/``F``/…), 缺省 ``fF``。
        label:  溯源用的短标签 (进 ``postpro_dir`` 与报错消息)。

    Raises:
        DesignDslError: 非二维数字列表 / dict 缺 ``maxwell`` 或带未知键 / 校验不过。
    """
    if isinstance(matrix, Mapping):
        unknown = sorted(set(matrix) - set(_INLINE_KEYS))
        if unknown:
            raise DesignDslError(
                f"{label}: unknown inline capacitance key(s) {unknown}; "
                f"supported keys are {list(_INLINE_KEYS)} (a mutual/all-positive "
                f"matrix also goes under 'maxwell' — the sign convention is "
                f"detected and converted)")
        rows = matrix.get("maxwell", matrix.get("matrix"))
        if rows is None:
            raise DesignDslError(
                f"{label}: inline capacitance needs a 'maxwell' key holding the "
                f"NxN matrix (got keys {sorted(matrix)})")
        if terminals is None:
            terminals = matrix.get("terminals")
        units = matrix.get("units", units)
    else:
        rows = matrix

    if isinstance(rows, (str, bytes)):
        raise DesignDslError(
            f"{label}: inline capacitance matrix must be a 2-D list of numbers, "
            f"not a string")
    try:
        clean = [[float(v) for v in row] for row in rows]
    except (TypeError, ValueError) as exc:
        raise DesignDslError(
            f"{label}: inline capacitance matrix must be a 2-D list of "
            f"numbers ({exc})") from exc

    _check_matrix(clean, label)
    maxwell, mutual = _as_maxwell(clean, label)
    scale = _unit_to_ff(units)
    return CapacitanceResult(
        postpro_dir=Path(label),
        available=True,
        terminals=_bind_terminals(terminals, len(maxwell), label),
        maxwell=_scaled(maxwell, scale),
        mutual=_scaled(mutual, scale) if mutual is not None else [],
        source="inline",
    )


# ---------------------------------------------------------------------------
# results write-back — OUTPUT-ONLY Layer-3 artifact (chip.results.yaml)
# ---------------------------------------------------------------------------

def _circuit_model_doc(circuit_model: Any) -> dict[str, Any]:
    """把 ``CircuitModelResult`` 转成 YAML-safe dict (M6 ``hamiltonian`` 段)。

    Duck-typed (不 import circuit_model, 避免 circuit_model→palace_adapter 的循环
    导入)。tuple → list 以便 ``yaml.safe_dump`` (它不能表示 Python tuple)。
    """
    return {
        "method": circuit_model.method,
        "validity": circuit_model.validity,
        "units": dict(circuit_model.units),
        "qubits": [
            {
                "name": q.name,
                "islands": list(q.islands),
                "C_sigma_fF": q.C_sigma_fF,
                "E_C_GHz": q.E_C_GHz,
                "E_J_GHz": q.E_J_GHz,
                "f01_GHz": q.f01_GHz,
                "anharmonicity_MHz": q.anharmonicity_MHz,
                "EJ_over_EC": q.EJ_over_EC,
            }
            for q in circuit_model.qubits
        ],
        "couplings": [
            {
                "qubit_a": c.qubit_a,
                "qubit_b": c.qubit_b,
                "C_g_fF": c.C_g_fF,
                "g_MHz": c.g_MHz,
            }
            for c in circuit_model.couplings
        ],
    }


def write_results_sidecar(
    result: CapacitanceResult,
    out_path: str | os.PathLike[str],
    *,
    provenance: Mapping[str, Any] | None = None,
    circuit_model: Any | None = None,
    tier: int | None = None,
) -> Path:
    """把 ``CapacitanceResult`` (+ 可选 M6 电路模型) 写成 OUTPUT-ONLY 的结果产物。

    schema tag ``qiskit-metal/design-results/1`` —— 与 Layer-1 的 ``design-dsl``
    家族不同, **永不** 被 ``parse_geo_meta_sidecar`` 读回; 与 chip.gds/chip.msh/
    chip.json 并排放在 out_dir, ``rm -r out_dir`` 即可重置全部派生态。矩阵行/列由
    ``capacitance.terminals[i]`` (index↔group↔attribute) 自描述。

    完整度 ``tier`` 是 **descending** 阶梯 (数值越小 = 派生越深): ``3`` = 仅电容矩阵
    (M3); ``2`` = 再加集总振子 Hamiltonian (M6, ``circuit_model`` 非空时)。``tier``
    缺省由 ``circuit_model`` 是否存在自动推断 —— 杜绝调用方传错 tier。

    Args:
        result:        已解析的电容结果 (含 terminals 绑定与矩阵)。
        out_path:      产物路径 (建议 ``<out_dir>/chip.results.yaml``)。
        provenance:    可选溯源 dict (solver / 输入 SHA-256 / 时间戳 / label→index)。
        circuit_model: 可选 ``CircuitModelResult`` (M6); 非空则写 ``hamiltonian`` 段
                       且 tier→2。
        tier:          可选显式覆盖; 缺省 = 2 (有 circuit_model) / 3 (无)。
    """
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    if tier is None:
        tier = 2 if circuit_model is not None else 3

    terminals_doc = [
        {
            "index": b.index,
            "group": b.group,
            "attribute": b.attribute,
            **({"terminal": b.terminal} if b.terminal else {}),
        }
        for b in result.terminals
    ]

    capacitance: dict[str, Any] = {
        "available": result.available,
        "units": result.units,
        # R4: 实解 vs 注入必须在产物里分得清 (source/sha256, 见 CapacitanceResult)。
        "source": result.source,
        **({"sha256": result.sha256} if result.sha256 else {}),
        "convention": {
            "maxwell": "Maxwell matrix C: symmetric, +diagonal, -offdiagonal "
                       "(terminal-C.csv)",
            "mutual": "lumped/SPICE matrix Cm: all-positive; Cm[i][i]=cap to "
                      "ground, Cm[i][j]=cap between i and j (terminal-Cm.csv)",
        },
        "terminals": terminals_doc,
    }
    if result.maxwell:
        capacitance["maxwell"] = result.maxwell
    if result.mutual:
        capacitance["mutual"] = result.mutual
    if result.csv_paths:
        capacitance["source_csv"] = {
            kind: Path(p).name for kind, p in sorted(result.csv_paths.items())
        }

    doc: dict[str, Any] = {
        "schema": "qiskit-metal/design-results/1",
        "tier": tier,
        "tier_meaning": "lower = more derived: 3 = capacitance matrix, "
                        "2 = + lumped-oscillator Hamiltonian",
        "capacitance": capacitance,
    }
    if circuit_model is not None:
        doc["hamiltonian"] = _circuit_model_doc(circuit_model)
    if provenance:
        doc["provenance"] = dict(provenance)

    with out.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(doc, fh, sort_keys=False, allow_unicode=True,
                       default_flow_style=False)
    return out
