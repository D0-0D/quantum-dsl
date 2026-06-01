# -*- coding: utf-8 -*-
"""生成 DSL v3 + Gmsh 演示 PDF (16:9 landscape)。

输出:
    examples/dsl/.note/presentation/dslv3_gmsh_presentation.pdf

设计原则:
- PDF 放在屏幕右侧, 左侧给编辑器 / 终端。所以 PDF 主要承载:
    * 流程图 / 模块图 / stage 表
    * schema / 命名约定 / 字典查找表
    * 小段引用片段 (3-5 行); 大段代码留给编辑器
- 演讲者读 speaker_guide.md, 不要把指示词放进 PDF 本身
"""

from __future__ import annotations

import warnings
import textwrap
from pathlib import Path

import matplotlib
matplotlib.use("Agg")

import matplotlib.font_manager as fm
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages


# ---------------------------------------------------------------------------
# 中文字体 (跨平台, 与用户全局偏好一致)
# ---------------------------------------------------------------------------
def set_chinese_font() -> None:
    candidates = [
        "SimHei", "Microsoft YaHei",
        "WenQuanYi Micro Hei", "WenQuanYi Zen Hei",
        "Noto Sans CJK SC", "Noto Sans CJK JP",
        "Source Han Sans CN", "Source Han Sans SC",
        "PingFang SC", "Heiti SC", "STHeiti",
        "Droid Sans Fallback",
    ]
    available = {f.name for f in fm.fontManager.ttflist}
    found = [f for f in candidates if f in available]
    plt.rcParams["font.sans-serif"] = found + ["DejaVu Sans"]
    # 让 family="monospace" 渲染 ASCII + CJK。matplotlib 的 family
    # 列表回退在某些版本下不会按 glyph 跨字体, 所以这里挑一个
    # 自带 ASCII + CJK 的真正等宽字体作为 *唯一* 主选; 之后才是
    # 仅 ASCII 的 Consolas 等。MS Gothic / Sarasa Mono SC / Noto
    # Sans Mono CJK 都符合, Windows 一般至少有 MS Gothic。
    mono_cjk_candidates = [
        "Sarasa Mono SC", "Noto Sans Mono CJK SC",
        "Source Han Mono SC", "MS Gothic",
    ]
    mono_cjk = [f for f in mono_cjk_candidates if f in available]
    fallback_mono = [f for f in ("Consolas", "DejaVu Sans Mono",
                                 "Courier New") if f in available]
    plt.rcParams["font.monospace"] = (mono_cjk + fallback_mono + found
                                       + ["DejaVu Sans"])
    plt.rcParams["axes.unicode_minus"] = False
    warnings.filterwarnings(
        "ignore", message="Glyph .* missing from current font")


set_chinese_font()


# ---------------------------------------------------------------------------
# 调色板 (低对比, 适合投影)
# ---------------------------------------------------------------------------
BG = "#FBFAF5"             # 米黄
FG = "#1F2933"             # 接近黑
ACCENT = "#1F4E79"         # 深蓝 标题色
ACCENT2 = "#A93226"        # 深红, 强调
SOFT_BLUE = "#D5E1EE"
SOFT_GREEN = "#D8E6CB"
SOFT_ORANGE = "#F4DCC2"
SOFT_PURPLE = "#E4D8E9"
SOFT_GREY = "#E6E6E6"
MONO_BG = "#F0EEE6"


# ---------------------------------------------------------------------------
# Slide 基础: figure / 标题区 / 内容区
# ---------------------------------------------------------------------------
def new_slide(title: str, subtitle: str | None = None):
    """开一张 16:9 幻灯片, 返回 (fig, ax)。坐标系 [0, 100] x [0, 100]。"""
    fig = plt.figure(figsize=(13.33, 7.5))
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.set_axis_off()
    # 顶部色条
    ax.add_patch(mpatches.Rectangle((0, 92), 100, 0.6,
                                    color=ACCENT, lw=0))
    # 标题
    ax.text(4, 95, title, fontsize=22, color=ACCENT, weight="bold",
            va="center")
    if subtitle:
        ax.text(4, 89, subtitle, fontsize=13, color=FG, alpha=0.75,
                va="center", style="italic")
    return fig, ax


def add_bullets(ax, x, y, bullets, *, fontsize=13, line_spacing=4.0,
                bullet_char="•", text_color=FG, bold_first_word=False):
    """从 (x, y) 向下写子弹列表。返回最后一行 y。"""
    for line in bullets:
        if line.startswith("# "):  # 子标题
            ax.text(x, y, line[2:], fontsize=fontsize + 1, color=ACCENT,
                    weight="bold", va="top")
            y -= line_spacing
            continue
        if line == "":
            y -= line_spacing * 0.6
            continue
        ax.text(x, y, f"{bullet_char}", fontsize=fontsize, color=ACCENT2,
                va="top", weight="bold")
        ax.text(x + 1.5, y, line, fontsize=fontsize, color=text_color,
                va="top")
        y -= line_spacing
    return y


def add_code(ax, x, y, lines, *, width=92, fontsize=11, lh=2.6,
             face=MONO_BG):
    """从 (x, y) 起绘制一段等宽代码 block, 返回新 y。"""
    n = len(lines)
    h = lh * n + 1.6
    ax.add_patch(mpatches.FancyBboxPatch(
        (x - 0.5, y - h), width, h, boxstyle="round,pad=0.4,rounding_size=0.6",
        facecolor=face, edgecolor="#CFCFCF", lw=0.6))
    for i, line in enumerate(lines):
        ax.text(x + 0.5, y - 1.2 - i * lh, line, fontsize=fontsize,
                color=FG, va="top", family="monospace")
    return y - h - 1.0


def _visual_len(text: str) -> float:
    """Approximate display width; CJK glyphs are visually wider than ASCII."""
    return sum(1.0 if ord(ch) > 127 else 0.55 for ch in text)


def _wrap_visual(text: str, max_visual: float) -> list[str]:
    if not text or _visual_len(text) <= max_visual:
        return [text]

    # Prefer breaking at natural separators so code-like labels stay readable.
    chunks = textwrap.wrap(
        text,
        width=max(12, int(max_visual / 0.55)),
        break_long_words=False,
        break_on_hyphens=False,
    )
    if len(chunks) > 1:
        return chunks

    lines: list[str] = []
    current = ""
    width = 0.0
    for ch in text:
        ch_width = 1.0 if ord(ch) > 127 else 0.55
        if current and width + ch_width > max_visual:
            lines.append(current)
            current = ch
            width = ch_width
        else:
            current += ch
            width += ch_width
    if current:
        lines.append(current)
    return lines


