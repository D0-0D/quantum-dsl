# v4 物理管线避坑清单(V4-2 / V4-3 / V4-6 实现者必读)

来源: 原仓 `D0-0D/quantum-dsl` issues #1–#28 全量调研 + 旧仓 session 取证
(2607280204 / 2607290110 / 2607290329 / 2606280304)+ **本机实证**(2026-08-24,
gmsh 4.15.2 + Palace 0.16, qdsl313)。原始调研报告见 session log 索引;
本文是给实现 agent 的行动版。

## 0. 本机已实证的事实(直接照抄, 不用再猜)

最小 void-carve 原型(约 250 行, `.claude/proto/two_pads_pipeline.py`)本机实跑:

| 变体 | 做法 | C 对 N7 golden 最大相对误差 |
|---|---|---|
| A(v3 复刻) | merge .geo → occ.dilate µm→m → SI 网格, Palace `L0=1.0` | **0.038%**(PASS, 容差 2%) |
| B(v4 候选, **推荐**) | 模型全程 µm, **不 dilate**, Palace `L0=1e-6` | **0.072%**(PASS) |
| A + mesh 20/2 | 网格加密(33k→244k 节点), order 2 | −0.7%~−1.18%(PASS)|
| A + order 1 | 同网格降阶 | +4.2%/+7.3%(**FAIL**)|

收敛读数: golden(order 2 + 40/4)本身未完全收敛, 真值在其下方 ≈1% ——
2% 容差有余量但不奢侈, 实现必须忠实复刻 order 2 + mesh 40/4;
**order 2 是硬承重件**(order 1 直接出 2% 容差 3 倍开外)。

配方(A/B 共用, 逐字生效): 金属面 extrude +2 µm → 从真空盒 `occ.cut` 挖空
(Approach A)→ fragment(真空+衬底)→ combined boundary 按 bbox 归位腔壁 →
Terminal=各导体腔壁组, Ground=外边界组; 衬底盒 z∈[-100,0] ε=11.45, 真空盒
z∈[-120,+120], 横向 bbox±80(+1 µm tol); 尺寸场 Distance/Threshold 4→40 µm
over 10→130 µm, Sigmoid=1, `MeshSizeExtendFromBoundary/FromPoints/FromCurvature=0`;
msh2.2, `ScalingFactor=1.0`; Solver: order 2, BoomerAMG+CG, Tol 1e-8。
⚠ **金属厚度 2 µm 是 golden 的一部分**(v3 layer_stack 默认), v4 meta 词汇里
没有这个键 → 实现里固定 2 µm。

Palace 调用: `PALACE_BIN` + `HWLOC_COMPONENTS=-gl`(缺了后者 MPI_Init 永久挂死,
hwloc gl 插件 TCP 探 X display), cwd=config 所在目录, `Model.Mesh` 用相对名。

V4-3 数学链条(全部对契约 golden 逐位复算通过):

- `E_C = e²/2 · [C⁻¹]_ii`, `C_Σ = 1/[C⁻¹]_ii`(**不是** Maxwell 对角);
  `E_J = (ħ/2e)²/L_J`; `f01 = (√(8·E_C·E_J) − E_C)/h`; `α = −E_C`。
- 耦合: `β = |C⁻¹_ij|/√(C⁻¹_ii·C⁻¹_jj)`, `g = ½·β·√(f01_i·f01_j)`
  (复算 375.0105675 MHz, 对 golden <1e-10; 契约钉的是 v3 口径——用修正后 f01,
  不是裸等离子频率, 别"顺手改进")。
- SQUID: `E_J(Φ) = (E_J1+E_J2)·hypot(cos(πφ), d·sin(πφ))`, `d=(E_J1−E_J2)/(E_J1+E_J2)`
  ——无奇点形式, 教科书 tan 写法在 φ=0.5 产 nan(N8 有测试)。
- 常数用 SI-2019 精确值: e=1.602176634e-19, h=6.62607015e-34。

