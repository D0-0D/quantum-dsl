// pad — 矩形焊盘模板 (局部坐标, 中心在原点)。接口见 pad.yaml。
// 输入: w, h (µm), gap (>0 时另出蚀刻 pocket = 焊盘外扩 gap, 供 ground: sheet 减去)。
// 输出: pad_faces(); 端口 E/N/W/S = 四条边中点, 外法向, 宽 = 边长 (CPW 从此边整宽出发)。
SetFactory("OpenCASCADE");
_s = news; Rectangle(_s) = { -w/2, -h/2, 0, w, h };
pad_faces() = { _s };
port_x() = { w/2, 0, -w/2, 0 };   port_y() = { 0, h/2, 0, -h/2 };
port_a() = { 0, Pi/2, Pi, -Pi/2 }; port_w() = { h, w, h, w };
If (gap > 0)
  _p = news; Rectangle(_p) = { -w/2 - gap, -h/2 - gap, 0, w + 2*gap, h + 2*gap };
  pocket() = { _p };
EndIf