def add_box(ax, x, y, w, h, title, lines, *,
            fc=SOFT_BLUE, ec=ACCENT, fontsize=11,
            title_fs=12, title_color=ACCENT):
    """带标题的小方块, 用于流程图节点。"""
    ax.add_patch(mpatches.FancyBboxPatch(
        (x, y), w, h, boxstyle="round,pad=0.3,rounding_size=0.5",
        facecolor=fc, edgecolor=ec, lw=1.2))
    max_title = max(8.0, w * 8.0 / title_fs)
    max_body = max(10.0, w * 8.2 / fontsize)
    title_lines = _wrap_visual(title, max_title)
    body_lines = [
        wrapped
        for line in lines
        for wrapped in _wrap_visual(line, max_body)
    ]

    if not body_lines:
        title_step = max(2.0, title_fs * 0.20)
        start_y = y + h / 2 + (len(title_lines) - 1) * title_step / 2
        for i, line in enumerate(title_lines):
            ax.text(x + w / 2, start_y - i * title_step, line,
                    fontsize=title_fs, color=title_color, weight="bold",
                    ha="center", va="center")
        return

    title_step = max(2.0, title_fs * 0.22)
    body_step = max(2.0, fontsize * 0.22)
    required = len(title_lines) * title_step + 1.0 + len(body_lines) * body_step
    available = max(1.0, h - 2.0)
    scale = min(1.0, available / required)
    title_fs_fit = max(7.0, title_fs * scale)
    body_fs_fit = max(7.0, fontsize * scale)
    title_step = max(1.8, title_step * scale)
    body_step = max(1.8, body_step * scale)

    cursor_y = y + h - 1.6
    for line in title_lines:
        ax.text(x + w / 2, cursor_y, line, fontsize=title_fs_fit,
                color=title_color, weight="bold", ha="center", va="top")
        cursor_y -= title_step
    cursor_y -= 0.7
    for line in body_lines:
        ax.text(x + w / 2, cursor_y, line, fontsize=body_fs_fit,
                color=FG, ha="center", va="top")
        cursor_y -= body_step


def add_arrow(ax, x1, y1, x2, y2, *, color=ACCENT, lw=1.8,
              connectionstyle="arc3,rad=0", label=None,
              label_offset=(0, 0)):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle="->", color=color, lw=lw,
                                connectionstyle=connectionstyle,
                                shrinkA=3, shrinkB=3,
                                mutation_scale=12))
    if label:
        ax.text((x1 + x2) / 2 + label_offset[0],
                (y1 + y2) / 2 + label_offset[1],
                label, fontsize=10, color=color, ha="center")


# ===========================================================================
# Slide 1 — Cover
# ===========================================================================
def slide_cover():
    fig = plt.figure(figsize=(13.33, 7.5))
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 100); ax.set_ylim(0, 100); ax.set_axis_off()

    # 装饰条
    ax.add_patch(mpatches.Rectangle((0, 0), 100, 1.5, color=ACCENT, lw=0))
    ax.add_patch(mpatches.Rectangle((0, 98.5), 100, 1.5, color=ACCENT, lw=0))

    ax.text(50, 72, "Qiskit Metal DSL v3", fontsize=42, color=ACCENT,
            weight="bold", ha="center")
    ax.text(50, 64, "Native YAML → QDesign → Gmsh mesh",
            fontsize=22, color=FG, ha="center")

    ax.text(50, 50, "一份 YAML，两条出口", fontsize=18, color=ACCENT2,
            ha="center", weight="bold")

    ax.text(50, 42, "左路: build_design()  →  Metal QDesign  →  GUI / GDS",
            fontsize=14, color=FG, ha="center", family="monospace")
    ax.text(50, 37, "右路: build_mesh()    →  Gmsh .msh   →  Elmer / palace / HFSS",
            fontsize=14, color=FG, ha="center", family="monospace")

    ax.text(50, 22,
            "src/qiskit_metal/toolbox_metal/dsl/   +   examples/dsl/",
            fontsize=12, color=FG, alpha=0.7, ha="center",
            family="monospace")
    ax.text(50, 17, "branch: full_chain",
            fontsize=11, color=FG, alpha=0.6, ha="center", style="italic")
    return fig


# ===========================================================================
# Slide 2 — 目标 / 边界
# ===========================================================================
def slide_goals():
    fig, ax = new_slide("DSL v3 是什么 / 为什么不是 qlibrary 的封装",
                        "“一份 YAML，描述清楚 Hamiltonian / Circuit / Netlist / Geometry / Simulation”")

    add_bullets(ax, 6, 84, [
        "# 目标",
        "用单个 .metal.yaml 文件描述芯片的逻辑+物理设计",
        "不走 qlibrary 的 Python 类 (不写 TransmonPocket(design, ...))",
        "直接生成 primitives + pins，再写进 QDesign 的 qgeometry 表",
        "",
        "# 5 个顶层段 (ROOT_KEYS)",
        "schema  / vars  / hamiltonian  / circuit  / netlist  / geometry  / simulation",
        "前 4 段是“逻辑设计”；geometry 是物理布局；simulation 是 EM 前端元数据",
        "",
        "# 两条出口",
        "build_design()  → Metal QDesign  (GUI / qgeometry / connect_pins)",
        "build_mesh()    → Gmsh .msh + named physical groups (跳过 QDesign)",
    ], fontsize=13, line_spacing=3.6)

    # 右侧亮点框
    ax.add_patch(mpatches.FancyBboxPatch(
        (62, 14), 33, 60, boxstyle="round,pad=0.6,rounding_size=1.0",
        facecolor=SOFT_BLUE, edgecolor=ACCENT, lw=1.2))
    ax.text(78.5, 70, "关键边界", fontsize=14, color=ACCENT,
            weight="bold", ha="center")
    add_bullets(ax, 64, 66, [
        "build_ir(yaml) 是唯一入口",
        "DSL 不实例化 qlibrary 组件",
        "DSL 不依赖 QGmshRenderer",
        "DSL 不依赖 LayerStackHandler",
        "DSL 不依赖 BoundsForPathAndPolyTables",
        "DSL 输出纯 dataclass + shapely",
        "Adapter 层负责 SI 转换",
        "schema 版本号: design-dsl/3",
    ], fontsize=11, line_spacing=3.0, text_color=FG)
    return fig


# ===========================================================================
# Slide 3 — 模块布局
# ===========================================================================
def slide_module_layout():
    fig, ax = new_slide("src/qiskit_metal/toolbox_metal/dsl/  —  模块结构",
                        "Builder / IR / Schema / Parsers / Templates  +  Gmsh adapter")

    # 左半: DSL 核心
    add_box(ax, 4, 50, 44, 38, "DSL 核心 (黑盒不依赖 gmsh)", [], fc=SOFT_GREEN)
    add_bullets(ax, 6, 86, [
        "schema.py        ROOT_KEYS / CURRENT_SCHEMA 等常量",
        "ir.py            PrimitiveIR / PinIR / ComponentIR / DesignIR",
        "builder.py       build_ir (L393-488) / build_design (L584)",
        "expression.py    walk_substitute (L111) / eval (L69)",
        "_helpers.py      UniqueKeyYamlLoader (L20-51) + deep_merge",
        "geometry_ops.py  shapely 操作 (union/buffer/difference...)",
        "parsers/geometry.py    _parse_components (L704-810)",
        "parsers/circuit.py     _derive (L61) / _validate (L118)",
        "parsers/simulation.py  _parse_simulation (L89)",
        "component_templates.py  expand_template (L25-134)",
        "template_registry.py    内置 / 用户模板表",
    ], fontsize=11, line_spacing=2.85)

    # 右半: gmsh adapter
    add_box(ax, 52, 50, 44, 38, "Gmsh adapter (build_mesh)", [], fc=SOFT_ORANGE)
    add_bullets(ax, 54, 86, [
        "gmsh_adapter.py    build_mesh (L355-467) 编排",
        "_gmsh_geometry.py  Stage A render_* (L178-294)",
        "                   GeomTracker (L44-150) / endcap (L379)",
        "_gmsh_layers.py    grounds (L29) / cut (L240) / fragment (L178)",
        "_gmsh_mesh.py      define_size_fields (L110-168)",
        "                   generate (L171) / write (L180-200)",
        "_gmsh_physical.py  assign_physical_groups (L166-230)",
        "",
        "依赖白名单 (硬约束):",
        "  本包 + parsing.parse_value + gmsh_utils 的纯函数",
        "  禁止 import: QGmshRenderer / designs.* / qlibrary.*",
    ], fontsize=11, line_spacing=2.85)

    # 底部 examples 行
    add_box(ax, 4, 4, 92, 36 - 4, "examples/dsl/", [], fc=SOFT_PURPLE)
    add_bullets(ax, 6, 38, [
        "chain_2q_native.metal.yaml   完整 demo (Q1+Q2+bus, $extend, simulation.gmsh)",
        "transmon_pocket_2q.metal.yaml  type: transmon_pocket 模板",
        "native_2q_minimal.metal.yaml   最小可运行示例",
        "run_chain_demo.py            build_design 烟囱测试",
        "run_chain_gmsh_demo.py       build_mesh 烟囱测试 + --gui 选项",
        "gmsh_mesh_demo.ipynb         端到端 notebook (build_mesh → meshio → Elmer SIF)",
    ], fontsize=11, line_spacing=2.85)
    return fig


