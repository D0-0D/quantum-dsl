"""径向射线: 盘边 / 爪内外边, 每爪单独拟合圆。用法: rays.py img cx cy um_per_px [mode]"""
import sys, numpy as np
from PIL import Image
img, cx, cy, s = sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4])
mode = sys.argv[5] if len(sys.argv) > 5 else 'lum'
a = np.asarray(Image.open(img).convert('RGB')).astype(float)
if mode == 'lum':      # 原图: 金属亮, 衬底暗
    f = a.mean(axis=2); thr = 125.0; sign = 1
else:                   # 假彩: 与衬底色的距离
    f = np.linalg.norm(a - np.array([67, 71, 78.]), axis=2); thr = 18.0; sign = 1
H, W = f.shape
def samp(x, y):
    x0 = np.clip(np.floor(x).astype(int), 0, W - 2); y0 = np.clip(np.floor(y).astype(int), 0, H - 2)
    dx, dy = x - x0, y - y0
    return (f[y0, x0]*(1-dx)*(1-dy) + f[y0, x0+1]*dx*(1-dy) + f[y0+1, x0]*(1-dx)*dy + f[y0+1, x0+1]*dx*dy)
def kasa(P):
    x, y = P[:, 0], P[:, 1]
    A = np.c_[2*x, 2*y, np.ones_like(x)]; b = x*x + y*y
    c = np.linalg.lstsq(A, b, rcond=None)[0]
    r = np.sqrt(c[2] + c[0]**2 + c[1]**2)
    res = np.hypot(x - c[0], y - c[1]) - r
    return c[0], c[1], r, res.std()
r = np.arange(0, 420, 0.1)
def cast(cx, cy, step=0.5):
    out = []
    for th in np.arange(0, 360, step):
        t = np.radians(th); x = cx + r*np.cos(t); y = cy - r*np.sin(t)   # 角度逆时针, y 向上
        v = samp(x, y) > thr
        e = np.nonzero(np.diff(v.astype(int)))[0]          # 跳变下标
        runs = [(r[e[i]], r[e[i+1]]) for i in range(len(e)-1) if not v[e[i]]]  # 金属段
        out.append((th, runs))
    return out
def edges(cx, cy):
    pts = []
    for th, runs in cast(cx, cy):
        d = [q for q in runs if lo < q[1] < hi]
        if d: pts.append((th, d[0][1]))
    return pts
lo, hi = 100.0, 260.0
for it in range(4):
    P = edges(cx, cy)
    xy = np.array([(cx + rr*np.cos(np.radians(t)), cy - rr*np.sin(np.radians(t))) for t, rr in P])
    rad = np.array([rr for _, rr in P])
    keep = np.abs(rad - np.median(rad)) < 6
    cx, cy, Rd, sd = kasa(xy[keep]); lo, hi = Rd - 15, Rd + 15
print(f'盘: 心 ({cx:.1f},{cy:.1f}) px  R = {Rd:.1f} px = {Rd*s:.1f} µm  D = {2*Rd*s:.1f} µm  残差 σ {sd:.2f} px  点 {keep.sum()}')
# 爪: 盘边之后的下一段金属, 起点在 Rd+2..Rd+40
cl = []
for th, runs in cast(cx, cy, 0.25):
    rr = [q for q in runs if Rd + 2 < q[0] < Rd + 40 and q[1] - q[0] < 120]
    if rr: cl.append((th, rr[0][0], rr[0][1]))
cl = np.array(cl)
# 按角度连续分组
groups, cur = [], [cl[0]]
for row in cl[1:]:
    if row[0] - cur[-1][0] <= 0.5: cur.append(row)
    else: groups.append(np.array(cur)); cur = [row]
groups.append(np.array(cur))
if len(groups) > 1 and groups[0][0, 0] < 0.3 and groups[-1][-1, 0] > 359.5:
    g = groups.pop(); g[:, 0] -= 360; groups[0] = np.vstack([g, groups[0]])
print(f'{"爪(中心角)":>10} {"角跨":>6} {"内径Δ":>7} {"内缘拟合心偏移":>18} {"内缘R":>7} {"外缘R":>7} {"间隙中段":>14} {"厚度中段":>8}  (µm)')
for g in groups:
    if g[-1, 0] - g[0, 0] < 5: continue
    g = g[3:-3]   # 去掉端头圆角
    th = np.radians(g[:, 0])
    pin = np.c_[cx + g[:, 1]*np.cos(th), cy - g[:, 1]*np.sin(th)]
    pout = np.c_[cx + g[:, 2]*np.cos(th), cy - g[:, 2]*np.sin(th)]
    xi, yi, ri, si = kasa(pin); xo, yo, ro, so = kasa(pout)
    mid = np.abs(g[:, 0] - g[:, 0].mean()) < 0.25*(g[-1, 0] - g[0, 0])
    gap = (g[mid, 1] - Rd)*s; thk = (g[mid, 2] - g[mid, 1])*s
    print(f'{g[:,0].mean():10.1f} {g[-1,0]-g[0,0]+1.5:6.1f} {(ri-Rd)*s:7.1f}   ({(xi-cx)*s:+6.1f},{-(yi-cy)*s:+6.1f}) |{np.hypot(xi-cx,yi-cy)*s:5.1f}| {ri*s:7.1f} {ro*s:7.1f}  {gap.min():5.1f}–{gap.max():5.1f} {thk.mean():8.1f}')
print('--- 间隙/厚度 vs 角度 (µm), 每 2°')
for g in groups:
    if g[-1, 0] - g[0, 0] < 5: continue
    sel = g[::8]
    print(f'{g[:,0].mean():6.1f}°: ' + ' '.join(f'{t:5.1f}:{(a_-Rd)*s:4.1f}/{(b_-a_)*s:4.1f}' for t, a_, b_ in sel))
