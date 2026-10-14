import sys; sys.path.insert(0, '.')
from lib import *
um = 500/365.5
Q = {'Q0': (891.61, 495.16), 'Q1': (2185.71, 495.73)}
for thr in [96, 121, 146]:
  for name, (cx, cy) in Q.items():
    for cl, a0, span in [('cpl',[0,90,180,270],22),('RO',[225],16)]:
        E = []
        for a in a0:
            for da in np.arange(-span, span+0.01, 0.5):
                if abs(da) < 5 and cl == 'cpl': continue   # strip axis
                if abs(da) < 2 and cl == 'RO': continue    # feed line
                cr, p, t = ray(cx, cy, a+da, 180, 250, thr=thr)
                if len(cr) >= 3 and [s for r,s in cr[:3]] == [-1,1,-1]:
                    E.append([cr[0][0], cr[1][0], cr[2][0], da])
        E = np.array(E)*um; E[:,3] /= um
        gap = E[:,1]-E[:,0]; th = E[:,2]-E[:,1]
        # gap vs |angle| linear trend (concentricity test)
        k = np.polyfit(np.abs(E[:,3]), gap, 1)[0]
        print(f'thr{thr} {name} {cl}: Rdisc {E[:,0].mean():.2f} Rin {E[:,1].mean():.2f} Rout {E[:,2].mean():.2f} | gap {gap.mean():.2f} (sd {gap.std():.2f}, 2deg-bin range {np.ptp([gap[(np.abs(E[:,3])>=b)&(np.abs(E[:,3])<b+2)].mean() for b in range(6 if cl=="cpl" else 2, span-1, 2)]):.2f}, slope {k*10:+.2f}um/10deg) thick {th.mean():.2f} (sd {th.std():.2f}) n={len(E)}')