# ===========================================================================
# Slide 4 — 总体工作流 (workflow diagram)
# ===========================================================================
def slide_workflow():
    fig, ax = new_slide("Drawing process workflow  —  YAML → IR → 两条出口",
                        "build_ir / build_design / build_mesh 的数据流")

    # === 顶部输入 ===
    add_box(ax, 39, 78.5, 22, 10, "chain_2q_native.metal.yaml",
            ["schema / vars / hamiltonian", "circuit / netlist /",
             "geometry / simulation"],
            fc=SOFT_PURPLE, title_fs=11, fontsize=9)

    # 第二层: yaml.load + 预处理
    add_box(ax, 12, 67, 22, 9, "1. yaml.load   builder.py:245",
            ["UniqueKeyYamlLoader", "_helpers.py:20-51"],
            fc=SOFT_GREY, title_fs=10, fontsize=9)
    add_box(ax, 39, 67, 22, 9, "2. _expand_includes  builder.py:278",
            ["$include 递归 + cycle", "deep_merge overrides"],
            fc=SOFT_GREY, title_fs=10, fontsize=9)
    add_box(ax, 66, 67, 22, 9, "3. $extend / $for  builder.py:308-366",
            ["_resolve_template / _expand_node", "walk_substitute → ${...}"],
            fc=SOFT_GREY, title_fs=10, fontsize=9)

    add_arrow(ax, 50, 78.5, 23, 76)
    add_arrow(ax, 50, 78.5, 50, 76)
    add_arrow(ax, 50, 78.5, 77, 76)

    # 第三层: 解析三段
    add_box(ax, 4, 50, 28, 11, "4. _parse_components  parsers/geometry.py:704",
            ["expand_component_template (L25)",
             "_primitive_from_spec (L237) → shapely",
             "_pin_from_spec (L345) → PinIR"],
            fc=SOFT_GREEN, title_fs=10, fontsize=9)
    add_box(ax, 36, 50, 28, 11, "5. _derive  parsers/circuit.py:61",
            ["bounds + path lengths + pin middles",
             "_validate_netlist_endpoints (L118)",
             "拆 \"Q1.bus\" → {component, pin}"],
            fc=SOFT_GREEN, title_fs=10, fontsize=9)
    add_box(ax, 68, 50, 28, 11, "6. _parse_simulation  simulation.py:89",
            ["layer_stack / airbox / ports",
             "symmetry / mesh / output",
             "schema 硬约束 (M1)"],
            fc=SOFT_GREEN, title_fs=10, fontsize=9)

    add_arrow(ax, 23, 67, 18, 61)
    add_arrow(ax, 50, 67, 50, 61)
    add_arrow(ax, 77, 67, 82, 61)

    # DesignIR 节点
    add_box(ax, 30, 34, 40, 10.5, "DesignIR  ir.py:74-101  (纯 dataclass)",
            ["vars / hamiltonian / circuit / netlist",
             "design / components[ComponentIR] / derived / simulation"],
            fc="#FCE9C8", ec=ACCENT2, title_fs=12, fontsize=10)
    add_arrow(ax, 18, 50, 40, 44)
    add_arrow(ax, 50, 50, 50, 44)
    add_arrow(ax, 82, 50, 60, 44)

    # 两条出口
    add_box(ax, 6, 12, 38, 16, "build_design + export_ir_to_metal  builder.py:512-592",
            ["每个 ComponentIR → NativeComponent (L138)",
             "  • design.qgeometry.add_qgeometry(...)",
             "  • component.add_pin(points, width, gap)",
             "design.connect_pins(...) → design.net_info",
             "结果 = 普通 Metal QDesign (GUI / GDS / EPR)"],
            fc=SOFT_BLUE, title_fs=11, fontsize=10)
    add_box(ax, 56, 12, 38, 16, "build_mesh / gmsh_adapter  gmsh_adapter.py:355-467",
            ["IR → SI → OCC PlaneSurface → extrude",
             "ground + vacuum + cut + fragment",
             "addPhysicalGroup (命名约定)",
             "mesh.generate(3) → gmsh.write(.msh)",
             "结果 = .msh + named physical groups"],
            fc=SOFT_ORANGE, title_fs=11, fontsize=10)

    add_arrow(ax, 40, 34, 25, 28)
    add_arrow(ax, 60, 34, 75, 28)

    # 底部下游
    ax.text(25, 6.5, "→ MetalGUI · QGDSRenderer · QAnsysRenderer",
            fontsize=10, color=FG, ha="center", style="italic")
    ax.text(75, 6.5, "→ Elmer / palace / HFSS  (EM 求解器读 .msh)",
            fontsize=10, color=FG, ha="center", style="italic")

    return fig


# ===========================================================================
# Slide 5 — YAML schema 顶层
# ===========================================================================
def slide_schema():
    fig, ax = new_slide("YAML 顶层结构  —  ROOT_KEYS",
                        "schema 版本号开头, 每段独立校验")

    add_code(ax, 4, 86, [
        "schema: qiskit-metal/design-dsl/3",
        "",
        "vars:          # 全局变量, 供 ${} 引用",
        "  qx: 1.2mm",
        "  trace_w: 12um",
        "",
        "hamiltonian:   # 子系统 / 耦合 (元数据, 不求解)",
        "  subsystems: {Q1: {model: transmon, EJ: 18GHz, C: 65fF}}",
        "  couplings: [{from: Q1, to: Q2, g: 12MHz}]",
        "",
        "circuit:       # 电路对象参数, geometry 可引用",
        "  Q1: {type: transmon, C: ${c_q}, pad_width: 420um}",
        "  bus: {width: 12um, gap: 7um}",
        "",
        "netlist:       # 拓扑连接, derived 计算 path/pin/middle",
        "  connections: [{from: Q1.bus, to: bus.start}]",
        "",
        "geometry:      # 物理布局 (design / templates / components)",
        "  design: {class: DesignPlanar, chip: {size: 6mm x 6mm}}",
        "  templates: {transmon_pad_pair: {...}}",
        "  components: {Q1: {$extend: transmon_pad_pair, ...}}",
        "",
        "simulation:    # EM 前端元数据 (可选)",
        "  gmsh: {layer_stack: ..., airbox: ..., mesh: ..., ports: ...}",
    ], width=56, fontsize=10, lh=2.4)

    # 右侧 cheatsheet
    ax.add_patch(mpatches.FancyBboxPatch(
        (63, 16), 32, 70, boxstyle="round,pad=0.6,rounding_size=1.0",
        facecolor=SOFT_BLUE, edgecolor=ACCENT, lw=1.0))
    ax.text(79, 82, "schema 约束", fontsize=13, color=ACCENT, weight="bold",
            ha="center")
    add_bullets(ax, 64.5, 78, [
        "unique key (重复直接 raise)",
        "未知顶层 key → DesignDslError",
        "${var}  /  ${vars.qx}  /  ${circuit.Q1.C}",
        "${qx} - ${bus_attach}  (允许 +-*/)",
        "12um / 0.5mm / 1.2e-5m  → mm float",
        "$extend: 模板名  (deep_merge)",
        "$for: [{name: q1}, {name: q2}]",
        "$include: ../shared.yaml",
        "",
        "geometry 二级 keys:",
        "  design / templates /",
        "  components / transforms",
        "",
        "simulation.gmsh 二级 keys:",
        "  layer_stack / airbox / ports",
        "  symmetry / mesh / output",
    ], fontsize=10, line_spacing=2.8, text_color=FG)
    return fig


