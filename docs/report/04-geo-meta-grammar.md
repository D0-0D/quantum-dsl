# Native Gmsh .geo and .meta.yaml grammar reference

This document is the practical reference for the native geometry path used by this project. It explains the grammar, the binding contract, and the authoring patterns implemented by the repository’s examples and parser code.

The short version is:

- The companion file [examples/dsl/geo/chip_layout.geo](../../examples/dsl/geo/chip_layout.geo) is the geometry source written in Gmsh’s OpenCASCADE .geo language.
- The sidecar [examples/dsl/geo/chip_layout.meta.yaml](../../examples/dsl/geo/chip_layout.meta.yaml) carries the physical metadata that the pipeline uses for meshing, GDS export, and Palace solving.
- The binding key between both layers is a structured physical name in the form:

  `<role>::<layer>::<component>::<primitive>`

---

## 1. Design model and purpose

The project uses a two-layer representation for geometry-driven work:

1. Layer 1: physics metadata in a standalone .meta.yaml sidecar.
2. Layer 2: geometry in a native Gmsh .geo file.

The geometry file contains only shape information. The sidecar contains everything else that is needed to make that geometry executable in the toolchain:

- material and dielectric properties
- mesh settings
- GDS layer mapping
- Palace solver settings
- optional circuit-model mapping for capacitance-to-Hamiltonian solving
- optional cell elaboration blocks for generated geometry

The design is intentionally split so the .geo file stays geometry-only while the .meta.yaml file carries all physical and solver semantics.

---

## 2. The shared binding contract

Every authored surface or curve in the .geo file must be tagged with a physical name that follows the project contract:

`<role>::<layer>::<component>::<primitive>`

This string is parsed by the loader and used to connect the geometry to:

- the layer stack in the sidecar
- the GDS layer map
- the Palace physical-group naming
- the circuit-model bindings for terminals and islands

### 2.1 Allowed roles

The parser recognizes the following roles.

#### Surface roles

These are 2D entities and are treated as extrudable surfaces:

- `metal`
- `ground`
- `jj`
- `substrate`

#### Marker roles

These are 1D entities and are treated as markers rather than conductors:

- `port`
- `symmetry`

### 2.2 Parsing rules

The loader enforces these rules:

- the name must contain exactly four `::`-delimited fields
- the role must be known
- the layer field must be an integer
- the component field and primitive field must be non-empty
- a surface role must be attached to a 2D physical surface
- a marker role must be attached to a 1D physical curve

### 2.3 Example

```geo
Physical Surface("metal::1::Q1::pad_top") = { sret };
Physical Surface("ground::1::chip::gnd") = { sret };
Physical Curve("port::1::Q1::bias") = { l1 };
```

The first field is the semantic role, the second is the layer index, the third is the component name, and the fourth is the primitive name.

---

## 3. .geo grammar and authoring model

The .geo files in this project are written in Gmsh’s OpenCASCADE syntax, with the project using a very specific authoring style.

### 3.1 File-level structure

A typical .geo file contains:

1. a factory declaration
2. optional includes of helper libraries
3. numeric variables for geometry parameters
4. geometry creation statements
5. boolean operations for cutouts and unions
6. physical surface/curve tags

### 3.2 Minimal syntax elements

#### Comments

Comments use `//`.

```geo
// This is a comment.
```

#### Variable assignment

Variables are assigned using `=` and terminated by `;`.

```geo
cpw_w = 10;
pad_w = 120;
```

Expressions are plain arithmetic expressions.

```geo
gap_w = cpw_w + 2*gap;
```

#### Factory selection

The project uses the OpenCASCADE kernel.

```geo
SetFactory("OpenCASCADE");
```

#### Include helper macros

The example library [examples/dsl/geo/qlib.geo](../../examples/dsl/geo/qlib.geo) defines reusable geometry macros. It is included like this:

```geo
Include "qlib.geo";
```

### 3.3 Geometry creation primitives

