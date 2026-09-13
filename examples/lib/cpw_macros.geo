// =====================================================================
// cpw_macros.geo — CPW 路由宏库 (供 examples/lib 的模板 .geo Include)。
// 单位 µm, OpenCASCADE。纯几何, 不打 Physical 名; include guard 保证同一 gmsh session 内
// 多次 Include (模板每实例化一次就 merge 一次) 不触发 "Redefinition of function"。
//
//   CPW          x1,y1,x2,y2,width          → 两点中心导体矩形, sret; 长度 _len
//   CPW_ARC      acx,acy,R,a0,a1,width      → 圆心 (acx,acy)、中心线半径 R、极角 a0→a1 (|Δ|<π) 的弧段, sret
//   CPW_MEANDER  x1,y1,x2,y2,width,R,n_legs,cpw_L
//                → 从 p1 到 p2 (轴), 总长 cpw_L 的蛇形 (引入直段 + 90° 弧 + n_legs 条垂直腿 + 180° 弯 + 引出直段);
//                  面表 cpw_faces(), 记账长度 cpw_len (== cpw_L), 解出的振幅 cpw_amp。装不下即 Error。
// ⚠ `Call X;` 独占一行 (gmsh 解析器会把同一行 Call 之后的语句在宏体执行前吃掉)。
// =====================================================================
SetFactory("OpenCASCADE");

If (!Exists(_CPW_MACROS_INCLUDED))
_CPW_MACROS_INCLUDED = 1;

Macro CPW
  _dx = x2 - x1;  _dy = y2 - y1;
  _len = Sqrt(_dx*_dx + _dy*_dy);
  _tx = _dx / _len;  _ty = _dy / _len;
  _nx = -_ty;        _ny =  _tx;
  _hw = width / 2;
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

Macro CPW_ARC
  If (Abs(a1 - a0) >= Pi)
    Error("CPW_ARC: |a1-a0| = %g rad must be < Pi (split the arc)", Abs(a1 - a0));
  EndIf
  If (R <= width/2)
    Error("CPW_ARC: R = %g must exceed width/2 = %g (inner radius <= 0)", R, width/2);
  EndIf
  _ri = R - width/2;  _ro = R + width/2;
  _ac = newp; Point(_ac) = { acx, acy, 0 };
  _q1 = newp; Point(_q1) = { acx + _ri*Cos(a0), acy + _ri*Sin(a0), 0 };
  _q2 = newp; Point(_q2) = { acx + _ro*Cos(a0), acy + _ro*Sin(a0), 0 };
  _q3 = newp; Point(_q3) = { acx + _ro*Cos(a1), acy + _ro*Sin(a1), 0 };
  _q4 = newp; Point(_q4) = { acx + _ri*Cos(a1), acy + _ri*Sin(a1), 0 };
  _m1 = newl; Line(_m1) = { _q1, _q2 };
  _m2 = newl; Circle(_m2) = { _q2, _ac, _q3 };
  _m3 = newl; Line(_m3) = { _q3, _q4 };
  _m4 = newl; Circle(_m4) = { _q4, _ac, _q1 };
  _acl = newll; Curve Loop(_acl) = { _m1, _m2, _m3, _m4 };
  sret = news; Plane Surface(sret) = { _acl };
  Delete { Point{ _ac }; }      // 圆心只是构造用, 不留孤立点进网格
Return

