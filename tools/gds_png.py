#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""GDS → PNG 命令行 (quantum_dsl.gds.render_gds_png 的薄壳; build() 已自动产 <stem>.gds.png,
本脚本只为换比例 / 裁剪; jj 层固定按 20 画品红)。

    PYTHONPATH=src python tools/gds_png.py foo.gds foo.png [px_per_um] [xmin,ymin,xmax,ymax]
"""
import sys

from quantum_dsl.gds import render_gds_png

a = sys.argv
bbox = None
if len(a) > 4:
    x0, y0, x1, y1 = (float(v) for v in a[4].split(","))
    bbox = ((x0, y0), (x1, y1))
print(render_gds_png(a[1], a[2], jj_layers=(20,),
                     px_per_um=float(a[3]) if len(a) > 3 else None, bbox=bbox))
