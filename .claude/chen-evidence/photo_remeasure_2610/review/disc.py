import sys; sys.path.insert(0, '.')
from lib import *
def disc(cx0, cy0, thr=None, excl=25, verbose=False):
    pts = []
    for ang in np.arange(0, 360, 0.5):
        d = min(abs((ang - 135 + 180) % 360 - 180), abs((ang - 315 + 180) % 360 - 180))
        if d < excl: continue
        cr, p, t = ray(cx0, cy0, ang, 120, 300, thr=thr)
        if p[0] < 140: continue
        e = [r for r, s in cr if s == -1]
        if e: pts.append((ang, e[0]))
    pts = np.array(pts)
    a = np.radians(pts[:, 0])
    x = cx0 + pts[:, 1] * np.cos(a); y = cy0 - pts[:, 1] * np.sin(a)
    return pts, x, y
for name, c0 in [('Q0', (890, 495)), ('Q1', (2185, 495))]:
    for thr in [96, 121, 146]:
        pts, x, y = disc(*c0, thr=thr)
        cx, cy, r, sd = fit_circle(x, y)
        # robust: drop outliers >2 px and refit
        res = np.hypot(x - cx, y - cy) - r; k = np.abs(res) < 2
        cx, cy, r, sd = fit_circle(x[k], y[k])
        # halves: NE half ang in (-45,135) ; SW half
        ang = pts[k, 0]; ne = (ang > 315) | (ang < 135)
        h1 = fit_circle(x[k][ne], y[k][ne]); h2 = fit_circle(x[k][~ne], y[k][~ne])
        print(f'{name} thr{thr}: c=({cx:.2f},{cy:.2f}) Dpx={2*r:.2f} sd={sd:.2f} n={k.sum()}/{len(x)} | NE c=({h1[0]:.1f},{h1[1]:.1f}) D={2*h1[2]:.1f} | SW c=({h2[0]:.1f},{h2[1]:.1f}) D={2*h2[2]:.1f}')
