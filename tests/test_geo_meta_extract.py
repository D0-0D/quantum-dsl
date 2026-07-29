# -*- coding: utf-8 -*-
"""M8 — Layer-1 sidecar schema + parsing for ``extract`` / ``assemble`` /
``subsystems`` (the New-LOM parity blocks, lom-parity-spec §4 P0-B..F).

纯解析测试 —— 不需要 gmsh / gdstk / Palace。覆盖:

* 三块齐全时解析出的**完整结构** (这是跨 agent 契约, geo_build 照它接线);
* 单位换算: ``C_j: 2fF`` → 法拉、``f_res: 7GHz`` → Hz、``E_J: 12.2GHz`` → 焦耳、
  ``cpw`` 长度 → **µm** (不是米)、``Z0: 50ohm`` → 欧姆;
* ``nodes:`` 的 key 两种形式 (结构化 geo 名 / 已 sanitize 的 group 名) 都**原样保留**;
* 每一条校验的报错路径;
* **向后兼容**: 既有 fixture / examples 的 sidecar 仍能解析, 且没声明这三个块时
  三个键都是 ``None``。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from quantum_dsl.dsl.errors import DesignDslError
from quantum_dsl.dsl.parsers.simulation import parse_geo_meta_sidecar

_FIXTURES = Path(__file__).parent / "fixtures"
_GEO = _FIXTURES / "two_pads.geo"
_EXAMPLES = Path(__file__).parent.parent / "examples" / "dsl" / "geo"

H_PLANCK = 6.62607015e-34


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _sidecar(tmp_path: Path, blocks: str, *, vars_block: str = "vars: {}\n") -> Path:
    """Write a minimal valid sidecar with ``blocks`` appended at the top level."""
    text = (
        "schema: qiskit-metal/design-dsl/3\n"
        f"geo: {_GEO}\n"
        f"{vars_block}"
        "simulation:\n"
        "  gmsh:\n"
        "    layer_stack:\n"
        "      1: {kind: metal, thickness: 2, z: 0, material: pec}\n"
        "      3: {kind: dielectric, thickness: -100, z: 0, eps_r: 11.45}\n"
        "    airbox: {top: 120, bottom: 120, side_buffer: 80}\n"
        "    mesh: {max_size: 40, min_size: 4}\n"
        f"{blocks}"
    )
    p = tmp_path / "x.meta.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def _extract(tmp_path: Path, block_body: str) -> dict:
    """Parse a sidecar carrying a single ``extract.blocks`` entry."""
    return parse_geo_meta_sidecar(_sidecar(
        tmp_path, "extract:\n  blocks:\n" + block_body))["extract"]


def _subsystems(tmp_path: Path, entries: str) -> list[dict]:
    return parse_geo_meta_sidecar(_sidecar(
        tmp_path, "subsystems:\n" + entries))["subsystems"]


_FULL = """\
extract:
  blocks:
    - name: qb1
      components: [QB1]
      nodes:
        metal::1::QB1::coupler_pad: coupling
        QB1_readout_pad_sfs: readout_qb1
      junctions:
        - name: j1
          between: [metal::1::QB1::pad_top, metal::1::QB1::pad_bot]
          E_J: 12.2GHz
          C_j: 2fF
    - name: qb2
      from: inline
      units: fF
      matrix:
        terminals: [QB2_pad_sfs, QB2_claw_sfs]
        maxwell: [[80.0, -3.0], [-3.0, 40.0]]
      nodes:
        metal::1::QB2::coupler_pad: coupling
        QB2_readout_pad_sfs: readout_qb2
      junctions:
        - {name: j2, between: [QB2_pad_sfs], L_J: 10nH}

assemble:
  ground_node: ground::1::chip::gnd
  nodes_force_keep: [readout_qb1, readout_qb2]

subsystems:
  - {name: QB1, type: transmon, junction: j1}
  - {name: QB2, type: transmon, junction: j2}
  - {name: RO1, type: tl_resonator, node: readout_qb1, f_res: 7.0GHz, Z0: 50ohm,
     mode: half_wave}
  - name: RO2
    type: tl_resonator
    node: readout_qb2
    Z0: 50ohm
    mode: quarter_wave
    cpw: {line_width: 10um, line_gap: 6um, length: 4200um}
