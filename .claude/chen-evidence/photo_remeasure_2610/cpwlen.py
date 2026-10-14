"""读出焊盘内 CPW 两条缝的骨架总长 → λ/4 物理长度。用法: cpwlen.py ax-008.png seed_x seed_y"""
import sys, numpy as np
from PIL import Image
from scipy import ndimage as nd
from skimage.morphology import skeletonize
s = 1.37363
L = np.asarray(Image.open(sys.argv[1]).convert('L')).astype(float)
sx, sy = int(sys.argv[2]), int(sys.argv[3])
M = L > 125
lab, _ = nd.label(M)
pad = lab == lab[sy, sx]
from skimage.morphology import convex_hull_image
filled = convex_hull_image(pad)
inner = nd.binary_erosion(filled, iterations=4)
dark = inner & ~M
blobs = nd.binary_opening(dark, structure=np.ones((9, 9)))          # 两个开窗 (≈50 µm 方块)
blobs = nd.binary_dilation(blobs, iterations=3)
lines = dark & ~blobs
lab2, n = nd.label(lines, structure=np.ones((3, 3)))
sizes = nd.sum(lines, lab2, range(1, n + 1))
keep = np.isin(lab2, 1 + np.nonzero(sizes > 30)[0])
sk = skeletonize(keep)
# 链长: 4 邻 1, 对角 √2 (只在无共享 4 邻时计对角, 防三角重复)
ys, xs = np.nonzero(sk); P = set(zip(ys.tolist(), xs.tolist()))
tot = 0.0
for y, x in P:
    for dy, dx in ((0, 1), (1, 0)):
        if (y + dy, x + dx) in P: tot += 1
    for dy, dx in ((1, 1), (1, -1)):
        if (y + dy, x + dx) in P and (y + dy, x) not in P and (y, x + dx) not in P: tot += 2 ** 0.5
w_gap = lines.sum() / tot
print(f'缝骨架总长 {tot:.0f} px = {tot*s:.0f} µm (新标尺) → CPW 中心线 ≈ 一半 = {tot*s/2:.0f} µm; 旧标尺 ×1/1.285 = {tot*s/2/1.285:.0f} µm')
print(f'暗线平均宽 {w_gap:.2f} px = {w_gap*s:.1f} µm; 开窗块面积 {blobs.sum()*s*s:.0f} µm²; 连通线段 {int((sizes>30).sum())}')
Image.fromarray((np.dstack([sk*255, keep*120, blobs*200]).astype(np.uint8))).save(sys.argv[1].replace('ax-008.png', 'cpw_skel.png'))
