import os, sys, time, subprocess, json, yaml
from pathlib import Path
from quantum_dsl import compile_layout, load_meta, build_mesh
from quantum_dsl.palace import palace_config, parse_capacitance
from quantum_dsl.circuit_model import solve_circuit_model, H_PLANCK
out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
comps = ["Q01_a", "Q01_b", "H01", "H01_pent", "Q11_a", "Q11_b"]
m = load_meta("examples/chen_2025_3x3.meta.yaml")
import dataclasses
if os.environ.get("TOP"): m = dataclasses.replace(m, airbox={**m.airbox, "top_um": float(os.environ["TOP"])})
lay = compile_layout(m)
t = time.time()
mesh = build_mesh(lay.for_block(comps), m, out / "block_H01.msh")
print("mesh", round(time.time() - t), "s", mesh.num_volume_cells, "tets", flush=True)
cfg = palace_config(mesh, m, out / "block_H01.json")
env = dict(os.environ, HWLOC_COMPONENTS="-gl")
t = time.time()
r = subprocess.run([os.environ["PALACE_BIN"], "-np", os.environ.get("NP", "8"), "block_H01.json"], cwd=out, env=env, capture_output=True, text=True)
(out / "palace.log").write_text(r.stdout + "\n--- stderr ---\n" + r.stderr)
print("palace rc", r.returncode, round(time.time() - t), "s", flush=True)
if r.returncode:
    print(r.stdout[-3000:], r.stderr[-2000:]); sys.exit(1)
cap = parse_capacitance(out / "postpro", labels=mesh.labels)
doc = {"labels": list(cap.labels), "maxwell_fF": cap.maxwell_fF, "mutual_fF": cap.mutual_fF}
qs = [q for q in lay.qubits if q["name"] in ("Q01", "H01", "Q11")]
js = [{"name": q["name"], "islands": q["islands"], "E_J": q["E_J"] * H_PLANCK} for q in qs]
model = solve_circuit_model(cap.labels, cap.maxwell_fF, js)
doc["hamiltonian"] = {"qubits": [q.__dict__ | {"islands": list(q.islands)} for q in model.qubits],
                      "couplings": [c.__dict__ for c in model.couplings]}
(out / "results.yaml").write_text(yaml.safe_dump(doc, sort_keys=False))
print(yaml.safe_dump(doc, sort_keys=False))
