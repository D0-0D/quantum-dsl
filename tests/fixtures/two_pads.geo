// =====================================================================
// two_pads.geo — minimal TWO-CONDUCTOR reference for the M3 capacitance
// write-back (clean-mesh end-to-end Palace solve).
//
// 单位: µm. OpenCASCADE. 两块 **分离** 的金属焊盘 (无重叠 / 无 ground sheet /
// 无 JJ) → fragment 后是 conformal 网格 → 一个适定的 2-terminal Electrostatic
// 电容问题 (Ground 退化为真空外边界 vacuum_outer)。
//
// 与 chip_layout 不同, 这里刻意 **不** 让金属与 ground 共面重叠 —— 共面重叠
// 的薄 slab 经 fragment 会产生被 3 个体共享的非流形内面, 真实求解 (非
// --dry-run) 时被 MFEM 拒绝。两块分离焊盘则缝合干净。
// =====================================================================

SetFactory("OpenCASCADE");

// ---- pad A (terminal 1) — 80 µm × 80 µm, 居左 ----------------------
padA = news;
Rectangle(padA) = { -120, -40, 0, 80, 80 };   // x[-120,-40] y[-40,40]
Physical Surface("metal::1::A::pad") = { padA };

// ---- pad B (terminal 2) — 80 µm × 80 µm, 居右, 与 A 留 80 µm 间隙 ----
padB = news;
Rectangle(padB) = { 40, -40, 0, 80, 80 };      // x[40,120] y[-40,40]
Physical Surface("metal::1::B::pad") = { padB };
