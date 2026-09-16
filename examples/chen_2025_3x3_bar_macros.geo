// chen_2025_3x3_bar_macros.geo — chen_2025_3x3_bars.geo 用的两个宏: BAR_POLY (局部顶点表 → 全局平面), BAR_COUPLER (一条 Chen 2025 条形耦合器:
// 条 + 五边形板 + 结, 与 lib/bar_coupler.geo 逐点同一几何, 并自己打 Physical 名)。入参见 chen_2025_3x3_bars.geo 头注。
// ⚠ 宏必须放在被 Include 的文件里, 不能写在手写步骤文件本身: 手写步骤文件是被 merge 的, 解析完即关闭, 里面定义的 Macro 随之失效,
//   同一进程第二次跑版图 (build() 出 GDS / 网格 / 分块时必然发生) 会在 Call 处炸掉 gmsh; Include 的文件 gmsh 不关, 宏体一直可用。
//   编排器对 merge 文件里的 Macro 直接 raise (layout.py _merge)。守卫 If (!Exists(...)) 让本文件可被反复 Include。
_pw = 378;  _wall = 125;  _ph = 300;  _pg = 75;  _off = 273;  _jw = 5;

If (!Exists(_CHEN_BARS_MACROS))           // 宏是进程级的, 反复 Include 不能重定义
  _CHEN_BARS_MACROS = 1;
  Macro BAR_POLY                          // 局部顶点表 _us()/_vs() (u 沿轴, v 垂直) → 全局平面 _face
    _pts() = {};
    For _k In {0 : #_us() - 1}
      _p = newp;  Point(_p) = { _x0 + _us(_k)*_ux + _vs(_k)*_vx, _y0 + _us(_k)*_uy + _vs(_k)*_vy, 0 };
      _pts() += { _p };
    EndFor
    _ls() = {};
    For _k In {0 : #_pts() - 1}
      _l = newl;  Line(_l) = { _pts(_k), _pts((_k + 1) % #_pts()) };
      _ls() += { _l };
    EndFor
    _cl = newll;  Curve Loop(_cl) = { _ls() };
    _face = news;  Plane Surface(_face) = { _cl };
  Return
  Macro BAR_COUPLER
    _D = Hypot(_x1 - _x0, _y1 - _y0);  _ux = (_x1 - _x0)/_D;  _uy = (_y1 - _y0)/_D;   // 轴向 (局部 +x)
    _s = 1 - 2*_flip;  _vx = -_uy*_s;  _vy = _ux*_s;                                    // 局部 +y, _flip 翻到另一侧
    _xc = _D - _off;  _yb = _w/2 + _pg;
    _us() = { 0, _D, _D, 0 };  _vs() = { -_w/2, -_w/2, _w/2, _w/2 };
    Call BAR_POLY;
    _bar = _face;
    _us() = { _xc - _pw/2, _xc + _pw/2, _xc + _pw/2, _xc, _xc - _pw/2 };
    _vs() = { _yb, _yb, _yb + _wall, _yb + _ph, _yb + _wall };
    Call BAR_POLY;
    _pent = _face;
    _us() = { _xc - _jw/2, _xc - _jw/2, _xc + _jw/2, _xc + _jw/2 };  _vs() = { _w/2, _yb, _yb, _w/2 };
    Call BAR_POLY;
    _jj = _face;
    Physical Surface(StrCat("metal::ta::", _name, "::bar")) = { _bar };
    Physical Surface(StrCat("metal::ta::", _name, "_pent::pent")) = { _pent };
    Physical Surface(StrCat("jj::jj::", _name, "::jj")) = { _jj };
  Return
EndIf
