// =====================================================================
// sung_2021_device.geo — v4 外部物理验证 fixture (N15)。
// Sung et al., Phys. Rev. X 11, 021058 (2021) / arXiv:2011.01261 三体
// tunable-coupler 器件的简化重现。论文参考值与本版图实测边界(哪些量可
// 复现、哪些结构性丢失)只写在 sung_2021_device.meta.yaml 头注 — 单一出处。
//
// 拓扑: QB1 — CPLR — QB2 一字排开, 每个都是浮动(差分)transmon =
// 两块 pad 由 JJ 桥接, 都不接地。
//
// ⚠ v4 命名约定: component 段 = 电学岛(net), 不是器件 —— 浮动 transmon 的
// 上下 pad 必须是不同 component(QB1_t / QB1_b), 否则会被并成同一 Terminal
// 把双岛短路(v3 踩过: C_Σ 错 1.70×)。器件归组在 meta 的 circuit_model
// (islands: [QB1_t, QB1_b])。jj:: 的 component 保持器件名(不进网格)。
//
// 几何要点(继承自 v3 调参实录):
//   * C_Σ ≈ 99/228/102 fF 要大 pad + 上下窄缝(m_y);
//   * C_1c = C_2c = 5.36 fF 要相邻 pocket 在 x 上 OVERLAP(dx < q_mx+c_mx),
//     qubit↔coupler 通道里不留 ground——否则差分耦合 ¼|c_tt+c_bb−c_tb−c_bt|
//     坍缩(v3 实测 20× 误差);
//   * dx 是耦合旋钮; m_x 是 C_Σ 微调旋钮。
//   * v3 在挖空管线实测: pocket overlap ≤10 µm 或不 overlap 时 OCC fragment
//     必炸(近简并布尔)。v4 imprint 路线未复测, 重调参数时保持舒适余量。
// =====================================================================

SetFactory("OpenCASCADE");
Include "qlib.geo";

// ---- Device geometry parameters (µm) --------------------------------
q_pad_w  = 360;   // qubit pad width
q_pad_h  = 180;   // pad height (per pad)
q_pad_sep= 8;     // slot between the two pads (junction bridges it)
q_mx     = 30;    // pad→ground gap, left/right
q_my     = 8;     // pad→ground gap, top/bottom

c_pad_w  = 720;   // coupler ~2x linear size for C_c ≈ 2.3 C_1
c_pad_h  = 360;
c_pad_sep= 8;
c_mx     = 30;
c_my     = 8;

dx       = 30;    // qubit pad ↔ coupler pad gap (sets C_1c / C_2c)
jj_w     = 2;     // JJ width (lumped element: GDS layer 20, not meshed)

q_cx     = dx + (q_pad_w + c_pad_w)/2;
q_cy     = 0;

g_w = 1900; g_h = 1100;   // ground sheet (single connected sheet)
g_x0 = -g_w/2; g_y0 = -g_h/2;

// ---- 1) QB1 (left floating transmon) --------------------------------
cx = -q_cx; cy = q_cy + (q_pad_h + q_pad_sep)/2; w = q_pad_w; h = q_pad_h;
Call PAD;
Physical Surface("metal::1::QB1_t::pad") = { sret };

cx = -q_cx; cy = q_cy - (q_pad_h + q_pad_sep)/2; w = q_pad_w; h = q_pad_h;
Call PAD;
Physical Surface("metal::1::QB1_b::pad") = { sret };

x1 = -q_cx; y1 = q_cy - q_pad_sep/2; x2 = -q_cx; y2 = q_cy + q_pad_sep/2;
width = jj_w;
Call JUNCTION;
Physical Surface("jj::1::QB1::jj") = { sret };

// ---- 2) CPLR (centre tunable coupler) -------------------------------
cx = 0; cy = q_cy + (c_pad_h + c_pad_sep)/2; w = c_pad_w; h = c_pad_h;
Call PAD;
Physical Surface("metal::1::CPLR_t::pad") = { sret };

cx = 0; cy = q_cy - (c_pad_h + c_pad_sep)/2; w = c_pad_w; h = c_pad_h;
Call PAD;
Physical Surface("metal::1::CPLR_b::pad") = { sret };

x1 = 0; y1 = q_cy - c_pad_sep/2; x2 = 0; y2 = q_cy + c_pad_sep/2; width = jj_w;
Call JUNCTION;
Physical Surface("jj::1::CPLR::jj") = { sret };

// ---- 3) QB2 (right floating transmon) -------------------------------
cx = q_cx; cy = q_cy + (q_pad_h + q_pad_sep)/2; w = q_pad_w; h = q_pad_h;
Call PAD;
Physical Surface("metal::1::QB2_t::pad") = { sret };

cx = q_cx; cy = q_cy - (q_pad_h + q_pad_sep)/2; w = q_pad_w; h = q_pad_h;
Call PAD;
Physical Surface("metal::1::QB2_b::pad") = { sret };

x1 = q_cx; y1 = q_cy - q_pad_sep/2; x2 = q_cx; y2 = q_cy + q_pad_sep/2;
width = jj_w;
Call JUNCTION;
Physical Surface("jj::1::QB2::jj") = { sret };

// ---- 4) Ground sheet with one merged vacuum pocket -------------------
gs = news;
Rectangle(gs) = { g_x0, g_y0, 0, g_w, g_h };
sground = gs;

// One pocket per island-pair = pad bbox inflated by (m_x, m_y). Neighbouring
// pockets overlap by q_mx + c_mx − dx > 0, so the three carves merge into a
// single vacuum region with NO ground between qubit and coupler pads.
pkt_cx = -q_cx; pkt_cy = q_cy;
pkt_w = q_pad_w + 2*q_mx; pkt_h = 2*q_pad_h + q_pad_sep + 2*q_my;
Call GROUND_POCKET;
sground = sret;

pkt_cx = 0; pkt_cy = q_cy;
pkt_w = c_pad_w + 2*c_mx; pkt_h = 2*c_pad_h + c_pad_sep + 2*c_my;
Call GROUND_POCKET;
sground = sret;

pkt_cx = q_cx; pkt_cy = q_cy;
pkt_w = q_pad_w + 2*q_mx; pkt_h = 2*q_pad_h + q_pad_sep + 2*q_my;
Call GROUND_POCKET;
sground = sret;

Physical Surface("ground::1::chip::gnd") = { sground };
