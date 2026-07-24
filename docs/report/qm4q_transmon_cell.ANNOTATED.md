# qm4q_transmon_cell — `.geo` + `.meta.yaml` 逐行导读

> 面向想看懂 / 改写本例两个手写输入的人。配套文件:
> - `qm4q_transmon_cell.geo`(几何,Layer 2)
> - `qm4q_transmon_cell.meta.yaml`(物理元数据,Layer 1)
> - `qlib.geo`(被 `.geo` `Include` 的宏库)
>
> 复现对象:qiskit-metal 教程 *1.3 Build a 4-qubit chip* 里的单个 `TransmonPocket`(Q1)。
> 目标:用本仓库 geo→Gmsh→Palace 静电管线解出 6×6 Maxwell 电容矩阵,与 qiskit-metal+Elmer
> 的 7×7 逐位对标。结果与残差分析见 `docs/report/qm4q_transmon_walkthrough.md`。

---

## 0. 整体:这两个文件是什么、怎么协作

本仓库 **native-geo 路径**的输入永远是**一对手写文件**(active path):

| 文件 | 角色 | 内容 |
|---|---|---|
| `*.meta.yaml` | **Layer 1 物理元数据** | 层栈/材料 εr、airbox、网格尺寸、GDS 层映射、Palace solver。它是**入口**,用 `geo:` 指向几何。 |
| `*.geo` | **Layer 2 几何** | 纯 OpenCASCADE 几何(微米),显式写出每片金属/地/JJ 的多边形,并打 Physical 标签。 |

入口命令(meta.yaml 是参数):
```bash
conda activate metal-env && export PYTHONPATH=src
python -m quantum_dsl.dsl.geo_build examples/dsl/geo/qm4q_transmon_cell.meta.yaml \
    --out-dir build/qm4q --run-palace        # 加 --png 顺手出 chip.png
```

管线对同一几何分两支:
- **GDS 分支**(gdstk):µm 原样 → `chip.gds`(2D 掩模,绕过网格)。
- **网格分支**(Gmsh):µm→m,把金属从真空盒里 **carve(挖空)**成空腔 → `fragment` 缝合 →
  物理组 → 网格 → **Palace Electrostatic** → `chip.results.yaml`(电容矩阵)。

### 绑定契约(THE binding key)
几何与 GDS、Palace、Layer-1 元数据之间,**唯一的桥**是 `.geo` 里每个面的结构化 Physical 名:
```
"<role>::<layer>::<component>::<primitive>"
```
- `role` ∈ `metal` / `ground` / `jj` / `substrate`(面),`port` / `symmetry`(标记)。
- `layer` = 整数,**对应 meta.yaml 的 `layer_stack` key**(本例金属都在 layer 1)。
- `component` = 器件名(本例 `Q1`,GDS `by_name` 映射也用它)。
- `primitive` = 图元名(`pad_top` / `conn_a` …)。

加载器把这些名映射到内部 `PHYSICAL_GROUP_NAMING`,`fragment` 后 `assign_physical_groups` 再
逐个重注册,使输出名与 legacy 路径**逐字节一致**(Palace 不知道几何从哪来)。

---

## 1. `qm4q_transmon_cell.geo` 逐行导读

### 1.1 文件头 / kernel / 宏库

```gcode
SetFactory("OpenCASCADE");      // 用 OCC kernel(布尔运算、Rectangle 原语都靠它)
Include "qlib.geo";             // 引入宏库:GROUND_POCKET / GROUND_CUTOUT / PAD / CPW / JJ …
```
- **物理意义**:声明这是一张以微米为单位、用 OpenCASCADE 造型的 2D 版图。`qlib.geo` 有
  include-guard(`If(!Exists(_QLIB_INCLUDED))`),可被 GDS+mesh 两条分支安全重复 Include。

### 1.2 设计参数(行 30–37)

