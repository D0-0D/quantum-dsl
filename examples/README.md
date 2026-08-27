# examples/ — 可运行的例子

每个例子 = 一份 `.geo`(几何, **µm**, OpenCASCADE)+ 一份 `*.meta.yaml`(材料 / 计算域 /
网格 / 求解器 / 结参数)。它们同时是测试套件(`tests/`)的输入,所以永远与代码同步、
拿来就能跑。语法参考见 [`../docs/grammar.md`](../docs/grammar.md)。

| 例子 | 是什么 | 用来看什么 | Palace 规模 |
|---|---|---|---|
| `two_pads.{geo,meta.yaml}` | 两块分离的 80×80 µm 焊盘,各挂 10 nH 结 | 整条管线的最小闭环;**回归锚**(C 矩阵实测 golden 写在头注) | 单核 ~4 min,内存 <2 G |
| `two_pads_blocks.meta.yaml` | 同一几何切成 A / B 两块 | 分块提取 `extract.blocks`,以及「跨块直接互容 = 结构性零」告警 | 不需要求解 |
| `sung_2021_device.{geo,meta.yaml}` | Sung et al., PRX 11, 021058 三体 tunable-coupler 的简化重现 | **外部物理锚**:三个浮动(差分)transmon 的 C_Σ、β 对论文;`ground::` 角色 + 开放边界 + `Include` 宏库 | 18.5M 未知量,**峰值内存 ~154 G**,96 核 ~20 min |
| `sung_2021_xmon.{geo,meta.yaml}` | 同一论文器件的**真拓扑**(接地 Xmon ×2 + 梳齿 coupler),用 ~20 个从 Fig. 1(c) 照片量出的参数写成,无调参 | 对论文的**无调参预测**(分清「标定命中」与「预测精度」,见 `docs/report/04` §8);`XMON` 宏;接地单岛写法 `island:` | 80/2 order-2 ~13M tets,需 384 G 远端机 |
| `sung_2021_xmon_traced.{geo,meta.yaml}` | 同一照片的逐点描摹(`tools/micrograph_to_geo.py` 生成,426 顶点,含视场内走线 / 读出槽 / SQUID 框) | 参数化版的保真参照(同粗网格差 C_Σ 1–4%、β_qc 0.4%);测量审计图 `docs/report/img/` 的来源;`POLY` 宏 | 15.4M tets,峰值 168 G |
| `qlib.geo` | OCC 宏库:`PAD` / `POLY` / `XMON` / `CPW` / `JUNCTION` / `GROUND_CUTOUT` | 被 sung 例子 `Include`;写自己的版图时可复用(纯几何宏,Physical 名由调用点打;⚠ `Call X;` 独占一行) | — |

## 跑起来

v4 只有 Python API(没有 CLI),入口是 `quantum_dsl.build`:

```bash
# conda env qdsl313 (Python 3.13 + gmsh + gdstk + shapely); 仓库根目录执行
P=~/miniconda3/envs/qdsl313/bin/python
export PYTHONPATH=src

# 1) 不求解: GDS + 3D 网格 + Palace config + manifest (几秒)
$P -c "from quantum_dsl import build; print(build('examples/two_pads.meta.yaml', 'build/two_pads'))"

# 2) 分块提取: 派生 block_A.geo / block_B.geo 各自网格与 config, 并对 A↔B 告警
$P -W always -c "from quantum_dsl import build; build('examples/two_pads_blocks.meta.yaml', 'build/blocks')"

# 3) 真实求解 → 电容矩阵 → 哈密顿量 (需要 Palace; WSL 上 build() 自动注入 HWLOC_COMPONENTS=-gl)
PALACE_BIN=/path/to/palace $P -c "from quantum_dsl import build; \
  r = build('examples/two_pads.meta.yaml', 'build/two_pads', solve=True); \
  print(r['capacitance'].maxwell_fF); print(open(r['results']).read())"
```

预期(3):`maxwell_fF ≈ [[24.53, -1.95], [-1.95, 24.54]]`(对头注 golden <2%),
`results.yaml` 里 `f01_GHz ≈ 9.40 / 9.40`、`g_MHz ≈ 376`。

sung 例子的跑法(远端大内存机)见 [`../docs/report/03-复现与演示.md`](../docs/report/03-复现与演示.md)
Demo F;`tools/palace_remote.sh` 是把 Palace 调用透明转到远端的 `PALACE_BIN` 垫片。

## 写自己的例子

1. 画 `.geo`:每个语义面挂 `Physical Surface("role::layer::component::primitive")`,
   role ∈ {metal, ground, jj};**component 段 = 电学岛(net)**,浮动 transmon 的两块 pad
   必须是不同 component(如 `QB1_t` / `QB1_b`),器件归组写在 meta 的 `circuit_model.islands`。
2. 写 `*.meta.yaml`:照 `two_pads.meta.yaml` 抄骨架;有片上 ground 时可用
   `solver: {outer_boundary: open}`(见 sung)。
3. `build(meta, out, solve=False)` 先看 GDS 与网格对不对,再 `solve=True`。
4. 报数前做两档网格(如 40/4 与 20/2)——单网格数字在复杂几何上有百分位级不确定度。
