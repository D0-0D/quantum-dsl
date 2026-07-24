# Spec: 复现 qiskit-metal 4-qubit 教程到电容矩阵 + 与 Elmer 对比

> 本文件准确记录**用户原始需求**与**截至暂停时的完整进度**,供后续会话恢复。
> 创建于 2026-06-27 会话。术语口径见 [口径与约束](#口径与约束)。

---

## 用户原始需求(逐条,按提出顺序)

1. **路径口径(/remote-control 时明确)**:接下来唯一在用(active/primary)的是
   **最新的 `*.meta.yaml` + 手写 `.geo`** 路径(`quantum_dsl.dsl.geo_build`)。
   - **「全用 YAML 写」**(旧 `.metal.yaml → shapely → QDesign`)记为 **legacy**。
   - **「emit geo」**(由 YAML 自动生成 `.geo`)也记为 **legacy**。
3. **诊断任务(已完成)**:看现有两个例子里"芯片那个"(`chip_layout`),给完整物理+计算图像,
   判断是否过于 toy-model。→ 已给结论:作为 DSL→GDS+mesh→Palace 全链路 demo 合格;作为真实
   芯片偏 toy(缺读出谐振器/ports/控制线、纯静电、直角矩形)。
4. **主任务**:去 qiskit-metal **官方 examples/教学**找一个**真实例子**(用户举例"一开始的完整
   4qubit,有简单点的更好"),**用我们的语言(meta.yaml + 手写 geo)做完整复现,到电容矩阵**,
   并**与 qiskit-metal 直接求解的电磁参数对比**。
5. **源码口径**:这是个 fork(`dyk07/qiskit-metal`)。**pip 包很旧**(conda-forge 0.5.1);
   qiskit-metal 正改名 **Quantum-metal**;**GitHub 上游 = 最新且权威**;本地 Windows fork
   次新且**有自己的废弃改动**(不可当权威)。
6. **至少 2 qubit**(确认要求 ≥2 qubit)。
7. **指定例子 + 拉源码**:用 `tutorials/1 Overview/1.3 Build a 4-qubit chip.ipynb`;
   **先在 WSL clone 最新源码**。
8. **环境**:WSL 有 conda `metal-env`;**直接用 metal-env** 跑 qiskit-metal 参考解。
9. **(本次暂停指令)**:先创建本 spec 到 `.claude/` 记录原始需求与完整进度,然后停下。

---

## 口径与约束

- **Active 路径**:手写 `meta.yaml` + 手写 `.geo` → `geo_build` → gmsh → (GDS) + (Palace 静电)。
- **Legacy(不推进)**:全 YAML 写法;emit-geo。
- **环境**:conda `metal-env`(qiskit_metal **0.5.1** conda-forge 二进制,含 `TransmonPocket` +
  `renderer_elmer` + `renderer_gmsh`);quantum_dsl 用 `PYTHONPATH=src`。
- **Palace** 0.16 via spack(`$PALACE_BIN`)。**Elmer** = apt PPA `elmerfem-csc 9.0`
  (`/usr/bin/ElmerSolver`,`/usr/bin/ElmerGrid`,banner 报 v26.2);spack 源码编译失败(gfortran 15
  对 Elmer 9.0 老 Fortran 报硬错误,已弃用该路)。

---

## 锁定的实验设计

| | 我们的路径(被测) | qiskit-metal 参考 |
|---|---|---|
| 几何 | 手写 `.geo` + `meta.yaml` | `TransmonPocket`(1.3 的 Q1 参数) |
| 网格 | gmsh(我们的 adapter) | gmsh(QGmshRenderer) |
| 求解 | **Palace** Electrostatic | **Elmer** StatElecSolver(P1) |
| 产物 | N×N Maxwell 电容矩阵 | (N+1)×(N+1) 含 ground 行 |

- **复现对象**:教程 **1.3 Build a 4-qubit chip** 的**单个 `TransmonPocket`(Q1)cell**。
  - 整片是 4×`TransmonPocket`(菱形)+ 4 条 6mm 蜿蜒 `RouteMeander`,5.95×2.65mm。
  - **方法论(对齐官方 4.19/4.05)**:蜿蜒线是读出/耦合谐振器,**不**进电容矩阵;**电容矩阵是
    每个 qubit pocket 局部解**(4 个 CPW pin 开路)。多 qubit 耦合在 **LOM 组合层**出现。
  - **≥2 qubit 的落实**:在 **LOM 组合**层用多 cell 组合(4.05 那样)体现耦合多 qubit 系统。
- **单 cell 导体 = 6 信号 + 地**:`pad_top`、`pad_bot`、`conn_a/b/c/d`(各 = connector_pad + wire),
  ground 是参考(不计端口)→ **6×6** Maxwell 矩阵。

### 单 cell 精确几何(µm,局部居中,取自 qiskit-metal 实渲染)
```
pad_top  x[-225,225] y[ 15,105]  450×90      conn_a pad x[100,225]  y[120,150] 125×30
pad_bot  x[-225,225] y[-105,-15] 450×90      conn_b pad x[-225,-100]y[120,150] 125×30
pocket   x[-325,325] y[-325,325] 650×650     conn_c pad x[25,225]   y[-150,-120]200×30
ground   x[-625,625] y[-525,525] 1250×1050   conn_d pad x[-225,-100]y[-170,-120]125×50
JJ (0,-15)-(0,15) 20µm 宽;  引线 25µm 线/49µm gap, 由 pad 伸到 |x|=425 开路端
layer 1 = pec 2µm @z0; layer 3 = silicon -750µm; eps_r=11.45(已确认与 Elmer 一致)
airbox: top 890 / bottom 1650 / side_buffer(待与 Elmer vacuum box 对齐, 现 200)
```
引线原始是 3 段折线(含斜段),我们用轴对齐近似(保线宽/gap/长度)。

---

## 完整进度(截至暂停)

### ✅ 已完成
- **clone 最新源码**:`/home/administrator/qiskit-metal`(`dyk07/qiskit-metal` main,HEAD `5eb380fd`,
  blobless)。
- **表征 1.3 整片** + **挖出单 cell 精确几何**(脚本 `dump_spec.py` / `render_cell.py`)。
- **确认物理对齐**:Elmer `elmer_configs.py` silicon `Relative Permittivity = 11.45`,与我们 meta 一致;
  MultiPlanar 层栈 = layer1 pec 2µm / layer3 silicon -750µm,与我们一致。
- **Elmer 参考解(含引线,min5/max50)**:`build/qm4q_elmer_ref/elmer_cap_matrix.txt`,7×7。
  关键值(fF):pad_top 109.8,pad_bot 114.6,conn a/b/c/d 63.3/63.5/74.9/67.3,
  pad_top–pad_bot −36.0,conn_a–pad_top −16.5,conn_c–pad_bot −23.6。
- **✅ 参考侧 notebook(可重跑,已固化)**:`examples/qiskit_metal_ref/qm4q_transmon_cell_ref.ipynb`
  (kernel=**metal-env**)。拼 1.3 几何(`TransmonPocket` 4-pad)+ 4.19 Elmer 流程,`nbconvert --execute`
  重跑出 7×7,与上面参考逐位吻合(diag 63.4/63.3/75.0/67.3/109.9/114.8/300,差异 <0.2 fF)。
  - **关键环境坑(已实证)**:参考侧**必须用 `metal-env`(gmsh 4.11.1)**。`qmetal-src`(gmsh 4.15.2,
    上游 `pyproject` 钉 `gmsh>=4.15.0,<5`)的 OCC `fragment` 退化 → dielectric/ground 体被合并吞掉
    (物理组 13→7)→ Elmer 出病态矩阵(负自电容、ground NaN)。同一份官方 4.19 脚本:4.11.1 出正定、
    4.15.2 出坏,已对跑验证。官方 ipynb 不带保存输出。见 memory `quantum-dsl-elmer-ref-env`。
  - **副产物(诊断用,可清)**:`build/qm4q_419_orig`(qmetal-src 坏)、`build/qm4q_419_metalenv`
    (metal-env 好)、`build/qm4q_cell_me`、`build/qm4q_elmer_ref_nb`(notebook 输出)。
- **我们 v1(无引线,粗网格 min8/max100,order1)**:`build/qm4q_v1/`,Palace ~10s 出 **6×6** 矩阵。
  关键值(fF):pad_top 169.0,pad_bot 158.2,conn a/b/c/d 47.9/42.8/51.3/43.3,
  pad_top–pad_bot −60.6,conn_a–pad_top −32.6,conn_c–pad_bot −30.1。
- **v1 vs Elmer 初步对比**:差异大但方向可解释 ——(1) v1 无引线 → connector 自电容偏低;
  (2) v1 网格极粗(仅 9326 未知数)+ order1 → FEM 系统性高估电容。**非 setup bug,是收敛/几何差异**。

### ⚠️ 进行中 / 当前阻塞点(恢复时从这里继续)
- **v2(含引线)的 `.geo` 仍处于"坏"中间态**:文件
  `examples/dsl/geo/qm4q_transmon_cell.geo` 当前是 BooleanUnion 版,**有 tag 撞号**
  (`conn_a` 与 `pad_bot` 共享 surface tag 5)→ 管线 extrude 失败。
- **根因(已查清)**:gmsh `.geo` 在 OpenCASCADE 下 `news` + Boolean 的 tag 管理不可靠 ——
  `news` 会返回已存在的 tag;OCC Boolean 会重编号先前面;留重叠独立面会触发共面合并。
- **✅ 已验证的修复方案(实验 `_exp_d.geo` 通过,但尚未写回正式 .geo)**:
  > **给所有金属面用显式唯一 surface tag(如 1001+,绕开 `news`);ground 用宏先建好(经 `sret`
  > 捕获),金属在 ground 之后用显式 tag 创建;pad+引线用同一 Physical 名标成双面(无需 Boolean)。**
  实验结果:`pad_top=1001 pad_bot=1002 jj=1003 conn_a={1004,1005} ground={1}`,无撞号、无 BAD。

### ⏳ 待办(恢复顺序)
1. **把上面的显式-tag 方案写回** `examples/dsl/geo/qm4q_transmon_cell.geo`,dry-run 验证成网。
2. **v2 收敛网格跑 Palace**:网格对齐 Elmer(min5/max50);Elmer 是 P1,故我们用 **order 1**
   做公平对比(或注明 order 差异)。注意:之前 min4/max50+order2 在小 pocket 上要 8min+(过细),
   要么 order1、要么适度网格。
3. **v2 vs Elmer 逐元素对比**:对齐端口命名(我们 `Q1_conn_a_sfs…` ↔ Elmer `Q1_a_connector_pad…`),
   算相对误差;预期收敛后显著靠拢(v1 的高估应消失)。
4. **LOM 组合**:把两边电容矩阵各喂进 qiskit-metal LOM 2.0(`CompositeSystem/Cell/Subsystem`,见
   4.19/4.05),出 qubit 频率/非谐性/g/χ 对比。我们管线也有 `solve_circuit_model`
   (`chip.results.yaml` 已含 circuit model),可一并对照。
5. **落实 ≥2 qubit**:多 cell(≥2)LOM 组合出耦合多 qubit 系统参数。
6. **收尾**:验证文件移入 `examples/`(已在那);更新 `.claude/status.md` + `plan.md` + 写 session log;
   报告(`docs/report/`)。
7. **可选边界对齐**:我们 airbox `side_buffer` 现 200µm,qiskit-metal vacuum box 侧向≈ground 边界
   (+~1µm);如对比显示边界驱动的偏差,再调。

---

## 文件 / 路径清单

**我们的 DSL(deliverable)**
- `examples/dsl/geo/qm4q_transmon_cell.meta.yaml` — Layer-1 物理元数据(层栈/airbox/mesh/gds/solver)。
- `examples/dsl/geo/qm4q_transmon_cell.geo` — 单 cell 几何 **(当前坏态,待应用显式-tag 修复)**。
- `examples/dsl/geo/qlib.geo` — 复用的宏库(PAD/CPW/JUNCTION/GROUND_POCKET/GROUND_CUTOUT/COUPLER)。

**结果**
- `build/qm4q_v1/` — 我们 v1 Palace(无引线/粗网格)输出 + `chip.results.yaml`(6×6 + circuit model)。
- `build/qm4q_elmer_ref/elmer_cap_matrix.txt` — Elmer 参考 7×7 矩阵。

**临时脚本(scratchpad)**
- `build_4q.py`(整片表征)、`render_cell.py`(单 cell 渲染+物理组 dump)、`dump_spec.py`(精确几何 spec)、
  `elmer_ref.py`(Elmer 参考解)。scratchpad =
  `/tmp/claude-1000/-home-administrator-quantum-dsl/<session>/scratchpad/`。

**外部源码**
- `/home/administrator/qiskit-metal` — clone 的 dyk07/main(权威最新)。
- `/mnt/d/Workspace/vsCOde/circuit/qiskit/qiskit-metal`(+ `…-worktrees/dyk07-main`)— Windows 本地 fork
  (次新+废弃改动,仅参考)。4-qubit 教程:`tutorials/1 Overview/1.3 Build a 4-qubit chip.ipynb`;
  Elmer 教程:`tutorials/4 Analysis/B…/4.19 Analyze a transmon using ElmerFEM.ipynb`;
  2-transmon LOM:`tutorials/4 Analysis/A…/4.05 New LOM and Two Coupled Transmon Example.ipynb`。

**命令**
```bash
# 跑我们的管线(metal-env):
source ~/miniconda3/etc/profile.d/conda.sh; conda activate metal-env
cd /home/administrator/quantum_dsl; export PYTHONPATH=src
python -m quantum_dsl.dsl.geo_build examples/dsl/geo/qm4q_transmon_cell.meta.yaml \
    --out-dir build/qm4q_v2 --run-palace [--dry-run]
# Elmer 参考(脚本在 scratchpad):python <scratchpad>/elmer_ref.py
```
