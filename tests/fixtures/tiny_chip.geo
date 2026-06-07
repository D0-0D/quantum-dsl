// =====================================================================
// tiny_chip.geo — minimal native-.geo fixture for fast round-trip tests.
//
// 单位: 微米 (µm). OpenCASCADE kernel. Self-contained (no Include) so it
// parses standalone and quickly:
//   - ONE metal rectangle   metal::1::P::pad   (100 µm × 60 µm, 居中)
//   - ONE ground sheet       ground::1::chip::gnd (300 µm × 300 µm) 带一个
//     矩形孔 (BooleanDifference 蚀刻出 80 µm × 40 µm 缺口)
//
// 用于 split_geo_name / load_geo / surface_outline_um / mesh-branch parity /
// GDS round-trip 的快速测试。
// =====================================================================

SetFactory("OpenCASCADE");

// ---- 1) metal rectangle (positive metal), centered at origin -------
pad = news;
Rectangle(pad) = { -50, -30, 0, 100, 60 };   // x[-50,50] y[-30,30]
Physical Surface("metal::1::P::pad") = { pad };

// ---- 2) ground sheet with one rectangular hole ---------------------
gnd  = news; Rectangle(gnd)  = { -150, -150, 0, 300, 300 };
hole = news; Rectangle(hole) = { -40,  -20,  0,  80,  40 };
diff() = BooleanDifference{ Surface{ gnd }; Delete; }{ Surface{ hole }; Delete; };
Physical Surface("ground::1::chip::gnd") = { diff(0) };
