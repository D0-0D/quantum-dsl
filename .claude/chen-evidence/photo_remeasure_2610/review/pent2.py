import sys; sys.path.insert(0, '.')
from lib import *
um = 500/365.5
def measure(orient, X0, X1, Y0, Y1, thr=121, base_sign=+1, verbose=True):
    """orient 'h': pentagon above horizontal strip, roof up (−y). 'v': pentagon right of vertical strip, roof to +x.
    Work in a local frame (a = along-strip coordinate, b = height away from strip, increasing toward apex)."""
    if orient == 'h':
        def prof_b(a, b0, b1):  # along b (decreasing image y)
            cr,p,t = line_prof(a, b0, 0, -1, 0, b0-b1, thr=thr); return [(b0-c, s) for c,s in cr]
        def prof_a(bimg, a0, a1):
            cr,p,t = line_prof(a0, bimg, 1, 0, 0, a1-a0, thr=thr); return [(a0+c, s) for c,s in cr]
    else:
        def prof_b(a, b0, b1):  # a = image y, b = image x increasing
            cr,p,t = line_prof(b0, a, 1, 0, 0, b1-b0, thr=thr); return [(b0+c, s) for c,s in cr]
        def prof_a(bimg, a0, a1):
            cr,p,t = line_prof(bimg, a0, 0, 1, 0, a1-a0, thr=thr); return [(a0+c, s) for c,s in cr]
    # 1) base edge & apex/roof: profiles along b at each a
    base=[]; top=[]
    for a in np.arange(X0, X1, 1.0):
        cr = prof_b(a, Y0, Y1)
        ups=[c for c,s in cr if s==1]; dns=[c for c,s in cr if s==-1]
        if ups and dns: base.append((a, ups[0])); top.append((a, dns[-1]))
    base=np.array(base); top=np.array(top)
    return base, top, prof_a
def analyse(name, orient, X0, X1, Y0, Y1, thr=121):
    base, top, prof_a = measure(orient, X0, X1, Y0, Y1, thr)
    # walls: from crude extents
    aL, aR = base[0,0], base[-1,0]
    # walls measured at b positions between base+15 and base+150 (image coords along b)
    bb = np.median(base[:,1])
    walls=[]
    for k in np.arange(15, 140, 1.0):
        bimg = (bb - k) if orient=='h' else (bb + k)
        cr = prof_a(bimg, X0, X1)
        ups=[c for c,s in cr if s==1]; dns=[c for c,s in cr if s==-1]
        if ups and dns: walls.append((k, ups[0], dns[-1]))
    walls=np.array(walls)
    wl=np.median(walls[:,1]); wr=np.median(walls[:,2]); ac=(wl+wr)/2
    # base: exclude centre ±45 px (SQUID lead) and corners ±20 px
    kb=(np.abs(base[:,0]-ac)>45)&(base[:,0]>wl+20)&(base[:,0]<wr-20)
    pb=np.polyfit(base[kb,0], base[kb,1], 1)
    bb=np.polyval(pb, ac)
    # height h(a) = distance from base
    sgn = -1 if orient=='h' else 1
    h = sgn*(top[:,1]-bb)
    # roof: fit h vs a on the two flanks
    kL=(top[:,0]>wl+35)&(top[:,0]<ac-30); kR=(top[:,0]>ac+30)&(top[:,0]<wr-35)
    pL=np.polyfit(top[kL,0],h[kL],1); pR=np.polyfit(top[kR,0],h[kR,1] if False else h[kR],1)
    aa=(pR[1]-pL[1])/(pL[0]-pR[0]); ha=np.polyval(pL,aa)
    hsL=np.polyval(pL,wl); hsR=np.polyval(pR,wr)
    # rounding: measured apex
    hap=h[np.argmin(np.abs(top[:,0]-aa))]
    angL=np.degrees(np.arctan(pL[0])); angR=np.degrees(np.arctan(-pR[0]))
    print(f'{name} thr{thr}: walls a={wl:.2f},{wr:.2f} (sd {walls[:,1].std():.2f},{walls[:,2].std():.2f}) base b={bb:.2f} tilt {np.degrees(np.arctan(pb[0])):+.3f}deg | width {(wr-wl)*um:.1f}um wall(sharp) {hsL*um:.1f}/{hsR*um:.1f} apex(sharp) h={ha*um:.1f} at a={aa:.2f} (vs centre {ac:.2f}) measured apex h={hap*um:.1f} | roof angles {angL:.2f},{angR:.2f} deg')
    return dict(wl=wl, wr=wr, ac=ac, bb=bb, ha=ha, aa=aa, hs=(hsL+hsR)/2)
r1 = analyse('H-pent (Q0-Q1)', 'h', 1470, 1890, 470, 60)
r2 = analyse('H-pent (left of Q0)', 'h', 180, 600, 470, 60)
r3 = analyse('V-pent (below Q0)', 'v', 790, 1220, 905, 1300)
r4 = analyse('V-pent (below Q1)', 'v', 790, 1220, 2200, 2600)
np.save('pents.npy', [r1, r2, r3, r4], allow_pickle=True)