The project relies on a small set of geometry operations that are common in the examples.

#### Points

```geo
p1 = newp; Point(p1) = { x, y, z };
```

#### Lines

```geo
l1 = newl; Line(l1) = { p1, p2 };
```

#### Curve loops and surfaces

```geo
cl = newll; Curve Loop(cl) = { l1, l2, l3, l4 };
 s = news; Plane Surface(s) = { cl };
```

#### Rectangle primitive

```geo
rect = news;
Rectangle(rect) = { x0, y0, 0, w, h };
```

### 3.4 Macro definitions and calls

The project uses macros heavily to keep the geometry readable and reusable.

#### Macro definition

```geo
Macro PAD
  sret = news;
  Rectangle(sret) = { cx - w/2, cy - h/2, 0, w, h };
Return
```

#### Macro call

```geo
Call PAD;
```

The macro contract is important: the geometry macro creates the geometry and writes the resulting surface tag into `sret`, while the author applies the physical tag afterwards.

This is a deliberate design pattern documented in [examples/dsl/geo/qlib.geo](../../examples/dsl/geo/qlib.geo): macros are geometry-only and do not carry semantic binding; the author assigns the physical surface name at the call site.

### 3.5 Boolean operations

Boolean operations are central to the project because they express cutouts and holes in a positive-tone geometry model.

#### Boolean difference

```geo
_diff() = BooleanDifference{ Surface{ sground }; Delete; }{ Surface{ tool }; Delete; };
```

This is used for ground cutouts and pockets, where a larger grounding sheet is cut by a tool surface to create vacuum gaps or pockets.

#### Boolean union

```geo
_cu() = BooleanUnion{ Surface{ _padb }; Delete; }{ Surface{ _neck, _paddle }; Delete; };
```

This is used to merge a pad with a neck and paddle into one conductor surface.

### 3.6 Physical tags

The .geo file uses physical tags to denote the semantic meaning of each geometric entity.

#### Physical surface

```geo
Physical Surface("metal::1::BUS::trace") = { sret };
```

#### Physical curve

```geo
Physical Curve("port::1::Q1::bias") = { l1 };
```

### 3.7 Project-specific usage patterns

#### Positive-tone conductors

The project uses a positive-tone convention:

- conductors (metal, jj) are created as positive surfaces
- subtractive features such as ground gaps and pockets are represented as cutouts in the ground sheet

This makes the geometry easy to reason about and keeps the mesh and GDS branches consistent.

#### Ground sheet synthesis

The geometry examples define a chip-wide ground face and cut holes out of it to create isolated regions, CPW gaps, and pockets.

Example from [examples/dsl/geo/chip_layout.geo](../../examples/dsl/geo/chip_layout.geo):

- a large rectangle is created as the base ground sheet
- multiple cutout operations carve vacuum gaps and qubit pockets
- the final face is tagged as `ground::1::chip::gnd`

#### JJ handling

The JJ is authored as a 2D surface but is treated semantically as a lumped element. The mesh branch removes it from the conductor set so it does not accidentally short the pads or corrupt the electrostatic solve.

Its physical role is therefore:

```geo
Physical Surface("jj::1::Q1::jj") = { sret };
```

---

## 4. .meta.yaml grammar and semantics

The .meta.yaml sidecar is the physics metadata file. It is parsed by the project’s sidecar parser and used as the entry point for the full build workflow.

### 4.1 Top-level keys

The parser recognizes the following top-level keys:

- `schema`
- `geo`
- `vars`
- `simulation`
- `circuit_model`
- `cells`

The exact allowed set is defined in [src/quantum_dsl/dsl/schema.py](../../src/quantum_dsl/dsl/schema.py).

### 4.2 Required schema header

The top-level `schema` key declares the DSL schema tag.

```yaml
schema: qiskit-metal/design-dsl/3
```

### 4.3 Geometry reference (`geo`)

The `geo` key points to the companion .geo file, relative to the sidecar file.

```yaml
geo: chip_layout.geo
```

