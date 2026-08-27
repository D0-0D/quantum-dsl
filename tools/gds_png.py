#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Render a GDS (µm) to PNG with PIL — metal light, substrate dark, jj layer magenta.

    python tools/gds_png.py build/x/foo.gds foo.png [px_per_um=2] [xmin,ymin,xmax,ymax]
"""
from __future__ import annotations

import sys

import gdstk
from PIL import Image, ImageDraw

METAL = (225, 225, 225)      # any layer-1 conductor (islands + ground sheet)
SUBSTRATE = (60, 60, 66)     # exposed Si (etched gaps)
JJ = (255, 0, 200)           # layer 20 lumped junctions


def main(argv):
    gds, out = argv[1], argv[2]
    scale = float(argv[3]) if len(argv) > 3 else 2.0
    lib = gdstk.read_gds(gds)
    cell = lib.top_level()[0]
    polys = cell.get_polygons(apply_repetitions=True, include_paths=True, depth=None)
    metal = [p for p in polys if p.layer != 20]
    jjs = [p for p in polys if p.layer == 20]
    if len(argv) > 4:
        x0, y0, x1, y1 = (float(v) for v in argv[4].split(","))
    else:
        (x0, y0), (x1, y1) = cell.bounding_box()
    W, H = int((x1 - x0) * scale) + 1, int((y1 - y0) * scale) + 1
    # substrate ground, then punch every etched gap dark, then paint junctions.
    # Boolean the full metal union against a covering rectangle → the true gaps, so
    # a keyholed ground polygon still renders with clean substrate gaps (PIL can't fill holes).
    img = Image.new("RGB", (W, H), METAL)
    d = ImageDraw.Draw(img)
    field = gdstk.rectangle((x0, y0), (x1, y1))
    for gap in gdstk.boolean(field, metal, "not"):
        d.polygon([((x - x0) * scale, (y1 - y) * scale) for x, y in gap.points], fill=SUBSTRATE)
    for p in jjs:
        d.polygon([((x - x0) * scale, (y1 - y) * scale) for x, y in p.points], fill=JJ)
    img.save(out)
    print(f"{out}: {W}x{H} px, {len(polys)} polygons, {scale} px/µm, bbox ({x0:.0f},{y0:.0f})-({x1:.0f},{y1:.0f})")


if __name__ == "__main__":
    main(sys.argv)