```gcode
pad_w   = 450;   pad_h = 90;   pad_gap = 30;       // 主焊盘 450×90,两焊盘间距 30
pad_cy  = (pad_h + pad_gap) / 2;   // = 60         // 焊盘中心 y = ±60
jj_w    = 20;                                       // JJ 宽 20
cpw_w   = 25;    cpw_gap = 12;   gap_w = cpw_w + 2*cpw_gap;  // 49  ← CPW 共面缺口总宽
open_gap = 15;                                      // 开路 pin 端的 ground 缺口余量
lead_tip = 425;  lead_y = 202.5;                    // 引线开路端坐标 (±425, ±202.5)
pkt_w   = 650;   pkt_h = 650;                        // pocket 650×650
g_x0 = -625; g_y0 = -525; g_w = 1250; g_h = 1050;   // ground sheet 1250×1050(器件盒+0.2mm/边)
```
- **物理意义**:这些就是 transmon 的全部几何尺寸,**1:1 取自 qiskit-metal 渲染值**。
  - `pad_w/pad_h/pad_gap` 决定两片岛(qubit 本体)的形状与间距 → 主电容。
  - `cpw_w/cpw_gap` 是共面波导(中心导体 25 + 两侧各 12 gap)→ 引线特征阻抗。
  - `gap_w = 49` 是 ground 上为引线让路的缺口总宽。
  - `lead_tip/lead_y` 是引线开路端(整片芯片里这端伸向读出/总线谐振器)。

### 1.3 ground + pocket + 4 条 CPW gap(行 40–46)—— 先建

```gcode
gs = news; Rectangle(gs) = { g_x0, g_y0, 0, g_w, g_h };       // 整块 ground sheet
sground = gs; pkt_cx = 0; pkt_cy = 0; Call GROUND_POCKET;     // 中央挖 650×650 pocket
sground = sret; gx1=225; gy1=lead_y; gx2=(lead_tip+open_gap); gy2=lead_y; gw=gap_w; Call GROUND_CUTOUT;   // conn_a 引线 slot
sground = sret; gx1=-225; ... Call GROUND_CUTOUT;            // conn_b
sground = sret; gx1=225; gy1=-lead_y; ... Call GROUND_CUTOUT; // conn_c
sground = sret; gx1=-225; gy1=-lead_y; ... Call GROUND_CUTOUT;// conn_d
Physical Surface("ground::1::chip::gnd") = { sret };          // 打 ground 标签
```
- **关键约定**:每个宏只造几何、把结果面 tag 写进全局 `sret`;**Physical 标签由作者在调用点打**。
  所以这里链式传 `sground = sret`:把上一步蚀刻结果继续喂给下一刀。
- **物理意义**:
  - `GROUND_POCKET`:在地平面正中挖一个矩形空腔,把两片焊盘从 ground 隔离开(否则焊盘和地
    同层短路、在 GDS 里被 union 进 ground 而消失)。
  - 4 次 `GROUND_CUTOUT`:沿 y=±202.5 各开一条直 slot,让 4 条引线穿出 pocket 到开路端。
    末端到 `lead_tip+open_gap`(=440),即 qiskit-metal 的 open-pin 余量。
  - **为什么先建 ground**:布尔运算(挖 pocket+slot)先一次性做完,后面金属用显式高位 tag,
    tag 才稳定、不会被布尔重排打乱(见行 21–24 的构造要点)。
- **名字**:`ground::1::chip::gnd` → role=ground,layer=1,component=chip,primitive=gnd。
  Palace 里它是电容矩阵的**参考地**(7×7 里的第 7 行;本例我方 6×6 把它接地不单列)。

### 1.4 主焊盘 + JJ(行 49–54)—— 显式高位 tag

```gcode
Rectangle(1001) = { -pad_w/2,  pad_cy - pad_h/2, 0, pad_w, pad_h };
Physical Surface("metal::1::Q1::pad_top") = { 1001 };        // 上岛
Rectangle(1002) = { -pad_w/2, -pad_cy - pad_h/2, 0, pad_w, pad_h };
Physical Surface("metal::1::Q1::pad_bot") = { 1002 };        // 下岛
Rectangle(1003) = { -jj_w/2, -pad_gap/2, 0, jj_w, pad_gap };
Physical Surface("jj::1::Q1::jj") = { 1003 };                // JJ(跨 pad_gap)
```
- **为什么 tag 从 1001 起**:ground 那步的布尔运算会消耗/重排低位 tag;金属用 ≥1001 的显式
  tag,保证后续 carve/fragment 引用稳定(见 `.geo` 头注释②)。
- **物理意义**:
  - `pad_top` / `pad_bot`:transmon 的两片岛,它们之间的互容(≈36 fF)就是 qubit 主电容,决定 E_C。
  - `jj`:role=`jj`,是 **lumped 元件**——进 GDS(layer 20),但**静电网格里被移除**
    (`populate_tracker_from_geo` 删掉它),否则会把两焊盘短路。

### 1.5 4 个折线连接器(行 56–163)

