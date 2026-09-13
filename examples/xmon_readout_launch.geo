// xmon_readout_launch.geo — 手写步骤: 读出腔另一端的耦合焊盘 (发射焊盘的简化), 面朝西, 在 x = 1400 处。
// 演示手写 .geo 与模板在同一模型里混用: 自己打 Physical 名 (层段 = 芯片层 id), 用输出变量声明端口与蚀刻工具面,
// 可以读到已放置实例的端口变量 (Q1_RO_x 等)。只增不改: 不动模板给的面。
SetFactory("OpenCASCADE");
lp_x = 1400;  lp_w = 60;  lp_h = 120;  lp_gap = 6;
f0 = news; Rectangle(f0) = { lp_x, -lp_h/2, 0, lp_w, lp_h };
Physical Surface("metal::m1::F0::launch") = { f0 };
f0_pocket = news; Rectangle(f0_pocket) = { lp_x - lp_gap, -lp_h/2 - lp_gap, 0, lp_w + 2*lp_gap, lp_h + 2*lp_gap };
f0_etch() = { f0_pocket };
f0_x() = { lp_x };  f0_y() = { 0 };  f0_a() = { Pi };  f0_w() = { 10 };     // 西边中点, 外法向 -x, CPW 宽 10
