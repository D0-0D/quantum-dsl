// =====================================================================
// qlib.geo — OpenCASCADE macro library for the quantum_dsl .geo DSL (M1).
//
// 单位: 微米 (µm). 全程 OpenCASCADE kernel.
//
// 约定 (THE binding contract):
//   每个 *geometry* 宏都是 **纯几何**: 它创建一个 2D Plane Surface 并把它的
//   tag 写进全局变量  sret  (surface-return)。宏 *不* 打 Physical 标签 —
//   绑定 (Physical Surface("role::layer::comp::prim") = { sret };) 由 *作者*
//   在调用点完成。这样同一个几何宏可被任意 role 复用。
//
// 提供的宏 (输入均为全局标量, 调用前赋值):
//   PAD            cx, cy, w, h                 → 矩形焊盘 (中心 cx,cy, 宽 w 高 h)
//   CPW            x1, y1, x2, y2, width        → 两点中心导体 (positive metal)
//   JUNCTION       x1, y1, x2, y2, width        → JJ 矩形 (沿 p1→p2, 宽 width)
//   GROUND_CUTOUT  sground, gx1,gy1,gx2,gy2,gw  → 在已存在的 ground 面 sground
//                                                 上, 用一条 CPW 形状 (gx1,gy1)->
//                                                 (gx2,gy2) 宽 gw 做 BooleanDifference
//                                                 蚀刻出 CPW gap; 结果面 tag 写回 sret。
//
// 注: GROUND_CUTOUT 会 Delete 工具面与原 ground 面, 把蚀刻后的面 tag 写进
//     sret (作者随后用 sret 打 ground:: 标签)。
// =====================================================================

SetFactory("OpenCASCADE");

// Include guard: gmsh 的 .geo 解析器在 session 内全局保留 Macro 定义,
// 重复 Include 会触发 "Redefinition of function"。用 If(!Exists()) 包住所有
// 宏定义, 使 qlib.geo 可被安全地多次 Include (e.g. GDS + mesh 两条分支)。
If (!Exists(_QLIB_INCLUDED))
_QLIB_INCLUDED = 1;

// ---------------------------------------------------------------------
// PAD(cx, cy, w, h) — 矩形焊盘, 中心 (cx,cy)。
// ---------------------------------------------------------------------
Macro PAD
  sret = news;
  Rectangle(sret) = { cx - w/2, cy - h/2, 0, w, h };
Return

// ---------------------------------------------------------------------
// CPW(x1, y1, x2, y2, width) — 两点之间的中心导体 (positive metal)。
// 沿 (x1,y1)->(x2,y2) 方向, 半宽 width/2 向两侧偏移构成矩形。
// ---------------------------------------------------------------------
Macro CPW
  _dx = x2 - x1;
  _dy = y2 - y1;
  _len = Sqrt(_dx*_dx + _dy*_dy);
  // 单位切向 / 法向
  _tx = _dx / _len;  _ty = _dy / _len;
  _nx = -_ty;        _ny =  _tx;
  _hw = width / 2;
  // 四角 (逆时针): p1+n, p2+n, p2-n, p1-n
  _p1 = newp; Point(_p1) = { x1 + _nx*_hw, y1 + _ny*_hw, 0 };
  _p2 = newp; Point(_p2) = { x2 + _nx*_hw, y2 + _ny*_hw, 0 };
  _p3 = newp; Point(_p3) = { x2 - _nx*_hw, y2 - _ny*_hw, 0 };
  _p4 = newp; Point(_p4) = { x1 - _nx*_hw, y1 - _ny*_hw, 0 };
  _l1 = newl; Line(_l1) = { _p1, _p2 };
  _l2 = newl; Line(_l2) = { _p2, _p3 };
  _l3 = newl; Line(_l3) = { _p3, _p4 };
  _l4 = newl; Line(_l4) = { _p4, _p1 };
  _cl = newll; Curve Loop(_cl) = { _l1, _l2, _l3, _l4 };
  sret = news; Plane Surface(sret) = { _cl };
Return

// ---------------------------------------------------------------------
// JUNCTION(x1, y1, x2, y2, width) — JJ 矩形 (与 CPW 同形, 但语义是结)。
// 留作 2D 面; mesh 分支 *不* extrude, 由 populate_tracker 平移到层中心。
// ---------------------------------------------------------------------
Macro JUNCTION
  _jdx = x2 - x1;
  _jdy = y2 - y1;
  _jlen = Sqrt(_jdx*_jdx + _jdy*_jdy);
  _jtx = _jdx / _jlen;  _jty = _jdy / _jlen;
  _jnx = -_jty;         _jny =  _jtx;
  _jhw = width / 2;
  _jp1 = newp; Point(_jp1) = { x1 + _jnx*_jhw, y1 + _jny*_jhw, 0 };
  _jp2 = newp; Point(_jp2) = { x2 + _jnx*_jhw, y2 + _jny*_jhw, 0 };
  _jp3 = newp; Point(_jp3) = { x2 - _jnx*_jhw, y2 - _jny*_jhw, 0 };
  _jp4 = newp; Point(_jp4) = { x1 - _jnx*_jhw, y1 - _jny*_jhw, 0 };
  _jl1 = newl; Line(_jl1) = { _jp1, _jp2 };
  _jl2 = newl; Line(_jl2) = { _jp2, _jp3 };
  _jl3 = newl; Line(_jl3) = { _jp3, _jp4 };
  _jl4 = newl; Line(_jl4) = { _jp4, _jp1 };
  _jcl = newll; Curve Loop(_jcl) = { _jl1, _jl2, _jl3, _jl4 };
  sret = news; Plane Surface(sret) = { _jcl };