# ===========================================================================
# Slide 6 — 模板 / 表达式 / 单位
# ===========================================================================
def slide_expression():
    fig, ax = new_slide("表达式引擎  —  ${...} + $extend + $for",
                        "expression.py + builder._expand_node + _walk_substitute")

    add_bullets(ax, 6, 84, [
        "# ${...} 解析  (expression.py)",
        "walk_substitute (L111-123)  递归 dict/list, 对每个 str 调 substitute_string",
        "substitute_string (L91-108)  整字段是 ${...} 时返回原对象类型, 否则字符串化",
        "evaluate_expression (L69-79)  简单 path → resolve_path; 复杂 → _compile (lru_cache 512)",
        "_eval_ast (L140-195)  受限 AST: Constant / Name / Attribute / Subscript / +-*/",
        "_replace_unit_literals (L126-137)  正则把 '12um' 替换成 repr(parse_value('12um'))",
        "",
        "# 单位 (mm float)  — qiskit_metal.toolbox_metal.parsing.parse_value",
        "12um → 0.012   0.5mm → 0.5   1.2e-5m → 12.0   18GHz → 18e9",
        "下游 (gmsh adapter _normalize_options) 入口处 × 1e-3 转 SI",
        "",
        "# $extend  /  $for  (builder.py:308-366)",
        "_resolve_template (L308-326)  $extend 递归 deep_merge, cycle → raise",
        "_expand_node (L329-356)  $for 迭代变量 → 多份 component",
        "_expand_list (L359-366)  对列表平铺所有展开结果",
    ], fontsize=11, line_spacing=3.0)

    # 底部对比框: 字符串 vs 数值
    ax.add_patch(mpatches.FancyBboxPatch(
        (6, 6), 88, 22, boxstyle="round,pad=0.5,rounding_size=0.7",
        facecolor=SOFT_GREEN, edgecolor=ACCENT, lw=1.0))
    ax.text(50, 25, "preserve_type 行为  (expression.substitute_string)",
            fontsize=12, color=ACCENT, weight="bold", ha="center")
    ax.text(15, 21, "整个字段 = ${...}  →  原对象类型", fontsize=11,
            color=FG, ha="left")
    ax.text(15, 17.5, '  width: "${circuit.bus.width}"   →  float 0.012',
            fontsize=10, color=FG, family="monospace")
    ax.text(15, 14, "字段含其它字符  →  字符串化", fontsize=11, color=FG)
    ax.text(15, 10.5,
            '  points: [["-${qx} + ${bus_attach}", 0mm], ...]   →  "-1.2 + 0.34"',
            fontsize=10, color=FG, family="monospace")
    return fig


# ===========================================================================
# Slide 7 — IR dataclasses
# ===========================================================================
def slide_ir():
    fig, ax = new_slide("IR  —  ir.py 4 个 dataclass",
                        "纯数据, 不依赖 gmsh / qiskit / matplotlib")

    add_code(ax, 4, 86, [
        "# ir.py",
        "",
        "@dataclass                          # L21-37",
        "class PrimitiveIR:",
        "    component: str; name: str; kind: str; shape: str",
        "    geometry: Any                  # shapely Polygon / LineString (mm)",
        "    subtract: bool = False          # 减法体 (CPW gap / pocket etch)",
        "    helper: bool = False            # 不出现在 mesh / qgeometry",
        "    layer: int = 1; chip: str = 'main'",
        "    width: Optional[float] = None   # path / junction",
        "    fillet: Optional[float] = None  # path 圆角",
        "    options: dict",
        "",
        "@dataclass                          # L40-56",
        "class PinIR:",
        "    component: str; name: str",
        "    points: list[list[float]]       # 2 端点 (mm)",
        "    width: float; gap: Optional[float] = None",
        "    chip: str = 'main'; input_as_norm: bool = False",
        "",
        "@dataclass                          # L59-71",
        "class ComponentIR:",
        "    name: str",
        "    primitives: list[PrimitiveIR]; pins: list[PinIR]",
        "    metadata / type / options / template / inherited",
        "",
        "@dataclass                          # L74-101",
        "class DesignIR:",
        "    schema; vars; hamiltonian; circuit; netlist; design",
        "    components: list[ComponentIR]",
        "    geometry; derived; simulation",
        "    to_metadata() → dict           # 给 design.metadata['dsl_chain']",
    ], width=56, fontsize=10, lh=2.2)

    # 右侧: derived 字典内容
    ax.add_patch(mpatches.FancyBboxPatch(
        (63, 12), 32, 74, boxstyle="round,pad=0.6,rounding_size=1.0",
        facecolor=SOFT_ORANGE, edgecolor=ACCENT, lw=1.0))
    ax.text(79, 82, "DesignIR.derived 关键字段", fontsize=13, color=ACCENT,
            weight="bold", ha="center")
    add_bullets(ax, 64.5, 78, [
        "components[name].bounds  (xmin, ymin, xmax, ymax)",
        "components[name].center  (重心, mm)",
        "components[name].pins[*].middle",
        "components[name].pins[*].normal",
        "",
        "netlist.connections:",
        "  [{from: {component, pin},",
        "    to:   {component, pin},",
        "    net_id: 0}]",
        "  (由 _validate_netlist_endpoints",
        "   把 'Q1.bus' 拆出来)",
        "",
        "Notebook 里能 import:",
        '  ir.derived["components"]["Q1"]',
        '  ir.derived["netlist"]["connections"]',
    ], fontsize=10, line_spacing=2.7, text_color=FG)
    return fig