If `geo` is absent, the sidecar may instead use a `cells:` block to generate geometry from v3 templates.

### 4.4 Variables (`vars`)

The `vars` block provides interpolation variables that can be substituted into the sidecar.

```yaml
vars:
  pad_width: 120
```

The parser resolves `${var}` expressions from this block. In the native .geo workflow the values are used in the metadata, not in the underlying .geo file itself.

### 4.5 Simulation block (`simulation`)

The `simulation` block is the main physics block. It is further divided into sub-blocks.

```yaml
simulation:
  gmsh:
    layer_stack: {}
    airbox: {}
    mesh: {}
    gds: {}
    solver: {}
```

#### 4.5.1 Layer stack (`simulation.gmsh.layer_stack`)

The layer stack is the mapping from integer layer indices in the .geo physical names to physical layer properties.

```yaml
simulation:
  gmsh:
    layer_stack:
      1:
        kind: metal
        thickness: 2
        z: 0
        material: pec
      3:
        kind: dielectric
        thickness: -750
        z: 0
        material: silicon
        eps_r: 11.45
```

Each layer entry may contain:

- `kind`: `metal` or `dielectric`
- `thickness`: a numeric value in micrometers
- `z`: vertical position in micrometers
- `material`: string identifier
- `eps_r`: relative permittivity for dielectrics
- `tan_delta`: optional loss tangent

The important detail is that the layer index in the .geo physical name must match the integer key used here.

#### 4.5.2 Airbox (`simulation.gmsh.airbox`)

The airbox defines the vacuum region around the chip.

```yaml
simulation:
  gmsh:
    airbox:
      top: 890
      bottom: 1650
      side_buffer: 200
```

Fields:

- `top`: vacuum thickness above the substrate
- `bottom`: vacuum thickness below the substrate
- `side_buffer`: padding around the chip extent

#### 4.5.3 Ports (`simulation.gmsh.ports`)

In the native .geo path, ports are bound by the physical-group name authored in the .geo file rather than by a component pin list. The parser accepts a list of entries.

```yaml
simulation:
  gmsh:
    ports:
      - pin: metal::1::Q1::pad_top
        type: lumped
```

Fields:

- `pin` or `group`: the physical-group name as authored in the .geo file
- `type`: `lumped` or `ground`
- `impedance`: optional impedance value
- `value`: optional numeric value

For the native .geo path the author should use the exact physical-group name given by the .geo file.

#### 4.5.4 Symmetry (`simulation.gmsh.symmetry`)

```yaml
simulation:
  gmsh:
    symmetry:
      - plane: x0
        condition: pec
```

Supported planes are `x0`, `y0`, and `z0`; supported conditions are `pec` and `pmc`.

#### 4.5.5 Mesh settings (`simulation.gmsh.mesh`)

```yaml
simulation:
  gmsh:
    mesh:
      max_size: 80
      min_size: 2
      max_size_jj: 0.5
      conductor_refine:
        min_dist: 2
        max_dist: 40
```

Fields:

- `max_size`: coarse mesh target in micrometers
- `min_size`: fine mesh target in micrometers
- `max_size_jj`: special sizing for the JJ region
- `conductor_refine`: refinement rule near conductors

#### 4.5.6 Output settings (`simulation.gmsh.output`)

```yaml
simulation:
  gmsh:
    output:
      format: msh2
      scaling: 1.0
```

#### 4.5.7 GDS settings (`simulation.gmsh.gds`)

The GDS block controls how the geometry is exported to GDSII using gdstk.

```yaml
simulation:
  gmsh:
    gds:
      lib_name: chip
      top_cell: chip
      unit: 1.0e-6
      precision: 1.0e-9
      arc_tol_um: 0.01
      union_same_layer: true
      default_datatype: 0
      by_role:
        metal: {layer: 1, datatype: 0}
        ground: {layer: 1, datatype: 0}
        jj: {layer: 20, datatype: 0}
```