Return

// ---------------------------------------------------------------------
// GROUND_CUTOUT(sground, gx1,gy1, gx2,gy2, gw) — 在 ground 面 sground 上蚀刻
// 一条 CPW 形状的 gap (从 (gx1,gy1) 到 (gx2,gy2), 宽 gw), BooleanDifference。
// 蚀刻结果面 tag 写回 sret (positive-tone ground, gap 已挖空)。
// ---------------------------------------------------------------------
Macro GROUND_CUTOUT
  // 用 CPW 宏画出 gap 工具面 (复用全局 x1..width)
  x1 = gx1; y1 = gy1; x2 = gx2; y2 = gy2; width = gw;
  Call CPW;
  _tool = sret;
  _diff() = BooleanDifference{ Surface{ sground }; Delete; }{ Surface{ _tool }; Delete; };
  sret = _diff(0);
Return

// ---------------------------------------------------------------------
// GROUND_POCKET(sground, pkt_cx,pkt_cy, pkt_w,pkt_h) — 在 ground 面 sground
// 上蚀刻一个矩形 pocket (中心 pkt_cx,pkt_cy, 宽 pkt_w 高 pkt_h), BooleanDifference。
// 用途: 把 qubit 焊盘从 ground 隔离 — 焊盘落在 pocket 真空区内, 四周留 gap, 不
// 与 ground 同层短路 (也就不会在 GDS 里被 union 进 ground 而消失)。
// 蚀刻结果面 tag 写回 sret (positive-tone ground, pocket 已挖空)。
// ---------------------------------------------------------------------
Macro GROUND_POCKET
  _pk = news; Rectangle(_pk) = { pkt_cx - pkt_w/2, pkt_cy - pkt_h/2, 0, pkt_w, pkt_h };
  _pdiff() = BooleanDifference{ Surface{ sground }; Delete; }{ Surface{ _pk }; Delete; };
  sret = _pdiff(0);
Return

// ---------------------------------------------------------------------
// COUPLER(_padb, cpx, pb_bot_y) — 给 qubit 下焊盘 _padb 接一个伸向 bus 的
// 电容耦合结构: 一条 neck (颈) + 一块平行 bus 的 paddle (耦合桨), 三者
// BooleanUnion 成 **一个** 导体 (与 _padb 同 terminal, 保持 qubit 岛悬浮)。
//   _padb   — 已存在的下焊盘面 tag (将被 union 消耗)
//   cpx     — qubit 中心 x (neck/paddle 居中于此)
//   pb_bot_y— 下焊盘底边 y (neck 由此向下接到 paddle)
// 复用全局: coup_neck_w, coup_pad_w, coup_pad_h, c_gap, coup_ov, cpw_w, bus_y。
// paddle 底距 bus 中心导体顶 c_gap → 平行板电容耦合 (galvanic 不接, 不短路)。
// 结果面 tag 写回 sret。
// ---------------------------------------------------------------------
Macro COUPLER
  // paddle: 平行 bus 的耦合桨, 桨底 = bus_y + cpw_w/2 + c_gap
  cx = cpx; cy = bus_y + cpw_w/2 + c_gap + coup_pad_h/2; w = coup_pad_w; h = coup_pad_h;
  Call PAD;
  _paddle = sret;
  // neck: 下焊盘底 → paddle 顶, 两端各 overlap coup_ov 进 pad / paddle。
  // *必须* 用 Rectangle (OCC primitive): pad/paddle 是 Rectangle, 而 CPW 造的
  // 是 Plane Surface — 两种类型 BooleanUnion 不会 fuse (退化成 fragment, 只裁
  // 不并), 只有同为 OCC primitive 的重叠面才会真正合并成单面。
  _ny0 = bus_y + cpw_w/2 + c_gap + coup_pad_h - coup_ov;  // neck 底 (探入 paddle)
  _ny1 = pb_bot_y + coup_ov;                              // neck 顶 (探入 pad)
  _neck = news;
  Rectangle(_neck) = { cpx - coup_neck_w/2, _ny0, 0, coup_neck_w, _ny1 - _ny0 };
  _cu() = BooleanUnion{ Surface{ _padb }; Delete; }{ Surface{ _neck, _paddle }; Delete; };
  sret = _cu(0);
Return

EndIf
// _QLIB_INCLUDED
