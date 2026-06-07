# -*- coding: utf-8 -*-
"""Pure tests for GDS layer-map resolution precedence (no gmsh / gdstk).

``_gds_layers.resolve_gds_layer`` is pure table logic, so this runs anywhere.
Covers the override precedence (high -> low):

    by_name  >  by_role  >  by_layer  >  built-in default

plus ``normalize_layer_map`` key validation and the emitted-role guard.
"""

from __future__ import annotations

import pytest

from quantum_dsl.dsl.errors import DesignDslError
from quantum_dsl.dsl._gds_layers import (
    GDS_LAYER_MAP,
    resolve_gds_layer,
    normalize_layer_map,
)


# -----------------------------------------------------------------------------
# built-in defaults (no layer_map)
# -----------------------------------------------------------------------------

def test_default_metal():
    assert resolve_gds_layer("metal", 1, "Q1", "pad") == (1, 0)


def test_default_ground():
    assert resolve_gds_layer("ground", 1, "chip", "gnd") == (1, 0)


def test_default_jj():
    assert resolve_gds_layer("jj", 1, "Q1", "jj") == (20, 0)


def test_default_matches_constant():
    assert resolve_gds_layer("metal", 5, "C", "P") == GDS_LAYER_MAP["metal"]


# -----------------------------------------------------------------------------
# precedence: by_name > by_role > by_layer > default
# -----------------------------------------------------------------------------

def _full_map() -> dict:
    # Distinct outputs at every tier so we can prove which one won.
    return {
        "by_name": {"Q1::pad": {"layer": 7, "datatype": 1}},
        "by_role": {"metal": {"layer": 8, "datatype": 2}},
        "by_layer": {1: {"layer": 9, "datatype": 3}},
    }


def test_by_name_wins_over_all():
    out = resolve_gds_layer("metal", 1, "Q1", "pad", layer_map=_full_map())
    assert out == (7, 1)


def test_by_role_wins_when_no_name_match():
    # component/primitive not in by_name -> falls to by_role.
    out = resolve_gds_layer("metal", 1, "Q2", "other", layer_map=_full_map())
    assert out == (8, 2)


def test_by_layer_wins_when_no_name_or_role():
    lm = {"by_layer": {1: {"layer": 9, "datatype": 3}}}
    out = resolve_gds_layer("metal", 1, "Q2", "other", layer_map=lm)
    assert out == (9, 3)


def test_default_when_nothing_matches():
    lm = {"by_layer": {2: {"layer": 9, "datatype": 3}}}  # layer 2, query layer 1
    out = resolve_gds_layer("metal", 1, "Q2", "other", layer_map=lm)
    assert out == (1, 0)  # built-in metal default


# -----------------------------------------------------------------------------
# by_layer accepts both int and str keys (YAML may stringify)
# -----------------------------------------------------------------------------

def test_by_layer_string_key():
    lm = {"by_layer": {"1": {"layer": 9, "datatype": 3}}}
    out = resolve_gds_layer("metal", 1, "Q2", "other", layer_map=lm)
    assert out == (9, 3)


# -----------------------------------------------------------------------------
# default_datatype fallback for entries that omit 'datatype'
# -----------------------------------------------------------------------------

def test_default_datatype_fallback():
    lm = {
        "default_datatype": 5,
        "by_role": {"metal": {"layer": 8}},  # no datatype
    }
    out = resolve_gds_layer("metal", 1, "Q1", "pad", layer_map=lm)
    assert out == (8, 5)


# -----------------------------------------------------------------------------
# role guards + entry validation
# -----------------------------------------------------------------------------

def test_non_emitted_role_raises():
    # port / symmetry markers are not emitted to GDS.
    with pytest.raises(DesignDslError, match="not emitted to GDS"):
        resolve_gds_layer("port", 1, "Q1", "pin0")


def test_entry_missing_layer_raises():
    lm = {"by_role": {"metal": {"datatype": 0}}}  # missing 'layer'
    with pytest.raises(DesignDslError, match="missing required 'layer'"):
        resolve_gds_layer("metal", 1, "Q1", "pad", layer_map=lm)


def test_entry_unknown_key_raises():
    lm = {"by_role": {"metal": {"layer": 1, "datatype": 0, "bogus": 9}}}
    with pytest.raises(DesignDslError, match="unknown key"):
        resolve_gds_layer("metal", 1, "Q1", "pad", layer_map=lm)


def test_entry_non_int_layer_raises():
    lm = {"by_role": {"metal": {"layer": "abc"}}}
    with pytest.raises(DesignDslError, match="must be integers"):
        resolve_gds_layer("metal", 1, "Q1", "pad", layer_map=lm)


# -----------------------------------------------------------------------------
# normalize_layer_map
# -----------------------------------------------------------------------------

def test_normalize_none_is_empty():
    assert normalize_layer_map(None) == {}


def test_normalize_passthrough_valid():
    lm = {"by_role": {"metal": {"layer": 1, "datatype": 0}}, "lib_name": "x"}
    assert normalize_layer_map(lm) == lm


def test_normalize_unknown_top_key_raises():
    with pytest.raises(DesignDslError, match="unknown key"):
        normalize_layer_map({"by_bogus": {}})


def test_normalize_non_mapping_raises():
    with pytest.raises(DesignDslError, match="must be a mapping"):
        normalize_layer_map([1, 2, 3])  # type: ignore[arg-type]
