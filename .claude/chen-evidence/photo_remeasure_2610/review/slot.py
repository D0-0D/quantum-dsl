import sys; sys.path.insert(0, '.')
from lib import *
um = 500/365.5
for name, (cx, cy) in [('Q0', (891.61, 495.16)), ('Q1', (2185.71, 495.73))]:
  for thr in [96, 121, 146]:
    u = np.array([1, 1]) / np.sqrt(2); n = np.array([1, -1]) / np.sqrt(2)
    E1, E2 = [], []
    for s in np.r_[np.arange(-165, -35, 1.0), np.arange(35, 165, 1.0)]:
        x0, y0 = cx + s * u[0], cy + s * u[1]
        cr, p, t = line_prof(x0, y0, n[0], n[1], -70, 70, thr=thr)
        dn = [r for r, sg in cr if sg == -1]; up = [r for r, sg in cr if sg == 1]
        if len(dn) == 1 and len(up) == 1 and dn[0] < up[0]:
            E1.append((s, dn[0])); E2.append((s, up[0]))
    E1 = np.array(E1); E2 = np.array(E2)
    p1 = np.polyfit(E1[:, 0], E1[:, 1], 1); p2 = np.polyfit(E2[:, 0], E2[:, 1], 1)
    w = E2[:, 1] - E1[:, 1]
    ang1 = np.degrees(np.arctan(p1[0])); ang2 = np.degrees(np.arctan(p2[0]))
    mid0 = (p1[1] + p2[1]) / 2
    print(f'{name} thr{thr}: n={len(w)} width mean={w.mean():.2f}px ({w.mean()*um:.1f}um) sd={w.std():.2f}  edges tilt vs 45deg: {ang1:.2f},{ang2:.2f} deg  mid-line offset from disc centre={mid0:.2f}px  w(s<0)={w[E1[:,0]<0].mean():.2f} w(s>0)={w[E1[:,0]>0].mean():.2f}')