# ===========================================================================
# Slide 8 — build_design path
# ===========================================================================
def slide_build_design():
    fig, ax = new_slide("build_design()  —  IR → Metal QDesign",
                        "把 IR 写进 design.qgeometry + design.connect_pins")

    add_bullets(ax, 6, 84, [
        "# 调用栈",
        "build_design(yaml)  →  build_ir + export_ir_to_metal",
        "export_ir_to_metal:  _instantiate_design + _validate_chip_spec",
        "                      for component in ir.components:",
        "                          NativeComponent(design, name, make=False)",
        "                          design.qgeometry.add_qgeometry(kind, ...)",
        "                          component.add_pin(name, points, width, gap)",
        "                      design.connect_pins(c1.id, p1, c2.id, p2)",
        "                      design.metadata['dsl_chain'] = ir.to_metadata()",
        "",
        "# NativeComponent  (qiskit_metal.qlibrary.core.base.QComponent 的最小子类)",
        "只是个壳, make() 留空; 数据全由 export_ir_to_metal 推进 qgeometry",
        "component_metadata 声明 path/poly/junction 三张表都允许",
        "好处: GUI / GDS / EPR / scanner 这些下游不知道这个 design 是 DSL 出的",
        "",
        "# connect_pins 之后",
        "design.net_info  会出现一行 net_id → {comp1.pin1, comp2.pin2}",
        "ir.derived.netlist.connections[*].net_id  写回 (int) 供后续追踪",
    ], fontsize=11, line_spacing=3.3)
    return fig


# ===========================================================================
# Slide 9 — Gmsh primer
# ===========================================================================
def slide_gmsh_primer():
    fig, ax = new_slide("Gmsh 入门  —  关键词翻译表",
                        "Gmsh 是开源的 3D 有限元 mesh 生成器, 不是 EM 求解器")

    # 左半: 三层概念
    ax.add_patch(mpatches.FancyBboxPatch(
        (4, 50), 44, 36, boxstyle="round,pad=0.5,rounding_size=0.8",
        facecolor=SOFT_GREEN, edgecolor=ACCENT, lw=1.0))
    ax.text(26, 84, "Gmsh 的三层概念", fontsize=14, color=ACCENT,
            weight="bold", ha="center")
    add_bullets(ax, 5.5, 80, [
        "OCC kernel  (OpenCASCADE)",
        "  布尔操作: addBox / cut / extrude / fragment",
        "  几何实体: Point / Curve / Surface / Volume",
        "  dimtag = (维度, tag) e.g. (3, 7) 第 7 号体",
        "",
        "Physical groups",
        "  给一组 (dim, tag) 取个名字 = 求解器看到的 region",
        "  跨多个 dimtag 也行, 求解器按名字加 BC / 材料",
        "",
        "Mesh",
        "  size field (Distance + Threshold) 控密度",
        "  generate(3) 跑 Delaunay → tet / triangle / line",
        "  gmsh.write('x.msh') 文件 = mesh + physical groups",
    ], fontsize=10, line_spacing=2.85)

    # 右半: gmsh 选项 / 工具链
    ax.add_patch(mpatches.FancyBboxPatch(
        (52, 50), 44, 36, boxstyle="round,pad=0.5,rounding_size=0.8",
        facecolor=SOFT_BLUE, edgecolor=ACCENT, lw=1.0))
    ax.text(74, 84, "Gmsh 在我们项目里的角色", fontsize=14, color=ACCENT,
            weight="bold", ha="center")
    add_bullets(ax, 53.5, 80, [
        "前端 (我们写) — 把 DSL → OCC API 调用",
        "  pip install gmsh  (含 OCC + FLTK)",
        "  import gmsh; gmsh.initialize(); gmsh.model.occ.addBox(...)",
        "",
        "Gmsh 自身只生成几何 + mesh",
        "不算 Maxwell / 不算 capacitance",
        "我们只用它做几何 + mesh 输出",
        "",
        "下游求解器认 .msh:",
        "  Elmer  (开源, SIF 脚本读 physical group)",
        "  palace (AWS, JSON config)",
        "  HFSS / Comsol (商业, 也读 .msh)",
        "",
        "GUI: gmsh xxx.msh  或  show_gui=True",
    ], fontsize=10, line_spacing=2.85)

    # 底部一行命名对照表
    add_code(ax, 4, 44, [
        "# Gmsh    ↔  我们项目里的对应",
        "model       ↔  一个 design (gmsh.model.add('dsl_design'))",
        "volume      ↔  primitive (poly/path 拉伸出来的) / ground / substrate / vacuum",
        "surface     ↔  junction 平面 / 体的边界面 / 端口面 / 对称面",
        "physical_group  ↔  result.physical_groups[name] = (dim, [tags])",
        "size field  ↔  options.mesh.{max_size, min_size, conductor_refine}",
        "msh4 format ↔  .msh 文件 v4.1 (二进制 / ASCII 都行)",
    ], width=92, fontsize=10, lh=2.6, face=MONO_BG)
    return fig


# ===========================================================================
# Slide 10 — Gmsh 在 EM 工具链里的位置
# ===========================================================================
def slide_em_chain():
    fig, ax = new_slide("Gmsh 在 EM 仿真链里的位置",
                        "我们做的是 geometry+mesh front-end, 不替代求解器")

    # 一行流程
    steps = [
        (2,  "YAML\nDSL v3",    SOFT_PURPLE),
        (15, "DesignIR",        SOFT_GREEN),
        (28, "OCC geometry\n(gmsh.model.occ)", SOFT_ORANGE),
        (43, "3D mesh\n(.msh)", SOFT_ORANGE),
        (58, "physical groups\n(named regions)", SOFT_BLUE),
        (73, "EM solver\nElmer / palace / HFSS", SOFT_GREY),
        (88, "S 参数 / Cmat /\nEPR / 模式", "#FCE9C8"),
    ]
    for (x, label, color) in steps:
        ax.add_patch(mpatches.FancyBboxPatch(
            (x, 55), 11, 14, boxstyle="round,pad=0.3,rounding_size=0.5",
            facecolor=color, edgecolor=ACCENT, lw=1.0))
        for i, line in enumerate(label.split("\n")):
            ax.text(x + 5.5, 64 - i * 3.3, line, fontsize=10, color=FG,
                    ha="center", va="center")

    for i in range(len(steps) - 1):
        x1 = steps[i][0] + 11
        x2 = steps[i + 1][0]
        add_arrow(ax, x1, 62, x2, 62)

    # 注释
    add_bullets(ax, 6, 48, [
        "前 4 步: 我们的代码 (DSL package + gmsh adapter); 中间产物纯数据, 可重现",
        "physical groups: 命名约定固定 (下面专门一页讲); 求解器按名字 attach 材料 / BC",
        "EM solver 完全可换 — 同一份 .msh 可以喂 Elmer 验真, 再切到 HFSS 跑大尺寸",
    ], fontsize=12, line_spacing=4.0)

    # 我们覆盖的范围
    ax.add_patch(mpatches.Rectangle((2, 53), 70, 18, fill=False,
                                    edgecolor=ACCENT2, lw=2.5, linestyle="--"))
    ax.text(37, 75, "DSL v3 + gmsh_adapter 覆盖范围",
            fontsize=12, color=ACCENT2, weight="bold", ha="center")

    # 下方 inset: 我们什么时候不用 gmsh
    ax.add_patch(mpatches.FancyBboxPatch(
        (6, 12), 88, 20, boxstyle="round,pad=0.5,rounding_size=0.7",
        facecolor=MONO_BG, edgecolor="#CFCFCF", lw=0.6))
    ax.text(50, 29, "什么时候不需要 build_mesh", fontsize=12, color=ACCENT,
            weight="bold", ha="center")
    add_bullets(ax, 10, 25.5, [
        "只想看 GUI / 导 GDS / 做 EPR  → 用 build_design 即可 (左路)",
        "想跑 capacitance Q3D / 商业 HFSS solver 自带 mesher  → 用 build_design + QHFSSRenderer",
        "需要 native mesh 控制 + 自动 physical group 命名 + 不依赖商业工具  → 用 build_mesh (右路)",
    ], fontsize=11, line_spacing=3.3)
    return fig


