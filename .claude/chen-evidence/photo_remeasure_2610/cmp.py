"""SI §D 11 电容对照 + d 标定。用法: cmp.py results.yaml...  (H01 块: Q01 = SI Q0, Q11 = SI Q1)
SI 节点: 1 = Q0 非耦合侧半盘 (Q01_b, SW), 2 = Q0 耦合侧 (Q01_a, NE, 对着 E 爪), 3 = 条 H01, 4 = 五边形, 5 = Q1 非耦合侧 (Q11_a, NE), 6 = Q1 耦合侧 (Q11_b, SW, 对着 W 爪)。"""
import sys, yaml, math
import numpy as np
SI = {"C01": 137, "C02": 119, "C12": 23, "C03": 133, "C04": 165, "C34": 28, "C05": 137, "C06": 119, "C56": 23, "C23": 26, "C36": 26}
node = {1: "Q01_b", 2: "Q01_a", 3: "H01", 4: "H01_pent", 5: "Q11_a", 6: "Q11_b"}
rows = []
for f in sys.argv[1:]:
    doc = yaml.safe_load(open(f)); lab = doc["capacitance"]["labels"]; M = np.array(doc["capacitance"]["maxwell_fF"])
    ix = {l: i for i, l in enumerate(lab)}
    def C(k):
        a, b = int(k[1]), int(k[2])
        if a == 0: i = ix[node[b]]; return M[i].sum()          # 对地 = 行和 (含块外导体时只算块内)
        return -M[ix[node[a]], ix[node[b]]]
    vals = {k: C(k) for k in SI}
    qs = {q["name"]: q for q in doc.get("hamiltonian", {}).get("qubits", [])}
    rows.append((doc["info"]["d_um"], doc["info"]["case"], vals, qs, doc))
print(f'{"":5}' + "".join(f'{k:>9}' for k in SI))
print(f'{"SI":5}' + "".join(f'{v:9.0f}' for v in SI.values()))
for d, case, vals, qs, _ in rows:
    print(f'{d:<5g}' + "".join(f'{vals[k]:9.1f}' for k in SI) + f'   {case}')
    print(f'{"  ×SI":5}' + "".join(f'{vals[k]/SI[k]:9.2f}' for k in SI))
for d, case, vals, qs, _ in rows:
    print(f'd={d:g} {case}: ' + "  ".join(f'{n} E_C {q['E_C_GHz']*1e3:.1f} C_Σ {q['C_sigma_fF']:.1f} α_exact {q.get("anharmonicity_exact_MHz", float("nan")):.1f} f01 {q['f01_exact_GHz']:.3f}' for n, q in qs.items()))
if len(rows) >= 2:      # d 标定: log C04 vs log d 插值到 165
    ds = np.array([r[0] for r in rows]); c4 = np.array([r[2]["C04"] for r in rows])
    o = np.argsort(ds); ds, c4 = ds[o], c4[o]
    p = np.polyfit(np.log(ds), np.log(c4), 1)
    print(f'C04 ∝ d^{p[0]:.3f}; C04 = 165 → d = {math.exp((math.log(165) - p[1]) / p[0]):.2f} µm')
# α 在 f01 钉到实测 f_max 均值 4.139 GHz (Table SI 12 只) 时的精确值: E_J 二分
from quantum_dsl.circuit_model import transmon_levels_hz, H_PLANCK
def alpha_at(ec_ghz, f01=4.139e9):
    lo, hi = 1.0, 200.0
    for _ in range(60):
        ej = (lo + hi) / 2
        f, _ = transmon_levels_hz(ec_ghz * 1e9 * H_PLANCK, ej * 1e9 * H_PLANCK)
        lo, hi = (ej, hi) if f < f01 else (lo, ej)
    f, f12 = transmon_levels_hz(ec_ghz * 1e9 * H_PLANCK, lo * 1e9 * H_PLANCK)
    return (f12 - f) / 1e6, lo
for d, case, vals, qs, _ in rows:
    print(f'd={d:g} {case}: α@f01=4.139 → ' + "  ".join(f'{n} {alpha_at(q["E_C_GHz"])[0]:.1f} (E_J {alpha_at(q["E_C_GHz"])[1]:.2f})' for n, q in qs.items() if n.startswith("Q")))
