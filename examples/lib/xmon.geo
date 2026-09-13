// xmon — 接地 Xmon 十字岛 (局部坐标, 十字中心在原点)。接口见 xmon.yaml。
// 输入: arm_w 臂宽, arm_L 臂端到端, gap 岛–地缝, jj_w 结宽 (结在北臂端跨缝到地),
//       ro (0/1) 是否画读出耦合桨: 东臂端外 ro_gap 处一块 ro_pad_w × ro_pad_h 的桨, 端口在桨外沿中点, 宽 ro_w (CPW 宽)。
// 输出: island(), moat() (岛同形外扩 gap, 蚀刻), jj_x1..jj_y2, ro_pad(), ro_pocket(), ro_x。
SetFactory("OpenCASCADE");
_a = news; Rectangle(_a) = { -arm_L/2, -arm_w/2, 0, arm_L, arm_w };
_b = news; Rectangle(_b) = { -arm_w/2, -arm_L/2, 0, arm_w, arm_L };
_u() = BooleanUnion{ Surface{ _a }; Delete; }{ Surface{ _b }; Delete; };
island() = { _u(0) };
_c = news; Rectangle(_c) = { -arm_L/2 - gap, -arm_w/2 - gap, 0, arm_L + 2*gap, arm_w + 2*gap };
_d = news; Rectangle(_d) = { -arm_w/2 - gap, -arm_L/2 - gap, 0, arm_w + 2*gap, arm_L + 2*gap };
_m() = BooleanUnion{ Surface{ _c }; Delete; }{ Surface{ _d }; Delete; };
moat() = { _m(0) };
jj_x1 = 0; jj_y1 = arm_L/2; jj_x2 = 0; jj_y2 = arm_L/2 + gap;      // 北臂端 → 地
If (ro != 0)
  _rx0 = arm_L/2 + ro_gap;                                           // 桨内沿 x
  _r = news; Rectangle(_r) = { _rx0, -ro_pad_h/2, 0, ro_pad_w, ro_pad_h };
  ro_pad() = { _r };
  _k = news; Rectangle(_k) = { _rx0 - gap, -ro_pad_h/2 - gap, 0, ro_pad_w + 2*gap, ro_pad_h + 2*gap };
  ro_pocket() = { _k };
  ro_x = _rx0 + ro_pad_w;                                            // 端口: 桨外沿中点, 外法向 +x
EndIf
