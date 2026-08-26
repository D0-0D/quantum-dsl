# -*- coding: utf-8 -*-
"""前端: 单位 (N1)、.geo 加载 (N2)、meta.yaml 加载 (N3)、参数化 cell (N12)。"""
from __future__ import annotations

import math

import pytest

from conftest import EXAMPLES, TWO_PADS_META


# ---------------------------------------------------------------- N1 单位
def test_parse_length_to_um():
    """契约 N1: 长度 → µm。裸数 = µm; 字符串须带长度单位; 垃圾一律 raise。"""
    from quantum_dsl import QuantumDslError, parse_length
    assert parse_length(5) == 5.0
    assert parse_length("5um") == 5.0
    assert parse_length("0.5mm") == 500.0
    assert parse_length("250nm") == pytest.approx(0.25)
    assert parse_length("1cm") == 10000.0
    assert parse_length("0.001m") == 1000.0
    for bad in ("abc", "5parsec", "", None, True, [1]):
        with pytest.raises(QuantumDslError):
            parse_length(bad)


def test_parse_quantity_to_si_requires_unit():
    """契约 N1: 物理量 → SI, **必须带单位** (裸数没有量纲)。"""
    from quantum_dsl import QuantumDslError, parse_quantity
    assert parse_quantity("10nH") == pytest.approx(1e-8)
    assert parse_quantity("3fF") == pytest.approx(3e-15)
    assert parse_quantity("2GHz") == pytest.approx(2e9)
    with pytest.raises(QuantumDslError):
        parse_quantity("10")


# ---------------------------------------------------------------- N2 .geo
def test_load_geo_two_pads():
    """契约 N2: 四段 Physical 名解析 + µm 包围盒。"""
    from quantum_dsl import load_geo
    geo = load_geo(EXAMPLES / "two_pads.geo")
    assert {p.name for p in geo.physicals} == {"metal::1::A::pad", "metal::1::B::pad"}
    pad_a = next(p for p in geo.physicals if p.component == "A")
    assert (pad_a.role, pad_a.layer, pad_a.primitive) == ("metal", 1, "pad")
    assert geo.bbox_um == pytest.approx((-120.0, -40.0, 120.0, 40.0))


def test_load_geo_rejects_malformed_physical_name(tmp_path):
    """契约 N2: 不合 role::layer::component::primitive 约定的名字 raise。"""
    from quantum_dsl import QuantumDslError, load_geo
    bad = tmp_path / "bad.geo"
    bad.write_text(
        'SetFactory("OpenCASCADE");\n'
        'r = news; Rectangle(r) = {0, 0, 0, 10, 10};\n'
        'Physical Surface("pad_without_role_segments") = { r };\n',
        encoding="utf-8")
    with pytest.raises(QuantumDslError):
        load_geo(bad)


# ---------------------------------------------------------------- N3 meta
def test_load_meta_two_pads():
    """契约 N3: 扁平词汇逐字段; circuit_model 的结参数加载时解析成 SI。"""
    from quantum_dsl import load_meta
    meta = load_meta(TWO_PADS_META)
    assert meta.geo_path == EXAMPLES / "two_pads.geo"
    assert meta.materials["substrate"]["eps_r"] == pytest.approx(11.45)
    assert meta.materials["substrate"]["thickness_um"] == pytest.approx(100)
    assert meta.airbox["side_um"] == pytest.approx(80)
    assert meta.mesh["max_size_um"] == pytest.approx(40)
    assert meta.solver == {"type": "electrostatic", "order": 2}
    assert meta.gds["by_role"]["metal"]["layer"] == 1
    qubits = meta.circuit_model["qubits"]
    assert [q["name"] for q in qubits] == ["A", "B"]
    assert qubits[0]["island"] == "A"
    assert qubits[0]["L_J"] == pytest.approx(1e-8)      # "10nH" → 亨利


def test_load_meta_rejects_unknown_key_and_wrong_schema(tmp_path):
    """契约 N3: 未知顶层键 (typo) 与错 schema 都不静默。"""
    from quantum_dsl import QuantumDslError, load_meta
    bad = tmp_path / "bad.meta.yaml"
    bad.write_text("schema: quantum-dsl/meta/1\ngeo: x.geo\ntypo_key: 1\n",
                   encoding="utf-8")
    with pytest.raises(QuantumDslError):
        load_meta(bad)
    bad.write_text("schema: qiskit-metal/design-dsl/3\ngeo: x.geo\n",
                   encoding="utf-8")
    with pytest.raises(QuantumDslError):
        load_meta(bad)


# ---------------------------------------------------------------- N12 cells
def test_rounded_polygon_area():
    """契约 N12: 100×100 方 + r=10 圆角 → 面积 10000 − (4−π)·r² (采样内接, 容 1%)。"""
    from quantum_dsl import rounded_polygon
    pts = rounded_polygon([(0, 0), (100, 0), (100, 100), (0, 100)], radius_um=10.0)
    assert len(pts) > 8            # 角上有采样点, 不再是 4 顶点
    area = 0.5 * abs(sum(x1 * y2 - x2 * y1
                         for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1])))
    assert area == pytest.approx(10000.0 - (4.0 - math.pi) * 100.0, rel=0.01)


def test_emit_geo_roundtrip(tmp_path):
    """契约 N12: emit 的 .geo 必须能被 load_geo 回读 (物理名契约闭环)。"""
    from quantum_dsl import emit_geo, load_geo
    text = emit_geo([{"component": "Q1", "layer": 1, "role": "metal",
                      "points": [(0, 0), (100, 0), (100, 100), (0, 100)],
                      "corner_radius_um": 10.0}])
    assert 'Physical Surface("metal::1::Q1::' in text
    p = tmp_path / "cells.geo"
    p.write_text(text, encoding="utf-8")
    (phys,) = load_geo(p).physicals
    assert (phys.component, phys.role) == ("Q1", "metal")
