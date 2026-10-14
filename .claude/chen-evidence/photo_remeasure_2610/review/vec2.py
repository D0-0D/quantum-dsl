import re, sys, numpy as np
sys.path.insert(0, '.')
from lib import fit_circle
L = open('ax3.svg').read().splitlines()
S, T0x, T0y = 0.0424069, 7.869948, 14.369729
um = 500/365.5
def parse(i):
    ln = L[i-1]
    d = re.search(r' d="([^"]+)"', ln).group(1)
    m = re.search(r'transform="matrix\(([^)]+)\)"', ln)
    M = [float(v) for v in m.group(1).split(',')] if m else [1,0,0,1,0,0]
    toks = re.findall(r'[MLCZ]|-?[\d.]+(?:e-?\d+)?', d)
    arc=[]; verts=[]; cur=None; k=0; cmd=None
    while k < len(toks):
        t = toks[k]
        if t in 'MLCZ': cmd = t; k += 1; 
        if cmd == 'Z': cmd=None; continue
        n = {'M':2,'L':2,'C':6}[cmd]; v=[float(x) for x in toks[k:k+n]]; k+=n
        if cmd=='C':
            p0=np.array(cur); p1,p2,p3=np.array(v[0:2]),np.array(v[2:4]),np.array(v[4:6])
            for s in np.linspace(0,1,41): arc.append(((1-s)**3)*p0+3*((1-s)**2)*s*p1+3*(1-s)*s*s*p2+s**3*p3)
            cur=v[4:6]
        else: cur=v
        verts.append(cur)
    tr=lambda P: np.c_[((M[0]*P[:,0]+M[2]*P[:,1]+M[4])-T0x)/S, ((M[1]*P[:,0]+M[3]*P[:,1]+M[5])-T0y)/S]
    return tr(np.array(arc)) if arc else None, tr(np.array(verts))
metal={'Q0':(891.61,495.16,382.46/2),'Q1':(2185.71,495.73,383.11/2)}
for i,q in [(7325,'Q0'),(7327,'Q0'),(7329,'Q1'),(7331,'Q1')]:
    arc,_=parse(i); cx,cy,r,sd=fit_circle(arc[:,0],arc[:,1])
    mx,my,mr=metal[q]
    print(f'line {i} ({q}) vector arc: c=({cx:.2f},{cy:.2f}) R={r:.2f}px sd={sd:.3f} | vs metal: dR={(r-mr)*um:+.2f}um, dc=({(cx-mx)*um:+.2f},{(cy-my)*um:+.2f})um |dc|={np.hypot(cx-mx,cy-my)*um:.2f}um')
_,v=parse(7333); print('green pentagon vertices (px):', np.round(v,1).tolist())
