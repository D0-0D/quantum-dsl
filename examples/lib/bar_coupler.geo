// bar_coupler — Chen 2025 条形浮动耦合器 (连接型: 从 from 口 (原点) 沿 +x 到 to 口 (D, 0))。接口见 bar_coupler.yaml。
// 注入: D 两口距离 (= pitch − 2·(盘半径 + gap + claw_t + stub)), w 条宽 (= 端口宽)。
// 参数: pent_w 五边形底, pent_wall 直壁高, pent_h 总高 (屋顶 = pent_h − pent_wall), pent_gap 条–板缝 (SQUID 跨此缝),
//       pent_off 五边形中心距 to 口 (照片: 距 B 端盘心 540, 距 A 端 843), jj_w 结宽。五边形在 +y 侧、尖朝 +y (步骤 mirror: x 翻到 −y)。
// 输出: bar() 条面, pent() 五边形面, jj_x1..jj_y2 结 (条边中点 → 五边形底边中点)。
SetFactory("OpenCASCADE");
_bar = news; Rectangle(_bar) = { 0, -w/2, 0, D, w };
bar() = { _bar };
_xc = D - pent_off;  _y0 = w/2 + pent_gap;
_p1 = newp; Point(_p1) = { _xc - pent_w/2, _y0, 0 };
_p2 = newp; Point(_p2) = { _xc + pent_w/2, _y0, 0 };
_p3 = newp; Point(_p3) = { _xc + pent_w/2, _y0 + pent_wall, 0 };
_p4 = newp; Point(_p4) = { _xc, _y0 + pent_h, 0 };
_p5 = newp; Point(_p5) = { _xc - pent_w/2, _y0 + pent_wall, 0 };
_l1 = newl; Line(_l1) = { _p1, _p2 };  _l2 = newl; Line(_l2) = { _p2, _p3 };  _l3 = newl; Line(_l3) = { _p3, _p4 };
_l4 = newl; Line(_l4) = { _p4, _p5 };  _l5 = newl; Line(_l5) = { _p5, _p1 };
_cl = newll; Curve Loop(_cl) = { _l1, _l2, _l3, _l4, _l5 };
_s = news; Plane Surface(_s) = { _cl };
pent() = { _s };
jj_x1 = _xc;  jj_y1 = w/2;  jj_x2 = _xc;  jj_y2 = _y0;
