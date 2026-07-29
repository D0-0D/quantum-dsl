# -*- coding: utf-8 -*-
"""P0-A — ``emit_block_geo``: 子集提取 (派生 ``block_<name>.geo``) + ground pocket 保留.

按 lom-parity-spec §3.0 的 G1, 块几何是一份**落盘的派生 ``.geo``**, 不是运行时的
内存过滤器 —— 所以这些测试全部围绕「写出来的那份文件」转: 先 ``emit_block_geo``,
再用 ``load_geo`` 把产物读回来断言。

覆盖 §4 P0-A 的五条规则:

* **S1** 只保留入选 component 的 ``metal::`` / ``jj::``;
* **S2** ground 的 pocket **不按 component 过滤** —— 被排除 component 留下一个
  有洞、没金属的空真空腔 (§11 R1 的头号 silent-wrong-result; ``keep_all_subtractive
  =False`` 是被量化的反例护栏);
* **S3** ground / substrate 按块窗口 (入选导体 bbox + ``side_buffer_um``) 裁剪;
* **S4** airbox 不用写代码 —— 块几何的 ``compute_chip_bbox_from_geo`` 自动变小;
* **S5** ``port::`` / ``symmetry::`` marker 随 S1 按 component 过滤。

⚠ ``chip_layout.geo`` ``Include "qlib.geo"``, 而 gmsh 的 ``Macro`` 表是**进程全局**
且能活过 ``finalize()``, 它的 include-guard 常量却不能 —— 所以整片 + 两个块变体的
断言全部塞进**一个子进程**里的**一个 session** (与
``test_geo_pipeline._SUNG_BUILD_CHILD`` 同一手法), 否则本文件会毒死后面
``test_geo_topology`` 里那个同样 Include qlib.geo 的测试。其余测试用不含 Include 的
``two_pads.geo`` 与临时合成的小 ``.geo``, 在进程内跑。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

gmsh = pytest.importorskip("gmsh")

from shapely.geometry import Point, Polygon  # noqa: E402

from quantum_dsl.dsl import _gmsh_geo_source as geo  # noqa: E402
from quantum_dsl.dsl.errors import DesignDslError  # noqa: E402
from quantum_dsl.dsl.geo_emit import emit_block_geo  # noqa: E402
from quantum_dsl.dsl.gmsh_adapter import build_mesh_from_geo  # noqa: E402
from quantum_dsl.dsl.parsers.simulation import (  # noqa: E402
    parse_geo_meta_sidecar,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
TWO_PADS = FIXTURES / "two_pads.geo"
TWO_PADS_META = FIXTURES / "two_pads.meta.yaml"
CHIP_LAYOUT = (Path(__file__).resolve().parents[1]
               / "examples" / "dsl" / "geo" / "chip_layout.geo")


@pytest.fixture(autouse=True)
def _clean_gmsh_session():
    """Each test starts and ends with gmsh finalized.

    ``emit_block_geo`` follows ``load_geo``'s契约: it initializes only when the
    caller hasn't and **never** finalizes — so the test owns the teardown.
    """
    if gmsh.isInitialized():
        gmsh.finalize()
    yield
    if gmsh.isInitialized():
        gmsh.finalize()


# --- 合成 fixture 1: 两个 **互不相连** 的 pocket ------------------------------
# chip_layout 的 6 次 GROUND_CUTOUT/GROUND_POCKET 在 .geo 内部已经连通成 **1 个**
# 大孔 (bus gap ∪ paddle pocket ∪ neck gap ∪ qubit pocket), 那个孔同时碰到入选与
# 未入选的金属, 所以 keep_all_subtractive=False 在它上面**什么都填不掉**。护栏要能
# 量化误差就需要一份 pocket 真正互不相连的几何 —— 就是这个。
TWO_POCKETS_GEO = """SetFactory("OpenCASCADE");
a = news; Rectangle(a) = { -100, -40, 0, 80, 80 };
Physical Surface("metal::1::A::pad") = { a };
b = news; Rectangle(b) = { 60, -40, 0, 80, 80 };
Physical Surface("metal::1::B::pad") = { b };
g = news; Rectangle(g) = { -400, -300, 0, 800, 600 };
ha = news; Rectangle(ha) = { -120, -60, 0, 120, 120 };
hb = news; Rectangle(hb) = { 40, -60, 0, 120, 120 };
d() = BooleanDifference{ Surface{ g }; Delete; }
                       { Surface{ ha }; Surface{ hb }; Delete; };
