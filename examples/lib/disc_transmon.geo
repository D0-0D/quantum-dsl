// disc_transmon — Chen et al. 2025 (Nat. Phys. 21, 1489) 圆盘浮动 transmon (局部坐标, 盘心在原点)。接口见 disc_transmon.yaml。
// 几何全部从 Fig. 1a 照片量出 (docs/design/paper-chen2025-geometry.md §3.2, 2.50 µm/px): 盘径 390, 缝 70 沿 −45°, 结在盘心跨缝。
// 输入: dia 盘径, slot 缝宽, slot_deg 缝方向 (度), jj_w 结宽; claw_E/N/W/S (0/1) 四个耦合器爪 (外挂面: 电学归接上来的
//       bar_coupler, 无邻居的方向关掉), gap 盘–爪间隙, claw_t 爪径向厚, claw_deg 爪半角跨 (度), stub 爪外沿到端口的颈长, bar_w 颈宽 (= 端口宽 = 条宽)。
// 输出: half_a() / half_b() 两半盘 (a 在缝法向 +侧); faces_E()… 爪面 (弧 ∪ 颈, 一块面); port_x/y/a/w(0..3) = E/N/W/S 端口 (颈外端中点,
//       外法向, 宽 bar_w); jj_x1..jj_y2 结 (a → b, 长 = slot)。
SetFactory("OpenCASCADE");
Include "cpw_macros.geo";
_r = dia/2;
_d = news; Disk(_d) = { 0, 0, 0, _r };
_ha = news; Rectangle(_ha) = { slot/2, -2*_r, 0, 2*_r, 4*_r };              // 半平面 n·p >= slot/2 (缝法向坐标系)
_hb = news; Rectangle(_hb) = { -slot/2 - 2*_r, -2*_r, 0, 2*_r, 4*_r };      // 半平面 n·p <= -slot/2
_phi = (slot_deg + 90) * Pi / 180;                                          // 缝法向 n 的方向角
Rotate { {0, 0, 1}, {0, 0, 0}, _phi } { Surface{ _ha, _hb }; }
_a() = BooleanIntersection{ Surface{ _d }; }{ Surface{ _ha }; Delete; };
_b() = BooleanIntersection{ Surface{ _d }; Delete; }{ Surface{ _hb }; Delete; };
half_a() = { _a(0) };  half_b() = { _b(0) };
jj_x1 = slot/2 * Cos(_phi);  jj_y1 = slot/2 * Sin(_phi);  jj_x2 = -jj_x1;  jj_y2 = -jj_y1;

// 爪: 与盘共形的弧 (中心线半径 _rc, 厚 claw_t, 角跨 ±claw_deg) ∪ 径向短颈 (宽 bar_w) → 端口在颈外端, 耦合器条从这里整宽出发
_rc = _r + gap + claw_t/2;  _r1 = _r + gap + claw_t + stub;
port_x() = { _r1, 0, -_r1, 0 };  port_y() = { 0, _r1, 0, -_r1 };
port_a() = { 0, Pi/2, Pi, -Pi/2 };  port_w() = { bar_w, bar_w, bar_w, bar_w };
_on() = { claw_E, claw_N, claw_W, claw_S };
For _k In {0:3}
  If (_on(_k) != 0)
    _th = _k * Pi/2;
    acx = 0;  acy = 0;  R = _rc;  a0 = _th - claw_deg*Pi/180;  a1 = _th + claw_deg*Pi/180;  width = claw_t;
    Call CPW_ARC;
    _arc = sret;
    x1 = _rc*Cos(_th);  y1 = _rc*Sin(_th);  x2 = _r1*Cos(_th);  y2 = _r1*Sin(_th);  width = bar_w;
    Call CPW;
    _u() = BooleanUnion{ Surface{ _arc }; Delete; }{ Surface{ sret }; Delete; };   // OCC 不合并成一块面 (弧 + 颈外段两面共边), 整表导出
    If (_k == 0)  faces_E() = _u();  EndIf
    If (_k == 1)  faces_N() = _u();  EndIf
    If (_k == 2)  faces_W() = _u();  EndIf
    If (_k == 3)  faces_S() = _u();  EndIf
  EndIf
EndFor
