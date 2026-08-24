> **性质: 原始参考资料**(codex gpt-5.6-sol xhigh, 202 次检索, 2026-08-24;
> gpt-5.5(68 次检索)独立交叉跑。两份唯一分歧: Krantz Eq.105 的 g 频率因子
> 读作 f01(5.5)还是"推导上对应 f_p"(5.6)——恰证明这是文献自身的口径分叉,
> 结论落点见 [physics-pipeline.md](physics-pipeline.md) §2。本文取 5.6 版全文。

以下统一按普通频率 \(f,g,\chi\)（Hz）书写；文献多用角频率 \(\omega,g\)（rad/s），只要全式一致，二者相差统一的 \(2\pi\)。

**1. \(g\) 的口径**

一句话结论：双 transmon 的标准首阶 Duffing/LOM 公式使用线性化的裸等离子频率 \(f_p=\sqrt{8E_CE_J}/h\)，用含 \(-E_C\) 修正的 \(f_{01}\) 会系统性低估 \(g\)，不是 Blais 或 Qiskit legacy LOM 的推导口径。

- Blais RMP Eq. (23)/(24) 从谐振近似定义相位、电荷零点涨落，Eq. (25) 明确区分
  \[
  f_p=\sqrt{8E_CE_J}/h,\qquad f_{01}=f_p-E_C/h.
  \]
  其双 transmon Eq. (133)/(134)
  \[
  \hbar J=\frac{2E_{C1}E_{C2}}{E_{C_c}}
  \left(\frac{E_{J1}}{2E_{C1}}\frac{E_{J2}}{2E_{C2}}\right)^{1/4}
  \]
  在弱耦合下等价于
  \[
  g_{\rm lin}=\frac{\beta}{2}\sqrt{f_{p1}f_{p2}}.
  \]
  证据：[Blais et al., Eq. 23–25、133–134](https://arxiv.org/html/2005.12667)。

- Krantz Eq. (27) 保留 \(4e^2C_g n_1n_2/(C_1C_2)\)，Eq. (31) 才写成 Duffing 耦合；它没有显式打印“用 \(f_{01}\) 还是 \(f_p\)”的紧凑式，因此严格说没有直接二选一，但按其谐振子零点涨落推导，leading order 同样对应 \(f_p\)。证据：[Krantz et al., Eq. 27、31](https://arxiv.org/html/1904.06560)。

- Qiskit legacy LOM 同时计算 `wq0=1/sqrt(LJ*Cq)` 和 `wq=wq0-EC`：[源码 L74–96](https://github.com/qiskit-community/qiskit-metal/blob/main/src/qiskit_metal/analyses/quantization/lumped_capacitive.py#L74-L96)；但 `gqbus` 用 `Zqp=sqrt(LJ/Cq)` 的线性零点涨落，而非后来覆盖的数值 \(f_{01}\)：[源码 L267–268](https://github.com/qiskit-community/qiskit-metal/blob/main/src/qiskit_metal/analyses/quantization/lumped_capacitive.py#L267-L268)。

- 新 composite LOM 更严格：直接以带符号的 \([C_k^{-1}]_{ij}\hat Q_i\hat Q_j\) 构造耦合并数值对角化，不需要人为选择 \(f_p\) 或 \(f_{01}\)：[`compute_gs` / `add_interaction`](https://qiskit-community.github.io/qiskit-metal/_modules/qiskit_metal/analyses/quantization/lom_core_analysis.html#CompositeSystem.compute_gs)。

定量地，令 \(r_i=E_{Ji}/E_{Ci}\)：

\[
\frac{g_{f_{01}}}{g_{f_p}}
=\sqrt{\left(1-\frac1{\sqrt{8r_1}}\right)
       \left(1-\frac1{\sqrt{8r_2}}\right)}.
\]

两边均 \(r=20\) 时低 \(7.906\%\)，均 \(r=50\) 时低 \(5.000\%\)，一边 20、一边 50 时低 \(6.46\%\)。另外，`abs(Cinv_ij)` 只适合输出耦合强度；内部 Hamiltonian 应保留符号，多路径或环路中相对符号可观测，Qiskit composite 源码也保留 `c_i = c_inv_k[idx1, idx2]`。

**2. \(\chi\) 公式**

一句话结论：你们的 `chi_0/chi_1` 是正确的三能级、二阶、含反旋转项结果，但并不是 Koch 2007 Eq. (3.9)/(3.10) 的原式，Qiskit 源码这里存在误引。

- Koch 期刊 Eq. (3.9)/(3.10)，对应 arXiv HTML Eq. (27)/(28)，实际是 RWA 形式：
  \[
  \chi=\chi_{01}-\chi_{12}/2,\qquad
  \chi_{ij}=\frac{g_{ij}^2}{\omega_{ij}-\omega_r},
  \]
  没有 \((\omega_{ij}+\omega_r)^{-1}\) 项。证据：[Koch 期刊 PDF](https://schusterlab.stanford.edu/static/pdfs/Koch2007.pdf)、[arXiv Eq. 27–28](https://arxiv.org/html/cond-mat/0703002v2)。

- Qiskit 的实现确实与你们相同，包括正频率和反旋转分母，但源码注释将两行分别标成 Koch Eq. (3.10)/(3.9)：[源码 L98–122](https://github.com/qiskit-community/qiskit-metal/blob/main/src/qiskit_metal/analyses/quantization/lumped_capacitive.py#L98-L122)。

- 完整非 RWA 的文献依据可用 Zhu et al.：Eq. (2) 保留 \((a+a^\dagger)\) 相互作用，Eq. (11)–(14) 对所有正、负虚跃迁作二阶求和；取三能级及 \(g_{12}=\sqrt2g\) 即得到你们两式。证据：[Zhu et al., Eq. 2、11–14](https://arxiv.org/html/1210.1605)。

令 \(\Delta=f_{01}-f_r\)、\(\Sigma=f_{01}+f_r\)、\(\alpha=-E_C/h\)，你们的最终结果可化为

\[
\chi_{\rm full}=g^2\left[
\frac1\Delta-\frac1{\Delta+\alpha}
+\frac1\Sigma-\frac1{\Sigma+\alpha}\right].
\]

常见 RWA 近似为

\[
\chi_{\rm RWA}=\frac{g^2\alpha}{\Delta(\Delta+\alpha)},
\qquad
\frac{\delta\chi_{\rm CR}}{\chi_{\rm RWA}}
=\frac{\Delta(\Delta+\alpha)}{\Sigma(\Sigma+\alpha)}.
\]

当最后一个比值远小于 1 且 \(|g/\Delta|,\ |\sqrt2g/(\Delta+\alpha)|\ll1\) 时用 RWA；需要 Bloch–Siegert 精度或 \(g/\Sigma\) 不小时用完整式；在 \(\Delta\approx0\) 或 \(\Delta+\alpha\approx0\) 附近两种二阶式都失效，应对完整 Hamiltonian 数值对角化。文档还必须明确 \(\chi\) 是单边 cavity pull 还是两态腔频差 \(2\chi\)。

**3. 非对称 SQUID**

一句话结论：`hypot(cos x,d sin x)` 是标准、无奇点且非负的有效 Josephson 幅值，等价于 Koch 公式在吸收相位支路后的写法。

Koch arXiv Eq. (17)/(18)，即期刊 Eq. (2.17)/(2.18)，给出

\[
H_J=-E_{J\Sigma}\cos x\sqrt{1+d^2\tan^2x}\cos(\varphi-\varphi_0),
\quad \tan\varphi_0=d\tan x,
\]

其中 \(x=\pi\Phi/\Phi_0\)：[Koch Eq. 17–18](https://arxiv.org/html/cond-mat/0703002v2)。把符号或 \(\pi\) 相移吸收到 \(\varphi_0\) 后，幅值就是

\[
E_{J,\rm amp}=E_{J\Sigma}\sqrt{\cos^2x+d^2\sin^2x},
\]

Krantz Eq. (22) 直接采用这一 positive-hypot 形式：[Krantz Eq. 22](https://arxiv.org/html/1904.06560)。该约化假定 SQUID 环几何电感可忽略；静态磁通可消掉 \(\varphi_0\)，动态磁通驱动时则不能随意删除其时间依赖。

**4. 浮动双岛约化**

一句话结论：先求完整 \(C'\) 的逆再取差模块是文献和 composite LOM 的正确口径，先删除共模行列再求逆对应钉住共模电压的另一物理约束，通常不等价。

若

\[
C'=\begin{pmatrix}A&B\\B^T&D\end{pmatrix},
\]

则固定守恒共模电荷 \(q_\sigma=0\) 后，

\[
[C'^{-1}]_{\theta\theta}=(A-BD^{-1}B^T)^{-1};
\]

先删掉 \(\sigma\) 再逆只得到 \(A^{-1}\)，仅在 \(B=0\) 时相同。

- Yanay et al. Eq. (50)/(51) 变换到 \(+/-\) 坐标，Eq. (52) 先写完整 \(\check C^{-1}\) Hamiltonian，Eq. (53)/(54) 再从逆矩阵移除守恒的 \(+\) 模；其 Eq. (56)/(57) 给浮动 transmon 的有效电容和带符号耦合电容：
  \[
  C_{q,\rm eff}=C_{\rm sh}+
  \left[(C_1+C_{g1})^{-1}+(C_2+C_{g2})^{-1}\right]^{-1},
  \]
  \[
  C_c=\frac{C_{g1}C_2-C_{g2}C_1}
  {C_1+C_2+C_{g1}+C_{g2}}.
  \]
  证据：[Yanay et al., Eq. 50–57](https://arxiv.org/html/1910.00933)。

- Qiskit LOM 论文 Eq. (7b) 以 Schur complement 消除非动态坐标，Eq. (8) 使用完整 \(C_k^{-1}\)，Eq. (11a) 从该逆矩阵取子系统块，Eq. (12)/(13a) 从非对角块构造耦合：[Minev et al., Eq. 7–13](https://arxiv.org/html/2103.10344)。对应源码先使用 `C_inv_k`，再从其对角和非对角元生成 \(E_C\) 与耦合：[composite LOM 源码](https://qiskit-community.github.io/qiskit-metal/_modules/qiskit_metal/analyses/quantization/lom_core_analysis.html)。

完全悬浮且存在全局 gauge 零模时，原始 \(C\) 会奇异，不能直接普通求逆；必须先选 datum、固定总电荷扇区，或在约束子空间中求逆。另需钉死 \(\theta=\phi_a-\phi_b\) 还是 \((\phi_a-\phi_b)/2\)，因为坐标缩放会改变共轭电荷和 \(E_C\) 的数值因子。

**5. CPW 公式谱系**

一句话结论：零厚金属、准静态 CPW 的椭圆积分公式是标准共形映射结果，动力学电感应加到总 \(L'\) 后同步重算 \(Z_0\) 与相速，而有限衬底、背面地和有限膜厚必须按实际截面选择对应分支。

理想无限衬底公式为

\[
L_g'=\frac{\mu_0}{4}\frac{K(k')}{K(k)},\quad
C'=4\epsilon_0\epsilon_{\rm eff}\frac{K(k)}{K(k')},\quad
k=\frac{w}{w+2s},
\]

见 Göppl Eq. (2)–(5)：[Göppl et al.](https://arxiv.org/html/0807.4094)。其经典源流是 [Wen 1969](https://doi.org/10.1109/TMTT.1969.1127105)；工程汇总可见 [Simons, Chapter 2](https://onlinelibrary.wiley.com/doi/abs/10.1002/0471224758.ch2) 和 [Wadell](https://us.artechhouse.com/Transmission-Line-Design-Handbook-P743.aspx)。AGM 只是计算 \(K\) 的稳定数值算法，不改变物理模型。

- 有限开放衬底：Simons Eq. (2.37)/(2.38) 使用
  \[
  k_1=\frac{\sinh(\pi w/4h)}
  {\sinh[\pi(w+2s)/4h]},
  \]
  并以 \(K(k_1)/K(k_1')\) 修正 \(\epsilon_{\rm eff}\)；背面金属接地的 conductor-backed CPW 使用 `tanh` 分支，不能与开放衬底 `sinh` 分支混用。

- 超导动力学电感：Clem Eq. (11) 从超流动能定义 \(L_k'\)，薄膜一般式为 Eq. (34)
  \[
  L_k'=\frac{\mu_0\Lambda}{2I^2}\int K_z^2(x)\,dx,
  \]
  有限槽宽解析近似见 Eq. (47)/(48)，总电感见 Eq. (35)：
  \[
  L'=L_g'+L_k'.
  \]
  证据：[Clem, Eq. 11、34、35、47–48](https://arxiv.org/html/1210.5929v1)。当膜厚 \(t<2\lambda\) 时应使用 Pearl 长度 \(\Lambda=2\lambda^2/t\)；文中给出 \(\Lambda\ll a\) 时几何电感主导、\(\Lambda\sim a\) 时两者可比、\(\Lambda\gg a\) 时动力学电感主导。

加入 \(L_k'\) 后必须使用

\[
Z_0=\sqrt{\frac{L_g'+L_k'}{C'}},\qquad
v_p=\frac1{\sqrt{(L_g'+L_k')C'}},
\]

不能继续以纯介质 \(c/\sqrt{\epsilon_{\rm eff}}\) 作为相速。有限衬底在 \(h\) 不再远大于 \(w+2s\) 时应至少计算修正式；有限金属厚度应比较有效边缘位移 \(\Delta\) 与槽宽 \(s\)，而非只比较 \(t/w\)。若存在窄槽、有限地宽、多层介质、背金属或封装，最好直接升级到 2D/3D EM，并以闭式模型差值和频率误差预算决定是否可忽略。

**最终判定**

- **与文献标准一致**：在正确选 ground、加入结电容并完成坐标约束后，\(E_C=e^2[C^{-1}]_{ii}/2\)、\(C_\Sigma=1/[C^{-1}]_{ii}\)；\(E_J=(\hbar/2e)^2/L_J\)；首阶 \(f_{01}\) 与 \(\alpha\)；静态 SQUID `hypot`；浮动双岛完整求逆取差模块；理想 CPW 共形映射及 \(L'=L_g'+L_k'\)。LOM Eq. (8)/(11a) 也明确支持逆矩阵对角，而非 Maxwell 对角：[LOM 论文](https://arxiv.org/html/2103.10344)。

- **多种惯例之一、必须钉死文档**：\(g\) 是 harmonic LOM 值、真实电荷矩阵元值还是经验校准值；\(g,\chi\) 的 Hz/rad·s\(^{-1}\) 单位；\(\chi\) 或 \(2\chi\) 定义；RWA/non-RWA；坐标归一化、datum、开放/背地 CPW 分支。\(C_\Sigma=1/[C^{-1}]_{ii}\) 应称为 dressed effective capacitance，而不是 Maxwell 自电容。

- **可疑、建议修改**：双 transmon 的紧凑 \(g\) 使用修正后 \(f_{01}\)；把完整非 RWA `chi_0/chi_1` 引成 Koch Eq. (3.9)/(3.10)；在内部 Hamiltonian 对 \(C^{-1}_{ij}\) 取绝对值；对仍含 ground/gauge 零模的矩阵直接求逆。

- **数值处理注意**：\((C+C^T)/2\) 只是小反对称数值残差的清理，不是物理步骤；应同时记录 \(\|C-C^T\|/\|C\|\)、最小特征值和条件数，残差不小时不能靠对称化掩盖问题。

- **SI-2019 表述需收窄**：\(h,e,c,\Phi_0\) 在新 SI 中精确，因此你们的量子电路常数链可以称精确；但 2019 后 \(\mu_0,\epsilon_0\) 不再是定义值而带实验不确定度，CPW 部分不能笼统称“全部常数精确”。证据：[BIPM SI Appendix 2](https://www.bipm.org/documents/20126/41489676/SI-App2-ampere.pdf)。