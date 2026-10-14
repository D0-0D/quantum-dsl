// readout_claw — Chen 2025 读出爪 (局部坐标, 比特盘心在原点)。接口见 readout_claw.yaml。
// 输入: r_in 爪内缘半径 (= 盘半径 + 盘–爪间隙), t 径向厚, deg 半角跨 (度), dir 方向角 (度), lead_w / lead_l 外缘起的细线宽 / 长。
// 输出: claw() = 弧 ∪ 细线 (一块面)。
SetFactory("OpenCASCADE");
Include "cpw_macros.geo";
_th = dir * Pi/180;  _rc = r_in + t/2;
_lib_cx = 0;  _lib_cy = 0;  _lib_R = _rc;  _lib_a0 = _th - deg*Pi/180;  _lib_a1 = _th + deg*Pi/180;  _lib_w = t;
Call LIB_CPW_ARC;
_arc = _lib_s;
_lib_x1 = _rc*Cos(_th);  _lib_y1 = _rc*Sin(_th);
_lib_x2 = (r_in + t + lead_l)*Cos(_th);  _lib_y2 = (r_in + t + lead_l)*Sin(_th);  _lib_w = lead_w;
Call LIB_CPW;
claw() = BooleanUnion{ Surface{ _arc }; Delete; }{ Surface{ _lib_s }; Delete; };
