// =====================================================================
// qm4q_transmon_cell.geo — 忠实复现 qiskit-metal 教程 "1.3 Build a 4-qubit
// chip" 里单个 TransmonPocket (Q1), 作为 LOM cell 做电容矩阵对比。
//
// 单位: 微米 (µm). OpenCASCADE kernel. Positive metal tone (CPW gap / pocket
// 用 BooleanDifference 从 ground sheet 蚀刻)。
//
// 几何 1:1 取自参考 notebook (examples/qiskit_metal_ref/qm4q_transmon_cell_ref.ipynb)
// 渲染的 design.qgeometry:
//   - pad_top / pad_bot  : 主焊盘 450×90µm, 间距 pad_gap=30µm, 中心 y=±60。
//   - conn_a..conn_d     : 4 个 connector_pad + 各自 **3 段折线 CPW 引线**
//                          (水平 → 斜段 → 水平到开路端 (±425,±202.5)), 宽 25µm。
//                          每条引线 = connector_pad ∪ 折线 wire 的合并轮廓 (单
//                          Plane Surface, 顶点由 qiskit-metal 中心线 mitre-buffer 算出)。
//   - JJ                 : 跨 pad_gap (lumped, 管线移除, 仅供 GDS)。
//   - ground sheet       : 1250×1050µm, 蚀刻 650×650 pocket + 4 条 CPW gap。
//                          引线只有水平段 (y=±202.5) 穿出 pocket 到开路端, 故 gap
//                          是 y=±202.5 的直 slot, 末端到 开路端+15µm (open-pin gap)。
//
// 构造要点:
//   1. ground 先建 (Boolean 先做完), 金属用显式高位 tag (≥1001) → tag 稳定。
//   2. 金属/衬底共面坐在 z=0 (金属直接坐硅上, 无真空缝); 管线在 fragment 时缩回
//      µm + 用 HXT 网格, 稳健处理这个共面界面 (见 _gmsh_layers/_gmsh_mesh)。
//   3. carve_conductors 先切 ground 再切导体两步, 避免 OCC 漏切穿缺口的引线。
// =====================================================================
SetFactory("OpenCASCADE");
Include "qlib.geo";

// ---- 设计参数 (µm) -------------------------------------------------
pad_w   = 450;   pad_h = 90;   pad_gap = 30;
pad_cy  = (pad_h + pad_gap) / 2;   // = 60
jj_w    = 20;
cpw_w   = 25;    cpw_gap = 12;   gap_w = cpw_w + 2*cpw_gap;  // 49
open_gap = 15;                    // qiskit-metal open-pin 端 gap
lead_tip = 425;  lead_y = 202.5;  // 引线开路端 (水平段在 y=±202.5)
pkt_w   = 650;   pkt_h = 650;
g_x0 = -625; g_y0 = -525; g_w = 1250; g_h = 1050;

// ---- 1) ground + pocket + 4 条直 CPW gap @ y=±202.5 (先建) ----------
gs = news; Rectangle(gs) = { g_x0, g_y0, 0, g_w, g_h };
sground = gs; pkt_cx = 0; pkt_cy = 0; Call GROUND_POCKET;
sground = sret; gx1 =  225; gy1 =  lead_y; gx2 =  (lead_tip+open_gap); gy2 =  lead_y; gw = gap_w; Call GROUND_CUTOUT;
sground = sret; gx1 = -225; gy1 =  lead_y; gx2 = -(lead_tip+open_gap); gy2 =  lead_y; gw = gap_w; Call GROUND_CUTOUT;
sground = sret; gx1 =  225; gy1 = -lead_y; gx2 =  (lead_tip+open_gap); gy2 = -lead_y; gw = gap_w; Call GROUND_CUTOUT;
sground = sret; gx1 = -225; gy1 = -lead_y; gx2 = -(lead_tip+open_gap); gy2 = -lead_y; gw = gap_w; Call GROUND_CUTOUT;
Physical Surface("ground::1::chip::gnd") = { sret };

// ---- 2) 主焊盘 + JJ (显式高位 tag) ---------------------------------
Rectangle(1001) = { -pad_w/2,  pad_cy - pad_h/2, 0, pad_w, pad_h };
Physical Surface("metal::1::Q1::pad_top") = { 1001 };
Rectangle(1002) = { -pad_w/2, -pad_cy - pad_h/2, 0, pad_w, pad_h };
Physical Surface("metal::1::Q1::pad_bot") = { 1002 };
Rectangle(1003) = { -jj_w/2, -pad_gap/2, 0, jj_w, pad_gap };
Physical Surface("jj::1::Q1::jj") = { 1003 };