Physical Surface("ground::1::chip::gnd") = { d() };
"""

# --- 合成 fixture 2: 带 port dim-1 marker (规则 S5) ---------------------------
PORTS_GEO = """SetFactory("OpenCASCADE");
a = news; Rectangle(a) = { -50, -50, 0, 100, 100 };
Physical Surface("metal::1::A::pad") = { a };
b = news; Rectangle(b) = { 200, -50, 0, 100, 100 };
Physical Surface("metal::1::B::pad") = { b };
pa1 = newp; Point(pa1) = { -50, -60, 0 };
pa2 = newp; Point(pa2) = {  50, -60, 0 };
la = newl; Line(la) = { pa1, pa2 };
Physical Curve("port::1::A::p1") = { la };
pb1 = newp; Point(pb1) = { 200, -60, 0 };
pb2 = newp; Point(pb2) = { 300, -60, 0 };
lb = newl; Line(lb) = { pb1, pb2 };
Physical Curve("port::1::B::p1") = { lb };
"""


def _names(path: Path) -> list[str]:
    """块 ``.geo`` 里的 physical 名 (按 4 段身份原样重组, 排序)。"""
    return sorted(f"{s.role}::{s.layer}::{s.component}::{s.primitive}"
                  for s in geo.load_geo(path, scale_to_si=False))


def _polygons(path: Path) -> dict[str, list[Polygon]]:
    """``.geo`` 的每个 dim-2 physical group → shapely Polygon 列表 (µm)。"""
    out: dict[str, list[Polygon]] = {}
    for surf in geo.load_geo(path, scale_to_si=False):
        if surf.dim != 2:
            continue
        polys = []
        for ent in surf.entities:
            exterior, holes = geo.surface_outline_um(int(ent), 0.5)
            polys.append(Polygon(exterior, holes))
        out[f"{surf.role}::{surf.layer}::{surf.component}::"
            f"{surf.primitive}"] = polys
    return out


# -----------------------------------------------------------------------------
# S1 — 只保留入选 component 的 metal/jj, 且产物能被 load_geo 读回
# -----------------------------------------------------------------------------

def test_block_keeps_only_selected_metal(tmp_path):
    """``two_pads`` + components=["A"] → 只有 A 的面, B 整个不见; 往返成功。"""
    out = emit_block_geo(TWO_PADS, components=["A"],
                         out_path=tmp_path / "block_A.geo")
    assert out == tmp_path / "block_A.geo" and out.is_file()
    text = out.read_text(encoding="utf-8")
    assert "AUTO-GENERATED" in text and "emit_block_geo" in text
    assert "two_pads.geo" in text and "side_buffer_um" in text

    # 往返: 产物是合法 .geo, physical 名与源逐字相同。
    assert _names(out) == ["metal::1::A::pad"]
    assert "metal::1::B::pad" not in text

    # A 的几何原样搬过来 (80×80 µm @ x[-120,-40])。
    pad = _polygons(out)["metal::1::A::pad"]
    assert len(pad) == 1
    assert pad[0].bounds == pytest.approx((-120.0, -40.0, -40.0, 40.0), abs=1e-6)
    assert pad[0].area == pytest.approx(6400.0, rel=1e-9)


# -----------------------------------------------------------------------------
# S4 — 块 bbox 明显收缩 (airbox 白拿的收益: 一行代码都不用写)
# -----------------------------------------------------------------------------

def test_block_chip_bbox_shrinks(tmp_path):
    """``compute_chip_bbox_from_geo(块)`` 明显小于整片 → airbox 自动跟着小。

    实测 two_pads: 整片 240×80 = 19,200 µm²; 块 A 80×80 = 6,400 µm² (33.3%)。
    """
    full = geo.compute_chip_bbox_from_geo(
        geo.load_geo(TWO_PADS, scale_to_si=False), 0.0)
    out = emit_block_geo(TWO_PADS, components=["A"],
                         out_path=tmp_path / "block_A.geo")
    block = geo.compute_chip_bbox_from_geo(
        geo.load_geo(out, scale_to_si=False), 0.0)

    def _area(b):
        return (b[2] - b[0]) * (b[3] - b[1])

    # rel 1e-6: gmsh's getBoundingBox pads by its geometric tolerance (~2e-7 µm).
    assert _area(block) == pytest.approx(6400.0, rel=1e-6)
    assert _area(full) == pytest.approx(19200.0, rel=1e-6)
    assert _area(block) < 0.5 * _area(full)


# -----------------------------------------------------------------------------
# S5 — port/symmetry marker 随 component 过滤
# -----------------------------------------------------------------------------

def test_block_markers_follow_their_component(tmp_path):
    """``port::1::A::p1`` 随 A 入选; ``port::1::B::p1`` 随 B 被丢掉。"""
    src = tmp_path / "ports.geo"
    src.write_text(PORTS_GEO, encoding="utf-8")
    out = emit_block_geo(src, components=["A"], out_path=tmp_path / "blk.geo")
    assert _names(out) == ["metal::1::A::pad", "port::1::A::p1"]


# -----------------------------------------------------------------------------
# S2 护栏 — keep_all_subtractive=False 把「只碰未入选金属」的 pocket 填实
# -----------------------------------------------------------------------------

def test_keep_all_subtractive_false_fills_excluded_pocket(tmp_path):
    """``False`` 的 ground **面积严格更大 + 孔数严格更少** —— 这就是 S2 的误差源。

    实测 (两个互不相连的 pocket, 各 120×120 µm, side_buffer 200 µm):
        True  → ground 面积 201,600 µm², 2 个孔 (B 的 pocket 仍在, 尽管 B 未入选)
        False → ground 面积 216,000 µm², 1 个孔 (B 的 pocket 被填实)
        差 14,400 µm² = +7.14% 的地金属, 正好等于 B 的 pocket 面积。
    这块金属会长在本该是真空腔的地方, 紧贴 A 的窗口 → A 的对地电容静默偏高
    (§4 P0-A / §11 R1)。live 的电容比值由 §7 的 Palace 护栏测试记录。
    """
    src = tmp_path / "two_pockets.geo"
    src.write_text(TWO_POCKETS_GEO, encoding="utf-8")

    keep = emit_block_geo(src, components=["A"],
                          out_path=tmp_path / "block_A_keep.geo")
    g_keep = _polygons(keep)["ground::1::chip::gnd"]
    drop = emit_block_geo(src, components=["A"],
                          out_path=tmp_path / "block_A_drop.geo",
                          keep_all_subtractive=False)
    g_drop = _polygons(drop)["ground::1::chip::gnd"]

    area_keep = sum(p.area for p in g_keep)
    area_drop = sum(p.area for p in g_drop)
    holes_keep = sum(len(p.interiors) for p in g_keep)
    holes_drop = sum(len(p.interiors) for p in g_drop)

    assert area_keep == pytest.approx(201600.0, rel=1e-6)
    assert area_drop == pytest.approx(216000.0, rel=1e-6)
    assert area_drop > area_keep            # 孔被填 → 地金属更多
    assert (area_drop - area_keep) == pytest.approx(14400.0, rel=1e-6)
    assert holes_keep == 2 and holes_drop == 1
    assert holes_drop < holes_keep

    # S2 正确行为的正面断言: B 未入选, 但 B 焊盘中心仍落在一个孔里 (空真空腔),
    # keep_all_subtractive=False 时它被地金属盖住 —— 这正是 add_endcaps() 语义。
    b_center = Point(100.0, 0.0)
    assert not any(p.covers(b_center) for p in g_keep)
    assert any(p.covers(b_center) for p in g_drop)
    # A 的 pocket 两边都必须在。
    a_center = Point(-60.0, 0.0)
    assert not any(p.covers(a_center) for p in g_keep)
    assert not any(p.covers(a_center) for p in g_drop)


# -----------------------------------------------------------------------------
# G1 byte-identical — 块几何的 physical-group 输出名是整片的逐字子集
# -----------------------------------------------------------------------------

def test_block_group_names_are_byte_identical_subset(tmp_path):
    """块与整片各跑一次完整 mesh: 块的 group 名集合 ⊂ 整片, 入选部分逐字相同。

    载体用 ``two_pockets`` (不含 ``Include``, 借 ``two_pads`` 的 sidecar + 粗网格)
    而不是 ``two_pads``, 因为它**带 ground**: 这样这条测试顺带证明块 ground 上被
    保留的 pocket 能活过 ``extrude`` —— ``_emit_face`` 对带孔的面走
    ``BooleanDifference`` 就是为了这个 (多环 ``Plane Surface`` 的孔会被 OCC extrude
    填实, M5a 的坑), 否则 pocket 会在 mesh 分支里悄悄消失。
    """
    src = tmp_path / "two_pockets.geo"
    src.write_text(TWO_POCKETS_GEO, encoding="utf-8")
    sim_gmsh = parse_geo_meta_sidecar(TWO_PADS_META)["simulation"]["gmsh"]
    sim_gmsh["mesh"] = {"max_size": 60, "min_size": 8}   # 粗: 这里查名字不查精度

    block = emit_block_geo(src, components=["A"],
                           out_path=tmp_path / "block_A.geo")
    assert sum(len(p.interiors) for p in
               _polygons(block)["ground::1::chip::gnd"]) == 2  # 孔真的在
    full_names = set(build_mesh_from_geo(
        src, sim_gmsh, output_path=None, generate=True).physical_groups)
    block_names = set(build_mesh_from_geo(
        block, sim_gmsh, output_path=None, generate=True).physical_groups)

    assert block_names <= full_names, block_names - full_names
    # 逐字相同, 不是「A / ground 的某个新名字」。
    assert {"A_pad_sfs", "gnd_layer1_sfs", "substrate_layer3",
            "vacuum", "vacuum_outer"} <= block_names
    assert "B_pad_sfs" in full_names and "B_pad_sfs" not in block_names


# -----------------------------------------------------------------------------
# 报错路径
# -----------------------------------------------------------------------------

def test_block_geo_rejects_empty_components(tmp_path):
    with pytest.raises(DesignDslError, match="'components' is empty"):
        emit_block_geo(TWO_PADS, components=[],
                       out_path=tmp_path / "nope.geo")
    assert not (tmp_path / "nope.geo").exists()


def test_block_geo_rejects_unknown_component(tmp_path):
    with pytest.raises(DesignDslError) as exc:
        emit_block_geo(TWO_PADS, components=["A", "Zz"],
                       out_path=tmp_path / "nope.geo")
    msg = str(exc.value)
    assert "unknown component" in msg and "Zz" in msg
    assert "['A', 'B']" in msg              # 可用名列表要在消息里
    assert not (tmp_path / "nope.geo").exists()


def test_block_geo_rejects_component_without_metal(tmp_path):
    """选中的 component 只有 ground 面 (没有 metal/jj) → 块是空的, 必须 raise。"""
    src = tmp_path / "two_pockets.geo"
    src.write_text(TWO_POCKETS_GEO, encoding="utf-8")
    with pytest.raises(DesignDslError, match=r"select no metal\|jj surface"):
        emit_block_geo(src, components=["chip"],
                       out_path=tmp_path / "nope.geo")


# -----------------------------------------------------------------------------
# S2 的核心断言 — chip_layout: 被排除 component 的 pocket 必须仍在
# -----------------------------------------------------------------------------

# 子进程 (见模块 docstring 的 ⚠): 整片 + 两个块变体在**一个** gmsh session 里
# 走完, qlib.geo 的 include guard 因此存活, 本文件也不会毒死后面 Include 它的测试。
_CHIP_BLOCK_CHILD = r'''
import json, sys
from pathlib import Path
import gmsh
from shapely.geometry import Point, Polygon
from quantum_dsl.dsl._gmsh_geo_source import (
    compute_chip_bbox_from_geo, load_geo, surface_outline_um)
from quantum_dsl.dsl.geo_emit import emit_block_geo

# 采样点 (µm): bus = 被排除 component BUS 的中心导体上; q1 = 入选 qubit 的焊盘对
# 中心; solid = 远离一切 feature 的实心地。
PROBES = {"bus": (0.0, 0.0), "q1": (-200.0, 180.0), "solid": (-450.0, -150.0)}

src, out = Path(sys.argv[1]), Path(sys.argv[2])
gmsh.initialize()                 # ONE session spans every merge of qlib.geo
gmsh.option.setNumber("General.Terminal", 0)


def probe(path):
    surfs = load_geo(path, scale_to_si=False)
    info = {
        "names": sorted(f"{s.role}::{s.layer}::{s.component}::{s.primitive}"
                        for s in surfs),
        "bbox": list(compute_chip_bbox_from_geo(surfs, 0.0)),
        "bytes": Path(path).stat().st_size,
    }
    ground = []
    for s in surfs:
        if s.role != "ground":
            continue
        for e in s.entities:
            exterior, holes = surface_outline_um(int(e), 0.5)
            ground.append(Polygon(exterior, holes))
    if ground:
        info["ground_area"] = sum(p.area for p in ground)
        info["ground_holes"] = sum(len(p.interiors) for p in ground)
        info["ground_bounds"] = [list(p.bounds) for p in ground]
        info["covers"] = {k: any(p.covers(Point(*xy)) for p in ground)
                          for k, xy in PROBES.items()}
    return info


res = {"full": probe(src)}
res["block"] = probe(emit_block_geo(src, components=["Q1"],
                                    out_path=out / "block_Q1.geo"))
res["block_nofill"] = probe(emit_block_geo(
    src, components=["Q1"], out_path=out / "block_Q1_nofill.geo",
    keep_all_subtractive=False))
gmsh.finalize()
print(json.dumps(res))
'''


def test_chip_layout_block_keeps_excluded_component_pockets(tmp_path):
    """S2 的核心断言: 只选 Q1, 但**被排除的 BUS 的 CPW gap 仍然是个洞**。

    ``chip_layout`` 的 ground 是一张带孔的面 (孔由 ``.geo`` 内的
    ``BooleanDifference`` 挖好), 块几何用 ``ground ∩ window`` 求交派生 —— 窗口内的
    孔**不问归属**全部保留。所以 BUS 虽然不在块里, 它那条 gap 还在: 块里留下一个
    有洞、没金属的空真空腔, 与 qiskit-metal ``add_endcaps()` 同语义。若改成「按
    component 重建孔集合」, ``covers["bus"]`` 会翻成 True —— 地金属长进本该真空的
    地方, 管线全绿而 Q1 对地电容静默偏高 (§11 R1)。

    实测 (side_buffer 200 µm, components=["Q1"]):
        整片 ground 583,304 µm² / 1 个孔 / bbox 1000×680 = 680,000 µm²
        块   ground 225,412 µm² / 0 个孔 / bbox  520×529 = 275,080 µm² (40.5%)
    块的孔数是 0 不是 1: 那个大孔从窗口右边界 (x=60) 破口而出, 求交后成了外轮廓上
    的一个凹口而不是内环 —— 所以 pocket 保留只能用「点是否被金属盖住」来断言,
    不能用孔计数。
    """
    if not CHIP_LAYOUT.is_file():  # pragma: no cover — example is optional
        pytest.skip(f"{CHIP_LAYOUT} not present")

    env = dict(os.environ)
    src_root = Path(geo.__file__).resolve().parents[2]      # .../src
    env["PYTHONPATH"] = os.pathsep.join(
        [str(src_root)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    proc = subprocess.run(
        [sys.executable, "-c", _CHIP_BLOCK_CHILD, str(CHIP_LAYOUT),
         str(tmp_path)],
        capture_output=True, text=True, env=env, timeout=600)
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    res = json.loads(proc.stdout.strip().splitlines()[-1])
    full, block = res["full"], res["block"]

    # S1: 只有 Q1 的 metal/jj + 被裁剪的 ground; BUS / Q2 全部不见。
    assert block["names"] == ["ground::1::chip::gnd", "jj::1::Q1::jj",
                             "metal::1::Q1::pad_bot", "metal::1::Q1::pad_top"]
    # G1: 块的 physical 名是整片的**逐字**子集。
    assert set(block["names"]) <= set(full["names"])

    # S2 核心: BUS 被排除, 但它的 CPW gap 仍是洞 (地金属没长进去)。
    assert full["covers"]["bus"] is False
    assert block["covers"]["bus"] is False, "S2 broken: ground 侵入 BUS 的 gap"
    # 入选 qubit 自己的 pocket 当然也在, 而远处的实心地必须还是金属。
    assert block["covers"]["q1"] is False
    assert block["covers"]["solid"] is True

    # S3: ground 被裁到块窗口 (bbox 明显小于整片) —— S4 的 airbox 白拿收益。
    def _area(b):
        return (b[2] - b[0]) * (b[3] - b[1])

    assert _area(block["bbox"]) == pytest.approx(275080.0, rel=1e-6)
    assert _area(full["bbox"]) == pytest.approx(680000.0, rel=1e-6)
    assert _area(block["bbox"]) < 0.5 * _area(full["bbox"])
    assert block["ground_area"] < full["ground_area"]

    # chip_layout 上 keep_all_subtractive=False **无效**: 它 6 次挖地的结果在
    # .geo 内部已连通成 1 个孔, 那个孔同时碰到 Q1 (入选) 与 BUS (未入选), 填掉它
    # 会把 Q1 也埋进金属 —— 所以护栏的量化在 two_pockets 那份合成几何上做。
    assert res["block_nofill"]["ground_area"] == pytest.approx(
        block["ground_area"], rel=1e-9)