每个 connector 是 `connector_pad ∪ 折线 wire` 合并后的**单个 Plane Surface**,用一串
`Point → Line → Curve Loop → Plane Surface` 显式描出闭合轮廓。以 conn_a(行 59–83)为例:

```gcode
Point(1004..1014) = { ... };                    // 11 个顶点,沿轮廓逆时针
Line(1015..1025) = { ... };                     // 顺次连成 11 条边
Curve Loop(1026) = { 1015, ..., 1025 };         // 闭合成一个环
Plane Surface(1027) = { 1026 };                 // 填成面
Physical Surface("metal::1::Q1::conn_a") = { 1027 };
```
- **顶点怎么来的**:取自 qiskit-metal 的引线**中心线**,做 `buffer(cap=flat, join=mitre)`
  (平头端、斜接拐角)外扩半宽算出的轮廓顶点 —— 所以坐标带 `.091`/`.909` 这种斜接小数。
- **为什么不用 CPW 宏**:CPW 宏只画**两点直矩形**;真实引线是**3 段折线**(短水平→斜段→
  水平到开路端),且要和 connector_pad 合并成一个连通导体,故直接显式写整条轮廓。
- **4 条引线的差异**(都接到不同岛、伸向不同方向):
  - `conn_a` 右上、`conn_b` 左上 → 接 **上岛 pad_top**;
  - `conn_c` 右下、`conn_d` 左下 → 接 **下岛 pad_bot**。
  - 它们的 connector_pad 尺寸略不同(a/b 125×30、c 200×30、d 125×50),对应 qiskit-metal
    各 pad 的 `pad_width/pad_height`。
- **物理意义**:每条引线对相邻岛的**互容**就是 qubit→读出腔/总线的耦合电容,决定耦合强度 g。

> ⚠️ 几何忠实化的两处坑(已修,见 walkthrough §4.4):① 引线必须是真实折线、开路端 ±202.5
> (不是臆造的直段);② carve 要先切 ground 再切导体,否则 OCC 漏切穿缺口的 conn_b/c/d。

---

## 2. `qm4q_transmon_cell.meta.yaml` 逐行导读

```yaml
schema: qiskit-metal/design-dsl/3      # DSL v3;固定串,加载器据此选解析器
geo: qm4q_transmon_cell.geo            # 指向同目录几何文件(相对 sidecar 路径)
vars: {}                               # 模板变量表(本例无;可填 ${name} 供 .geo/cells 插值)

simulation:
  gmsh:                                 # 所有 Gmsh/Palace 相关配置都在此块下
```

### 2.1 层栈 `layer_stack`(行 26–37)

```yaml
    layer_stack:
      1:                               # ← 这个 key '1' 必须对上 .geo Physical 名里的 layer 字段
        kind: metal                    # metal | dielectric
        thickness: 2                   # µm;金属厚 2µm(网格分支据此 extrude)
        z: 0                           # 该层底面 z(µm)
        material: pec                  # 理想导体
      3:
        kind: dielectric
        thickness: -750                # 负 = 向下 750µm(衬底在金属下方)
        z: 0
        material: silicon
        eps_r: 11.45                   # 硅相对介电常数(与 Elmer 配置一致,显著增大电容)
```
- **物理意义**:layer 1 是金属(坐在 z=0),layer 3 是硅衬底(z=0 向下 750µm)。**金属直接坐
  在硅上**(共面,无真空缝)——这是把电容从系统性偏低 ~30% 拉回正确的关键(见 §2.5)。
- **`eps_r`**:介质必须建对,硅 εr=11.45 会把共面耦合电容放大约一个量级。

### 2.2 airbox(行 41–44)

```yaml
    airbox:
      top: 890                         # 金属上方真空延伸 µm
      bottom: 1650                     # 衬底下方真空延伸 µm(对齐 qiskit-metal vacuum z[-1650,+890])
      side_buffer: 200                 # 侧向在 ground 边界外再留 200µm
```
- **物理意义**:静电求解的"仿真盒"。Palace 静电没有真 FarField,盒边界近似自由空间。
  `side_buffer` 偏小时,贴近边界的引线尖端会**过耦合**(连接器自电容偏高 +14~17% 的来源之一);
  想压低残差可加大它。

### 2.3 网格 `mesh`(行 48–54)

