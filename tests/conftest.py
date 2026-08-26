# -*- coding: utf-8 -*-
"""测试共享常量与 live 闸门。

布局:
* ``examples/`` —— 可运行的例子 (two_pads / sung 论文器件 / qlib 宏库), 同时是
  测试输入, 所以永远与代码同步;
* ``tests/fixtures/`` —— 只放 Palace 0.16 的 verbatim 输出样本 (不是例子)。

golden 的三种来源, 都与实现无关 (出处见各测试 docstring, 索引见 SPEC.md):
* 闭式可手验 (Schur 3×3、SQUID flux 甜点、λ/4 LC、E_C=e²/2C、χ 微扰式、CPW 自洽集);
* 同一物理输入上的实测值 (two_pads C 矩阵 = 零厚度片配方 2026-08-24 实测,
  docs/physics.md「网格与收敛」) —— 物理回归锚, 不是 API 兼容锚;
* Palace 0.16 的 verbatim CSV 输出。
历史教训 (2026-08-24): N10 曾直接钉 qiskit-metal 参考实现的输出, 把
"Z0/λ_g 不含 Lk、ε_eff 与 C 不自洽" 这些已知错误锚成了需求 —— 已翻案为
自洽物理集。golden 不锚参考实现, 只锚物理与闭式。
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
EXAMPLES = ROOT / "examples"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

TWO_PADS_META = EXAMPLES / "two_pads.meta.yaml"
BLOCKS_META = EXAMPLES / "two_pads_blocks.meta.yaml"
SUNG_META = EXAMPLES / "sung_2021_device.meta.yaml"

# two_pads 的实测 Maxwell 矩阵 (fF) — live 回归锚 (契约 N7)。
# 配方 = v4 产品路径: 零厚度金属片 imprint 进衬底/真空界面, µm 网格 +
# Model.L0=1e-6, mesh 40/4 µm, order 2, 接地盒 (Palace 0.16, 2026-08-24 实测;
# 见 docs/physics.md「网格与收敛」)。
# 历史: v3 的 2 µm 板挖空配方给 [[24.7288,-1.976],[-1.976,24.7293]] —— 板厚
# 工件偏置 ~1%, 不是物理更优。
LIVE_MAXWELL_GOLDEN = [[24.5324, -1.9472], [-1.9472, 24.5353]]

# 电路模型的纯数学输入 (契约 N8; golden 由它 + 10 nH 闭式导出, 与 Palace 无关,
# 数值无需跟随 LIVE_MAXWELL_GOLDEN 变动)。
N8_MAXWELL = [[24.73, -1.98], [-1.98, 24.72]]

live = pytest.mark.skipif(
    not os.environ.get("QDSL_RUN_PALACE"),
    reason="live Palace solve — enable with QDSL_RUN_PALACE=1")

# sung 整片 order-2 是重解 (18.5M 未知量, 峰值内存 ~154 G, 小时级),
# 不挂在快速 live 闸下; 需要 64C+/384G 机 (远端接入见 tools/palace_remote.sh)。
live_sung = pytest.mark.skipif(
    not os.environ.get("QDSL_RUN_PALACE_SUNG"),
    reason="sung paper-validation solve — enable with QDSL_RUN_PALACE_SUNG=1")