## 1. 必守规则(按 v4 里程碑分组)

### V4-2(mesh / palace_config)

1. **金属底面与衬底顶面精确共面(z=0)**。任何 ε 真空缝是标定旋钮不是物理:
   1 µm 缝压低 C_AA 29% / 耦合 40%(耦合远比自电容敏感); 且 ε 非单调
   (ε=0.5 µm 产损坏拓扑, 0.001–0.1 µm 才单调)。two_pads 无 ground, 不触发此坑。
2. **不 dilate**(若变体 B 实证通过): dilate 是 `BRepBuilderAPI_GTransform`
   全量 shape-heal, 对多数几何是纯损伤; v3 的 `FRAGMENT_SCALE_LADDER=(1.0,1e2)`
   只在 boolean **抛异常**时升档。µm 模型 + `L0=1e-6` 从根上绕开。
3. **fragment 后必须断言拓扑不变量**(违者 raise, 不 warn): 每 dielectric 层
   恰 1 体; 无负 mass 实体(dim 2/3); Σ体积 ≤ 模型 bbox 体积×1.001。
   实测过的静默损坏: 衬底复制成 2 体、负面积 face、整张 z=0 界面被误标 ground
   → Palace 无报错出错解。qdsl313 的 gmsh **4.15.2 正是实证过 OCC fragment
   退化的版本**(4.11.1 好 / 4.15.2 在 qiskit-metal 路径上坏)——两_pads 上
   v4 路径已实证无恙, 但断言是暴露它的唯一手段。
4. **面归位禁止只用质心-in-bbox**: 必须加"face 自身 bbox 被认领方 bbox 包住"
   +(带 ground 时)腔壁总面积 ≤ bbox 表面积×2 校验。chip-wide ground 的 bbox
   会吞掉质心 (0,0,0) 的整张衬底界面。
5. **尺寸场覆盖电容缝两侧全部导体面**, 含 carve 出的无 3D 体腔壁面(v3 漏过
   ground_faces → 2 µm 竖边三共线点 → 零面积三角形 → "overlapping facets",
   一切 carved-ground 设计网格必炸)。
6. **每条 3D 网格出口都过空网格守卫**(gmsh 对共面 PLC 失败**不抛异常**,
   静默返回空网格); Delaunay 划不动共面界面时回退 HXT(Algorithm3D=10),
   但 HXT 不能当全局默认(部分几何反而炸)。空网格 raise 是 N5 契约。
7. Terminal 分类按 role/名字**精确匹配**, 禁前缀匹配(v3 按 `gnd_`/`vacuum`
   前缀排除, 用户组件撞前缀即被静默丢出 C 矩阵)。
8. 场输出(Paraview/GridFunction/Save)默认**关**——电容工作流只要
   `terminal-C.csv`, 场输出在大网格上是最慢最占盘的一段。

### V4-3(纯数学内核)

9. C 矩阵求逆前 `(C+Cᵀ)/2` 对称化; 近奇异守卫用尺度相对判据
   (`|pivot| ≤ 1e-12·‖C‖`), 不是绝对 1e-300; 一切输入(CSV、L_J/E_J)拒
   NaN/Inf——`not (isfinite(v) and v > 0)`, 因为 `1e400` 溢出成 inf 能绕过 `<=0`。
10. **多岛/浮动导体是 v3 最大的一类物理错**(v4 契约 N8 只有单岛+junctions
    dict, 但 islands 是列表——留了口子): 双岛差分 transmon 当单岛算 C_Σ 错
    1.70× 且全绿。正解 = 结支路坐标 `C'=BᵀC_S·B`, **求完整 C' 的逆再取 θθ 块**
    (只删 σ 行列有非对称反例)。实现 N8 时若只支持单岛, 对 len(islands)>1
    必须 raise 而非静默取第一个。