```yaml
    mesh:
      max_size: 50                     # 全局最大网格尺寸 µm(对齐参考 Elmer)
      min_size: 5                      # 全局最小
      max_size_jj: 20                  # JJ 处更细(虽然 JJ 不进静电网格,GDS/几何仍用)
      conductor_refine:                # 导体表面附近自适应加密
        min_dist: 4                    # 距导体 <4µm 用 min_size
        max_dist: 30                   # 距导体 >30µm 渐变到 max_size
```
- **物理意义**:电场集中在导体边缘/共面缝隙,故近导体加密。网格收敛与否直接影响电容精度
  (order-1 在此网格欠收敛 ±20%,故对标用 order-2,见 §2.6)。

### 2.4 GDS 层映射 `gds`(行 57–68)

```yaml
    gds:
      lib_name: qm4q_cell              # gdstk 库名
      top_cell: qm4q_cell              # 顶层 cell 名(chip.png 标题里的那个)
      unit: 1.0e-6                     # 1 user-unit = 1µm(µm 原样写出,不缩放)
      precision: 1.0e-9                # 数据库精度 1nm
      arc_tol_um: 0.01                 # 圆弧离散容差
      union_same_layer: true           # 同层多边形合并(干净掩模)
      default_datatype: 0
      by_role:                         # 按 role 映射到 GDS (layer, datatype)
        metal:  {layer: 1,  datatype: 0}
        ground: {layer: 1,  datatype: 0}
        jj:     {layer: 20, datatype: 0}   # JJ 单独放 layer 20
```
- **物理意义**:控制 `.geo` 各 role 落到 GDS 哪一层。映射优先级 `by_name > by_role > by_layer >
  内置 default`。本例只用 `by_role`:金属/地都进 L1,JJ 进 L20(就是 chip.png 里那一小块橙色)。

### 2.5 衬底缝 `substrate_gap_um`(行 72)

```yaml
    substrate_gap_um: 0                # 0 = 金属共面坐硅上(物理精确);默认 1µm 会让电容偏低 ~30%
```
- **物理意义**:旧管线为绕开 OCC 数值毛病,在金属下垫 1µm 真空缝 → 共面电场被削弱 → 全矩阵
  偏低 ~30%。设 0 让金属直接坐硅上;数值稳健性改由"fragment 临时缩回 µm + 网格 HXT 回退"解决
  (见 `_gmsh_layers`/`_gmsh_mesh`)。**默认仍是 1µm**(保旧 fixture 字节一致),qm4q 显式设 0。

### 2.6 Palace solver(行 75–81)

```yaml
    solver:
      type: Electrostatic              # 静电求解(解电容矩阵)
      order: 2                         # 有限元阶数;order-1 欠收敛±20%,对标必须 order-2
      l0: 1.0                          # Palace 长度归一 L0=1.0(µm→m 在 OCC 边界处理)
      outer_boundary: open             # open=自然 Neumann≈自由空间 FarField,对齐 Elmer;默认 ground=接地盒
```
- **物理意义**:
  - `order: 2`:二阶 FEM 收敛到主焊盘 −5.5%;order-1 同设置两次网格能给 74 vs 91(±20%),不可用。
  - `outer_boundary: open`:对齐 qiskit-metal/Elmer 的 FarField 外边界(默认 `ground` 是接地盒,
    会低估对地外的电容)。

---

## 3. `qlib.geo` 宏速查(本例用到 / 可用)

每个**几何宏**只造一个 2D Plane Surface,把 tag 写进全局 `sret`,**不打 Physical 标签**
(标签由作者在调用点打)——同一几何宏可被任意 role 复用。调用前先给全局标量赋值。

| 宏 | 入参(全局标量) | 作用 |
|---|---|---|
| `PAD` | `cx, cy, w, h` | 矩形焊盘(中心 cx,cy) |
| `CPW` | `x1, y1, x2, y2, width` | 两点间中心导体(positive metal 直矩形) |
| `JUNCTION` | `x1, y1, x2, y2, width` | JJ 矩形(语义=结,mesh 分支不 extrude) |
| `GROUND_POCKET` | `sground, pkt_cx, pkt_cy, pkt_w, pkt_h` | 在 ground 面上挖矩形 pocket(BooleanDifference) |
| `GROUND_CUTOUT` | `sground, gx1, gy1, gx2, gy2, gw` | 在 ground 面上蚀一条 CPW 形 gap |
| `COUPLER` | `_padb, cpx, pb_bot_y` | 给下焊盘接 neck+paddle 耦合桨,union 成一个导体 |

