# -*- coding: utf-8 -*-
"""GDS layer-map 解析 — 把 ``(role, layer, component, primitive)`` 映射到
GDSII ``(layer, datatype)``。

层映射默认值 (plan §locked-decisions) + sidecar ``simulation.gmsh.gds`` 块覆盖。
覆盖优先级 (高 → 低):

    by_name  >  by_role  >  by_layer  >  内置 default

- ``by_name``: ``{"<component>::<primitive>": {layer, datatype}}`` (最精确)。
- ``by_role``: ``{"metal"|"ground"|"jj": {layer, datatype}}``。
- ``by_layer``: ``{<int>: {layer, datatype}}`` (.geo layer key → GDS layer)。
- default: 内置 ``GDS_LAYER_MAP`` (metal=1/0, ground=1/0, jj=20/0)。

单一来源真值: 本模块不导入 gmsh / gdstk, 纯查表逻辑, 供 ``gds_adapter`` 复用,
也方便 (TESTS agent) 单测层映射优先级。
"""

from __future__ import annotations

from typing import Any, Optional

from .errors import DesignDslError
from .schema import GDS_SIM_KEYS, GDS_LAYER_MAP_ENTRY_KEYS, GEO_SURFACE_ROLES


__all__ = [
    "GDS_LAYER_MAP",
    "resolve_gds_layer",
    "normalize_layer_map",
]

# 内置默认 (role → (gds_layer, gds_datatype))。plan §locked-decisions:
#   metal=1/0, ground=1/0, jj=20/0
GDS_LAYER_MAP: dict[str, tuple[int, int]] = {
    "metal": (1, 0),
    "ground": (1, 0),
    "jj": (20, 0),
}

# 写入 GDS 的角色 (port/symmetry 是 1D marker, 不进 GDS)。
GDS_EMIT_ROLES = {"metal", "ground", "jj"}


def _coerce_entry(entry: Any, *, where: str,
                  default_datatype: int) -> tuple[int, int]:
    """把一条层映射项 ``{layer, datatype}`` 规范成 ``(int, int)``。

    ``datatype`` 缺省时回落到 ``default_datatype``。校验键集 = GDS_LAYER_MAP_ENTRY_KEYS。
    """
    if not isinstance(entry, dict):
        raise DesignDslError(
            f"gds layer map {where}: expected a mapping with keys "
            f"{sorted(GDS_LAYER_MAP_ENTRY_KEYS)}, got {type(entry).__name__}.")
    unknown = set(entry) - GDS_LAYER_MAP_ENTRY_KEYS
    if unknown:
        raise DesignDslError(
            f"gds layer map {where}: unknown key(s) {sorted(unknown)} "
            f"(allowed: {sorted(GDS_LAYER_MAP_ENTRY_KEYS)}).")
    if "layer" not in entry:
        raise DesignDslError(
            f"gds layer map {where}: missing required 'layer' field.")
    try:
        gds_layer = int(entry["layer"])
        gds_dt = int(entry.get("datatype", default_datatype))
    except (TypeError, ValueError) as exc:
        raise DesignDslError(
            f"gds layer map {where}: 'layer'/'datatype' must be integers "
            f"({entry!r}).") from exc
    return gds_layer, gds_dt


def normalize_layer_map(layer_map: Optional[dict[str, Any]]
                        ) -> dict[str, Any]:
    """校验 sidecar ``gds`` 块结构, 返回原 dict (浅校验, 不改值)。

    只校验顶层键 ∈ ``GDS_SIM_KEYS`` 并对各 ``by_*`` 子表的项做 entry 键检查
    (惰性: 真正取值在 ``resolve_gds_layer``)。``None`` → 空 dict。
    """
    if layer_map is None:
        return {}
    if not isinstance(layer_map, dict):
        raise DesignDslError(
            f"gds layer map must be a mapping, got {type(layer_map).__name__}.")
    unknown = set(layer_map) - GDS_SIM_KEYS
    if unknown:
        raise DesignDslError(
            f"gds block has unknown key(s) {sorted(unknown)} "
            f"(allowed: {sorted(GDS_SIM_KEYS)}).")
    return layer_map


def resolve_gds_layer(role: str, layer: int, component: str, primitive: str,
                      *, layer_map: Optional[dict[str, Any]] = None
                      ) -> tuple[int, int]:
    """解析 ``(role, layer, component, primitive)`` → GDS ``(layer, datatype)``。

    优先级 by_name > by_role > by_layer > 内置 default。
    ``default_datatype`` (sidecar 顶层) 作为各项 datatype 的回落值; 内置默认
    自带 datatype。

    Raises:
        DesignDslError: role 不属于可写 GDS 的角色, 或映射项结构非法。
    """
    if role not in GDS_EMIT_ROLES:
        raise DesignDslError(
            f"gds layer resolution: role {role!r} is not emitted to GDS "
            f"(only {sorted(GDS_EMIT_ROLES)} are).")
    lm = layer_map or {}
    default_datatype = int(lm.get("default_datatype", 0))

    # 1) by_name — "<component>::<primitive>"
    by_name = lm.get("by_name") or {}
    name_key = f"{component}::{primitive}"
    if name_key in by_name:
        return _coerce_entry(by_name[name_key],
                             where=f"by_name[{name_key!r}]",
                             default_datatype=default_datatype)

    # 2) by_role — "metal" / "ground" / "jj"
    by_role = lm.get("by_role") or {}
    if role in by_role:
        return _coerce_entry(by_role[role], where=f"by_role[{role!r}]",
                             default_datatype=default_datatype)

    # 3) by_layer — int .geo layer key (YAML keys may be str)
    by_layer = lm.get("by_layer") or {}
    for key in (layer, str(layer)):
        if key in by_layer:
            return _coerce_entry(by_layer[key], where=f"by_layer[{layer!r}]",
                                 default_datatype=default_datatype)

    # 4) 内置 default
    return GDS_LAYER_MAP[role]
