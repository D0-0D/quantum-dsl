# quantum_dsl — Plan

Backlog 只放**尚未做**的事; 已落地的看 [`status.md`](status.md), 踩过的坑看文末「已了结」。按需立项, 不是排期。
Legend: `[ ]` not started · `[~]` in progress · `[x]` done。

## Backlog

- [x] **读出链路 + `tune:`（2026-10-04, deep-research 调研后落地）**: 见 status; 物理口径 physics §8.1, 语法 grammar §3.5。
- [ ] **读出 / 综合的后续（2026-10-04 列, 按调研优先级）**:
      ① 带馈线的例子（`ports` 的 κ 与 `T1_port_us` 至今只有闭式测试锚）—— xmon_readout 加一条直通馈线 + λ/4 短路端不画;
      ② `cpw_route` 的 `length:` 接 f_r 旋钮（现在只有 `cpw_meander` 例子跑过 `R1.length.f_r`）; 2–4 比特小芯片综合示例;
      ③ 第 0 步闭式初值: f01 + α → (E_J, C_Σ*) 联合反推（嵌套求根, 无 scipy → 自写二分）, 给几何旋钮好的起点（ANMod 随机初值 2/10 不收敛）;
      ④ 求解可信度（调研**未取证**, 先补查再做）: converge 三档 + Richardson 观测阶、airbox 尺寸扫、工艺参数 ±δ 有限差分灵敏度 → 线性协方差进 validation;
         注意 gmsh 重网格噪声须 ≪ tol（ANMod 的 κ 噪声让旋钮抖 10%）;
      ⑤ FEM 结果按内容哈希缓存（tune / 灵敏度复用）; 频域 driven（Palace）交叉验证 κ / Purcell（单模 κ(g/Δ)² 只是近似）;
      ⑦ **lit-research 灵感（2026-10-05, 23 条三票确认只落在求解可信度 / 工艺离散 / 碰撞良率; 其余是未核验线索, 用前回原文）**:
         便宜: Palace 每次静电解都算 ZZ 误差指示量（error-indicators.csv, 能量范数, 多 terminal 取 RMS）→ 免费读进 results 当报警, **不能**当 C_ij 收敛证据;
         converge 加 GCI（两档用理论阶 p = 2 + Fs = 3 现在就能做, 三档出观测阶 + 渐近比; 比例取 1/0.8/0.64 别用 r = 2）; FEM 结果按内容哈希缓存（gplugins: GDS 字节 MD5 + 排序 kwargs → npz + sidecar yml）;
         结参数加 `R_n`（Ambegaokar–Baratoff, 制备后按室温电阻重预测 f01）与可选 `E_J2/E_J1` 约瑟夫森高次谐波（KIT/IBM 实测 few %, 解释 |α| 高估; 电荷基里 cos2φ 一行）;
         重网格噪声探针（同几何亚 µm 平移重解, 定 tune tol 与有限差分步长的底噪; 文献: 只重网格就让代价变 ~2×, 对策 FEMWARP 网格形变）。
         中等: 分布式腔模型（λ/4 超越方程 tan θ = C₀Z₀ω, Google 1801.07904 App. D; 或 TL+耦合电容 S 参数拟合 L_eff/C_eff, arXiv 2607.19543 对 HFSS 频率 <0.5% / 线宽 <3%）替代 `drawn: full` 换对地;
         线性正规模（多模 LOM）→ Purcell 滤波器节点 + 读出复用（Google: 每腔一滤波器, 间隔 ~160 MHz, J/2π 10 / κ_P/2π 40 MHz 抗 5 MHz 失谐）;
         `process:` 块 σ 传播（f01 离散 Rn 主导: IBM σf 2.3% / σR 4.6%; 但 Chalmers σEC 0.8% 与 Rn 相当, 只算结低估 √2; α/g/χ 几何是主项）+ 碰撞良率 MC（规则表用户声明, 与门架构绑定; Morvan 2112.01634 九族线性约束, Zhang 2410.20283 MILP 开源）。
         贵: 盲验证 = SQuADDS_DB `measured_device_database`（3 器件带公开设计代码, WM1 六对 qubit–腔实测 f01/α/g/χ/f_r）—— 要把 Qiskit Metal 设计移植成模板（无 GDS 导入）;
         对照基线 SQDMetal 8 只 transmon RMSE f 6.0 / α 13.3 / g 24.5 / f_r 3.5%; Palace 本征模 / driven 第二、三 pass（2511.09041: 腔频 <0.3%, κ 3/4 在 16% 内; 收敛设置 r1.5o4）; AMR 透传（先验证零厚度 imprint 兼容）。
      ⑥ 天花板: tune 只支持版图路线顶层步骤参数; 耦合比例律（χ ∝ (w_rq/w_q)² 那种 2D 子问题）未做, 现在靠对数割线吸收串扰; 终版配置丢 YAML 注释。