This block supports:

- `lib_name`: output library name
- `top_cell`: top cell name
- `unit / precision`: gdstk writer settings
- `arc_tol_um`: tolerance for curved geometry sampling
- `union_same_layer`: whether to union shapes on same layer
- `default_datatype`: default GDS datatype
- `by_name`, `by_role`, `by_layer`: layer-map overrides

#### 4.5.8 Solver settings (`simulation.gmsh.solver`)

```yaml
simulation:
  gmsh:
    solver:
      type: Electrostatic
      order: 2
      l0: 1.0
```

The current project scope supports the `Electrostatic` solver; other families are deferred.

#### 4.5.9 Optional substrate gap override

```yaml
simulation:
  gmsh:
    substrate_gap_um: 0
```

This controls the gap between a carved ground and the substrate in the mesh branch when a small vacuum gap is needed for a robust geometry carve.

### 4.6 Circuit model block (`circuit_model`)

The optional `circuit_model` block maps conductor islands to qubit parameters so the capacitance matrix can be converted into a Hamiltonian model.

```yaml
circuit_model:
  qubits:
    - name: Q1
      island: metal::1::Q1::pad_top
      L_J: 10nH
```

Each qubit entry accepts:

- `name`: a human-readable qubit name
- `island` or `islands`: one or more conductor-island references
- exactly one of `L_J`, `E_J` or `squid`

The parser accepts SI-prefixed inductance strings such as `10nH` and frequency-form energy values such as `14GHz`.

A flux-tunable (and possibly asymmetric) qubit declares a `squid:` sub-block instead of a single junction energy:

```yaml
circuit_model:
  qubits:
    - name: CPLR
      islands: [metal::1::CPLR::pad_top, metal::1::CPLR::pad_bot]
      squid: {E_J1: 60GHz, E_J2: 11GHz, flux: 0.0}
```

`E_J1` and `E_J2` (both required) are the two parallel junctions and take exactly the same unit-bearing strings as `E_J`; `flux` is a bare, dimensionless float, the external flux normalised to the flux quantum (Φ/Φ0), default `0.0`. The solver reports the effective Josephson energy at that flux, `E_JΣ·sqrt(cos²(πΦ/Φ0) + d²sin²(πΦ/Φ0))` with `d = (E_J2 − E_J1)/(E_J1 + E_J2)` (Koch et al. 2007) — so zero flux gives `E_J1 + E_J2`, and a symmetric SQUID switches off at `flux: 0.5`.

### 4.7 Cells block (`cells`)

The `cells` block is an advanced feature that lets the project lower a v3 cell-library design into a generated .geo file instead of requiring a hand-authored geometry file.

```yaml
cells:
  - cell_type: transmon_pocket
    component: Q1
    x: "-700um"
    params:
      connection_pads: {}
```

Each cell entry contains:

- `cell_type`: template id
- `component`: globally unique component name
- `x`, `y`, `rot`, `layer`: placement options
- `params`: per-template overrides

When a `cells:` block is present, the geometry is generated by the emit_geo bridge and written to an elaborated .geo file. The geometry is then consumed by the same downstream GDS and mesh pipeline as a hand-authored .geo file.

---

## 5. How the pipeline uses the two files together

The build flow is:

1. read the .meta.yaml sidecar
2. resolve the companion .geo file or generated elaborated .geo file
3. load the geometry into Gmsh
4. parse the physical names and bind them to layers and roles
5. export to GDS and/or mesh the geometry
6. optionally run Palace and write a results artifact

### 5.1 Native .geo path

The native path is centered around [src/quantum_dsl/dsl/geo_build.py](../../src/quantum_dsl/dsl/geo_build.py).

It:

- loads the sidecar with the parser
- resolves the companion .geo or the generated cells flow
- builds the geometry mesh
- emits GDS
- runs the Palace solver if requested

### 5.2 Geometry loading and validation

