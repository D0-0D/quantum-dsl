import sys; sys.path.insert(0, '.')
from lib import *
um = 500/365.5
def hstrip(xs, yc, thr=121):
    W=[]
    for x in xs:
        cr,p,t = line_prof(x, yc-45, 0, 1, 0, 90, thr=thr)
        if len(cr)==2 and cr[0][1]==1: W.append((x, cr[0][0]+yc-45, cr[1][0]+yc-45))
    return np.array(W)
def vstrip(ys, xc, thr=121):
    W=[]
    for y in ys:
        cr,p,t = line_prof(xc-45, y, 1, 0, 0, 90, thr=thr)
        if len(cr)==2 and cr[0][1]==1: W.append((y, cr[0][0]+xc-45, cr[1][0]+xc-45))
    return np.array(W)
for thr in [96,121,146]:
    for lab, W in [('H Q0-Q1', hstrip(np.arange(1120,1960,1.0), 495, thr)), ('H left of Q0', hstrip(np.arange(5,660,1.0), 495, thr)),
                   ('H right of Q1', hstrip(np.arange(2420,2670,1.0), 496, thr)),
                   ('V above Q0', vstrip(np.arange(5,270,1.0), 891, thr)), ('V below Q0', vstrip(np.arange(720,1300,1.0), 891, thr)),
                   ('V above Q1', vstrip(np.arange(5,270,1.0), 2185, thr)), ('V below Q1', vstrip(np.arange(720,1300,1.0), 2185, thr))]:
        w = W[:,2]-W[:,1]; c = (W[:,2]+W[:,1])/2
        k = np.abs(w-np.median(w))<3
        sl = np.polyfit(W[k,0], c[k], 1)
        print(f'thr{thr} {lab:13s}: n={k.sum()} width {w[k].mean():.2f}px = {w[k].mean()*um:.2f}um sd {w[k].std()*um:.2f}; centre-line {np.median(c[k]):.2f} px, tilt {np.degrees(np.arctan(sl[0]))*1:+.3f} deg; range {W[k,0].min():.0f}-{W[k,0].max():.0f}')
