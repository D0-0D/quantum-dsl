// =====================================================================
// cpw_macros.geo — CPW 路由宏库 (供 examples/lib 的模板 .geo Include)。
// 单位 µm, OpenCASCADE。纯几何, 不打 Physical 名; include guard 保证同一 gmsh session 内
// 多次 Include (模板每实例化一次就 merge 一次) 不触发 "Redefinition of function"。
//
// ⚠ 宏名与入参一律 LIB_ / _lib_ 前缀: gmsh 的 Macro 与变量都是**进程级全局**, session 从不
//   finalize。不加前缀则 (a) 与用户自己的宏库重名即 "Redefinition of function" 炸掉整个
//   session (examples/qlib.geo 也有 Macro CPW), (b) 裸名入参 (x1/y1/width/R…) 会活到后续
//   手写 geo 步骤里, 漏设一个就读到上一个模板实例的陈旧值而不报错。
//
//   LIB_CPW          _lib_x1,_lib_y1,_lib_x2,_lib_y2,_lib_w     → 两点中心导体矩形, _lib_s; 长度 _lib_len
//   LIB_CPW_ARC      _lib_cx,_lib_cy,_lib_R,_lib_a0,_lib_a1,_lib_w
//                    → 圆心 (cx,cy)、中心线半径 R、极角 a0→a1 (|Δ|<π) 的弧段, _lib_s
//   LIB_CPW_MEANDER  _lib_x1,_lib_y1,_lib_x2,_lib_y2,_lib_w,_lib_R,_lib_n,_lib_L
//                    → 从 p1 到 p2 (轴), 总长 _lib_L 的蛇形 (引入直段 + 90° 弧 + _lib_n 条垂直腿 + 180° 弯 +
//                      引出直段); 面表 _lib_faces(), 记账长度 _lib_mlen (== _lib_L), 解出的振幅 _lib_amp。装不下即 Error。
// ⚠ `Call X;` 独占一行 (gmsh 解析器会把同一行 Call 之后的语句在宏体执行前吃掉)。
// =====================================================================
SetFactory("OpenCASCADE");

If (!Exists(_CPW_MACROS_INCLUDED))
_CPW_MACROS_INCLUDED = 1;

Macro LIB_CPW
  _dx = _lib_x2 - _lib_x1;  _dy = _lib_y2 - _lib_y1;
  _lib_len = Sqrt(_dx*_dx + _dy*_dy);
  _tx = _dx / _lib_len;  _ty = _dy / _lib_len;
  _nx = -_ty;        _ny =  _tx;
  _hw = _lib_w / 2;
  _p1 = newp; Point(_p1) = { _lib_x1 + _nx*_hw, _lib_y1 + _ny*_hw, 0 };
  _p2 = newp; Point(_p2) = { _lib_x2 + _nx*_hw, _lib_y2 + _ny*_hw, 0 };
  _p3 = newp; Point(_p3) = { _lib_x2 - _nx*_hw, _lib_y2 - _ny*_hw, 0 };
  _p4 = newp; Point(_p4) = { _lib_x1 - _nx*_hw, _lib_y1 - _ny*_hw, 0 };
  _l1 = newl; Line(_l1) = { _p1, _p2 };
  _l2 = newl; Line(_l2) = { _p2, _p3 };
  _l3 = newl; Line(_l3) = { _p3, _p4 };
  _l4 = newl; Line(_l4) = { _p4, _p1 };
  _cl = newll; Curve Loop(_cl) = { _l1, _l2, _l3, _l4 };
  _lib_s = news; Plane Surface(_lib_s) = { _cl };
Return

