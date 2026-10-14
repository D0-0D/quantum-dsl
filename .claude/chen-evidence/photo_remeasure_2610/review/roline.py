import sys; sys.path.insert(0, '.')
from lib import *
um = 500/365.5
cx, cy = 891.61, 495.16
d = np.array([-1, 1])/np.sqrt(2); n = np.array([1, 1])/np.sqrt(2)
for s in np.arange(225, 420, 8.0):
    cr, p, t = line_prof(cx+s*d[0], cy+s*d[1], n[0], n[1], -60, 60, step=0.1)
    print(f's={s*um:6.1f}um', [(round(r*um,1), sg) for r, sg in cr], ' min', round(p.min()), 'max', round(p.max()))
