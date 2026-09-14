// cpw_meander — 连接型模板: 从原点 (from 端口) 沿 +x 到 (D, 0) (to 端口) 的定长蛇形 CPW。接口见 cpw_meander.yaml。
// 注入: D 两口距离, w 中心导体宽 (= 端口宽), L 目标画出长度; 参数: R 弯半径, n_legs 腿数, gap 缝宽。
// 输出: cpw_centre() 中心导体面表, cpw_etch() 缝工具面表 (宽 w + 2 gap, 同一路径), cpw_length 记账长度 (== L)。
SetFactory("OpenCASCADE");
Include "cpw_macros.geo";
_lib_x1 = 0; _lib_y1 = 0; _lib_x2 = D; _lib_y2 = 0; _lib_w = w;
_lib_R = R; _lib_n = n_legs; _lib_L = L;
Call LIB_CPW_MEANDER;
cpw_centre() = _lib_faces();  cpw_length = _lib_mlen;
_lib_w = w + 2*gap;
Call LIB_CPW_MEANDER;
cpw_etch() = _lib_faces();
