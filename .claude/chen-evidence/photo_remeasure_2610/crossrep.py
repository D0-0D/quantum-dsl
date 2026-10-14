"""十字结果摘要: 比特 / 耦合器 E_C、α (E_J 12.4 与 f01 钉 4.139 两种)、g、读出。用法: crossrep.py results.yaml..."""
import sys, yaml
sys.path.insert(0, sys.argv[0].rsplit('/', 1)[0])
from cmp import alpha_at
for f in sys.argv[1:]:
    doc = yaml.safe_load(open(f)); h = doc['hamiltonian']; d = doc['info']['d_um']
    q = {x['name']: x for x in h['qubits']}
    g = {(c['qubit_a'], c['qubit_b']): c['g_MHz'] for c in h['couplings']}
    ro = {r['qubit']: r for r in h.get('readout', [])}
    rs = h.get('resonators', [{}])[0]
    print(f"d={d:g}: 中心 Q11 C_Σ {q['Q11']['C_sigma_fF']:.1f} E_C {q['Q11']['E_C_GHz']*1e3:.1f} α(E_J12.4) {q['Q11']['anharmonicity_exact_MHz']:.1f} α@4.139 {alpha_at(q['Q11']['E_C_GHz'])[0]:.1f} | "
          f"臂 Q01 C_Σ {q['Q01']['C_sigma_fF']:.1f} α@4.139 {alpha_at(q['Q01']['E_C_GHz'])[0]:.1f} | 耦合器 E_C {q['H01']['E_C_GHz']*1e3:.1f} | "
          f"g_qc {g.get(('Q01','H01'), g.get(('H01','Q01'))):.1f}/{g.get(('Q11','H01'), g.get(('H01','Q11'))):.1f} g_qq {g.get(('Q11','Q01'), g.get(('Q01','Q11'))):.2f} | "
          f"读出 g {ro['Q11']['g_MHz']:.1f} χ {ro['Q11']['chi_MHz']:.3f} f_r(负载) {rs.get('f_r_GHz', 0):.3f}")