- [ ] **`cpw_meander` 退不退役**（拍板）: 它是 `cpw_route` 的退化情形（直段需求也由 `cpw_route` 无 `length:` 覆盖）。退役要迁 `xmon_readout`（= `xmon_readout_tune` 底版, `R1.length.f_r` 旋钮）
      → `cpw_route`、`tests/test_layout.py` 三处、`tests/test_route.py` 的退化一致性锚与报错测试; `LIB_CPW_ARC` / `length:` 已有多个消费者, 不动。
- [ ] **自动布线 v3 候选（2026-10-01 调研, 未拍板）**: ① 多路顺序布线（已布的路膨胀 2R 当障碍, 失败换顺序 / 拆一条重布; PathFinder 协商拥塞等真撞了再上）—— 轨道图已是底座;
      ② 定长可行性预检: 走廊可装长度 ≈ 面积 / 节距 (BSG-Route, ICCAD 2008), 分摊前早报错; ③ 轨道图 k 条最优 (现每对端弧一条)。出处见 session 2610011200。
- [ ] **自动布线收尾（v1 遗留）**: 拍板 ① pad↔pad（两岛端, 如馈线）没有 net 命名规则（`_net` raise）; ② `axis: free` 只做 Dubins CSC, 两口距 < 4R 时不保证最短（可行）。
      CCC 型 / taper / 分端 lead 仍是 `# ponytail:` 天花板, 有需求再开（设计稿 `auto-route.md` §13）。
- [~] **Chen 2025 phase 2**: ① 整片 42 导体一次解 —— **已做**（2026-09-18 c24a1, 100/4, 8.1 M 未知量, 69 GB, 86 min; physics §13.1 ⑤）, 中心比特与十字到 0.1 MHz 相同, 以后比特级量用十字;
      ② d 单量拟合 —— 改用实测 α 定 d（十字 d = 4.0 µm 命中）, 其余（g_qc / g_qq / 11 个 SI 电容）作预测; 用 C04 定 d 的方案作废（SI 电容与我们互差 ×0.4–1.45, 不是干净的锚）;
      ③ 网格两档 —— **已做**（十字 100/4 vs 80/3 E_C +0.3%; 3×3 100/4 vs 150/6 E_C −0.6%）; gap ±3 µm + 蓝宝石 ε 9.4/11.5 灵敏度未做（互容 ×0.4–0.5 的缺口在 gap）; ④ 读出爪（225°）/ 45° 方焊盘 / λ/4 谐振器 —— 谐振器形状用 `cpw_route` 或手写, 等效长度来源仍开放;
      ⑤ 5 µm 薄板厚度方向的 Box 尺寸场（session 2609121024 的 G7, 粗网格实测能跑, 报数前再评估）。
- [ ] **`readout_pad.geo` demo 落仓**（2026-09-16 `.claude/session/2609161007.md`）: 9/14 演示过的 `{geo: readout_pad.geo, frame: Q00}` 文件没进仓, chen 版图头注引的就是它;
      `frame:` 至今无测试。做法: 文件进 `examples/`, chen 头注改「取消注释这一步即可」（不进正式步骤: 会多一个无结浮岛, 动 87 名 / 12 块 / 物理口径）, `tests/test_layout.py` 加一条 `frame:` 断言。
- [x] **`targets:` 块**（issue #23, 2026-09-24 落地; 分块结果不核对 / 无 capacitance 元素目标 = 有需求再加）: meta 里声明期望的 C / E_C / g, `build(solve=True)` 在 results.yaml 里报偏差。sung 的「对论文 ±8%」现在写死在测试里, 应该是用户可声明的数据。
- [x] **网格收敛扫描**（issue #26, 2026-09-24 落地 `converge()`; 只做 h 加密, 不扫 order / 渐变区）: 每个报出的 C 值给两档网格的相对变化。实测依据: sung 契约配方（80/2）与粗档（160/10）跨 ~5.5%, 未收敛; two_pads 40/4 → 20/2 移 ~0.8%。
      可作为 `build(..., converge=True)` 或独立工具。
- [x] ~~**第二求解器后端**（issue #25）~~ 2026-09-24 关闭: 差异已在 §12 结案, StatElecSolve 只有 P1 做不了报数后端: ElmerFEM 交叉验证在 sung 翻案里已证明价值。2026-08-27 已验证可行路径: `ElmerGrid 14 2` 直接吃我们的 gmsh msh + `StatElecSolve`
      （P1, Calculate Capacitance Matrix, Coordinate Scaling 1e-6）, 与 Palace order-1 同网格整 3×3 相对差 1.9e-7（sif 在 `.claude/xmon-evidence/`）。剩下的只是产品化（SPICE→Maxwell 换算）。
