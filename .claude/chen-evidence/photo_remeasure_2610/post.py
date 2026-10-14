"""远端 postpro 拉回后: C 矩阵 + 电路模型 → results.yaml。用法: post.py <outdir>"""
import sys, json, yaml
from pathlib import Path
from quantum_dsl import load_meta, compile_layout
from quantum_dsl.palace import parse_capacitance
from quantum_dsl.build import _results_doc, _merge, _in_scope
out = Path(sys.argv[1]); info = json.loads((out / "info.json").read_text())
m = load_meta(info["meta"]); lay = compile_layout(m)
cap = parse_capacitance(out / "postpro", labels=tuple(info["labels"]))
cm = dict(m.circuit_model or {})
qs = _merge(list(cm.get("qubits") or []), lay.qubits, "qubit")
cm = {"qubits": _in_scope(qs, cap.labels, "island"),
      "resonators": _in_scope(cm.get("resonators") or [], cap.labels, "net")}
doc = {"info": info, **_results_doc(cap, [], cm)}
(out / "results.yaml").write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
print("ok", out / "results.yaml")
