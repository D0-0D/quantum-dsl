# -*- coding: utf-8 -*-
"""Native ``.geo`` + ``*.meta.yaml`` → GDS + Palace orchestrator (M1 pivot).

一个原生 Gmsh ``.geo`` (Layer 2 几何, 微米) + 一个独立的 ``*.meta.yaml``
sidecar (Layer 1 物理元数据) 分叉成两条后端:

    Layer 1 (*.meta.yaml)  ─┐
    Layer 2 (chip.geo)     ─┤
                            ├─► GDS backend  (gdstk)            → chip.gds
                            └─► Mesh backend (Gmsh → Palace)    → chip.msh + chip.json

GDS 与 mesh 两条分支在 M1 各自 **独立加载** ``.geo`` (load twice — 简单解耦);
单位契约见各 adapter docstring (GDS 保留微米; mesh dilate µm→m, Palace L0=1.0)。

公开 API:
    build_geo(geo_path=None, meta_path, out_dir, *, run_palace=False, dry_run=True) -> dict

CLI:
    python -m quantum_dsl.dsl.geo_build <meta.yaml> --out-dir build/ [--run-palace --dry-run]
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Union

from .errors import DesignDslError
from .parsers.simulation import parse_geo_meta_sidecar


__all__ = ["build_geo", "main"]


def _sha256_file(path: Optional[Union[str, Path]]) -> Optional[str]:
    """文件内容 SHA-256 (十六进制); 路径为 None 或不存在则返回 None。

    用于结果产物的溯源/失效检测: 消费端重算输入哈希与产物记录比对, 不符即 stale。
    """
    if path is None:
        return None
    p = Path(path)
    if not p.is_file():
        return None
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_geo(geo_path: Optional[Union[str, Path]] = None,
              meta_path: Optional[Union[str, Path]] = None,
              out_dir: Union[str, Path] = "build",
              *,
              run_palace: bool = False,
              dry_run: bool = True) -> dict[str, Any]:
    """从 sidecar (+ 配套 ``.geo``) 分叉构建 GDS + mesh + Palace 配置。

    Args:
        geo_path: 可选, 显式覆盖 sidecar 里 ``geo`` 指向的 ``.geo`` 路径。
            ``None`` 时用 sidecar 解析出的 ``geo`` (相对 sidecar 解析为绝对路径)。
        meta_path: ``*.meta.yaml`` sidecar 路径 (必填)。
        out_dir: 输出目录 (chip.gds / chip.msh / chip.json 写到这里)。
        run_palace: True 时调 ``run_palace`` (受 ``dry_run`` 控制)。
        dry_run: 传给 ``run_palace`` (``--dry-run``: 只校验/划分, 不求解)。

    Returns:
        ``{"gds": Path|None, "msh": Path|None, "palace_json": Path,
           "physical_groups": [sorted names], "results": Path|None}``。
        ``results`` 仅在 ``run_palace and not dry_run`` 且 Palace 真写出了电容
        CSV 时, 指向 ``out_dir/chip.results.yaml`` (OUTPUT-ONLY 结果产物); 否则 None。

    Raises:
        DesignDslError: sidecar / geo 缺失或非法, 或下游 adapter 报错。
    """
    if meta_path is None:
        raise DesignDslError("build_geo requires meta_path (the *.meta.yaml).")

    # Lazy import of the optional gmsh/gdstk-backed adapters — keep the package
    # importable without gmsh/gdstk; only this orchestrator needs them.
    from .gmsh_adapter import build_mesh_from_geo
    from .palace_adapter import (
        build_palace_config,
        validate_config,
        write_palace_config,
    )

    meta = parse_geo_meta_sidecar(meta_path)

    sim_gmsh = (meta.get("simulation") or {}).get("gmsh") or {}
    if not sim_gmsh:
        raise DesignDslError(
            f"sidecar {meta_path} has no simulation.gmsh block — cannot build "
            f"mesh / Palace config.")
    layer_stack = sim_gmsh.get("layer_stack") or {}
    solver = sim_gmsh.get("solver") or {}

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ---- resolve the geometry source (M5a) ------------------------------
    # Precedence: explicit geo_path arg > generated from a ``cells:`` block
    # (emit_geo bridge → out_dir/<stem>.elaborated.geo) > the sidecar's ``geo``.
    # The elaborated path is substituted here so BOTH the GDS and mesh forks
    # below consume it unchanged (nothing under load_geo knows the difference).
    if geo_path is not None:
        geo = Path(geo_path).resolve()
    elif meta.get("cells"):
        from .geo_emit import elaborate_cells
        # Strip the full ``.meta.yaml`` / ``.meta.yml`` suffix (NOT just the first
        # dot — a sidecar like ``chip.layout.meta.yaml`` must give stem
        # ``chip.layout``, else two such sidecars collide on ``chip.elaborated.geo``).
        name = Path(meta_path).name
        if name.endswith(".meta.yaml"):
            stem = name[: -len(".meta.yaml")]
        elif name.endswith(".meta.yml"):
            stem = name[: -len(".meta.yml")]
        else:
            stem = Path(name).stem
        geo = out_dir / f"{stem}.elaborated.geo"
        elaborate_cells(meta["cells"], geo, emit_ports=False)
    else:
        geo = meta.get("geo")
    if geo is None or not Path(geo).is_file():
        raise DesignDslError(f"geo file not found: {geo}")

    result: dict[str, Any] = {
        "gds": None,
        "msh": None,
        "palace_json": None,
        "physical_groups": [],
        "results": None,
    }

    # SESSION OWNERSHIP (critical): the GDS and mesh branches each call
    # load_geo, which Includes qlib.geo.  qlib.geo's macros (PAD/CPW/...) live in
    # a PROCESS-GLOBAL parser table that survives gmsh.finalize()+initialize(),
    # but its ``_QLIB_INCLUDED`` include-guard CONSTANT does NOT — so if each
    # branch owned (and finalized) its OWN session, the 2nd merge would re-Include
    # qlib.geo with the guard gone and hit "Redefinition of function PAD".
    # Fix: build_geo owns ONE gmsh session spanning both branches.  Each branch's
    # _did_initialize guard then sees gmsh already-initialized → it does NOT
    # finalize → the guard constant survives → the 2nd Include is correctly
    # skipped.  load_geo still switches to a fresh, uniquely-named model per
    # call, so the two branches stay decoupled at the model level.
    import gmsh  # lazy: optional gmsh dependency
    _did_initialize = not gmsh.isInitialized()
    if _did_initialize:
        gmsh.initialize()
        gmsh.option.setNumber("General.Terminal", 0)
    try:
        # ---- GDS branch (gdstk) — microns verbatim, bypasses the 3D mesh ----
        from .gds_adapter import build_gds  # lazy: optional gdstk dependency
        gds_path = out_dir / "chip.gds"
        gds_result = build_gds(
            geo, output_path=gds_path, layer_map=sim_gmsh.get("gds"))
        result["gds"] = gds_result.gds_path

        # ---- MESH branch (Gmsh) — µm→m dilate, msh2.2 for Palace ------------
        msh_path = out_dir / "chip.msh"
        mesh_result = build_mesh_from_geo(
            geo, sim_gmsh, output_path=msh_path, generate=True)
        result["msh"] = mesh_result.mesh_path
        result["physical_groups"] = sorted(mesh_result.physical_groups)
    finally:
        if _did_initialize and gmsh.isInitialized():
            gmsh.finalize()

    # ---- PALACE — Electrostatic config from geo-derived attributes ---------
    # run_palace cd's into the config's directory before invoking Palace, so
    # Model.Mesh must be RELATIVE to that dir. chip.json and chip.msh share
    # out_dir, so the mesh reference is just its basename.
    mesh_rel = (Path(mesh_result.mesh_path).name
                if mesh_result.mesh_path else None)
    l0 = float(solver.get("l0", 1.0))
    order = int(solver.get("order", 2))
    cfg = build_palace_config(
        mesh_result.physical_attributes,
        layer_stack,
        sim_gmsh.get("ports", ()),
        l0=l0,
        order=order,
        mesh_path=mesh_rel,
    )
    validate_config(cfg, mesh_result.physical_attributes)
    palace_json = out_dir / "chip.json"
    write_palace_config(cfg, palace_json)
    result["palace_json"] = palace_json

    if run_palace:
        from .palace_adapter import run_palace as _run_palace
        _run_palace(palace_json, dry_run=dry_run)

        # ---- RESULTS write-back (M3): OUTPUT-ONLY chip.results.yaml --------
        # Only a real solve (not --dry-run) produces capacitance CSVs.  Derive
        # the postpro dir from the config's Problem.Output (NOT a hardcoded
        # literal) and reuse build_palace_config's terminal binding as the
        # single source of truth for the matrix row/col labels.
        if not dry_run:
            from .palace_adapter import (
                parse_capacitance_matrix,
                terminal_bindings,
                write_results_sidecar,
            )
            postpro = out_dir / cfg["Problem"].get("Output", "postpro")
            bindings = terminal_bindings(mesh_result.physical_attributes)
            cap = parse_capacitance_matrix(postpro, terminals=bindings)
            if cap.available:
                provenance = {
                    "generated_utc": datetime.now(timezone.utc)
                    .isoformat(timespec="seconds"),
                    "solver": {"type": "Electrostatic", "order": order, "l0": l0},
                    "out_dir": str(out_dir),
                    "label_index_map": {b.group: b.index for b in bindings},
                    "inputs": {
                        "geo": Path(geo).name,
                        "geo_sha256": _sha256_file(geo),
                        "mesh": (Path(mesh_result.mesh_path).name
                                 if mesh_result.mesh_path else None),
                        "mesh_sha256": _sha256_file(mesh_result.mesh_path),
                        "palace_json": palace_json.name,
                        "config_sha256": _sha256_file(palace_json),
                    },
                }
                result["results"] = write_results_sidecar(
                    cap, out_dir / "chip.results.yaml", provenance=provenance)

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m quantum_dsl.dsl.geo_build",
        description="Fork a native Gmsh .geo + *.meta.yaml sidecar into a GDS "
                    "(gdstk) layout and a Palace Electrostatic mesh+config.",
    )
    parser.add_argument(
        "meta", help="path to the *.meta.yaml sidecar (its 'geo' key names "
                     "the companion .geo).")
    parser.add_argument(
        "--geo", default=None,
        help="optional explicit .geo path (overrides the sidecar's 'geo').")
    parser.add_argument(
        "--out-dir", default="build", help="output directory (default: build).")
    parser.add_argument(
        "--run-palace", action="store_true",
        help="also invoke Palace on the generated config.")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="pass --dry-run to Palace (validate/partition only).")
    args = parser.parse_args(argv)

    try:
        result = build_geo(
            geo_path=args.geo,
            meta_path=args.meta,
            out_dir=args.out_dir,
            run_palace=args.run_palace,
            dry_run=args.dry_run,
        )
    except DesignDslError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"GDS         : {result['gds']}")
    print(f"MSH         : {result['msh']}")
    print(f"Palace JSON : {result['palace_json']}")
    if result.get("results"):
        print(f"Results     : {result['results']}")
    print(f"physical_groups ({len(result['physical_groups'])}): "
          f"{result['physical_groups']}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
