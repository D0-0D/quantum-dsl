# -*- coding: utf-8 -*-
"""native Gmsh ``.geo`` 加载 + 四段 Physical 名解析 (契约 N2)。

作者约定 (SPEC「从 v3 继承」第 1 条): OpenCASCADE、µm、每个语义面挂一个
Physical 名 ``"<role>::<layer>::<component>::<primitive>"``。**component 段 =
电学岛 (net)**, 是电容矩阵/circuit_model/assemble 的绑定键。

解析用 gmsh 本体 (它就是 .geo 的解释器 —— fixtures 里有变量/宏/Include,
文本解析撑不住 bbox); **惰性 import**, ``import quantum_dsl`` 不拉起 gmsh (N0)。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .errors import QuantumDslError

__all__ = ["ROLES", "Physical", "Geo", "parse_physical_name", "load_geo"]

ROLES = frozenset({"metal", "ground", "jj", "substrate", "port", "symmetry"})


@dataclass(frozen=True)
class Physical:
    """一个 Physical 组: ``role::layer::component::primitive`` 的解析结果。"""

    name: str
    role: str
    layer: int
    component: str
    primitive: str


@dataclass(frozen=True)
class Geo:
    """已加载的 ``.geo``: Physical 组 + 模型包围盒 (µm)。"""

    path: Path
    physicals: tuple[Physical, ...]
    bbox_um: tuple[float, float, float, float]  # (xmin, ymin, xmax, ymax)


def parse_physical_name(name: str) -> Physical:
    """``"metal::1::A::pad"`` → :class:`Physical`; 不合约定即 raise。"""
    parts = name.split("::")
    if len(parts) != 4:
        raise QuantumDslError(
            f"Physical name {name!r} is not 'role::layer::component::primitive' "
            f"(got {len(parts)} segment(s))")
    role, layer_s, component, primitive = parts
    if role not in ROLES:
        raise QuantumDslError(
            f"Physical name {name!r}: role {role!r} not in {sorted(ROLES)}")
    try:
        layer = int(layer_s)
    except ValueError:
        raise QuantumDslError(
            f"Physical name {name!r}: layer {layer_s!r} is not an integer") from None
    if not component or not primitive:
        raise QuantumDslError(
            f"Physical name {name!r}: empty component/primitive segment")
    return Physical(name=name, role=role, layer=layer,
                    component=component, primitive=primitive)


def load_geo(path) -> Geo:
    """加载 ``.geo``, 返回 Physical 组与 µm 包围盒。名字不合约定即 raise。"""
    path = Path(path)
    if not path.is_file():
        raise QuantumDslError(f"load_geo: no such file: {path}")
    import gmsh  # 惰性: N0 import 纯度

    owns = not gmsh.isInitialized()
    if owns:
        gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        try:
            gmsh.open(str(path))
        except Exception as exc:
            raise QuantumDslError(f"load_geo: gmsh cannot parse {path}: {exc}") from exc
        physicals = tuple(
            parse_physical_name(gmsh.model.getPhysicalName(dim, tag))
            for dim, tag in gmsh.model.getPhysicalGroups())
        xmin, ymin, _zmin, xmax, ymax, _zmax = gmsh.model.getBoundingBox(-1, -1)
    finally:
        if owns:
            gmsh.finalize()
        else:
            gmsh.clear()
    return Geo(path=path, physicals=physicals, bbox_um=(xmin, ymin, xmax, ymax))
