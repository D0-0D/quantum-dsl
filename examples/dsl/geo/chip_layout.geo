// =====================================================================
// chip_layout.geo — worked demo for the native Gmsh .geo geometry DSL (M1).
//
// 单位: 微米 (µm). OpenCASCADE kernel. Positive metal tone — CPW gaps 用
// BooleanDifference 从 ground sheet 蚀刻 (tracker.subtracts 保持空, apply_cuts
// no-op)。
//
// 几何 (single metal layer 1 + dielectric substrate layer 3):
//   - 一条水平 CPW bus 中心导体 (BUS.trace)
//   - 两个 transmon: 上下焊盘 (Q{1,2}.pad_top / pad_bot) + JJ 跨缝桥接;
//     下焊盘 union 一个伸向 bus 的耦合桨 (neck+paddle), 电容耦合到 bus (不短路)
//   - 两条 JJ 线 (Q1.jj, Q2.jj) 桥接各自的焊盘对 (2D, 不 extrude)
//   - 一张 ground sheet (chip.gnd), 沿 bus / 焊盘 / 耦合结构四周蚀刻出 gap
//
// 绑定: 每个面用 Physical Surface("role::layer::comp::prim") 标注。
// 衬底 (substrate::3) 此处不显式画 — populate_tracker_from_geo 在没有
// substrate:: 面时按 chip bbox 自动补 dielectric layer (见 meta sidecar)。
// =====================================================================

SetFactory("OpenCASCADE");
Include "qlib.geo";

// ---- 设计参数 (µm) -------------------------------------------------
cpw_w   = 10;     // CPW 中心导体宽
gap     = 6;      // CPW gap (蚀刻宽 = cpw_w + 2*gap)
gap_w   = cpw_w + 2*gap;
pad_w   = 120;    // qubit 焊盘宽
pad_h   = 80;     // qubit 焊盘高
pad_sep = 30;     // 一对焊盘之间的缝隙
jj_w    = 2;      // JJ 线宽
pkt_gap = 20;     // qubit pocket: 焊盘到 ground 的真空隔离间距

// ---- 耦合结构 (capacitive coupling to bus) ------------------------
coup_neck_w = 10;     // 颈宽 (下焊盘 → paddle)
coup_pad_w  = 60;     // 耦合桨长 (平行 bus)
coup_pad_h  = 12;     // 耦合桨高
c_gap       = 6;      // 耦合桨底到 bus 中心导体的真空间隙
coup_ov     = 6;      // neck 两端 overlap 进 pad/paddle, 保证 union 成单面

bus_y   = 0;      // bus 沿 y=0
bus_x0  = -400; bus_x1 = 400;

q1_cx   = -200;   // 两个 qubit 中心 x
q2_cx   =  200;
q_cy    =  180;   // qubit 焊盘对的中心 y (在 bus 上方)

// ---- 1) CPW bus 中心导体 (positive metal) --------------------------
x1 = bus_x0; y1 = bus_y; x2 = bus_x1; y2 = bus_y; width = cpw_w;
Call CPW;
Physical Surface("metal::1::BUS::trace") = { sret };

// ---- 2) Qubit Q1 焊盘对 + JJ --------------------------------------
// 上下两块焊盘, 中间 pad_sep 缝, JJ 跨缝。
cx = q1_cx; cy = q_cy + (pad_h + pad_sep)/2; w = pad_w; h = pad_h;
Call PAD;
Physical Surface("metal::1::Q1::pad_top") = { sret };

// 下焊盘 + 伸向 bus 的耦合桨 (union 成同一导体, qubit 岛悬浮)。
cx = q1_cx; cy = q_cy - (pad_h + pad_sep)/2; w = pad_w; h = pad_h;
Call PAD;
_padb = sret;
cpx = q1_cx; pb_bot_y = q_cy - (pad_h + pad_sep)/2 - pad_h/2;
Call COUPLER;
Physical Surface("metal::1::Q1::pad_bot") = { sret };

x1 = q1_cx; y1 = q_cy - pad_sep/2; x2 = q1_cx; y2 = q_cy + pad_sep/2; width = jj_w;
Call JUNCTION;
Physical Surface("jj::1::Q1::jj") = { sret };

