// =====================================================================
// qm4q_transmon_cell.geo — 复现 qiskit-metal 教程 "1.3 Build a 4-qubit
// chip" 里单个 TransmonPocket (Q1), 作为 LOM cell 做电容矩阵对比。
//
// 单位: 微米 (µm). OpenCASCADE kernel. Positive metal tone (CPW gap / pocket
// 用 BooleanDifference 从 ground sheet 蚀刻)。
//
// 几何 (single metal layer 1 + dielectric substrate layer 3, 衬底自动补):
//   - pad_top / pad_bot  : 2 块主焊盘 (450×90µm, 间距 pad_gap=30µm)
//   - conn_a..conn_d     : 4 个连接 pad + 各自 CPW 引线 (open pin), 同名标注成
//                          一个导体 (= qiskit-metal 的 net: connector_pad + wire)
//   - JJ                 : 跨 pad_gap (lumped, 管线移除, 仅供 GDS)
//   - ground sheet       : 1250×1050µm, 蚀刻 650×650 pocket + 4 条引线 CPW gap
//
// 坐标取自 qiskit-metal 实渲染几何 (MultiPlanar, pos=origin):
//   pad_top  x[-225,225]  y[ 15,105]      conn_a pad x[100,225] y[120,150]
//   pad_bot  x[-225,225]  y[-105,-15]     conn_b pad x[-225,-100] y[120,150]
//   pocket   x[-325,325]  y[-325,325]     conn_c pad x[25,225]  y[-150,-120]
//   ground   x[-625,625]  y[-525,525]     conn_d pad x[-225,-100] y[-170,-120]
//   引线 25µm 宽 (gap 49µm), 由 pad 边伸到 x=±425 的开路端。
//
// ⚠ 构造要点 (OCC .geo tag 稳定性, 踩坑记录):
//   1. **ground 先建**: GROUND_POCKET / GROUND_CUTOUT 是 BooleanDifference,
//      会重编号/复用 surface tag。放在所有金属 Physical 标注 *之前* 做完, 之后
//      再无 Boolean 扰动金属面 → 金属 tag 稳定。(旧版金属在前 / ground 在后,
//      ground 的 Boolean 把第一个 connector 的 union 结果 tag 冲掉, conn_a 被
//      静默吞并 → 只出 5 个导体而非 6, 还不报错。)
//   2. **金属用显式高位 tag (>=1001)**: 绕开 `news` 在 OCC Boolean 删面后复用
//      旧 tag 的不确定性。pad+引线 BooleanUnion 熔成单面 (都是 Rectangle 稳定
//      fuse; 留 ov=5µm overlap 保证熔合)。
//   3. JJ 用 OCC Rectangle (lumped, 管线移除, 仅供 GDS)。
//
// 注: 带 ground+引线的几何在 carve (导体挖空) 后, 真空被薄金属层夹成多块
//   (pocket 内部 + 每条引线的 CPW-gap sliver) — 管线已支持多真空体 (全部赋
//   vacuum 材料), 见 _gmsh_layers.carve_conductors。
// =====================================================================
SetFactory("OpenCASCADE");
Include "qlib.geo";

// ---- 设计参数 (µm) -------------------------------------------------
pad_w   = 450;   pad_h = 90;   pad_gap = 30;
pad_cy  = (pad_h + pad_gap) / 2;   // = 60
jj_w    = 20;
cpw_w   = 25;    cpw_gap = 12;   gap_w = cpw_w + 2*cpw_gap;  // 49
ov      = 5;     // 引线探入 pad 的 overlap, 保证 BooleanUnion 熔合
lead_x  = 425;   // 引线开路端 |x|
pkt_w   = 650;   pkt_h = 650;
g_x0 = -625; g_y0 = -525; g_w = 1250; g_h = 1050;

// ---- 1) ground sheet + pocket + 4 条引线 CPW gap (先建, Boolean 先做完) ----
gs = news; Rectangle(gs) = { g_x0, g_y0, 0, g_w, g_h };
sground = gs; pkt_cx = 0; pkt_cy = 0; Call GROUND_POCKET;
sground = sret; gx1 =  225; gy1 =  137.5; gx2 =  lead_x; gy2 =  137.5; gw = gap_w; Call GROUND_CUTOUT;
sground = sret; gx1 = -225; gy1 =  137.5; gx2 = -lead_x; gy2 =  137.5; gw = gap_w; Call GROUND_CUTOUT;
sground = sret; gx1 =  225; gy1 = -137.5; gx2 =  lead_x; gy2 = -137.5; gw = gap_w; Call GROUND_CUTOUT;
sground = sret; gx1 = -225; gy1 = -137.5; gx2 = -lead_x; gy2 = -137.5; gw = gap_w; Call GROUND_CUTOUT;
Physical Surface("ground::1::chip::gnd") = { sret };

// ---- 2) 金属导体: 显式高位 tag (>=1001), 连接器 union 成单面 -----------
Rectangle(1001) = { -pad_w/2,  pad_cy - pad_h/2, 0, pad_w, pad_h };
Physical Surface("metal::1::Q1::pad_top") = { 1001 };

Rectangle(1002) = { -pad_w/2, -pad_cy - pad_h/2, 0, pad_w, pad_h };
Physical Surface("metal::1::Q1::pad_bot") = { 1002 };

// JJ (lumped, 管线移除, 仅供 GDS): x[-10,10] y[-15,15]
Rectangle(1003) = { -jj_w/2, -pad_gap/2, 0, jj_w, pad_gap };
Physical Surface("jj::1::Q1::jj") = { 1003 };

// conn_a (top-right): pad x[100,225] y[120,150] + 引线伸到 x=425
Rectangle(1004) = { 100, 120, 0, 125, 30 };
Rectangle(1005) = { 225 - ov, 137.5 - cpw_w/2, 0, (lead_x - 225) + ov, cpw_w };
_ua() = BooleanUnion{ Surface{1004}; Delete; }{ Surface{1005}; Delete; };
Physical Surface("metal::1::Q1::conn_a") = { _ua(0) };

// conn_b (top-left)
Rectangle(1006) = { -225, 120, 0, 125, 30 };
Rectangle(1007) = { -lead_x, 137.5 - cpw_w/2, 0, (lead_x - 225) + ov, cpw_w };
_ub() = BooleanUnion{ Surface{1006}; Delete; }{ Surface{1007}; Delete; };
Physical Surface("metal::1::Q1::conn_b") = { _ub(0) };

// conn_c (bottom-right): pad x[25,225] y[-150,-120] 200x30
Rectangle(1008) = { 25, -150, 0, 200, 30 };
Rectangle(1009) = { 225 - ov, -137.5 - cpw_w/2, 0, (lead_x - 225) + ov, cpw_w };
_uc() = BooleanUnion{ Surface{1008}; Delete; }{ Surface{1009}; Delete; };
Physical Surface("metal::1::Q1::conn_c") = { _uc(0) };

// conn_d (bottom-left): pad x[-225,-100] y[-170,-120] 125x50
Rectangle(1010) = { -225, -170, 0, 125, 50 };
Rectangle(1011) = { -lead_x, -137.5 - cpw_w/2, 0, (lead_x - 225) + ov, cpw_w };
_ud() = BooleanUnion{ Surface{1010}; Delete; }{ Surface{1011}; Delete; };
Physical Surface("metal::1::Q1::conn_d") = { _ud(0) };
