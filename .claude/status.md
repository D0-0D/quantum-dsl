# Quantum-DSL — Current Status

**在做的项目, 不是完成品。** 每个 session 开工前读这份 + [`plan.md`](plan.md)。
本文件只放「现在在哪」的快照 —— 详细里程碑清单在 `plan.md`, 过程记录在 `session/*.md`,
未决问题在 **GitHub issue**（本文件只留一行指针, 不复制内容）。
_headline 变了（里程碑翻页 / 分支合并 / 测试数变 / 结论被推翻）就更新这里。_

---

## At a glance

| | |
|---|---|
| 分支 | `main`（native Gmsh `.geo` pivot 经 PR #14 / `931b8ec` 合入）。**⚠ v4 greenfield 重写已立项**: orphan 分支 `v4`（worktree `~/quantum_dsl-v4`, Python 3.13, 无 qiskit_metal）, 契约 = 那边的 `SPEC.md` + `tests/test_spec.py`（38 红 = 需求清单）;本仓转为参考实现（算法审后搬运, 坑清单见下「已了结, 别重新踩」） |
| 本阶段范围 | 圆角多边形 cell + **静电电容矩阵**。eigenmode/driven、lumped port、损耗 **不在本阶段**（deferred, 非否决） |
| 已完成 | **M1 · M3 · M5a · M6 · M7**（本阶段目标全部达成）+ **M8 P0**（`lom-parity-spec.md` 的 P0-A…F = M8a–M8d） |
| 测试 | **619 passed, 3 skipped — 0 failed / 0 errors / 0 deselected**（conda `metal-env`, 2 分 37 秒） |
| 跑法 | `PYTHONPATH=src python -m pytest tests/ -q` —— **不要** export `QDSL_MESH_ALGO3D`；Palace 必须 `HWLOC_COMPONENTS=-gl`（两条 ⚠ 见 `CLAUDE.md`） |
| 3 个 skip | 2 × viz（`gdsfactory` 缺）+ 1 × gated live Palace。**不再需要手工 `--deselect`** |

**三条端到端路径都活着**：

- **整片**：`build_geo(two_pads.meta.yaml --run-palace)` → 实解 C `[[24.7288,-1.976],[-1.976,24.7293]]` fF
  → tier-2 `hamiltonian`（C_Σ 24.571 fF, E_C 0.7883 GHz, f01 9.365 GHz, g 374.2 MHz）。
- **分块（M8 P0）**：sidecar 带 `extract:` / `assemble:` / `subsystems:` → 每块派生并**落盘**
  `block_<name>.geo` → 各自 mesh + Palace → 电容图按共享节点名累加 + **Schur 消元** →
  系统级 `chip.results.yaml`（含 `TL_RESONATOR` / χ / `C_j`；`--no-solve` 可零 FEM 成本走全链）。
- **cell 库**：`cells:` sidecar → `<stem>.elaborated.geo` → GDS + mesh + carved-ground Palace config（M5a）。

## 读数前必看 —— 现役数值的可信边界

| 量 | 现状 |
|---|---|
| 分块引入的误差 | 可信值只有 `two_pads` 的 **+1.03%**（同 order / 同网格的受控对照）。`sung` 那组（对 Elmer −3%）是**两个大误差反向抵消**：同 order 下分块本身 +12~15%，order 1→2 又 −21% —— 卡在 #22 + #26，在 sung 上无法干净分离 |
| 分块的算力收益 | **总墙钟没降**（3 块合计 2.19 M 未知量 ≈ 整片 2.24 M；每块要重划自己的衬底+airbox）。真收益是**单次求解规模降一个量级 → order 2 才跑得起**、峰值内存降 |
| 网格收敛 | **从来没测过离收敛多远**。sung order 1→2 差 21%；Elmer 自己 5/50→2/30 就降 6%。`tier` 只描述完整度、不描述精度 → **#26** |
| Palace vs Elmer | 整片 order 1 对 Elmer **+8.4~8.7%**，三个 qubit 高度一致 → 系统性偏移而非噪声（最可能是网格收敛，次因外边界不等价）。表述：**两个独立求解器在较粗一方的收敛不确定度之内互相印证** |
| χ（色散位移） | Koch 2007 eq.(3.10) 二阶微扰，结果标 `chi_method: perturbative`。对老 LOM **−16.1%**，已分解成 g 定义（−8.5%）+ 数值 CPB 谱（−8.3%），**公式本身对参考实现逐位一致**。近共振 / 强耦合别用 |
| 跨块耦合 | 切割面只能落在 component 边界 ⇒ 跨块**互电容必然为 0**，只能靠共享节点名表达。**想保哪两个导体的耦合, 就把它们放进同一个块** |
| 硬接地 vs Schur | Schur 只在 **`extract:` 分块路径**生效。不带 `extract:` 的整片路径仍把未被引用的 Terminal 当接地电极 → 会把跨 cell 的 `g` 整条删掉（实测 25.14 MHz → 0.00）= **#20 的剩余一半** |

## Open —— 都在 GitHub issue 里