"""


# ---------------------------------------------------------------------------
# (1) happy path — the full cross-agent contract shape
# ---------------------------------------------------------------------------

def test_full_parse_shape(tmp_path):
    meta = parse_geo_meta_sidecar(_sidecar(tmp_path, _FULL))

    blocks = meta["extract"]["blocks"]
    assert [b["name"] for b in blocks] == ["qb1", "qb2"]

    qb1 = blocks[0]
    assert qb1["components"] == ("QB1",)          # tuple, not list
    assert qb1["source"] == "solve"               # ``from`` defaults to solve
    assert qb1["path"] is None and qb1["matrix"] is None
    assert qb1["units"] == "fF"
    assert qb1["nodes"] == {"metal::1::QB1::coupler_pad": "coupling",
                            "QB1_readout_pad_sfs": "readout_qb1"}
    j1 = qb1["junctions"][0]
    assert j1["name"] == "j1"
    assert j1["between"] == ("metal::1::QB1::pad_top", "metal::1::QB1::pad_bot")
    assert j1["E_J"] == pytest.approx(12.2e9 * H_PLANCK)   # GHz -> Joule (xh)
    assert j1["L_J"] is None and j1["E_J1"] is None and j1["E_J2"] is None
    assert j1["flux"] == 0.0
    assert j1["C_j"] == pytest.approx(2e-15)               # 2fF -> Farad

    qb2 = blocks[1]
    assert qb2["source"] == "inline" and qb2["components"] == ()
    assert qb2["matrix"]["terminals"] == ("QB2_pad_sfs", "QB2_claw_sfs")
    assert qb2["matrix"]["maxwell"] == ((80.0, -3.0), (-3.0, 40.0))
    j2 = qb2["junctions"][0]
    assert j2["between"] == ("QB2_pad_sfs",)               # 1 node = to ground
    assert j2["L_J"] == pytest.approx(10e-9)               # 10nH -> Henry
    assert j2["E_J"] is None and j2["C_j"] == 0.0          # C_j defaults to 0

    assert meta["assemble"] == {"ground_node": "ground::1::chip::gnd",
                                "nodes_force_keep": ("readout_qb1",
                                                     "readout_qb2")}

    subs = meta["subsystems"]
    assert subs[0] == {"name": "QB1", "type": "transmon", "junction": "j1"}
    ro1 = subs[2]
    assert ro1["type"] == "tl_resonator" and ro1["node"] == "readout_qb1"
    assert ro1["f_res"] == pytest.approx(7.0e9)            # 7.0GHz -> Hz
    assert ro1["Z0"] == pytest.approx(50.0) and ro1["mode"] == "half_wave"
    assert ro1["cpw"] is None
    ro2 = subs[3]
    assert ro2["f_res"] is None and ro2["mode"] == "quarter_wave"
    # cpw lengths stay in µm (repo-internal unit); geo_build x1e-6 for cpw_analytic.
    assert ro2["cpw"] == {"line_width": 10.0, "line_gap": 6.0, "length": 4200.0}


def test_squid_junction_and_optional_cpw_keys(tmp_path):
    extract = _extract(tmp_path,
        "    - name: b\n"
        "      components: [C]\n"
        "      junctions:\n"
        "        - name: js\n"
        "          between: [C_top_sfs, C_bot_sfs]\n"
        "          squid: {E_J1: 60GHz, E_J2: 11GHz, flux: 0.25}\n")
    j = extract["blocks"][0]["junctions"][0]
    assert j["E_J1"] == pytest.approx(60e9 * H_PLANCK)
    assert j["E_J2"] == pytest.approx(11e9 * H_PLANCK)
    assert j["flux"] == pytest.approx(0.25)
    assert j["L_J"] is None and j["E_J"] is None

    subs = _subsystems(tmp_path,
        "  - name: R\n"
        "    type: tl_resonator\n"
        "    node: n1\n"
        "    cpw: {line_width: 10um, line_gap: 6um, length: 4.2mm,\n"
        "          substrate_thickness: 380um, film_thickness: 200nm}\n")
    cpw = subs[0]["cpw"]
    assert cpw["length"] == pytest.approx(4200.0)          # 4.2mm -> µm
    assert cpw["substrate_thickness"] == pytest.approx(380.0)
    assert cpw["film_thickness"] == pytest.approx(0.2)     # 200nm -> µm
    # defaults when Z0/mode omitted
    assert subs[0]["Z0"] == pytest.approx(50.0)
    assert subs[0]["mode"] == "half_wave"


def test_z0_accepts_bare_number(tmp_path):
    subs = _subsystems(tmp_path,
        "  - {name: R, type: tl_resonator, node: n1, f_res: 7GHz, Z0: 42}\n")
    assert subs[0]["Z0"] == pytest.approx(42.0)


def test_nodes_keys_kept_verbatim_both_forms(tmp_path):
    """``nodes:`` keys may be structured geo names OR already-sanitized terminal
    group names; the parser must NOT normalise either (resolution happens in
    geo_build against the real TerminalBinding set)."""
    extract = _extract(tmp_path,
        "    - name: b\n"
        "      components: [C]\n"
        "      nodes:\n"
        "        metal::1::C::pad: shared\n"
        "        C_claw_sfs: other\n"
        "        already_shared: still_renamed\n")
    assert extract["blocks"][0]["nodes"] == {
        "metal::1::C::pad": "shared",
        "C_claw_sfs": "other",
        "already_shared": "still_renamed",
    }


def test_from_file_resolves_path_relative_to_sidecar(tmp_path):
    measured = tmp_path / "measured"
    measured.mkdir()
    csv = measured / "QB1.csv"
    csv.write_text("dummy\n", encoding="utf-8")
    extract = _extract(tmp_path,
        "    - name: b\n"
        "      from: file\n"
        "      path: measured/QB1.csv\n"
        "      units: pF\n")
    block = extract["blocks"][0]
    assert block["source"] == "file"
    assert block["path"] == csv.resolve() and block["path"].is_absolute()
    assert block["units"] == "pF"
    assert block["matrix"] is None and block["components"] == ()


def test_var_interpolation_matches_rest_of_sidecar(tmp_path):
    """``${var}`` must resolve inside the new blocks exactly as it does for
    ``simulation`` / ``circuit_model`` (same ``_walk_substitute`` against vars)."""
    meta = parse_geo_meta_sidecar(_sidecar(
        tmp_path,
        "extract:\n"
        "  blocks:\n"
        "    - name: b\n"
        "      components: [C]\n"
        "      junctions:\n"
        "        - {name: j, between: [C_pad_sfs], E_J: '${ej}'}\n"
        "assemble: {ground_node: '${gnd}'}\n"
        "subsystems:\n"
        "  - {name: R, type: tl_resonator, node: n, f_res: '${fr}'}\n",
        vars_block="vars: {ej: 12GHz, gnd: gnd_layer1_sfs, fr: 7GHz}\n"))
    assert meta["extract"]["blocks"][0]["junctions"][0]["E_J"] == pytest.approx(
        12e9 * H_PLANCK)
    assert meta["assemble"]["ground_node"] == "gnd_layer1_sfs"
    assert meta["subsystems"][0]["f_res"] == pytest.approx(7e9)


# ---------------------------------------------------------------------------
# (2) extract validation
# ---------------------------------------------------------------------------

def test_unknown_keys_rejected(tmp_path):
    cases = [
        ("extract:\n  blocks: []\n  bogus: 1\n", r"Unknown .*extract key"),
        ("extract:\n  blocks:\n    - {name: b, components: [C], bogus: 1}\n",
         r"Unknown .*blocks\[0\] key"),
        ("extract:\n  blocks:\n    - name: b\n      components: [C]\n"
         "      junctions:\n"
         "        - {name: j, between: [a], L_J: 10nH, bogus: 1}\n",
         r"Unknown .*junctions\[0\] key"),
        ("extract:\n  blocks:\n    - name: b\n      from: inline\n"
         "      matrix: {terminals: [a], maxwell: [[1.0]], bogus: 1}\n",
         r"Unknown .*matrix key"),
        ("assemble: {ground_node: g, bogus: 1}\n", r"Unknown .*assemble key"),
        ("subsystems:\n  - {name: Q, type: transmon, junction: j, bogus: 1}\n",
         r"Unknown .*subsystems\[0\] key"),
        ("subsystems:\n  - {name: R, type: tl_resonator, node: n,\n"
         "     cpw: {line_width: 10um, line_gap: 6um, length: 1um, bogus: 1}}\n",
         r"Unknown .*cpw key"),
    ]
    for block, msg in cases:
        with pytest.raises(DesignDslError, match=msg):
            parse_geo_meta_sidecar(_sidecar(tmp_path, block))


def test_source_required_fields(tmp_path):
    cases = [
        # from: solve (explicit and defaulted) needs components
        ("    - {name: b, from: solve}\n", r"components is required for from: solve"),
        ("    - {name: b}\n", r"components is required for from: solve"),
        ("    - {name: b, from: file}\n", r"path is required for from: file"),
        ("    - {name: b, from: file, path: nope/missing.csv}\n",
         r"capacitance-matrix file not found"),
        ("    - {name: b, from: inline}\n", r"matrix is required for from: inline"),
        ("    - {name: b, from: guess, components: [C]}\n",
         r"from must be one of \['file', 'inline', 'solve'\]"),
    ]
    for body, msg in cases:
        with pytest.raises(DesignDslError, match=msg):
            _extract(tmp_path, body)


def test_inline_matrix_validation(tmp_path):
    cases = [
        # non-square row
        ("      matrix: {terminals: [a, b], maxwell: [[1.0, 0.0], [0.0]]}\n",
         r"maxwell\[1\] has 1 entr\(ies\), expected 2"),
        # row count != terminals
        ("      matrix: {terminals: [a, b], maxwell: [[1.0, 0.0]]}\n",
         r"maxwell has 1 row\(s\) but 2 terminal\(s\)"),
        # nan / inf -> silent-nan-results guard
        ("      matrix: {terminals: [a], maxwell: [[.nan]]}\n",
         r"is not finite"),
        ("      matrix: {terminals: [a], maxwell: [[.inf]]}\n",
         r"is not finite"),
        # non-numeric cell
        ("      matrix: {terminals: [a], maxwell: [[abc]]}\n",
         r"must be a number"),
        # duplicate terminal names
        ("      matrix: {terminals: [a, a], maxwell: [[1.0, 0.0], [0.0, 1.0]]}\n",
         r"terminals has duplicate names"),
        # empty / wrong-typed pieces
        ("      matrix: {terminals: [], maxwell: [[1.0]]}\n",
         r"terminals must be a non-empty list"),
        ("      matrix: {terminals: [a], maxwell: []}\n",
         r"maxwell must be a non-empty list"),
    ]
    for matrix, msg in cases:
        with pytest.raises(DesignDslError, match=msg):
            _extract(tmp_path, "    - name: b\n      from: inline\n" + matrix)


def test_duplicate_block_and_junction_names(tmp_path):
    with pytest.raises(DesignDslError, match=r"duplicate block name 'b'"):
        _extract(tmp_path,
            "    - {name: b, components: [C1]}\n"
            "    - {name: b, components: [C2]}\n")
    with pytest.raises(DesignDslError,
                       match=r"junction name 'j' already used by block 'b1'"):
        _extract(tmp_path,
            "    - name: b1\n      components: [C1]\n"
            "      junctions: [{name: j, between: [a], L_J: 10nH}]\n"
            "    - name: b2\n      components: [C2]\n"
            "      junctions: [{name: j, between: [b], L_J: 10nH}]\n")


def test_junction_between_arity(tmp_path):
    for between in ("[]", "[a, b, c]", "a"):
        with pytest.raises(DesignDslError,
                           match=r"between must be a list of 1 or 2 node names"):
            _extract(tmp_path,
                "    - name: b\n      components: [C]\n"
                f"      junctions: [{{name: j, between: {between}, L_J: 10nH}}]\n")


def test_junction_element_exactly_one(tmp_path):
    cases = ["", "L_J: 10nH, E_J: 12GHz",
             "L_J: 10nH, squid: {E_J1: 60GHz, E_J2: 11GHz}"]
    for element in cases:
        body = ("    - name: blk\n      components: [C]\n"
                "      junctions: [{name: jx, between: [a]"
                + (f", {element}" if element else "") + "}]\n")
        with pytest.raises(DesignDslError,
                           match=r"junction 'jx'\) must set exactly one of "
                                 r"'L_J' / 'E_J' / 'squid'"):
            _extract(tmp_path, body)


def test_junction_non_positive_and_non_finite_values(tmp_path):
    cases = [("L_J: 0nH", r"L_J must be > 0 and finite"),
             ("L_J: 1e400H", r"L_J must be > 0 and finite"),
             ("E_J: -1GHz", r"E_J must be > 0 and finite"),
             ("C_j: -1fF", r"C_j must be >= 0 and finite")]
    for element, msg in cases:
        base = "L_J: 10nH, " if element.startswith("C_j") else ""
        with pytest.raises(DesignDslError, match=msg):
            _extract(tmp_path,
                "    - name: b\n      components: [C]\n"
                f"      junctions: [{{name: j, between: [a], {base}{element}}}]\n")


def test_bare_numbers_rejected_for_prefixed_units(tmp_path):
    """``C_j: 2`` is ambiguous (2 F vs 2 fF differ by 1e15) — the shared
    ``_parse_unit_value`` contract requires the unit to be spelled."""
    with pytest.raises(DesignDslError, match=r"C_j needs an explicit unit"):
        _extract(tmp_path,
            "    - name: b\n      components: [C]\n"
            "      junctions: [{name: j, between: [a], L_J: 10nH, C_j: 2}]\n")
    with pytest.raises(DesignDslError, match=r"f_res needs an explicit unit"):
        _subsystems(tmp_path,
            "  - {name: R, type: tl_resonator, node: n, f_res: 7}\n")


def test_extract_structural_errors(tmp_path):
    cases = [
        ("extract: [1]\n", r"extract must be a mapping"),
        ("extract:\n  blocks: []\n", r"blocks must be a non-empty list"),
        ("extract:\n  blocks: [1]\n", r"blocks\[0\] must be a mapping"),
        ("extract:\n  blocks:\n    - {components: [C]}\n",
         r"name must be a non-empty string"),
        ("extract:\n  blocks:\n    - {name: b, components: []}\n",
         r"components must be a non-empty list"),
        ("extract:\n  blocks:\n    - {name: b, components: [C], nodes: [a]}\n",
         r"nodes must be a mapping"),
        ("extract:\n  blocks:\n    - {name: b, components: [C], junctions: []}\n",
         r"junctions must be a non-empty list"),
        ("extract:\n  blocks:\n    - {name: b, components: [C], units: farad}\n",
         r"units must be one of"),
    ]
    for block, msg in cases:
        with pytest.raises(DesignDslError, match=msg):
            parse_geo_meta_sidecar(_sidecar(tmp_path, block))


# ---------------------------------------------------------------------------
# (3) assemble validation
# ---------------------------------------------------------------------------

def test_assemble_defaults_and_errors(tmp_path):
    empty = parse_geo_meta_sidecar(_sidecar(tmp_path, "assemble: {}\n"))
    assert empty["assemble"] == {"ground_node": None, "nodes_force_keep": ()}
    for block, msg in [
        ("assemble: [1]\n", r"assemble must be a mapping"),
        ("assemble: {ground_node: 1}\n", r"ground_node must be a non-empty"),
        ("assemble: {nodes_force_keep: n1}\n",
         r"nodes_force_keep must be a list"),
        ("assemble: {nodes_force_keep: ['']}\n",
         r"nodes_force_keep\[0\] must be a non-empty"),
    ]:
        with pytest.raises(DesignDslError, match=msg):
            parse_geo_meta_sidecar(_sidecar(tmp_path, block))


# ---------------------------------------------------------------------------
# (4) subsystems validation
# ---------------------------------------------------------------------------

def test_subsystem_type_must_be_known(tmp_path):
    with pytest.raises(
            DesignDslError,
            match=r"type must be one of \['tl_resonator', 'transmon'\]"):
        _subsystems(tmp_path, "  - {name: X, type: fluxonium, node: n}\n")
    with pytest.raises(DesignDslError, match=r"type must be one of"):
        _subsystems(tmp_path, "  - {name: X}\n")


def test_transmon_names_a_junction_not_a_node(tmp_path):
    """Deliberate deviation from the spec's ``{type: transmon, node: j1}`` example:
    a transmon names its JUNCTION.  Writing ``node:`` must fail loudly rather than
    silently look a junction name up in the node namespace (risk R2)."""
    with pytest.raises(DesignDslError,
                       match=r"does not accept key\(s\) \['node'\]"):
        _subsystems(tmp_path, "  - {name: Q, type: transmon, node: j1}\n")
    with pytest.raises(DesignDslError,
                       match=r"junction is required for type 'transmon'"):
        _subsystems(tmp_path, "  - {name: Q, type: transmon}\n")
    with pytest.raises(DesignDslError,
                       match=r"does not accept key\(s\) \['f_res'\]"):
        _subsystems(tmp_path,
                    "  - {name: Q, type: transmon, junction: j1, f_res: 7GHz}\n")


def test_tl_resonator_requires_node_and_exactly_one_frequency_source(tmp_path):
    with pytest.raises(DesignDslError,
                       match=r"node is required for type 'tl_resonator'"):
        _subsystems(tmp_path, "  - {name: R, type: tl_resonator, f_res: 7GHz}\n")
    with pytest.raises(DesignDslError,
                       match=r"does not accept key\(s\) \['junction'\]"):
        _subsystems(tmp_path,
                    "  - {name: R, type: tl_resonator, node: n, junction: j}\n")
    # neither f_res nor cpw
    with pytest.raises(DesignDslError,
                       match=r"must set exactly one of 'f_res' .* / 'cpw'"):
        _subsystems(tmp_path, "  - {name: R, type: tl_resonator, node: n}\n")
    # both
    with pytest.raises(DesignDslError,
                       match=r"must set exactly one of 'f_res' .* / 'cpw'"):
        _subsystems(tmp_path,
            "  - {name: R, type: tl_resonator, node: n, f_res: 7GHz,\n"
            "     cpw: {line_width: 10um, line_gap: 6um, length: 1um}}\n")


def test_resonator_mode_z0_and_cpw_errors(tmp_path):
    cases = [
        ("  - {name: R, type: tl_resonator, node: n, f_res: 7GHz, mode: lambda}\n",
         r"mode must be one of \['half_wave', 'quarter_wave'\]"),
        ("  - {name: R, type: tl_resonator, node: n, f_res: 7GHz, Z0: 0}\n",
         r"Z0 must be > 0 and finite"),
        ("  - {name: R, type: tl_resonator, node: n, f_res: -7GHz}\n",
         r"f_res must be > 0 and finite"),
        ("  - {name: R, type: tl_resonator, node: n, cpw: [1]}\n",
         r"cpw must be a mapping"),
        ("  - {name: R, type: tl_resonator, node: n,\n"
         "     cpw: {line_width: 10um, line_gap: 6um}}\n",
         r"cpw.length is required"),
        ("  - {name: R, type: tl_resonator, node: n,\n"
         "     cpw: {line_width: 0um, line_gap: 6um, length: 1um}}\n",
         r"cpw.line_width must be > 0 and finite"),
    ]
    for entry, msg in cases:
        with pytest.raises(DesignDslError, match=msg):
            _subsystems(tmp_path, entry)


def test_duplicate_subsystem_name(tmp_path):
    with pytest.raises(DesignDslError, match=r"duplicate subsystem name 'Q'"):
        _subsystems(tmp_path,
            "  - {name: Q, type: transmon, junction: j1}\n"
            "  - {name: Q, type: transmon, junction: j2}\n")


def test_subsystems_structural_errors(tmp_path):
    for block, msg in [
        ("subsystems: {}\n", r"subsystems must be a non-empty list"),
        ("subsystems: []\n", r"subsystems must be a non-empty list"),
        ("subsystems: [1]\n", r"subsystems\[0\] must be a mapping"),
        ("subsystems:\n  - {type: transmon, junction: j}\n",
         r"name must be a non-empty string"),
    ]:
        with pytest.raises(DesignDslError, match=msg):
            parse_geo_meta_sidecar(_sidecar(tmp_path, block))


# ---------------------------------------------------------------------------
# (5) backward compatibility — sidecars without the three blocks are untouched
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("sidecar", sorted(_EXAMPLES.glob("*.meta.yaml"))
                         + sorted(_FIXTURES.glob("*.meta.yaml")))
def test_shipped_sidecars_still_parse(sidecar):
    """Every shipped sidecar must still parse, and each of the three new keys must
    be ``None`` exactly when its block is absent from the YAML (so today's
    whole-chip path is byte-for-byte unchanged)."""
    meta = parse_geo_meta_sidecar(sidecar)
    raw = yaml.safe_load(sidecar.read_text(encoding="utf-8"))
    for key in ("extract", "assemble", "subsystems"):
        assert key in meta                       # key always present ...
        if key in raw:
            assert meta[key] is not None         # ... parsed when declared
        else:
            assert meta[key] is None             # ... None when absent


def test_no_block_declared_keeps_legacy_keys(tmp_path):
    meta = parse_geo_meta_sidecar(_sidecar(tmp_path, ""))
    assert meta["extract"] is None
    assert meta["assemble"] is None
    assert meta["subsystems"] is None
    assert meta["circuit_model"] is None
    assert meta["cells"] == []
    assert meta["geo"] == _GEO.resolve()
