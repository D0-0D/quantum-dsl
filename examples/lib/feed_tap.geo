// feed_tap — 馈线耦合焊盘 (局部坐标, 原点 = 馈线西沿)。接口见 feed_tap.yaml。
// 输入: tap_w × tap_h 焊盘, tap_gap 焊盘–馈线间距, gap 焊盘–地缝。输出: tap(), pocket() (开到原点, 中间不留地), tap_x / tap_a = 端口。
SetFactory("OpenCASCADE");
tap_x = -tap_gap - tap_w;
_t = news; Rectangle(_t) = { tap_x, -tap_h/2, 0, tap_w, tap_h };
tap() = { _t };
_p = news; Rectangle(_p) = { tap_x - gap, -tap_h/2 - gap, 0, tap_w + tap_gap + gap, tap_h + 2*gap };
pocket() = { _p };
tap_a = Pi;
