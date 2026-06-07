# -*- coding: utf-8 -*-
"""Single source of truth for the DSL's internal length unit.

The DSL's internal / default length unit is the **micron (µm)**:

* Bare numbers in the YAML (e.g. ``width: 12``) mean ``12 µm``.
* Quantities carrying an explicit unit (``"12mm"``, ``"3nm"``, ``"0.5cm"`` …)
  are converted to µm (``"12mm"`` → ``12000``, ``"3nm"`` → ``0.003``).
* Every float stored in the IR or passed between DSL stages is expressed in µm,
  matching ``PrimitiveIR.geometry`` and the Gmsh adapter's input convention.

This is enforced by overriding qiskit-metal's *global* default parsing unit
(:data:`qiskit_metal.toolbox_metal.parsing.units`), which is the unit
``parse_value`` converts every length literal to.  Importing this module applies
the override as a side effect, so it must be imported before the first
``parse_value`` call — :mod:`quantum_dsl.dsl` (and the low-level
``_helpers`` / ``expression`` modules that call ``parse_value``) import it
eagerly for exactly that reason.

NOTE: the override is process-wide.  Because this package never instantiates
qlibrary components and exports its IR into a QDesign whose units are likewise
set to µm (see ``builder._instantiate_design``), the whole qiskit-metal length
pipeline stays self-consistent in µm.
"""

from __future__ import annotations

#: The DSL's internal length unit, as a pint-compatible string.
INTERNAL_UNIT = "um"

#: SI metres per internal unit (µm).  Adapters convert IR floats → SI by
#: multiplying with this factor (1 µm = 1e-6 m).
SI_PER_INTERNAL = 1e-6


def set_default_parsing_unit(unit: str = INTERNAL_UNIT) -> None:
    """Make qiskit-metal's ``parse_value`` resolve quantities into *unit*.

    qiskit-metal ships with ``millimetre`` as the default unit; calling this
    swaps it for *unit* (µm by default) so unit-less numbers as well as
    unit-bearing literals are normalised to the DSL's internal unit.
    """
    from qiskit_metal.toolbox_metal import parsing
    parsing.units = unit


# Apply on import so the override is active before any parse happens.
set_default_parsing_unit()