11. 未被 junction/subsystem 引用的 Terminal 会被**静默接地**——v3 实测把跨块
    中介 g 从 25.14 MHz 删成 0。N9 的 `assemble` keep 拼错名 raise 是同一坑的
    契约化; solve_circuit_model 侧对"有标签但没人认领"的行为要么 Schur 消掉
    要么 raise, 不能默认接地不吭声。
12. 纯代数 golden 锚点(零 FEM): qiskit-metal LOM 2.0 双 transmon parity
    (v3 Schur C_k 偏差 7.7e-16, E_C <0.1%)——搬运 assemble/约化时用它自检,
    spec 在旧仓 `.claude/lom-parity-spec.md`。

### V4-6(live 验证)

13. **单网格数字自带 6–21% 不确定度**(order 1→2 移动 C_Σ −21%; Elmer 网格
    加密 −6%)。two_pads 上本机实测: 网格加密一档移动 −1.2%, order 1 偏
    +7.3%(见 §0 表)。报告 C 值时至少给两档网格的相对变化。
14. order 2 多 rank 在大网格(>1M tets)上会静默掉 rank(疑似 ZZ 误差估计器
    的 RT 空间, H1 的 6×)——two_pads 规模无此问题, 但 N7 实现用 `-np 1` 即可,
    别为小网格开多 rank。
15. live 测试断言 golden **数值**(N7 已经是), 别只断结构/符号; Palace 还免费
    写 `terminal-Cinv.csv`, 解析它对照自家 `inv(C)` 是零成本交叉校验。

## 2. 对照案例锚点(将来扩展验证用, 均在旧仓)

- **two_pads**(N7 golden 本体): 唯一整片实解 golden, 无 ground → 从不触发
  ε-nudge。golden 自身网格扰动 spread 0.202%。
- **qm4q_transmon_cell**(qiskit-metal 同几何 Elmer 对照):
  `~/quantum_dsl/examples/dsl/geo/qm4q_transmon_cell.*` + Elmer 参考
  notebook(`examples/qiskit_metal_ref/`, kernel=metal-env)。误差演化:
  1 µm 缝+接地边界 −30% → 共面+接地 +41% → 共面+开放 o1 +44%(欠收敛)→
  共面+开放+**o2 −5.5%**。三杠杆(去缝/开放边界/order 2)缺一不可。
  开放边界 = 不给 vacuum_outer 上 Ground(自然 Neumann), 仅在有金属 ground
  提供 V=0 参考时合法, 否则问题奇异。
- **sung_2021_device**(论文对照, PRX 11 021058): 3 浮动双岛 transmon;
  论文 C_Σ 99.3/227.9/101.9 fF。Elmer 权威档 102.1/232.8/102.1(+1~3%);
  直接 q-q 互容 C_12 **未复现**(0.003 vs 0.125 fF——差分远场相消, 几何
  路径本身缺失); g 偏高 1.4–1.5×主因未建磁通工作点。引用它前先读
  2607280204——"分块 o2 对 Elmer −3%"是 +12~15% 与 −21% 两个反向误差抵消。
- **Elmer 侧口径**: Elmer 输出 SPICE 互容矩阵(对角=对地), sif
  `Permittivity of Vacuum=1` → 原始值×ε0; qiskit-metal 的 pandas 后处理在
  pandas≥2 下静默错, 必须从原始 `cap_matrix.txt` 自建 Maxwell。

## 3. v4 契约外、但迟早要还的债(不在本轮做)

- `conductor_mode: volume`(金属 as-volume / fragment-into-interface, Palace
  官方 CPW 例的做法)——根治共面布尔, 且与 void 路线互为对照。原仓 #24。
- `--converge` 多档网格自动收敛报告(#26); sidecar `targets:` 声明期望值 +
  输出 `validation:` 段(#23)。
- 带 ground 的 live fixture(现契约 N7 只有 two_pads, 覆盖不到规则 1/4/5 的
  触发路径)。
