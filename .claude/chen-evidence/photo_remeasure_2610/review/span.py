import sys; sys.path.insert(0, '.')
from lib import *
um = 500/365.5
Q = {'Q0': (891.61, 495.16), 'Q1': (2185.71, 495.73)}
def arc_ends(cx, cy, r, a0, thr=121):
    da = np.arange(-35, 35, 0.02)
    a = np.radians(a0 + da)
    p = samp(cx + r*np.cos(a), cy - r*np.sin(a))
    cr = crossings(p, thr, da)
    lo = max([c for c, s in cr if c < 0], default=np.nan); hi = min([c for c, s in cr if c > 0], default=np.nan)
    return lo, hi
for name, (cx, cy) in Q.items():
    for cl, a0, rr in [('E',0,(274,286,297)),('N',90,(274,286,297)),('W',180,(274,286,297)),('S',270,(274,286,297)),('RO',225,(268,289,310))]:
        out = []
        for r_um in rr:
            lo, hi = arc_ends(cx, cy, r_um/um, a0)
            # convert to tangential half-length (chord distance from axis) in um
            out.append(f'r={r_um}: {lo:+.2f}/{hi:+.2f} deg  (perp dist {r_um*np.sin(np.radians(-lo)):.1f}/{r_um*np.sin(np.radians(hi)):.1f} um)')
        print(name, cl, ' | '.join(out))