Macro LIB_CPW_ARC
  If (Abs(_lib_a1 - _lib_a0) >= Pi)
    Error("LIB_CPW_ARC: |_lib_a1 - _lib_a0| = %g rad must be < Pi (split the arc)", Abs(_lib_a1 - _lib_a0));
  EndIf
  If (_lib_R <= _lib_w/2)
    Error("LIB_CPW_ARC: _lib_R = %g must exceed _lib_w/2 = %g (inner radius <= 0)", _lib_R, _lib_w/2);
  EndIf
  _ri = _lib_R - _lib_w/2;  _ro = _lib_R + _lib_w/2;
  _ac = newp; Point(_ac) = { _lib_cx, _lib_cy, 0 };
  _q1 = newp; Point(_q1) = { _lib_cx + _ri*Cos(_lib_a0), _lib_cy + _ri*Sin(_lib_a0), 0 };
  _q2 = newp; Point(_q2) = { _lib_cx + _ro*Cos(_lib_a0), _lib_cy + _ro*Sin(_lib_a0), 0 };
  _q3 = newp; Point(_q3) = { _lib_cx + _ro*Cos(_lib_a1), _lib_cy + _ro*Sin(_lib_a1), 0 };
  _q4 = newp; Point(_q4) = { _lib_cx + _ri*Cos(_lib_a1), _lib_cy + _ri*Sin(_lib_a1), 0 };
  _m1 = newl; Line(_m1) = { _q1, _q2 };
  _m2 = newl; Circle(_m2) = { _q2, _ac, _q3 };
  _m3 = newl; Line(_m3) = { _q3, _q4 };
  _m4 = newl; Circle(_m4) = { _q4, _ac, _q1 };
  _acl = newll; Curve Loop(_acl) = { _m1, _m2, _m3, _m4 };
  _lib_s = news; Plane Surface(_lib_s) = { _acl };
  Delete { Point{ _ac }; }      // 圆心只是构造用, 不留孤立点进网格
Return

