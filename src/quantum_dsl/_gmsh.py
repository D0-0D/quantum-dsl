# -*- coding: utf-8 -*-
"""进程级 gmsh session 管理 (load_geo / build_gds / build_mesh 共用)。

为什么不是 initialize/finalize 每次一对: ``.geo`` 的 **Macro 定义是进程级
永久状态** —— finalize、``gmsh.clear()``、``gmsh.parser.clear()`` 都清不掉
(2026-08-24 实测), 而 include-guard 变量 (qlib.geo 的 ``_QLIB_INCLUDED``)
会被 finalize/clear 清掉 → 同一宏库二次解析必炸 "Redefinition of function"
(先 ``gmsh.parser.setNumber`` 预置 guard 变量则直接把 flex 扫描器弄挂)。

唯一稳健口径: 整个进程共用一个 session, **从不 finalize/clear**; 每次解析
进一个独立命名的新 model, 用完 remove —— parser 变量随 session 存活,
include guard 按作者本意生效, 模型之间互不污染。

代价: gmsh.option 是全局的 —— 每个调用点必须显式设置自己依赖的选项
(尤其 Mesh.Algorithm3D: HXT 回退会把它改掉, 下一次调用要复位)。
"""

from __future__ import annotations

import contextlib
import itertools
from pathlib import Path

from .errors import QuantumDslError

__all__ = ["geo_model"]

_counter = itertools.count()


@contextlib.contextmanager
def geo_model(path):
    """把 ``.geo`` 解析进一个一次性的新 model, 退出时移除该 model。"""
    path = Path(path)
    if not path.is_file():
        raise QuantumDslError(f"no such file: {path}")
    import gmsh  # 惰性: N0 import 纯度

    if not gmsh.isInitialized():
        gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    name = f"qdsl_{next(_counter)}"
    gmsh.model.add(name)
    gmsh.model.setCurrent(name)
    try:
        try:
            gmsh.merge(str(path))
        except Exception as exc:
            raise QuantumDslError(f"gmsh cannot parse {path}: {exc}") from exc
        gmsh.model.occ.synchronize()
        yield gmsh
    finally:
        gmsh.model.setCurrent(name)
        gmsh.model.remove()
