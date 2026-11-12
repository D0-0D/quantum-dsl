// two_pads_eigen.geo — two_pads.geo + 一个桥接间隙的结面 (tools/eigen_check.py 的本征模交叉验证用)。
//
// 焊盘与 two_pads.geo 逐位相同; 多出的 JJ 面 x[-40,40] × y[-5,5] 在两焊盘之间, role = jj:
// * 走产品静电管线 (build) 时 jj 面在网格化前被删 → 网格与 two_pads 回归锚相同, 结 = 集总 L 进 LOM
//   (meta 里 islands: [A, B] 的浮动 transmon);
// * tools/eigen_check.py 把它改名成 metal 面留在网格里, Palace 本征模挂 LumpedPort(L = 10 nH)。
SetFactory("OpenCASCADE");

padA = news;
Rectangle(padA) = { -120, -40, 0, 80, 80 };
Physical Surface("metal::1::A::pad") = { padA };

padB = news;
Rectangle(padB) = { 40, -40, 0, 80, 80 };
Physical Surface("metal::1::B::pad") = { padB };

jj = news;
Rectangle(jj) = { -40, -5, 0, 80, 10 };        // 80 µm 长 (跨缝) × 10 µm 宽
Physical Surface("jj::1::Q::jj") = { jj };
