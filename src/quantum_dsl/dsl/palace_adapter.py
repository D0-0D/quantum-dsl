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
    write_results_sidecar(result, out_path, *, provenance=None,
                          circuit_model=None, tier=None) -> Path
"""

from __future__ import annotations

import json
import math
import os
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

    要求至少 **2 个 Terminal** (电容矩阵需≥2 导体), 否则 ``DesignDslError``。
    """
    bindings = terminal_bindings(physical_attributes)
    if len(bindings) < 2:
        names = [b.group for b in bindings]
        raise DesignDslError(
            "Electrostatic capacitance needs >=2 conductor terminals "
            f"(found {len(bindings)}: {names or '<none>'}). "
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
    """

    postpro_dir: Path
    available: bool = False
    units: str = "fF"
    terminals: tuple[TerminalBinding, ...] = ()
    maxwell: list[list[float]] = field(default_factory=list)
    mutual: list[list[float]] = field(default_factory=list)
    csv_paths: dict[str, Path] = field(default_factory=dict)
    raw: dict[str, str] = field(default_factory=dict)

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
