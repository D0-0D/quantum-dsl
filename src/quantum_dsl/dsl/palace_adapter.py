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
    validate_config(config, physical_attributes) -> None
    write_palace_config(config, path) -> Path
    run_palace(config_path, *, dry_run=True, num_procs=1) -> None
    _to_wsl_path(win_path) -> str
    parse_capacitance_matrix(postpro_dir) -> CapacitanceResult
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
from typing import Any, Iterable, Mapping, Sequence

from .errors import DesignDslError


__all__ = [
    "build_palace_config",
    "validate_config",
    "write_palace_config",
    "run_palace",
    "parse_capacitance_matrix",
    "CapacitanceResult",
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
    conductor_names = _conductor_groups(physical_attributes)
    if len(conductor_names) < 2:
        raise DesignDslError(
            "Electrostatic capacitance needs >=2 conductor terminals "
            f"(found {len(conductor_names)}: {conductor_names or '<none>'}). "
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
    terminals: list[dict] = []
    surface_flux: list[dict] = []
    for index, name in enumerate(conductor_names, start=1):
        attr = _attr_of(physical_attributes, name)
        terminals.append({"Index": index, "Attributes": [attr]})
        surface_flux.append({
            "Index": index,
            "Attributes": [attr],
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
# results (M1 stub; full parser in a later milestone)
# ---------------------------------------------------------------------------

@dataclass
class CapacitanceResult:
    """Palace 电容结果的轻量容器 (M1 stub)。

    M1 只做存在性探测: ``terminal-Cm.csv`` 在则读到 ``raw_csv``, 不解析成矩阵
    (完整 Maxwell 矩阵解析放后续 milestone)。

    Fields:
        postpro_dir: 被探测的 postpro 目录。
        available:   ``terminal-Cm.csv`` 是否存在。
        csv_path:    若存在, 其路径; 否则 None。
        raw_csv:     若存在, 文件原文; 否则 None。
        matrix:      预留的稠密矩阵 (M1 始终空)。
    """

    postpro_dir: Path
    available: bool = False
    csv_path: Path | None = None
    raw_csv: str | None = None
    matrix: list[list[float]] = field(default_factory=list)


def parse_capacitance_matrix(
    postpro_dir: str | os.PathLike[str],
) -> CapacitanceResult:
    """读取 ``<postpro_dir>/terminal-Cm.csv`` (Maxwell 电容矩阵) — M1 stub。

    缺文件不报错: 返回 ``available=False`` 的结果。完整矩阵解析在后续
    milestone 实现, 这里只保证不崩。
    """
    base = Path(postpro_dir)
    csv_path = base / "terminal-Cm.csv"
    if not csv_path.is_file():
        return CapacitanceResult(postpro_dir=base, available=False)
    try:
        raw = csv_path.read_text(encoding="utf-8")
    except OSError:
        return CapacitanceResult(postpro_dir=base, available=False,
                                 csv_path=csv_path)
    return CapacitanceResult(
        postpro_dir=base,
        available=True,
        csv_path=csv_path,
        raw_csv=raw,
    )
