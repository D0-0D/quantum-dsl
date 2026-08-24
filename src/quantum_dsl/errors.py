# -*- coding: utf-8 -*-
"""quantum_dsl 的唯一异常类型 (契约 N0)。"""

from __future__ import annotations

__all__ = ["QuantumDslError"]


class QuantumDslError(Exception):
    """本包所有可预期失败的统一异常 (输入非法 / 解析失败 / 物理不适定)。"""
