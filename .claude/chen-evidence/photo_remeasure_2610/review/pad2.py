import sys; sys.path.insert(0, '.')
from lib import *
um = 500/365.5
R = np.load('rot.npy'); u0, v0 = -1000, -450
u = np.arange(R.shape[1]) + u0; v = np.arange(R.shape[0]) + v0
def edges_rows(vs, ulo, uhi, thr=121, sign=None):
    out=[]
    for vv in vs:
        p = R[int(vv - v0)]; m=(u>=ulo)&(u<=uhi)
        c=[x for x,s in crossings(p[m], thr, u[m]) if sign is None or s==sign]
        if len(c)==1: out.append(c[0])
    return np.array(out)
def edges_cols(us, vlo, vhi, thr=121, sign=None):
    out=[]
    for uu in us:
        p = R[:, int(uu - u0)]; m=(v>=vlo)&(v<=vhi)
        c=[x for x,s in crossings(p[m], thr, v[m]) if sign is None or s==sign]
        if len(c)==1: out.append(c[0])
    return np.array(out)
for thr in [96,121,146]:
    L = edges_rows(np.r_[-240:-120, 120:235], -900, -820, thr)      # left edge
    Rr = edges_rows(np.r_[-240:-80, 80:235], -400, -340, thr)     # right edge main
    T = edges_cols(np.r_[-840:-380], -290, -220, thr)             # top edge (v min)
    B = edges_cols(np.r_[-840:-380], 220, 290, thr)
    Tr = edges_rows(np.r_[-50:-10, 10:50], -345, -300, thr)       # tab outer edge
    Tt = edges_cols(np.r_[-355:-330], -120, -20, thr)             # tab top/bottom (v)
    Tb = edges_cols(np.r_[-355:-330], 20, 120, thr)
    print(f'thr{thr}: left {L.mean():.2f}({L.std():.2f}) right {Rr.mean():.2f}({Rr.std():.2f}) top {T.mean():.2f}({T.std():.2f}) bot {B.mean():.2f}({B.std():.2f}) | tab outer {Tr.mean():.2f} tab v {Tt.mean():.2f}..{Tb.mean():.2f}')
    W = Rr.mean()-L.mean(); H = B.mean()-T.mean()
    uc=(Rr.mean()+L.mean())/2; vc=(B.mean()+T.mean())/2
    e1=np.array([1,-1])/np.sqrt(2); e2=np.array([1,1])/np.sqrt(2)
    off=uc*e1+vc*e2
    print(f'   side u {W*um:.1f} um, side v {H*um:.1f} um; centre (u,v)=({uc*um:.1f},{vc*um:.1f}) um ; image dx={off[0]*um:.1f} dy(up)={-off[1]*um:.1f} um; tab: protrude {(Tr.mean()-Rr.mean())*um:.1f} um, width {(Tb.mean()-Tt.mean())*um:.1f} um, centre v {(Tb.mean()+Tt.mean())/2*um:.1f} um; tab outer edge at {-Tr.mean()*um:.1f} um from Q0 centre')
