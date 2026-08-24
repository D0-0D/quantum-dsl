# -*- coding: utf-8 -*-
"""单位解析 (契约 N1)。

约定 (SPEC「从 v3 继承」第 2 条): 仓库内部长度单位是 **µm**, 物理量是 **SI**。

* ``parse_length``   → µm。裸数 (int/float) 就是 µm; 字符串必须带长度单位。
* ``parse_quantity`` → SI。**必须带单位** —— 裸数没有量纲, 一律拒绝
  (例: ``"10nH"`` → 1e-8 H, ``"2GHz"`` → 2e9 Hz)。
"""

from __future__ import annotations

import math
import re

from .errors import QuantumDslError

__all__ = ["parse_length", "parse_quantity"]

_NUM = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
_LENGTH_RE = re.compile(rf"({_NUM})\s*([a-zµ]+)")
_QUANTITY_RE = re.compile(rf"({_NUM})\s*([A-Za-zµΩ]+)")

_UM_PER_UNIT = {"m": 1e6, "cm": 1e4, "mm": 1e3, "um": 1.0, "µm": 1.0, "nm": 1e-3}

# 量纲单位 (最长后缀优先匹配: "GHz" 得先撞上 "Hz" 而不是 "H")。
_SI_UNITS = ("Hz", "Ohm", "H", "F")
_SI_PREFIX = {"": 1.0, "f": 1e-15, "p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6,
              "m": 1e-3, "k": 1e3, "M": 1e6, "G": 1e9, "T": 1e12}


def parse_length(value) -> float:
    """长度 → **µm**。裸数 = µm; 字符串须带单位 (m/cm/mm/um/µm/nm)。"""
    # bool 是 int 的子类, 必须先挡 (True == 1 不是长度)。
    if isinstance(value, bool):
        raise QuantumDslError(f"parse_length: not a length: {value!r}")
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            raise QuantumDslError(f"parse_length: not finite: {value!r}")
        return float(value)
    if not isinstance(value, str):
        raise QuantumDslError(f"parse_length: not a length: {value!r}")
    m = _LENGTH_RE.fullmatch(value.strip())
    if not m or m.group(2) not in _UM_PER_UNIT:
        raise QuantumDslError(
            f"parse_length: cannot parse {value!r} — expected e.g. '5um', "
            f"'0.5mm' (units: {', '.join(_UM_PER_UNIT)})")
    return float(m.group(1)) * _UM_PER_UNIT[m.group(2)]


def parse_quantity(value) -> float:
    """带单位的物理量 → **SI** (H/F/Hz/Ohm + SI 词头)。裸数没有量纲 → 拒绝。"""
    if not isinstance(value, str):
        raise QuantumDslError(
            f"parse_quantity: needs a unit-suffixed string like '10nH', "
            f"got {value!r} — a bare number has no dimension")
    m = _QUANTITY_RE.fullmatch(value.strip())
    if m:
        number, suffix = float(m.group(1)), m.group(2)
        for unit in _SI_UNITS:
            if suffix.endswith(unit):
                prefix = suffix[: -len(unit)]
                if prefix in _SI_PREFIX:
                    result = number * _SI_PREFIX[prefix]
                    if math.isfinite(result):
                        return result
                break
    raise QuantumDslError(
        f"parse_quantity: cannot parse {value!r} — expected e.g. '10nH', "
        f"'3fF', '2GHz' (units: {', '.join(_SI_UNITS)}; SI prefixes f..T)")
