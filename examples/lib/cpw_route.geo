// cpw_route — 自动布线 CPW 模板 (芯片坐标, 位姿恒等)。接口见 cpw_route.yaml, 规划器见 src/quantum_dsl/route.py。
// 注入: w 中心导体宽 (= 端口宽), D 两口距离 (未用), L 目标长度 (给了 length: 才有, 未用 —— 规划器已按它定振幅);
//       _rt_n 段数, _rt_kind(k) 0 直段 / 1 弧, _rt_p0(k).._rt_p4(k) = 直段 (x1, y1, x2, y2, 0) / 弧 (cx, cy, R, a0, a1)。
// 参数: R, n_legs 供规划器; gap 缝宽。输出: cpw_centre() 中心导体面表, cpw_etch() 缝工具面表 (同路径, 宽 w + 2 gap),
//       cpw_length = Σ 直段长 + Σ R·|a1 − a0| (与规划器 route.path_length 同口径, 编排器对 L 闭合)。
SetFactory("OpenCASCADE");
Include "cpw_macros.geo";
cpw_centre() = {};  cpw_etch() = {};  cpw_length = 0;
For _rt_k In {0:_rt_n-1}
  If (_rt_kind(_rt_k) == 0)
    _lib_x1 = _rt_p0(_rt_k);  _lib_y1 = _rt_p1(_rt_k);  _lib_x2 = _rt_p2(_rt_k);  _lib_y2 = _rt_p3(_rt_k);
    _lib_w = w;
    Call LIB_CPW;
    cpw_centre() += { _lib_s };  cpw_length += _lib_len;
    _lib_w = w + 2*gap;
    Call LIB_CPW;
    cpw_etch() += { _lib_s };
  Else
    _lib_cx = _rt_p0(_rt_k);  _lib_cy = _rt_p1(_rt_k);  _lib_R = _rt_p2(_rt_k);  _lib_a0 = _rt_p3(_rt_k);  _lib_a1 = _rt_p4(_rt_k);
    _lib_w = w;
    Call LIB_CPW_ARC;
    cpw_centre() += { _lib_s };  cpw_length += _lib_R*Abs(_lib_a1 - _lib_a0);
    _lib_w = w + 2*gap;
    Call LIB_CPW_ARC;
    cpw_etch() += { _lib_s };
  EndIf
EndFor