> 本例没用 `PAD`/`CPW`(主焊盘用裸 `Rectangle` + 高位 tag 以稳 tag;引线用显式折线轮廓),
> ground 蚀刻用了 `GROUND_POCKET` + `GROUND_CUTOUT`。

---

## 4. 其它可选 key(本例没用到的)

下面是 `*.meta.yaml` 在当前 schema 下**还支持但本例未用**的 key。来源:`src/quantum_dsl/dsl/schema.py`。
未知 key 会被 `reject_unknown_keys` 报错,所以只能用这些。

### 4.1 meta.yaml 顶层(`GEO_META_ROOT_KEYS`)
`schema` · `geo` · `vars` · `simulation` · **`circuit_model`** · **`cells`**

- **`circuit_model:`** — 电容矩阵→哈密顿量的结点输入(M6)。结构:
  ```yaml
  circuit_model:
    qubits:
      - name: Q1
        islands: [pad_top, pad_bot]   # 或单个 island: <name>
        L_J: 10nH                      # 或 E_J: 14GHz(二选一,须带显式单位)
  ```
  填了它,管线可在解出 C 矩阵后接着算 E_C/f01 等(本例没填 → 停在 C 矩阵,见 walkthrough §三)。
- **`cells:`** — 用 v3 组件模板**生成** `.geo`(emit_geo 桥)。给了 `cells` 时 `geo` 可省。
  单个 cell 的 key:`cell_type` · `component` · `x` · `y` · `rot` · `layer` · `params`。
  (这是 legacy/模板写法,active path 是手写 `.geo`,故本例不用。)

### 4.2 `simulation.gmsh` 块(`GMSH_SIM_KEYS`)
`layer_stack` · `airbox` · **`ports`** · **`symmetry`** · `mesh` · **`output`** · `gds` · `solver` · `substrate_gap_um`

- **`ports:`** — 端口标记(对 `.geo` 里 `port::...` 标记)。每条 key(`PORT_KEYS`):
  `pin` · `type`(`lumped`|`ground`) · `impedance`(如 `"50ohm"`) · `value`。
  静电电容矩阵不需要端口(每个金属面自动成 terminal);驱动/本征模才用。
- **`symmetry:`** — 对称面减小求解规模。key(`SYMMETRY_KEYS`):
  `plane`(`x0`|`y0`|`z0`) · `condition`(`pec`|`pmc`)。本例几何对称但未启用。
- **`output:`** — 输出设置(`OUTPUT_KEYS`):`format` · `scaling`。

### 4.3 `layer_stack` 每层(`LAYER_STACK_ENTRY_KEYS`)
`kind` · `thickness` · `z` · `material` · `eps_r` · **`tan_delta`**

- **`tan_delta`** — 介质损耗角正切;静电不用,损耗/品质因数相关求解才用。

### 4.4 `mesh`(`MESH_KEYS`)
`max_size` · `min_size` · `max_size_jj` · `conductor_refine`(内含 `min_dist` · `max_dist`)
—— 本例已全用上。

### 4.5 `gds`(`GDS_SIM_KEYS`)
`lib_name` · `top_cell` · `unit` · `precision` · `arc_tol_um` · `union_same_layer` ·
`default_datatype` · `by_role` · **`by_name`** · **`by_layer`**

- **`by_name:`** — 最精确,`{"<component>::<primitive>": {layer, datatype}}`,
  例如把单个 `Q1::conn_a` 单独放一层。优先级最高。
- **`by_layer:`** — `{<.geo layer int>: {layer, datatype}}`,按几何层号映射。

### 4.6 `solver`(`SOLVER_KEYS`)
`type`(目前只 `Electrostatic`) · `order` · `l0` · `outer_boundary`(`open`|`ground`) · **`device`**

- **`device`** — Palace 运行设备相关项(CPU/GPU 等),本例用默认。

---

## 5. 一句话总结

`.meta.yaml`(物理:层栈/εr/airbox/网格/solver)+ `.geo`(几何:每片金属的多边形 + 结构化
Physical 名)是这条管线唯一的两个手写输入;**Physical 名 `role::layer::component::primitive`
是把几何、GDS、Palace、Layer-1 元数据绑在一起的唯一桥**。本例把 qiskit-metal transmon 几何
1:1 写进 `.geo`,把对齐 Elmer 的物理参数写进 `.meta.yaml`,跑出 6×6 电容矩阵做对标。
