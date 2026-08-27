// =====================================================================
// sung_2021_xmon.geo — Sung et al. PRX 11, 021058 (2021) 论文真版图的**参数化**重建。
// 拓扑 = 两只接地 Xmon 十字 + 一个接地梳齿 coupler, 一字排开 (QB1 — CPLR — QB2)。
//
// 下面每个数字都是从 Fig. 1(c) 显微照片**量出来**的 (tools/micrograph_to_geo.py 矢量化后在多边形上
// 精确读取; 1 px = 1.516 µm, 每条边 ±1 px ≈ ±1.5 µm), 不是设计值, 也没有任何为凑论文而调的旋钮。
// 照片保真的逐点描摹版 (426 顶点, 含控制/读出线与 SQUID 框) 是 sung_2021_xmon_traced.geo;
// 本文件按 Xmon 十字、梳齿两种理想形状把它压成 ~20 个参数, 省掉视场内的走线、空气桥与 SQUID 框——
// 两者的 FEM 差别见 sung_2021_xmon.meta.yaml 头注。原点 = 照片中心, y 向上, 单位 µm。
// =====================================================================

SetFactory("OpenCASCADE");
Include "qlib.geo";

// ---- Xmon (measured) -------------------------------------------------
xm_w   = 30.3;            // arm width (20 px)
q1_cx  = -352.5;  q1_cy = -44.5;  q1_L = 339;  q1_g = 32.2;   // QB1 centre, tip-to-tip span, arm→ground gap
q2_cx  =  350.2;  q2_cy = -44.3;  q2_L = 342;  q2_g = 30.7;   // QB2 (centre distance 702.7)

// ---- comb coupler (measured) ----------------------------------------
c_x0 = -273.7;  c_x1 = 272.1;      // bottom bar x extent
c_y0 =   34.9;  c_y1 =  60.6;      // bottom bar y extent (thickness 25.7)
c_tooth_w   = 24.5;                // tooth width (16-17 px)
c_tooth_top = 185.0;               // tooth top y (all six equal; tooth length 124.4)
c_g         = 26.5;                // comb → ground gap, uniform on all sides
c_tooth_x() = { -261.5, -163.0, -64.1, 48.5, 160.7, 259.3 };   // tooth centres (pitch 98.6 / 98.6 / 112.6 / 112.2 / 98.6)
                                                                // ⇒ ground fingers = pitch − tooth − 2 g ≈ 21 (measured 20.5)
jj_w = 2;                          // lumped JJ bar (GDS layer 20 only, never meshed)

g_w = 1900; g_h = 1240;            // ground sheet = photographed field (1398 × 741) + ~250 margin

// ---- 1) QB1, QB2 -----------------------------------------------------
cx = q1_cx; cy = q1_cy; xm_L = q1_L; xm_g = q1_g;
Call XMON;
isl_QB1 = sret; moat_QB1 = mret;
Physical Surface("metal::1::QB1::island") = { isl_QB1 };

cx = q2_cx; cy = q2_cy; xm_L = q2_L; xm_g = q2_g;
Call XMON;
isl_QB2 = sret; moat_QB2 = mret;
Physical Surface("metal::1::QB2::island") = { isl_QB2 };

// ---- 2) comb coupler: bar ∪ teeth; moat = same rectangles grown by c_g --------------
comb = news; Rectangle(comb) = { c_x0, c_y0, 0, c_x1 - c_x0, c_y1 - c_y0 };
moat = news; Rectangle(moat) = { c_x0 - c_g, c_y0 - c_g, 0, c_x1 - c_x0 + 2*c_g, c_y1 - c_y0 + 2*c_g };
For i In {0:5}
  t = news; Rectangle(t) = { c_tooth_x(i) - c_tooth_w/2, c_y0, 0, c_tooth_w, c_tooth_top - c_y0 };
  u() = BooleanUnion{ Surface{ comb }; Delete; }{ Surface{ t }; Delete; };
  comb = u(0);
  t = news; Rectangle(t) = { c_tooth_x(i) - c_tooth_w/2 - c_g, c_y0, 0, c_tooth_w + 2*c_g, c_tooth_top - c_y0 + c_g };
  u() = BooleanUnion{ Surface{ moat }; Delete; }{ Surface{ t }; Delete; };
  moat = u(0);
EndFor
Physical Surface("metal::1::CPLR::island") = { comb };

// ---- 3) ground sheet minus the three moats -------------------------------------
gnd = news; Rectangle(gnd) = { -g_w/2, -g_h/2, 0, g_w, g_h };
gd() = BooleanDifference{ Surface{ gnd }; Delete; }{ Surface{ moat_QB1, moat_QB2, moat }; Delete; };
Physical Surface("ground::1::chip::gnd") = { gd(0) };

// ---- 4) junctions: arm tip → ground across the gap ------------------------------
x1 = q1_cx; y1 = q1_cy + q1_L/2; x2 = q1_cx; y2 = q1_cy + q1_L/2 + q1_g; width = jj_w;
Call JUNCTION;
Physical Surface("jj::1::QB1::jj") = { sret };

x1 = c_tooth_x(3); y1 = c_tooth_top; x2 = c_tooth_x(3); y2 = c_tooth_top + c_g; width = jj_w;
Call JUNCTION;
Physical Surface("jj::1::CPLR::jj") = { sret };

x1 = q2_cx; y1 = q2_cy - q2_L/2; x2 = q2_cx; y2 = q2_cy - q2_L/2 - q2_g; width = jj_w;
Call JUNCTION;
Physical Surface("jj::1::QB2::jj") = { sret };