// ---- 3) Qubit Q2 焊盘对 + JJ --------------------------------------
cx = q2_cx; cy = q_cy + (pad_h + pad_sep)/2; w = pad_w; h = pad_h;
Call PAD;
Physical Surface("metal::1::Q2::pad_top") = { sret };

// 下焊盘 + 伸向 bus 的耦合桨 (union 成同一导体, qubit 岛悬浮)。
cx = q2_cx; cy = q_cy - (pad_h + pad_sep)/2; w = pad_w; h = pad_h;
Call PAD;
_padb = sret;
cpx = q2_cx; pb_bot_y = q_cy - (pad_h + pad_sep)/2 - pad_h/2;
Call COUPLER;
Physical Surface("metal::1::Q2::pad_bot") = { sret };

x1 = q2_cx; y1 = q_cy - pad_sep/2; x2 = q2_cx; y2 = q_cy + pad_sep/2; width = jj_w;
Call JUNCTION;
Physical Surface("jj::1::Q2::jj") = { sret };

// ---- 4) Ground sheet 带 CPW gap + qubit pockets (positive tone) -----
// ground 覆盖整个 chip。蚀刻三类 gap:
//   (a) 沿 bus 一条 CPW gap。gap 两端各伸出 bus 30µm, 让 bus 端面落在真空里
//       (否则 bus 端面与 gap 端壁共面重叠 → 网格失败)。
//   (b) 每个 qubit 焊盘对四周一个矩形 pocket, 使焊盘成为被真空环绕的孤立岛,
//       不与 ground 短路 (也就不会在 GDS 里被 union 进 ground 而消失)。JJ 留在
//       pocket 内桥接上下两块焊盘。
//   (c) 每个耦合结构 (neck+paddle) 周围清地: paddle pocket + neck gap, 把 bus gap
//       与 qubit pocket 连通成一条真空通道。paddle 底正对 bus 中心导体 (隔 c_gap
//       真空) → 电容耦合; qubit 经此耦合到 bus, 但不与 bus 短路。
g_x0 = -500; g_y0 = -340; g_w = 1000; g_h = 680;
gs = news; Rectangle(gs) = { g_x0, g_y0, 0, g_w, g_h };

// (a) bus CPW gap
sground = gs; gx1 = bus_x0 - 30; gy1 = bus_y; gx2 = bus_x1 + 30; gy2 = bus_y; gw = gap_w;
Call GROUND_CUTOUT;

// (b) qubit pockets — 容纳上下两块焊盘 + pad_sep 缝, 四周留 pkt_gap 真空。
pkt_w = pad_w + 2*pkt_gap;
pkt_h = 2*pad_h + pad_sep + 2*pkt_gap;
sground = sret; pkt_cx = q1_cx; pkt_cy = q_cy;
Call GROUND_POCKET;
sground = sret; pkt_cx = q2_cx; pkt_cy = q_cy;
Call GROUND_POCKET;

// (c) 耦合结构清地: 每 qubit 一个 paddle pocket (清桨四周) + 一条 neck gap
//     (沿颈清地, 连通 paddle pocket → qubit pocket)。
paddle_cy = bus_y + cpw_w/2 + c_gap + coup_pad_h/2;
paddle_top = bus_y + cpw_w/2 + c_gap + coup_pad_h;
pb_bot_y = q_cy - (pad_h + pad_sep)/2 - pad_h/2;
pkt_w = coup_pad_w + 2*c_gap;
pkt_h = coup_pad_h + 2*c_gap;
// Q1
sground = sret; pkt_cx = q1_cx; pkt_cy = paddle_cy;
Call GROUND_POCKET;
sground = sret; gx1 = q1_cx; gy1 = paddle_top; gx2 = q1_cx; gy2 = pb_bot_y; gw = gap_w;
Call GROUND_CUTOUT;
// Q2
sground = sret; pkt_cx = q2_cx; pkt_cy = paddle_cy;
Call GROUND_POCKET;
sground = sret; gx1 = q2_cx; gy1 = paddle_top; gx2 = q2_cx; gy2 = pb_bot_y; gw = gap_w;
Call GROUND_CUTOUT;

Physical Surface("ground::1::chip::gnd") = { sret };
