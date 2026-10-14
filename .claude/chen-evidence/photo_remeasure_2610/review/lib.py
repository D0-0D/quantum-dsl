import numpy as np
from PIL import Image

_D = '/tmp/claude-1000/-home-administrator-quantum-dsl-v4/12462065-54d4-43c8-9297-6c8d2bb6fe7c/scratchpad/review/'
A = np.asarray(Image.open(_D + 'img/ax-008.png')).astype(float)
Y = A @ [0.299, 0.587, 0.114]
MET, SUB = 172.0, 70.0
UM = 500.0 / 365.5  # um/px (see scale bar check); override in callers


def samp(x, y, img=Y):
    """bilinear sample at float arrays x,y"""
    x = np.asarray(x, float); y = np.asarray(y, float)
    x0 = np.floor(x).astype(int); y0 = np.floor(y).astype(int)
    fx = x - x0; fy = y - y0
    x0 = np.clip(x0, 0, img.shape[1] - 2); y0 = np.clip(y0, 0, img.shape[0] - 2)
    return (img[y0, x0] * (1 - fx) * (1 - fy) + img[y0, x0 + 1] * fx * (1 - fy)
            + img[y0 + 1, x0] * (1 - fx) * fy + img[y0 + 1, x0 + 1] * fx * fy)


def crossings(p, thr, t):
    """sub-sample positions (in units of t) where profile p crosses thr; sign +1 = dark->bright"""
    s = p - thr
    out = []
    for i in np.where(np.sign(s[1:]) != np.sign(s[:-1]))[0]:
        if s[i] == s[i + 1]:
            continue
        f = s[i] / (s[i] - s[i + 1])
        out.append((t[i] + f * (t[i + 1] - t[i]), 1 if s[i + 1] > 0 else -1))
    return out


def ray(cx, cy, ang_deg, r0, r1, step=0.25, thr=None, smooth=0):
    """profile along ray; angle in math convention with y UP (image y = cy - r sin)."""
    thr = (MET + SUB) / 2 if thr is None else thr
    t = np.arange(r0, r1, step)
    a = np.radians(ang_deg)
    p = samp(cx + t * np.cos(a), cy - t * np.sin(a))
    if smooth:
        k = np.ones(smooth) / smooth
        p = np.convolve(p, k, 'same')
    return crossings(p, thr, t), p, t


def line_prof(x0, y0, dx, dy, s0, s1, step=0.25, thr=None):
    thr = (MET + SUB) / 2 if thr is None else thr
    t = np.arange(s0, s1, step)
    p = samp(x0 + t * dx, y0 + t * dy)
    return crossings(p, thr, t), p, t


def fit_circle(x, y):
    x = np.asarray(x); y = np.asarray(y)
    M = np.c_[x, y, np.ones_like(x)]
    b = x * x + y * y
    c, *_ = np.linalg.lstsq(M, b, rcond=None)
    cx, cy = c[0] / 2, c[1] / 2
    r = np.sqrt(c[2] + cx * cx + cy * cy)
    res = np.hypot(x - cx, y - cy) - r
    return cx, cy, r, res.std()