# ===========================================================================
# Slide 11 — gmsh_adapter 模块分工
# ===========================================================================
def slide_adapter_modules():
    fig, ax = new_slide("gmsh_adapter 模块分工",
                        "build_mesh 编排, 5 个私有模块各管一段")

    add_box(ax, 32, 73, 36, 12, "build_mesh(source, output_path, options)",
            ["唯一对外入口 (gmsh_adapter.py)",
             "源 = YAML / DesignIR; 输出 = GmshMeshResult"],
            fc=SOFT_ORANGE, title_fs=13)

    # 五个子模块横排
    cols = [
        (4,  "_gmsh_geometry.py", ["Stage A/B/B'", "render_* L178-294",
                                    "GeomTracker L44-150",
                                    "endcap L379-431"]),
        (23, "_gmsh_layers.py",   ["Stage C/C'/D/E",
                                    "render_grounds L29",
                                    "apply_cuts L240",
                                    "fragment L178"]),
        (42, "_gmsh_mesh.py",     ["Stage G", "define_size_fields",
                                    "L110-168",
                                    "generate / write L171-200"]),
        (61, "_gmsh_physical.py", ["Stage F",
                                    "assign_physical_groups",
                                    "L166-230",
                                    "NAMING L44-56"]),
        (80, "parsers/simulation", ["build_ir 时跑",
                                     "_parse_simulation L89",
                                     "_parse_gmsh_sim",
                                     "(kwarg 走同路径)"]),
    ]
    for (x, name, lines) in cols:
        add_box(ax, x, 28, 16, 38, name, lines, fc=SOFT_GREEN,
                title_fs=11, fontsize=10)

    # 用一条清晰的 bus 表示 build_mesh 编排 5 个模块, 避免扇形箭头互相穿插。
    bus_y = 68.8
    centers = [x + 8 for x, _, _ in cols]
    ax.plot([50, 50], [73, bus_y], color=ACCENT, lw=1.8)
    ax.plot([centers[0], centers[-1]], [bus_y, bus_y], color=ACCENT, lw=1.8)
    for cx in centers:
        add_arrow(ax, cx, bus_y, cx, 66, color=ACCENT)

    # 底部硬约束
    ax.add_patch(mpatches.FancyBboxPatch(
        (4, 4), 92, 18, boxstyle="round,pad=0.5,rounding_size=0.7",
        facecolor=MONO_BG, edgecolor="#CFCFCF", lw=0.6))
    ax.text(50, 19, "依赖白名单 / 黑名单 (硬约束)", fontsize=12,
            color=ACCENT, weight="bold", ha="center")
    add_bullets(ax, 7, 15.5, [
        "允许 import: 本包  +  qiskit_metal.toolbox_metal.parsing.parse_value",
        "                 +  qiskit_metal.renderers.renderer_gmsh.gmsh_utils 的纯函数",
        "禁止 import: qiskit_metal.designs.*  /  qiskit_metal.qlibrary.*  /  LayerStackHandler  /  QGmshRenderer",
        "好处: 一份 YAML 在没装 PySide6 / 没 GUI 的环境也能跑出 .msh (build_design 才需要 QDesign 全栈)",
    ], fontsize=10, line_spacing=2.9)
    return fig


# ===========================================================================
# Slide 12 — build_mesh 7-stage 流水线 (大图)
# ===========================================================================
def slide_stages_pipeline():
    fig, ax = new_slide("build_mesh 7-stage 流水线",
                        "每个 stage 都是 OCC 调用; tracker 累计 tag, fragment 完成后重映射")

    # 顶部输入
    add_box(ax, 39, 84.5, 22, 4, "DesignIR + options", [],
            fc="#FCE9C8", title_fs=11)
    add_arrow(ax, 50, 84.5, 26, 82)
    add_arrow(ax, 50, 84.5, 74, 82)

    stages = [
        (4,   68, "A.  render_polygon / path / junction  (_gmsh_geometry.py:178-294)",
                  ["shapely → OCC: addPoint + addLine + addCurveLoop + addPlaneSurface",
                   "occ.extrude(dz=layer.thickness)   → 3D 体 (poly/path)",
                   "junction = 2D surface (不 extrude, 平移到 layer 中心)"],
                  SOFT_BLUE),
        (4,   50, "B.  GeomTracker.add_*  (_gmsh_geometry.py:44-150)",
                  ["polys / paths / juncs / subtracts dict 按 (comp, prim) 二元组存 tag",
                   "remap() 在 fragment 后批量改 tag (L117-150)"],
                  SOFT_BLUE),
        (4,   32, "B'. _stage_endcaps_and_ports  (gmsh_adapter.py:286-332)",
                  ["compute_open_pins L351 (从 derived.netlist 推断)",
                   "render_open_pin_endcap L379-431 (addBox + _PortBoxSpec)",
                   "→ tracker.endcap_subtracts / port_box_specs / port_metadata"],
                  SOFT_GREEN),
        (4,   14, "C.  render_layer_grounds + render_vacuum_box  (_gmsh_layers.py:29-75)",
                  ["每层 layer_stack 出一个 addBox → tracker.layer_ground",
                   "vacuum: bbox + top/bottom airbox → tracker.vacuum_box"],
                  SOFT_GREEN),

        (52,  68, "C'. apply_symmetry_cuts  (_gmsh_layers.py:77-177)  — 可选",
                  ["对 x0 / y0 / z0 三种 plane 各画半空间 box 当 cut tool",
                   "顺序硬约束: 必须在 D / E 之前 (切面与 fragment 共面缝合相关)"],
                  SOFT_ORANGE),
        (52,  50, "D.  apply_cuts  (_gmsh_layers.py:240-284)",
                  ["occ.cut(ground, subtracts + endcaps) → 新 ground tag",
                   "subtracts.clear() / endcap_subtracts.clear()"],
                  SOFT_ORANGE),
        (52,  32, "D'. resolve_port_surfaces  (_gmsh_geometry.py:503-556)",
                  ["从 ground 边界面里筛端口面 (法向 = +pin_normal)",
                   "_face_is_outer_wall L456-482 — 单一垂直壁  → tracker.ports"],
                  SOFT_PURPLE),
        (52,  14, "E → F → G  (_gmsh_layers/_gmsh_physical/_gmsh_mesh)",
                  ["E  fragment_everything (layers:178-237) → tracker.remap",
                   "F  assign_physical_groups (physical:166-230) → 命名表",
                   "G  define_size_fields (mesh:110) → generate(3) → write .msh"],
                  "#FCE9C8"),
    ]
    for (x, y, title, lines, color) in stages:
        add_box(ax, x, y, 44, 14, title, lines,
                fc=color, title_fs=10, fontsize=9)

    # 两列内部是直下箭头; C→C' 走中间竖向转接线, 不穿过任何文字。
    for y_top, y_next_top in [(68, 64), (50, 46), (32, 28)]:
        add_arrow(ax, 26, y_top, 26, y_next_top)
        add_arrow(ax, 74, y_top, 74, y_next_top)

    handoff_y = 21
    ax.plot([48, 50], [handoff_y, handoff_y], color=ACCENT2, lw=2.0)
    ax.plot([50, 50], [handoff_y, 75], color=ACCENT2, lw=2.0)
    add_arrow(ax, 50, 75, 52, 75, color=ACCENT2, lw=2.0,
              label="cross to right column", label_offset=(0, 2.2))
    return fig


