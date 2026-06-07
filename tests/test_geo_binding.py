# -*- coding: utf-8 -*-
"""Pure tests for the ``.geo`` binding contract (no gmsh / gdstk).

覆盖 the lynchpin name binding:
- ``split_geo_name`` valid + invalid (bad arity / unknown role / empty fields /
  non-int layer → ``DesignDslError``);
- ``geo_name_to_group`` output names byte-match ``PHYSICAL_GROUP_NAMING`` for
  every role (metal / ground / substrate / jj / port / symmetry).

Both functions are pure-Python (no gmsh import), so this file runs in any env.
"""

from __future__ import annotations

import pytest

from quantum_dsl.dsl.errors import DesignDslError
from quantum_dsl.dsl._gmsh_geo_source import split_geo_name, lint_geo_names
from quantum_dsl.dsl._gmsh_physical import geo_name_to_group, _sanitize


# -----------------------------------------------------------------------------
# split_geo_name — valid 4-tuples
# -----------------------------------------------------------------------------

@pytest.mark.parametrize(
    "name,expected",
    [
        ("metal::1::Q1::pad_left", ("metal", 1, "Q1", "pad_left")),
        ("ground::1::chip::gnd", ("ground", 1, "chip", "gnd")),
        ("substrate::3::chip::sub", ("substrate", 3, "chip", "sub")),
        ("jj::1::Q1::jj", ("jj", 1, "Q1", "jj")),
        ("port::1::Q1::pin0", ("port", 1, "Q1", "pin0")),
        ("symmetry::0::sym::y0", ("symmetry", 0, "sym", "y0")),
    ],
)
def test_split_geo_name_valid(name, expected):
    assert split_geo_name(name) == expected


# -----------------------------------------------------------------------------
# split_geo_name — invalid forms each raise DesignDslError
# -----------------------------------------------------------------------------

def test_split_geo_name_bad_arity_too_few():
    with pytest.raises(DesignDslError, match="exactly 4"):
        split_geo_name("metal::1::Q1")


def test_split_geo_name_bad_arity_too_many():
    with pytest.raises(DesignDslError, match="exactly 4"):
        split_geo_name("metal::1::Q1::pad::extra")


def test_split_geo_name_unknown_role():
    with pytest.raises(DesignDslError, match="unknown role"):
        split_geo_name("wire::1::Q1::pad")


def test_split_geo_name_non_int_layer():
    with pytest.raises(DesignDslError, match="not an"):
        split_geo_name("metal::top::Q1::pad")


def test_split_geo_name_empty_component():
    with pytest.raises(DesignDslError, match="component field is empty"):
        split_geo_name("metal::1::::pad")


def test_split_geo_name_empty_primitive():
    with pytest.raises(DesignDslError, match="primitive field is empty"):
        split_geo_name("metal::1::Q1::")


# -----------------------------------------------------------------------------
# lint_geo_names — returns offenders without raising
# -----------------------------------------------------------------------------

def test_lint_geo_names_collects_offenders():
    names = [
        "metal::1::Q1::pad",       # ok
        "ground::1::chip::gnd",    # ok
        "wire::1::Q1::pad",        # bad role
        "metal::1::Q1",            # bad arity
    ]
    bad = lint_geo_names(names)
    assert bad == ["wire::1::Q1::pad", "metal::1::Q1"]


def test_lint_geo_names_all_valid_returns_empty():
    assert lint_geo_names(["metal::1::Q1::pad", "jj::2::Q2::jj"]) == []


# -----------------------------------------------------------------------------
# geo_name_to_group — matches PHYSICAL_GROUP_NAMING (output strings) per role
# -----------------------------------------------------------------------------

def test_geo_name_to_group_metal():
    # metal::N::C::P -> '{C}_{P}'
    assert geo_name_to_group("metal", 1, "Q1", "pad_left") == "Q1_pad_left"


def test_geo_name_to_group_ground():
    # ground::N::*::* -> 'gnd_layer{N}'
    assert geo_name_to_group("ground", 1, "chip", "gnd") == "gnd_layer1"


def test_geo_name_to_group_substrate():
    # substrate::N::*::* -> 'substrate_layer{N}'
    assert geo_name_to_group("substrate", 3, "chip", "sub") == "substrate_layer3"


def test_geo_name_to_group_jj():
    # jj::N::C::P -> '{C}_{P}_jj' (template suffix).
    assert geo_name_to_group("jj", 1, "Q1", "jj") == "Q1_jj_jj"


def test_geo_name_to_group_port():
    # port::N::C::pin -> 'port_{C}_{pin}'
    assert geo_name_to_group("port", 1, "Q1", "pin0") == "port_Q1_pin0"


def test_geo_name_to_group_symmetry():
    # symmetry::*::*::plane -> 'symmetry_{plane}' (plane in primitive slot).
    assert geo_name_to_group("symmetry", 0, "sym", "y0") == "symmetry_y0"


def test_geo_name_to_group_unknown_role_raises():
    with pytest.raises(ValueError, match="unknown geo role"):
        geo_name_to_group("wire", 1, "Q1", "pad")


# -----------------------------------------------------------------------------
# geo_name_to_group — sanitization of '.'/'-'/digit-leading names
# -----------------------------------------------------------------------------

def test_geo_name_to_group_sanitizes_dots():
    # '.' -> '_' via _sanitize (Palace identifier constraint).
    assert geo_name_to_group("metal", 1, "Q1.bus", "pad.left") == "Q1_bus_pad_left"


def test_geo_name_to_group_matches_sanitize_helper():
    # The output is exactly _sanitize applied to the formatted template.
    raw = "Q1-a_pad-b"
    assert geo_name_to_group("metal", 1, "Q1-a", "pad-b") == _sanitize(raw)
