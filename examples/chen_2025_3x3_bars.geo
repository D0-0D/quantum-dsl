// chen_2025_3x3_bars.geo — chen_2025_3x3_hand.layout.yaml 的手写步骤: 12 条 Chen 2025 条形耦合器 (条 + 五边形板 + 条–板间的结),
// 与 lib/bar_coupler.geo 逐点同一几何 (条宽 = 端口宽 30, 五边形 378 底 × 直壁 125 × 总高 300, 条–板缝 75, 板心距 to 口 273, 结宽 5),
// 只是不经模板, 在全局坐标下直接从编排器注入的端口变量 <实例>_<口>_x/y/w 起画。
// 每条: _x0,_y0 = from 口, _x1,_y1 = to 口, _w = 口宽, _flip = 五边形在 from→to 轴的哪一侧 (0 左 = 模板默认; 1 右 = 模板的 mirror: x),
// _name = net 名 (宏在 chen_2025_3x3_bar_macros.geo)。Physical 名与模板路线一致: metal::ta::<name>::bar / metal::ta::<name>_pent::pent / jj::jj::<name>::jj;
// 两端的爪 (比特模板画的外挂面) 由 layout 步骤的 connect: 归入 <name>。结能量在 meta circuit_model.qubits 里。
SetFactory("OpenCASCADE");
Include "chen_2025_3x3_bar_macros.geo";   // 宏与常数; 宏不能定义在本文件 (见那里的头注)

// 横向 H<i><j>: Q<i><j>.E → Q<i+1><j>.W, 五边形在 +y (轴左侧)
_name = "H00";  _x0 = Q00_E_x;  _y0 = Q00_E_y;  _x1 = Q10_W_x;  _y1 = Q10_W_y;  _w = Q00_E_w;  _flip = 0;
Call BAR_COUPLER;
_name = "H10";  _x0 = Q10_E_x;  _y0 = Q10_E_y;  _x1 = Q20_W_x;  _y1 = Q20_W_y;  _w = Q10_E_w;  _flip = 0;
Call BAR_COUPLER;
_name = "H01";  _x0 = Q01_E_x;  _y0 = Q01_E_y;  _x1 = Q11_W_x;  _y1 = Q11_W_y;  _w = Q01_E_w;  _flip = 0;
Call BAR_COUPLER;
_name = "H11";  _x0 = Q11_E_x;  _y0 = Q11_E_y;  _x1 = Q21_W_x;  _y1 = Q21_W_y;  _w = Q11_E_w;  _flip = 0;
Call BAR_COUPLER;
_name = "H02";  _x0 = Q02_E_x;  _y0 = Q02_E_y;  _x1 = Q12_W_x;  _y1 = Q12_W_y;  _w = Q02_E_w;  _flip = 0;
Call BAR_COUPLER;
_name = "H12";  _x0 = Q12_E_x;  _y0 = Q12_E_y;  _x1 = Q22_W_x;  _y1 = Q22_W_y;  _w = Q12_E_w;  _flip = 0;
Call BAR_COUPLER;
// 纵向 V<i><j>: Q<i><j>.N → Q<i><j+1>.S, 五边形在 +x (轴右侧 = 模板路线的 mirror: x)
_name = "V00";  _x0 = Q00_N_x;  _y0 = Q00_N_y;  _x1 = Q01_S_x;  _y1 = Q01_S_y;  _w = Q00_N_w;  _flip = 1;
Call BAR_COUPLER;
_name = "V10";  _x0 = Q10_N_x;  _y0 = Q10_N_y;  _x1 = Q11_S_x;  _y1 = Q11_S_y;  _w = Q10_N_w;  _flip = 1;
Call BAR_COUPLER;
_name = "V20";  _x0 = Q20_N_x;  _y0 = Q20_N_y;  _x1 = Q21_S_x;  _y1 = Q21_S_y;  _w = Q20_N_w;  _flip = 1;
Call BAR_COUPLER;
_name = "V01";  _x0 = Q01_N_x;  _y0 = Q01_N_y;  _x1 = Q02_S_x;  _y1 = Q02_S_y;  _w = Q01_N_w;  _flip = 1;
Call BAR_COUPLER;
_name = "V11";  _x0 = Q11_N_x;  _y0 = Q11_N_y;  _x1 = Q12_S_x;  _y1 = Q12_S_y;  _w = Q11_N_w;  _flip = 1;
Call BAR_COUPLER;
_name = "V21";  _x0 = Q21_N_x;  _y0 = Q21_N_y;  _x1 = Q22_S_x;  _y1 = Q22_S_y;  _w = Q21_N_w;  _flip = 1;
Call BAR_COUPLER;