Macro CPW_MEANDER
  _md_x1 = x1;  _md_y1 = y1;  _md_x2 = x2;  _md_y2 = y2;
  _md_D = Hypot(_md_x2 - _md_x1, _md_y2 - _md_y1);
  _md_tx = (_md_x2 - _md_x1)/_md_D;  _md_ty = (_md_y2 - _md_y1)/_md_D;   // 轴切向 t
  _md_nx = -_md_ty;                  _md_ny = _md_tx;                    // 左法向 n
  _md_th = Atan2(_md_ty, _md_tx);
  If (n_legs < 2 || n_legs != Floor(n_legs))
    Error("CPW_MEANDER: n_legs = %g must be an integer >= 2", n_legs);
  EndIf
  If (2*R <= width)
    Error("CPW_MEANDER: adjacent legs overlap: 2R = %g <= width = %g", 2*R, width);
  EndIf
  _md_lead = (_md_D - 2*R*n_legs)/2;
  If (_md_lead < 0)
    Error("CPW_MEANDER: 2*R*n_legs = %g exceeds endpoint distance D = %g (fewer legs or smaller R)",
          2*R*n_legs, _md_D);
  EndIf
  cpw_amp = (cpw_L - _md_D + 2*R*n_legs - n_legs*Pi*R + 2*R) / (2*(n_legs - 1));
  If (cpw_amp <= R)
    Error("CPW_MEANDER: cpw_L = %g too short for n_legs = %g, R = %g (amplitude %g <= R): fewer legs, smaller R or longer target",
          cpw_L, n_legs, R, cpw_amp);
  EndIf
  cpw_faces() = {};  cpw_len = 0;
  // 1) 引入直段 (lead 可为 0)
  _md_px = _md_x1 + _md_lead*_md_tx;  _md_py = _md_y1 + _md_lead*_md_ty;
  If (_md_lead > 0)
    x1 = _md_x1;  y1 = _md_y1;  x2 = _md_px;  y2 = _md_py;
    Call CPW;
    cpw_faces() += { sret };  cpw_len += _len;
  EndIf
  // 2) 90° 弧, 左转到 +n; 圆心 = 当前点 + R·n
  acx = _md_px + R*_md_nx;  acy = _md_py + R*_md_ny;  a0 = _md_th - Pi/2;  a1 = _md_th;
  Call CPW_ARC;
  cpw_faces() += { sret };  cpw_len += R*Pi/2;
  _md_px = acx + R*_md_tx;  _md_py = acy + R*_md_ty;
  _md_s = 1;                                   // 当前沿 n 的行进方向 (+1 / -1)
  For _md_k In {1:n_legs}
    If (_md_k == 1 || _md_k == n_legs)
      _md_h = cpw_amp - R;                     // 首/末腿: 从 ±R 到 ±cpw_amp
    Else
      _md_h = 2*cpw_amp;
    EndIf
    x1 = _md_px;  y1 = _md_py;  x2 = _md_px + _md_s*_md_h*_md_nx;  y2 = _md_py + _md_s*_md_h*_md_ny;
    Call CPW;
    cpw_faces() += { sret };  cpw_len += _len;
    _md_px = x2;  _md_py = y2;
    // 弯: 圆心 = 当前点 + R·t, 从极角 th+π 出发, 顶部 (s=+1) 顺时针 / 底部 (s=-1) 逆时针
    acx = _md_px + R*_md_tx;  acy = _md_py + R*_md_ty;
    a0 = _md_th + Pi;  a1 = _md_th + Pi - _md_s*Pi/2;
    Call CPW_ARC;
    cpw_faces() += { sret };  cpw_len += R*Pi/2;
    If (_md_k < n_legs)                        // 180° 弯的后半段, 然后掉头
      a0 = a1;  a1 = _md_th + Pi - _md_s*Pi;
      Call CPW_ARC;
      cpw_faces() += { sret };  cpw_len += R*Pi/2;
      _md_px = acx + R*_md_tx;  _md_py = acy + R*_md_ty;
      _md_s = -_md_s;
    EndIf
  EndFor
  // 3) 最后一个 90° 弧已回到轴上 (圆心 + s·R·n), 引出直段到终点
  _md_px = acx + _md_s*R*_md_nx;  _md_py = acy + _md_s*R*_md_ny;
  If (_md_lead > 0)
    x1 = _md_px;  y1 = _md_py;  x2 = _md_x2;  y2 = _md_y2;
    Call CPW;
    cpw_faces() += { sret };  cpw_len += _len;
  EndIf
  If (Abs(cpw_len - cpw_L) > 1e-6*cpw_L || Hypot(_md_px + _md_lead*_md_tx - _md_x2, _md_py + _md_lead*_md_ty - _md_y2) > 1e-6*_md_D)
    Error("CPW_MEANDER internal: bookkeeping length %g vs target %g, or path missed the end point", cpw_len, cpw_L);
  EndIf
  x1 = _md_x1;  y1 = _md_y1;  x2 = _md_x2;  y2 = _md_y2;   // 还原入参 (子调用 CPW 改写了 x1..y2), 可直接再 Call 画缝工具
Return

EndIf
// _CPW_MACROS_INCLUDED