- [ ] **Palace AMR 试点**: `Model.Refinement`（0.12 起支持 Electrostatic）是边缘 seed 网格之上的二次自适应, 不能取代 Distance/Threshold 尺寸场; 大网格（sung 级）再试,
      1–2 轮、设 MaxSize, 避开 `SaveAdaptMesh+SaveAdaptIterations` 组合（0.16.1 覆盖 bug）。
- [ ] **域尺寸扫**: sung 例子 airbox 取自 v3 实测档, two_pads 的 side=80 是刻意小型化; 给真实器件报数前应做 1×/1.5×/2× 扫（C 变化 <0.2–0.5% 验收）。
- [ ] **CI**: 默认 `pytest -q` 在 CI 上就是 39 passed / 2 skipped, 只需 Python 3.13 + `pip install -e '.[gmsh,gds,test]'`（gmsh 装得起, Palace 装不起——live 正好 skip）。
- [ ] **sung 求解产物缓存**: 一次 build 现已同时断言 C_Σ 与 β（不再重复求解）; 要在同一 results.yaml 上加断言, 直接读 `v4-dev` 分支 `.claude/n15-evidence/results_o2_contract.yaml` 归档件, 不必重跑。
- [ ] **sung 措辞订正两处**（2026-08-26 对照论文原文发现）: ① meta 头注与 physics §12 说论文 g 在「ω_c/2π=5.45 GHz 工作点」—— 论文 Table I 脚注 c 写明 g 是在 ω_1=ω_2=ω_c=4.16 GHz 处报的;
      我们 g_1c=106.8 MHz 折回 4.16 GHz 得 81.7 MHz（+13%, 与 β +8% 同源）, 频率因子解释不变、参考点要改。② physics §12 把 −4~6% 缺口归因「版图缺失」, 但几何是 v3 在 Elmer P1 上标定到论文值的 ——
      缺口首先是标定吸收 P1 正偏的必然结果（report 04 §6 ③）; 版图 / 拓扑差异解释的是「为何不该期待精确命中」。因果主次待改。
- [ ] **sung_2021_xmon 后续**（2026-08-27, `docs/report/Aug27/04` §8）: ① 描摹器亚像素边缘拟合 + 局部自适应阈值（阈值是主导测量误差: THR 143.5→120 ⇒ C_Σ +2.5/+4.0/+6.1%）;
      ② 参数化版若要再逼近描摹版, 补 Xmon 上臂旁的 L 形读出槽与 5 条走线（值 1–4% C_Σ, β 无关）; ③ 5 µm 地条的 FEM 敏感性——β 的 ±5–10% 估计未实测;
      ④ 合并时把 `.claude/xmon-evidence/`、`.claude/chen-evidence/` 迁到 v4-dev（sung 证据的惯例）; ⑤ 要不要给 xmon 加一条只记录不断言的 live 测试（它是预测不是判据）。

## 已了结, 别重新踩

- **契约编号 Nxx 已清除（2026-09-17）**: v4.0 收口时是有意保留的（`447590d` 提交信息明写「表的测试列改指新测试函数」, 编号照留）, 之后版图编排、Chen 模板又各叠了一个编号;
  现在 SPEC 条目按名字引用, 测试 docstring 写「契约「名」」。别再往 SPEC 加编号。session log 是历史, 不改。
- **「两口正对」的来历**: 8/27 工作树 `CPW_MEANDER_PORTS`（用户: cpw 起始角必须是 pad 的面）→ 设计稿 v3 §1.4 → `layout.py` `_connect_pose`。它是端点约束, 不是算法能力; 不正对的两口现由 `cpw_route` 处理。
- Palace order 2 多 rank「静默掉 rank」（v3 issue #22）: 64C 裸机 np=4/32 均 rc=0 且 C 一致到 1e-12 —— 是 v3 运行环境 / 构建问题, 不是 Palace bug, 不必为它保留分块降规模。
- OCC 共面布尔 / ε-nudge / fragment scale-ladder（v3 issues #18 #24）: 零厚度片 imprint 路线下没有布尔减, 这一整类失效结构性消失。
- 「Palace 拒绝内部面 Terminal」（v3 判断）: 误诊。根因是作者 Physical 组在 imprint 路径下存活并与实现组重叠 → 同一面两条边界元; 捕获后 `removePhysicalGroups()` 即愈。
- WSL 上 MPI_Init 挂死: hwloc gl 插件探测 X display; `HWLOC_COMPONENTS=-gl` 根治, 裸机不需要。