# ===========================================================================
# Slide 13 — physical group 命名约定
# ===========================================================================
def slide_physical_groups():
    fig, ax = new_slide("Physical group 命名表  —  下游求解器的契约",
                        "PHYSICAL_GROUP_NAMING (_gmsh_physical.py:44-56) + _sanitize (L62-73)")

    headers = ["类型", "命名模板", "dim", "来源"]
    rows = [
        ("metal ground 体",    "gnd_layer{layer}",            "3",
         "tracker.layer_ground (kind=metal)"),
        ("metal ground 外表面", "gnd_layer{layer}_sfs",        "2",
         "getBoundary(layer_ground)"),
        ("dielectric 体",     "substrate_layer{layer}",       "3",
         "tracker.layer_ground (kind=dielectric)"),
        ("component 体",      "{component}_{primitive}",     "3",
         "tracker.polys / tracker.paths"),
        ("component 外表面",   "{component}_{primitive}_sfs", "2",
         "getBoundary(component_volume)"),
        ("Josephson 面",      "{component}_{primitive}_jj",  "2",
         "tracker.juncs"),
        ("真空体",            "vacuum",                       "3",
         "tracker.vacuum_box"),
        ("真空外边界",         "vacuum_outer",                 "2",
         "getBoundary(vacuum_box)"),
        ("lumped port",      "port_{component}_{pin}",      "2",
         "tracker.ports + is_lumped=True"),
        ("ground port",      "port_{component}_{pin}_gnd",  "2",
         "tracker.ports + is_lumped=False"),
        ("symmetry 面",       "symmetry_{plane}",            "2",
         "_collect_symmetry_face_tags"),
    ]

    col_x = [5, 24, 51, 58]
    col_w = [19, 27, 7, 38]
    y = 82
    # header
    ax.add_patch(mpatches.Rectangle((4, y - 1), 92, 3.0, color=ACCENT,
                                    alpha=0.9, lw=0))
    for i, h in enumerate(headers):
        ax.text(col_x[i], y + 0.5, h, fontsize=11, color="white",
                weight="bold", va="center")
    y -= 4
    for j, row in enumerate(rows):
        if j % 2 == 0:
            ax.add_patch(mpatches.Rectangle(
                (4, y - 0.6), 92, 4.8, color=SOFT_GREY, alpha=0.45, lw=0))
        ax.text(col_x[0], y + 1, row[0], fontsize=10, color=FG, va="center")
        ax.text(col_x[1], y + 1, row[1], fontsize=10, color=ACCENT2,
                va="center", family="monospace")
        ax.text(col_x[2], y + 1, row[2], fontsize=10, color=FG,
                va="center", ha="center")
        ax.text(col_x[3], y + 1, row[3], fontsize=10, color=FG, va="center",
                family="monospace")
        y -= 4.8

    # 底部 _sanitize 规则
    ax.add_patch(mpatches.FancyBboxPatch(
        (4, 6), 92, 16, boxstyle="round,pad=0.5,rounding_size=0.7",
        facecolor=MONO_BG, edgecolor="#CFCFCF", lw=0.6))
    ax.text(50, 19, "_sanitize 规则 + 命名硬约束", fontsize=12,
            color=ACCENT, weight="bold", ha="center")
    add_bullets(ax, 7, 15.5, [
        "非 [A-Za-z0-9_] 字符 → '_'      ('Q1.bus.pad_left' → 'Q1_bus_pad_left')",
        "数字开头 → 加前缀 'g_'           ('2um_pad' → 'g_2um_pad')",
        "重名直接 raise ValueError       (例: 两个 component 同名同 primitive)",
        "命名正则 ^[A-Za-z][A-Za-z0-9_]*$  ←  Elmer/palace 期望的标识符语法",
    ], fontsize=10, line_spacing=2.9)
    return fig


# ===========================================================================
# Slide 14 — chain_2q_native 端到端运行结果
# ===========================================================================
def slide_chain_demo():
    fig, ax = new_slide("examples/dsl/run_chain_gmsh_demo.py  —  端到端运行结果",
                        "YAML → build_mesh → 17 个 named physical groups  "
                        "(_DEMO_MESH L44-49, required L102-103)")

    add_code(ax, 4, 86, [
        "$ python examples/dsl/run_chain_gmsh_demo.py --output build/chain_2q.msh",
        "",
        "schema           : qiskit-metal/design-dsl/3",
        "components       : ['Q1', 'Q2', 'bus']",
        "bounding_box (m) : xmin=-0.0018, ymin=-0.00046,",
        "                   xmax=0.0018,  ymax=0.00046",
        "mesh file        : build/chain_2q.msh",
        "mesh size (bytes): 101_768",
        "physical groups  : 17",
        "  - Q1_jj_jj             (dim=2, n_tags=1)",
        "  - Q1_pad_left          (dim=3, n_tags=2)   ← fragment 后切碎成 2 块",
        "  - Q1_pad_left_sfs      (dim=2, n_tags=11)",
        "  - Q1_pad_right + sfs   ...",
        "  - Q2_pad_left  + sfs   ...",
        "  - Q2_pad_right + sfs   ...",
        "  - bus_center_trace     (dim=3, n_tags=1)",
        "  - bus_center_trace_sfs (dim=2, n_tags=8)",
        "  - gnd_layer1           (dim=3, n_tags=1)",
        "  - gnd_layer1_sfs       (dim=2, n_tags=20)",
        "  - substrate_layer3     (dim=3, n_tags=1)",
        "  - vacuum               (dim=3, n_tags=1)",
        "  - vacuum_outer         (dim=2, n_tags=60)",
        "PASS: native DSL chain meshed via gmsh_adapter",
    ], width=60, fontsize=10, lh=2.4)

    # 右侧: 推送给 Elmer 的最小 SIF
    ax.add_patch(mpatches.FancyBboxPatch(
        (67, 14), 28, 72, boxstyle="round,pad=0.5,rounding_size=0.7",
        facecolor=SOFT_BLUE, edgecolor=ACCENT, lw=1.0))
    ax.text(81, 82, "下游消费示例 (Elmer SIF)",
            fontsize=12, color=ACCENT, weight="bold", ha="center")
    add_code(ax, 68, 78, [
        "Body 1",
        "  Target Bodies(1) = $ vacuum",
        "  Material = 1",
        "End",
        "",
        "Body 2",
        "  Target Bodies(1) = $ substrate_layer3",
        "  Material = 2",
        "End",
        "",
        "Boundary Condition 1",
        "  Target Boundaries(1)",
        "    = $ gnd_layer1_sfs",
        "  Potential = 0.0",
        "End",
        "",
        "Material 2",
        "  Relative Permittivity",
        "    = 11.45",
        "End",
    ], width=27, fontsize=9, lh=2.1)
    return fig


