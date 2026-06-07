// =====================================================================
// chip_layout.geo — worked demo for the native Gmsh .geo geometry DSL (M1).
//
// 单位: 微米 (µm). OpenCASCADE kernel. Positive metal tone — CPW gaps 用
// BooleanDifference 从 ground sheet 蚀刻 (tracker.subtracts 保持空, apply_cuts
// no-op)。
//
// 几何 (single metal layer 1 + dielectric substrate layer 3):
//   - 一条水平 CPW bus 中心导体 (BUS.trace)
//   - 两对 qubit 焊盘 (Q1.pad_left / Q1.pad_right, Q2.pad_left / Q2.pad_right)
//   - 两条 JJ 线 (Q1.jj, Q2.jj) 桥接各自的焊盘对 (2D, 不 extrude)
//   - 一张 ground sheet (chip.gnd), 沿 bus + 焊盘四周蚀刻出 CPW gap
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

cx = q1_cx; cy = q_cy - (pad_h + pad_sep)/2; w = pad_w; h = pad_h;
Call PAD;
Physical Surface("metal::1::Q1::pad_bot") = { sret };

x1 = q1_cx; y1 = q_cy - pad_sep/2; x2 = q1_cx; y2 = q_cy + pad_sep/2; width = jj_w;
Call JUNCTION;
Physical Surface("jj::1::Q1::jj") = { sret };

// ---- 3) Qubit Q2 焊盘对 + JJ --------------------------------------
cx = q2_cx; cy = q_cy + (pad_h + pad_sep)/2; w = pad_w; h = pad_h;
Call PAD;
Physical Surface("metal::1::Q2::pad_top") = { sret };

cx = q2_cx; cy = q_cy - (pad_h + pad_sep)/2; w = pad_w; h = pad_h;
Call PAD;
Physical Surface("metal::1::Q2::pad_bot") = { sret };

x1 = q2_cx; y1 = q_cy - pad_sep/2; x2 = q2_cx; y2 = q_cy + pad_sep/2; width = jj_w;
Call JUNCTION;
Physical Surface("jj::1::Q2::jj") = { sret };

// ---- 4) Ground sheet 带 CPW gap (positive tone, gap 蚀刻) -----------
// ground 覆盖整个 chip, 沿 bus 蚀刻一条 CPW gap。gap 两端各伸出 bus 30µm,
// 让 bus 端面落在真空里 (否则 bus 端面与 gap 端壁共面重叠 → 网格失败)。
// pads / JJ 与 ground 在同一 metal 层 (z 0..thickness) 重叠 / 嵌入, 交由
// fragment_everything 统一缝合 — 与 legacy chain_2q 同拓扑 (该参考能正常
// 网格化, 包含嵌在 ground slab 里的 JJ 面)。
g_x0 = -500; g_y0 = -340; g_w = 1000; g_h = 680;
gs = news; Rectangle(gs) = { g_x0, g_y0, 0, g_w, g_h };

sground = gs; gx1 = bus_x0 - 30; gy1 = bus_y; gx2 = bus_x1 + 30; gy2 = bus_y; gw = gap_w;
Call GROUND_CUTOUT;
Physical Surface("ground::1::chip::gnd") = { sret };
