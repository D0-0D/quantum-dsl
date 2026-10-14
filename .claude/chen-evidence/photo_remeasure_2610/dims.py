"""arXiv 原图 (2675x1382, 1.37363 µm/px) 上量主要尺寸。y 向下为图像坐标, 输出换成 y 向上。"""
import sys, numpy as np
from PIL import Image
from scipy import ndimage as nd
s = 1.37363
a = np.asarray(Image.open(sys.argv[1]).convert('RGB')).astype(float)
L = a.mean(axis=2); M = L > 125
Q0 = np.array([891.6, 495.1]); Q1 = np.array([2185.6, 495.6])
def run_len(x0, y0, ux, uy, half=60, want=True):
    t = np.arange(-half, half, 0.05)
    v = nd.map_coordinates(L, [y0 + t*uy, x0 + t*ux], order=1) > 125
    v = v if want else ~v
    i0 = np.argmin(np.abs(t))
    if not v[i0]: return np.nan
    lo = i0;  hi = i0
    while lo > 0 and v[lo-1]: lo -= 1
    while hi < len(t)-1 and v[hi+1]: hi += 1
    return (t[hi] - t[lo]) * s
# 1 中缝: 沿缝方向 (图像里 NW→SE: ux=+, uy=+) 取点, 垂直方向 (NE: ux=+, uy=-) 量衬底游程
d = np.array([1, 1])/np.sqrt(2); n = np.array([1, -1])/np.sqrt(2)
for Q, nm in ((Q0, 'Q0'), (Q1, 'Q1')):
    w = [run_len(*(Q + k*d), *n, want=False) for k in list(range(-150, -60, 5)) + list(range(60, 150, 5))]
    print(f'{nm} 中缝宽 {np.nanmedian(w):.1f} µm (范围 {np.nanmin(w):.1f}–{np.nanmax(w):.1f})')
# 2 横条宽 (Q0–Q1 之间) 与竖条宽 (Q0 下方)
hb = [run_len(x, 495.3, 0, 1) for x in range(1150, 1950, 20)]
vb = [run_len(891.6, y, 1, 0) for y in range(780, 1300, 20)]
print(f'横条宽 {np.nanmedian(hb):.1f} ({np.nanmin(hb):.1f}–{np.nanmax(hb):.1f}); 竖条宽 {np.nanmedian(vb):.1f} ({np.nanmin(vb):.1f}–{np.nanmax(vb):.1f})')
# 3 连通分量: 五边形 (横向耦合器, Q0–Q1 之间条上方) / 纵向耦合器五边形 (Q0 下方右侧) / 读出焊盘 (Q0 左下)
lab, nlab = nd.label(M)
def comp(px, py):
    k = lab[int(py), int(px)]; ys, xs = np.nonzero(lab == k); return k, xs, ys
def rel(x, y, Q): return ((x - Q[0])*s, (Q[1] - y)*s)
for nm, seed, Q in (('横向五边形', (Q1[0]-540/s*1.27, 495-150/s*1.27), Q1), ('纵向五边形', (Q0[0]+200, Q0[1]+520), Q0), ('读出焊盘', (Q0[0]-560, Q0[1]+560), Q0)):
    k, xs, ys = comp(*seed)
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    print(f'{nm}: bbox {(x1-x0+1)*s:.0f} × {(y1-y0+1)*s:.0f} µm, 面积 {len(xs)*s*s:.0f} µm², bbox 中心相对比特 ({rel((x0+x1)/2,(y0+y1)/2,Q)[0]:+.0f}, {rel((x0+x1)/2,(y0+y1)/2,Q)[1]:+.0f}), 质心 ({rel(xs.mean(),ys.mean(),Q)[0]:+.0f}, {rel(xs.mean(),ys.mean(),Q)[1]:+.0f})')
    if nm == '横向五边形':
        # 底边 y1 (图像下沿) 到横条上沿的缝; 逐行宽度 → 直壁高度
        strip_top = 495.3 - np.nanmedian(hb)/2/s
        print(f'   底边到横条上沿缝 {(strip_top - y1)*s:.1f} µm')
        wid = np.array([(xs[ys == y].max() - xs[ys == y].min() + 1)*s for y in range(y0, y1+1)])
        full = wid > wid.max() - 3
        print(f'   底宽 {wid.max():.0f}, 等宽段高 {full.sum()*s:.0f}, 总高 {(y1-y0+1)*s:.0f}, 屋顶高 {(y1-y0+1-full.sum())*s:.0f}')
    if nm == '纵向五边形':
        vstrip_right = 891.6 + np.nanmedian(vb)/2/s
        print(f'   底边到竖条右沿缝 {(x0 - vstrip_right)*s:.1f} µm')
        wid = np.array([(ys[xs == x].max() - ys[xs == x].min() + 1)*s for x in range(x0, x1+1)])
        full = wid > wid.max() - 3
        print(f'   底宽 {wid.max():.0f}, 等宽段 {full.sum()*s:.0f}, 总高 {(x1-x0+1)*s:.0f}')
# 4 半盘面积
k, xs, ys = comp(Q0[0]+80, Q0[1]-80); A1 = len(xs)*s*s
k, xs, ys = comp(Q0[0]-80, Q0[1]+80); A2 = len(xs)*s*s
print(f'Q0 两半盘面积 {A1:.0f} / {A2:.0f} µm² (含 SQUID 引线)')
# 5 爪角跨: 在爪厚度中线半径上扫角度
R = 191.2; th = np.radians(np.arange(0, 360, 0.1))
for rr, nm in ((R + (9.6 + 14.5)/s, '耦合器爪中线'), (R + (3.6 + 24)/s, '读出爪中线')):
    v = nd.map_coordinates(L, [Q0[1] - rr*np.sin(th), Q0[0] + rr*np.cos(th)], order=1) > 125
    e = np.nonzero(np.diff(v.astype(int)))[0]; deg = np.degrees(th)
    segs = [(deg[e[i]+1], deg[e[i+1]]) for i in range(len(e)-1) if v[e[i]+1]]
    print(nm, ' '.join(f'[{a_:.1f},{b_:.1f}]' for a_, b_ in segs))