| # | 一句话 | 备注 |
|---|---|---|
| **#26** | 网格收敛扫描 `--converge` | **当前性价比最高** —— 它决定分块误差到底能不能测 |
| **#23** | `targets:` 验收块（声明期望的 C / E_C / g，管线报偏差） | 2607280204 那次事故的根因级预防 |
| #22 | Palace order 2 多 rank 解不出来（第 2 个 terminal 静默掉 rank；order 1 / 8 rank 干净） | 后果：sung 无法在本机跑出它 sidecar 自己声明的精度 |
| #18 | carved ground 面被排除在网格细化外 → C 有偏 | 量化影响仍欠。与 ε-nudge 是**两个**旋钮，别混 |
| #20 | 整片路径的浮动 bus 仍被硬接地 | 分块路径已由 Schur 解掉；`chip_layout` 要享受它得改写成 `extract.blocks` + `nodes_force_keep` |
| #24 | `mesh.conductor_mode: void\|volume` | 第二条网格路线，绕开脆弱的共面 OCC 布尔；也是第一次能让两条路的 C 互相对照 |
| #25 | Elmer 第二求解器后端 | 脚本仍在 scratchpad（含 ElmerFEM 9.0 构建坑 + qiskit-metal 两个上游 bug） |
| #27 | `run_palace` / Palace config 三处粗糙（`dry_run` 吞掉 `num_procs`、`-np` 两分支不一致、场输出硬编码） | |
| #28 | live `two_pads` 回归只断言结构/符号，不断言数值（含未被利用的 `terminal-Cinv.csv` 交叉校验） | |
| #15 · #19 | PR #14 review 的剩余 follow-up | 那 3 个 critical fix **已在 `main`** |

**还没有 issue 的欠账**：

- 🔴 `lom-parity-spec.md` §7 的 **S2 live Palace 护栏没跑** —— 需要一个 pocket **互不相连**的小设计
  （`chip_layout` 的 6 个 pocket 被 OCC 合成了 1 个连通孔，`keep_all_subtractive=False` 在它上面是 no-op）。
  目前 S2 由几何层的点覆盖 + 面积/孔数断言守着，**没有**「两解对地电容比值」这条实解证据。
- P1-G / P1-H / P2-I / P2-J / P2-K 未做（本次范围是 P0，见 `lom-parity-spec.md` §5）。
  **P1-H**（电荷基精确 CPB 对角化）是关掉 χ 偏差里「谱」那一半的唯一途径。
- M5a 尾巴：emit_geo ground 设计的整片 live Palace 解（gated）；connection-pad transmon 可能与 ground 重叠
  （clean-disjoint cell 才是被测过的路）。

## 已了结, 别重新踩

| 坑 | 结论 | 取证 |
|---|---|---|
| **任何** MPI 程序零输出挂死 | hwloc 的 `gl` 插件**通过 TCP** 探测 X display `:0…:N`；本机 127.0.0.1:6001 黑洞掉 SYN（WSL2 localhost 转发，无 listener 也无 RST）→ `connect()` 永久阻塞，`MPI_Init` 返回前就死。修法 `HWLOC_COMPONENTS=-gl`，已持久化进 `metal-env` 与 `quantum-metal`（新建 env 必须照做）。⚠ 早先「`DISPLAY` 为空所以不是 X11」的判断是错的 | `session/2607280204.md` |
| 「挖空 ground 有 ~30% 内在误差」 | **错**。那是默认 ε-nudge 比需要的大三个数量级：1 µm → **0.01 µm** 后只差 0.03%。ε=0 不是万能解（该几何在任何 scale 下都 fragment 失败），OCC 共面布尔的抽风是**非单调**的 | `_gmsh_geo_source.CARVED_GROUND_SUBSTRATE_GAP_SI` 的 ε 阶梯表 |
| fragment 的 dilate 往返 | 不是单位换算，是**意外 shape-heal**（`occ.dilate` 重建每条曲线/曲面并放大容差）→ 改成 `FRAGMENT_SCALE_LADDER = (1.0, 1e2)`，1.0 档完全不 dilate | `session/2607280204.md` |
| `occ.fragment` 对近邻但不重叠的 pocket carve | 重叠 30/40 µm 干净；重叠 10 µm 与**完全不重叠**都抛 `Boolean fragments failed`，scale 1/1e2/1e3 皆然 → 是 boolean 本身。重画几何时留意 | `sung_2021_device.geo` header |
| legacy YAML→gmsh 路径静默写空网格 | 空网格守卫把它**暴露**出来（不是造成）并修好；新 gmsh 对共面 PLC 失败不抛异常是根因 | `session/2607021950.md` |
| 参考侧交叉验算怎么跑 | ElmerFEM 9.0 在 `~/opt/elmer`（`export PATH=$HOME/opt/elmer/bin:$PATH`）+ conda `quantum-metal` = quantum-metal 0.7.6。两个上游坑要绕：`ElmerRunner` 假定相对路径布局；`_get_capacitance_matrix` 用 pandas 链式赋值设 Maxwell 对角，pandas ≥2 下**静默失效** | `session/2607280204.md` |
| 缺口 ⑤ SQUID 磁通可调 · ⑦ `geo_build --np N` · ⑥ 浮动 bus 的 Schur 消元 | 都已落地（⑤⑦ 在 2607290110，⑥ 在 M8 P0；Schur 对 4.05 golden 的 `C_k` 偏差 **7.7e-16**） | `session/2607290110.md` · `session/2607290329.md` |
| #20 的三条里两条 | ✅ 多岛浮动/差分 transmon 已实现（与 LOM 2.0 吻合 <0.1%）；✅ 「meta→tier-2 wiring bug」核实**本就不存在**（已补测试钉住） | `session/2607280204.md` |

## 历史

每个 session 的完整记录 + 里程碑逐条状态见 [`plan.md`](plan.md)（底部 `## Session logs` 索引）。
最近三条：`session/2607290329.md`（M8 P0 全部落地）· `session/2607290110.md`（缺口 ⑤⑦）·
`session/2607280204.md`（Palace↔Elmer↔论文三方闭环 + 4-agent 修复）。
`CLAUDE.md` 不再钉死 "M1–M5" —— 里程碑按 phase 重新划定（见 `plan.md`）。