// ---- 3) 4 个折线连接器 (connector_pad ∪ bent wire, 单 Plane Surface) ----
// 顶点取自 qiskit-metal 中心线 buffer(cap=flat, join=mitre); 见 docs 说明。
// conn_a (top-right): pad x[100,225] y[120,150] + 折线到开路端 (425,202.5)
Point(1004) = { 225.000, 120.000, 0 };
Point(1005) = { 100.000, 120.000, 0 };
Point(1006) = { 100.000, 150.000, 0 };
Point(1007) = { 225.000, 150.000, 0 };
Point(1008) = { 245.091, 150.000, 0 };
Point(1009) = { 315.091, 215.000, 0 };
Point(1010) = { 425.000, 215.000, 0 };
Point(1011) = { 425.000, 190.000, 0 };
Point(1012) = { 324.909, 190.000, 0 };
Point(1013) = { 254.909, 125.000, 0 };
Point(1014) = { 225.000, 125.000, 0 };
Line(1015) = { 1004, 1005 };
Line(1016) = { 1005, 1006 };
Line(1017) = { 1006, 1007 };
Line(1018) = { 1007, 1008 };
Line(1019) = { 1008, 1009 };
Line(1020) = { 1009, 1010 };
Line(1021) = { 1010, 1011 };
Line(1022) = { 1011, 1012 };
Line(1023) = { 1012, 1013 };
Line(1024) = { 1013, 1014 };
Line(1025) = { 1014, 1004 };
Curve Loop(1026) = { 1015, 1016, 1017, 1018, 1019, 1020, 1021, 1022, 1023, 1024, 1025 };
Plane Surface(1027) = { 1026 };
Physical Surface("metal::1::Q1::conn_a") = { 1027 };
// conn_b (top-left): pad x[-225,-100] y[120,150] + 折线到 (-425,202.5)
Point(1100) = { -100.000, 150.000, 0 };
Point(1101) = { -100.000, 120.000, 0 };
Point(1102) = { -225.000, 120.000, 0 };
Point(1103) = { -225.000, 125.000, 0 };
Point(1104) = { -254.909, 125.000, 0 };
Point(1105) = { -324.909, 190.000, 0 };
Point(1106) = { -425.000, 190.000, 0 };
Point(1107) = { -425.000, 215.000, 0 };
Point(1108) = { -315.091, 215.000, 0 };
Point(1109) = { -245.091, 150.000, 0 };
Point(1110) = { -225.000, 150.000, 0 };
Line(1111) = { 1100, 1101 };
Line(1112) = { 1101, 1102 };
Line(1113) = { 1102, 1103 };
Line(1114) = { 1103, 1104 };
Line(1115) = { 1104, 1105 };
Line(1116) = { 1105, 1106 };
Line(1117) = { 1106, 1107 };
Line(1118) = { 1107, 1108 };
Line(1119) = { 1108, 1109 };
Line(1120) = { 1109, 1110 };
Line(1121) = { 1110, 1100 };
Curve Loop(1122) = { 1111, 1112, 1113, 1114, 1115, 1116, 1117, 1118, 1119, 1120, 1121 };
Plane Surface(1123) = { 1122 };
Physical Surface("metal::1::Q1::conn_b") = { 1123 };
// conn_c (bottom-right): pad x[25,225] y[-150,-120] 200×30 + 折线到 (425,-202.5)
Point(1200) = { 324.909, -190.000, 0 };
Point(1201) = { 425.000, -190.000, 0 };
Point(1202) = { 425.000, -215.000, 0 };
Point(1203) = { 315.091, -215.000, 0 };
Point(1204) = { 245.091, -150.000, 0 };
Point(1205) = { 225.000, -150.000, 0 };
Point(1206) = { 25.000, -150.000, 0 };
Point(1207) = { 25.000, -120.000, 0 };
Point(1208) = { 225.000, -120.000, 0 };
Point(1209) = { 225.000, -125.000, 0 };
Point(1210) = { 254.909, -125.000, 0 };
Line(1211) = { 1200, 1201 };
Line(1212) = { 1201, 1202 };
Line(1213) = { 1202, 1203 };
Line(1214) = { 1203, 1204 };
Line(1215) = { 1204, 1205 };
Line(1216) = { 1205, 1206 };
Line(1217) = { 1206, 1207 };
Line(1218) = { 1207, 1208 };
Line(1219) = { 1208, 1209 };
Line(1220) = { 1209, 1210 };
Line(1221) = { 1210, 1200 };
Curve Loop(1222) = { 1211, 1212, 1213, 1214, 1215, 1216, 1217, 1218, 1219, 1220, 1221 };
Plane Surface(1223) = { 1222 };
Physical Surface("metal::1::Q1::conn_c") = { 1223 };
// conn_d (bottom-left): pad x[-225,-100] y[-170,-120] 125×50 + 折线到 (-425,-202.5)
Point(1300) = { -315.091, -215.000, 0 };
Point(1301) = { -425.000, -215.000, 0 };
Point(1302) = { -425.000, -190.000, 0 };
Point(1303) = { -324.909, -190.000, 0 };
Point(1304) = { -254.909, -125.000, 0 };
Point(1305) = { -225.000, -125.000, 0 };
Point(1306) = { -225.000, -120.000, 0 };
Point(1307) = { -100.000, -120.000, 0 };
Point(1308) = { -100.000, -170.000, 0 };
Point(1309) = { -225.000, -170.000, 0 };
Point(1310) = { -225.000, -150.000, 0 };
Point(1311) = { -245.091, -150.000, 0 };
Line(1312) = { 1300, 1301 };
Line(1313) = { 1301, 1302 };
Line(1314) = { 1302, 1303 };
Line(1315) = { 1303, 1304 };
Line(1316) = { 1304, 1305 };
Line(1317) = { 1305, 1306 };
Line(1318) = { 1306, 1307 };
Line(1319) = { 1307, 1308 };
Line(1320) = { 1308, 1309 };
Line(1321) = { 1309, 1310 };
Line(1322) = { 1310, 1311 };
Line(1323) = { 1311, 1300 };
Curve Loop(1324) = { 1312, 1313, 1314, 1315, 1316, 1317, 1318, 1319, 1320, 1321, 1322, 1323 };
Plane Surface(1325) = { 1324 };
Physical Surface("metal::1::Q1::conn_d") = { 1325 };
