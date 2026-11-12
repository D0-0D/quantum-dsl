// two_pads_eigen_leads.geo — two_pads_eigen.geo 的诊断变体: 结面缩短到 4 µm, 两侧用 10 µm 宽金属引线补齐间隙。
// 引线挂在各自焊盘的 component 上 (A / B), 所以静电 LOM 把它算进岛电容; 本征模里端口才更接近"集总"。
// 用途: 区分 two_pads_eigen 的 f_eig−f_LOM 偏差里有多少来自 80 µm 长端口本身 (tools/eigen_check.py)。
SetFactory("OpenCASCADE");

padA = news;
Rectangle(padA) = { -120, -40, 0, 80, 80 };
leadA = news;
Rectangle(leadA) = { -40, -5, 0, 38, 10 };     // x[-40,-2]
Physical Surface("metal::1::A::pad") = { padA, leadA };

padB = news;
Rectangle(padB) = { 40, -40, 0, 80, 80 };
leadB = news;
Rectangle(leadB) = { 2, -5, 0, 38, 10 };       // x[2,40]
Physical Surface("metal::1::B::pad") = { padB, leadB };

jj = news;
Rectangle(jj) = { -2, -5, 0, 4, 10 };          // 4 µm 长 (跨缝) × 10 µm 宽
Physical Surface("jj::1::Q::jj") = { jj };