# ===========================================================================
# Slide 15 — 单位 / 踩坑落字
# ===========================================================================
def slide_units():
    fig, ax = new_slide("单位与契约  —  踩坑落字",
                        "YAML / IR / build_mesh kwarg = mm float; adapter 入口 × 1e-3 转 SI")

    add_bullets(ax, 6, 84, [
        "# 长度单位 (parse_value 默认 mm)",
        "YAML 写 12um / 0.012mm / 1.2e-5m  → IR 里都是 0.012  (mm float)",
        "build_mesh 的 options 也是 mm float, 与 IR 同语义",
        "adapter _normalize_options (gmsh_adapter.py:194-251)  一次性 ×1e-3 → SI",
        "_layer_stack_to_si (L127-136) / _airbox_to_si (L139-140) 做实际换算",
        "",
        "# mesh kwarg 防呆  _check_mesh_length_mm (L174-191)",
        "  _MESH_LENGTH_MIN_MM = 1e-5    # L170, 10 nm",
        "  _MESH_LENGTH_MAX_MM = 100.0   # L171, 10 cm",
        "options={'mesh': {'max_size': 0.001}}      # 1um, 正确",
        "options={'mesh': {'max_size': 0.000005}}   # 5 nm  → raise ValueError",
        "踩坑历史: 把 SI 米传进 kwarg 再被 × 1e-3 = 5 nm, gmsh.generate 内存爆",
        "",
        "# Windows kernel 安全  (memory: feedback_gmsh_matplotlib_dll_order)",
        "matplotlib 必须先 import + 跑一次 plt.subplots 预热, 再 gmsh.initialize",
        "gmsh wheel 捆绑 freetype / OpenMP / libpng, 抢占 native symbol",
        "os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')  ← notebook 第一格",
    ], fontsize=11, line_spacing=3.0)
    return fig


# ===========================================================================
# Slide 16 — 测试与可信度
# ===========================================================================
def slide_tests():
    fig, ax = new_slide("测试覆盖  —  契约靠这些 assertion 锁定",
                        "tests/test_design_dsl*.py + run_*_demo.py 内联 assert")

    # 左侧: IR 契约
    ax.add_patch(mpatches.FancyBboxPatch(
        (4, 14), 44, 72, boxstyle="round,pad=0.5,rounding_size=0.8",
        facecolor=SOFT_GREEN, edgecolor=ACCENT, lw=1.0))
    ax.text(26, 82, "test_design_dsl.py  (~740 行)",
            fontsize=13, color=ACCENT, weight="bold", ha="center")
    add_bullets(ax, 5.5, 78, [
        "L88  test_build_ir_resolves_circuit_to_geometry",
        "       ${circuit.Q1.pad_width} 真的进 primitive bounds",
        "L101 test_build_design_writes_qgeometry_pins_and_netlist",
        "       IR → Metal QDesign 各表行数 / 数据完整",
        "L142 test_derived_contains_bounds_lengths_pins_and_connections",
        "       derived 字段完整 (bbox / path length / pin middle)",
        "L158 test_overrides_recompute_geometry",
        "       overrides 重算几何, IR 链路 round-trip 不丢",
        "L248 test_polygon_and_junction_primitives",
        "       poly / junction kind 解析正确",
        "L276 test_build_ir_rejects_bad_netlist_endpoint",
        "       netlist 错误引用 → DesignDslError",
        "L606 test_resolved_transforms_are_preserved",
        "       transform 写入 chain metadata, 可追溯",
        "L621 test_template_extend_requires_template_name",
        "       $extend 用未注册名字 → raise",
    ], fontsize=10, line_spacing=2.75)

    # 右侧: Gmsh 契约
    ax.add_patch(mpatches.FancyBboxPatch(
        (52, 14), 44, 72, boxstyle="round,pad=0.5,rounding_size=0.8",
        facecolor=SOFT_ORANGE, edgecolor=ACCENT, lw=1.0))
    ax.text(74, 82, "test_design_dsl_gmsh.py  (~550 行)",
            fontsize=13, color=ACCENT, weight="bold", ha="center")
    add_bullets(ax, 53.5, 78, [
        "L38  test_build_mesh_rejects_unsupported_input_type",
        "       QDesign / 其它对象 → TypeError",
        "L56  test_chain_2q_native_builds_geometry  (M2)",
        "       chain_2q YAML 跑通 build_mesh 全流程",
        "L89  test_simulation_options_si_units",
        "       kwarg / IR 单位转换一致",
        "L100 test_default_layer_stack_used_when_simulation_absent",
        "       不写 simulation 段时走默认 stack",
        "L151-210  layer_stack schema 校验",
        "       thickness=0 / 缺 metal / 缺引用 layer → raise",
        "L299 test_m3_required_physical_groups",
        "       gnd_layer1 / substrate_layer3 / vacuum 必出",
        "L382 test_m4_lumped_port_surface_exists",
        "       lumped port = 单一垂直壁 (len(tags)==1)",
        "L413 test_m4_symmetry_y0_creates_group_and_truncates_model",
        "       y0 切完后 symmetry_y0 group 存在",
    ], fontsize=10, line_spacing=2.75)

    ax.text(50, 7, "tox -e py3.12 -- tests/test_design_dsl_gmsh.py",
            fontsize=11, color=FG, ha="center", family="monospace")
    return fig


# ===========================================================================
# Slide 17 — 回顾 / 下一步
# ===========================================================================
def slide_summary():
    fig, ax = new_slide("总结",
                        "一份 YAML, 三种工具链, 一条命名契约")

    add_bullets(ax, 6, 84, [
        "# 我们造了什么",
        "完整 schema (design-dsl/3): 5 段 YAML, IR 数据类 4 个, 表达式 + 模板引擎",
        "build_design (左路): IR → Metal QDesign  (qgeometry / pins / net_info)",
        "build_mesh   (右路): IR → Gmsh .msh + 17 个 named physical groups",
        "",
        "# 关键设计选择",
        "唯一入口 build_ir; 不实例化 qlibrary, 不依赖 QGmshRenderer / LayerStackHandler",
        "IR 单位 = mm float; adapter 入口统一 × 1e-3 转 SI",
        "physical group 命名是契约, 改名要通知下游求解器 (Elmer / palace)",
        "stage 顺序硬约束: B' endcap → C ground/vacuum → C' symmetry → D cut → E fragment",
        "",
        "# 下一步 / 可拓展点",
        "M5 已完成: lumped port 单顶面收紧, mesh kwarg 防呆, dielectric subtract 警告",
        "M6 候选: 真正接 Elmer / palace 跑 capacitance, 把 C 矩阵 round-trip 回 hamiltonian",
        "其它: ground_bbox: chip_size|auto 开关, port box 跨对称面修正 (nit 4.3)",
    ], fontsize=12, line_spacing=3.6)

    # 底部
    ax.text(50, 6, "End  —  问答 / 现场跑代码",
            fontsize=14, color=ACCENT, weight="bold", ha="center")
    return fig


# ===========================================================================
# 编译 PDF
# ===========================================================================
def main():
    here = Path(__file__).resolve().parent
    out_pdf = here / "dslv3_gmsh_presentation.pdf"

    slides = [
        slide_cover,
        slide_goals,
        slide_module_layout,
        slide_workflow,
        slide_schema,
        slide_expression,
        slide_ir,
        slide_build_design,
        slide_gmsh_primer,
        slide_em_chain,
        slide_adapter_modules,
        slide_stages_pipeline,
        slide_physical_groups,
        slide_chain_demo,
        slide_units,
        slide_tests,
        slide_summary,
    ]

    with PdfPages(out_pdf) as pdf:
        for i, builder in enumerate(slides, start=1):
            fig = builder()
            pdf.savefig(fig, facecolor=BG)
            plt.close(fig)
            print(f"slide {i:>2d}/{len(slides)}  {builder.__name__}")

    print(f"\nwrote {out_pdf}  ({out_pdf.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