Macro LIB_CPW_MEANDER
  _md_x1 = _lib_x1;  _md_y1 = _lib_y1;  _md_x2 = _lib_x2;  _md_y2 = _lib_y2;
  _md_D = Hypot(_md_x2 - _md_x1, _md_y2 - _md_y1);
  _md_tx = (_md_x2 - _md_x1)/_md_D;  _md_ty = (_md_y2 - _md_y1)/_md_D;   // 轴切向 t
  _md_nx = -_md_ty;                  _md_ny = _md_tx;                    // 左法向 n
  _md_th = Atan2(_md_ty, _md_tx);
  If (_lib_n < 2 || _lib_n != Floor(_lib_n))
    Error("LIB_CPW_MEANDER: _lib_n = %g must be an integer >= 2", _lib_n);
  EndIf
  If (2*_lib_R <= _lib_w)
    Error("LIB_CPW_MEANDER: adjacent legs overlap: 2*_lib_R = %g <= _lib_w = %g", 2*_lib_R, _lib_w);
  EndIf
  _md_lead = (_md_D - 2*_lib_R*_lib_n)/2;
  If (_md_lead < 0)
    Error("LIB_CPW_MEANDER: 2*_lib_R*_lib_n = %g exceeds endpoint distance D = %g (fewer legs or smaller _lib_R)",
          2*_lib_R*_lib_n, _md_D);
  EndIf
  _lib_amp = (_lib_L - _md_D + 2*_lib_R*_lib_n - _lib_n*Pi*_lib_R + 2*_lib_R) / (2*(_lib_n - 1));
  If (_lib_amp <= _lib_R)
    Error("LIB_CPW_MEANDER: _lib_L = %g too short for _lib_n = %g, _lib_R = %g (amplitude %g <= _lib_R): fewer legs, smaller _lib_R or longer target",
          _lib_L, _lib_n, _lib_R, _lib_amp);
  EndIf
  _lib_faces() = {};  _lib_mlen = 0;
  // 1) 引入直段 (lead 可为 0)
  _md_px = _md_x1 + _md_lead*_md_tx;  _md_py = _md_y1 + _md_lead*_md_ty;
  If (_md_lead > 0)
    _lib_x1 = _md_x1;  _lib_y1 = _md_y1;  _lib_x2 = _md_px;  _lib_y2 = _md_py;
    Call LIB_CPW;
    _lib_faces() += { _lib_s };  _lib_mlen += _lib_len;
  EndIf
  // 2) 90° 弧, 左转到 +n; 圆心 = 当前点 + _lib_R·n
  _lib_cx = _md_px + _lib_R*_md_nx;  _lib_cy = _md_py + _lib_R*_md_ny;  _lib_a0 = _md_th - Pi/2;  _lib_a1 = _md_th;
  Call LIB_CPW_ARC;
  _lib_faces() += { _lib_s };  _lib_mlen += _lib_R*Pi/2;
  _md_px = _lib_cx + _lib_R*_md_tx;  _md_py = _lib_cy + _lib_R*_md_ty;
  _md_s = 1;                                   // 当前沿 n 的行进方向 (+1 / -1)
  For _md_k In {1:_lib_n}
    If (_md_k == 1 || _md_k == _lib_n)
      _md_h = _lib_amp - _lib_R;                     // 首/末腿: 从 ±_lib_R 到 ±_lib_amp
    Else
      _md_h = 2*_lib_amp;
    EndIf
    _lib_x1 = _md_px;  _lib_y1 = _md_py;  _lib_x2 = _md_px + _md_s*_md_h*_md_nx;  _lib_y2 = _md_py + _md_s*_md_h*_md_ny;
    Call LIB_CPW;
    _lib_faces() += { _lib_s };  _lib_mlen += _lib_len;
    _md_px = _lib_x2;  _md_py = _lib_y2;
    // 弯: 圆心 = 当前点 + _lib_R·t, 从极角 th+π 出发, 顶部 (s=+1) 顺时针 / 底部 (s=-1) 逆时针
    _lib_cx = _md_px + _lib_R*_md_tx;  _lib_cy = _md_py + _lib_R*_md_ty;
    _lib_a0 = _md_th + Pi;  _lib_a1 = _md_th + Pi - _md_s*Pi/2;
    Call LIB_CPW_ARC;
    _lib_faces() += { _lib_s };  _lib_mlen += _lib_R*Pi/2;
    If (_md_k < _lib_n)                        // 180° 弯的后半段, 然后掉头
      _lib_a0 = _lib_a1;  _lib_a1 = _md_th + Pi - _md_s*Pi;
      Call LIB_CPW_ARC;
      _lib_faces() += { _lib_s };  _lib_mlen += _lib_R*Pi/2;
      _md_px = _lib_cx + _lib_R*_md_tx;  _md_py = _lib_cy + _lib_R*_md_ty;
      _md_s = -_md_s;
    EndIf
  EndFor
  // 3) 最后一个 90° 弧已回到轴上 (圆心 + s·_lib_R·n), 引出直段到终点
  _md_px = _lib_cx + _md_s*_lib_R*_md_nx;  _md_py = _lib_cy + _md_s*_lib_R*_md_ny;
  If (_md_lead > 0)
    _lib_x1 = _md_px;  _lib_y1 = _md_py;  _lib_x2 = _md_x2;  _lib_y2 = _md_y2;
    Call LIB_CPW;
    _lib_faces() += { _lib_s };  _lib_mlen += _lib_len;
  EndIf
  If (Abs(_lib_mlen - _lib_L) > 1e-6*_lib_L || Hypot(_md_px + _md_lead*_md_tx - _md_x2, _md_py + _md_lead*_md_ty - _md_y2) > 1e-6*_md_D)
    Error("LIB_CPW_MEANDER internal: bookkeeping length %g vs target %g, or path missed the end point", _lib_mlen, _lib_L);
  EndIf
  _lib_x1 = _md_x1;  _lib_y1 = _md_y1;  _lib_x2 = _md_x2;  _lib_y2 = _md_y2;   // 还原入参 (子调用 CPW 改写了 _lib_x1.._lib_y2), 可直接再 Call 画缝工具
Return

EndIf
// _CPW_MACROS_INCLUDED
