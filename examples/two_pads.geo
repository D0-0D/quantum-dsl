// =====================================================================
// two_pads.geo — 最小两导体例子: 两块分离的 80×80 µm 金属焊盘, 间隙 80 µm。
//
// 单位 µm, OpenCASCADE。没有 ground、没有 JJ —— 一个适定的 2-terminal 静电
// 问题 (电位参考 = 接地盒壁, 见 two_pads.meta.yaml 的 solver 段)。
//
// 它是整条管线的回归锚: 零厚度片配方 (Palace 0.16, order 2, 网格 40/4 µm)
// 实测 Maxwell C = [[24.5324, -1.9472], [-1.9472, 24.5353]] fF,
// 见 docs/physics.md「网格与收敛」与 tests/test_live.py。
//
// 命名约定: Physical Surface("role::layer::component::primitive");
// component 段 (这里的 A / B) = 电学岛 = C 矩阵行列标签 = circuit_model 的 island。
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