The loader in [src/quantum_dsl/dsl/_gmsh_geo_source.py](../../src/quantum_dsl/dsl/_gmsh_geo_source.py) does the following:

- merges the .geo file into a Gmsh session
- snapshots the physical groups
- validates the physical names against the project’s `role::layer::component::primitive` contract
- maps the imported surfaces to the project’s internal geometry model

### 5.3 GDS branch

The GDS branch reads the same physical names and maps them to GDS layers using [src/quantum_dsl/dsl/parsers/simulation.py](../../src/quantum_dsl/dsl/parsers/simulation.py) and [src/quantum_dsl/dsl/gds_adapter.py](../../src/quantum_dsl/dsl/gds_adapter.py).

### 5.4 Mesh and Palace branch

The mesh branch uses the same imported geometry and converts the internal geometry to SI units before feeding it into Gmsh meshing and Palace configuration.

---

## 6. Common authoring rules and pitfalls

### 6.1 Use micrometers in .geo files

The .geo geometry is authored in micrometers. The adapters handle the conversion to SI for the mesh and solver stages.

### 6.2 Keep physical names exact

The physical name string is the project’s real contract. A mismatch between the .geo and the sidecar assumptions will break the binding.

### 6.3 Use positive-tone geometry for conductors

The project is organized around a positive-tone model:

- metal surfaces are created as positive surfaces
- ground sheets are cut by holes or gaps rather than being manually drawn as complex negative shapes

### 6.4 Be careful with ground cutouts

Ground pockets and gaps must be authored as actual boolean differences to preserve the intended vacuum regions and to avoid short circuits or incorrect conductor unions.

### 6.5 Use the `jj` role for Josephson junctions

The JJ should be authored as a separate surface with the `jj` role. The mesh branch treats it as a lumped element and does not mesh it as a conductor.

### 6.6 Keep component names unique when using `cells:`

The `component` field in the `cells:` block becomes part of the binding name. Duplicate names are rejected.

---

## 7. Minimal working example

### Minimal .geo example

```geo
SetFactory("OpenCASCADE");

pad = news;
Rectangle(pad) = { -50, -30, 0, 100, 60 };
Physical Surface("metal::1::P::pad") = { pad };
```

### Minimal sidecar example

```yaml
schema: qiskit-metal/design-dsl/3
geo: tiny_chip.geo

simulation:
  gmsh:
    layer_stack:
      1:
        kind: metal
        thickness: 2
        z: 0
        material: pec
    mesh:
      max_size: 80
      min_size: 2
    gds:
      lib_name: tiny_chip
      top_cell: tiny_chip
      by_role:
        metal: {layer: 1, datatype: 0}
    solver:
      type: Electrostatic
      order: 2
      l0: 1.0
```

This is the same pattern used by the fixture [tests/fixtures/tiny_chip.geo](../../tests/fixtures/tiny_chip.geo) and [tests/fixtures/tiny_chip.meta.yaml](../../tests/fixtures/tiny_chip.meta.yaml).

---

## 8. Recommended authoring workflow

1. Write the geometry in .geo using the project’s macro style.
2. Tag every surface and marker with a valid physical name.
3. Add a sidecar .meta.yaml with layer-stack and solver information.
4. Make sure the layer indices in the physical names match the layer_stack keys.
5. Validate the geometry with the project’s build workflow.

Typical command:

```powershell
$env:PYTHONPATH = "src"
python -m quantum_dsl.dsl.geo_build examples/dsl/geo/chip_layout.meta.yaml --out-dir build/demo
```

---

## 9. Summary

The project’s native geometry workflow combines two languages with one binding contract:

- the .geo file defines geometry and physical-group names
- the .meta.yaml file defines the physics interpretation and execution parameters
- the structured physical name `role::layer::component::primitive` is the shared key that links them together

That contract is what allows the same geometry to be consumed by:

- GDS export
- Gmsh meshing
- Palace electrostatic solving
- circuit-model Hamiltonian generation

This is the core grammar and usage model behind the project’s native Gmsh path.
