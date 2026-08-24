**1. Palace 内部边界 Terminal/Ground**
结论：`Ground/PEC` 内部边界有明确的 Palace cracking 机制支持；`Terminal` 会被当作 electrostatic Dirichlet 边界处理，但我没有找到官方文档/issue 明确承诺“Terminal 可自动处理两侧都有体单元的内部面”，且源码显示 `Terminal` 不在自动 cracking 属性集合里，所以需要最小回归验证或预先 crack 网格。

- Palace schema 有 `CrackInternalBoundaryElements`，说明为“Duplicate nodes along internal boundary elements to create a crack”，默认 `true`：https://github.com/awslabs/palace/blob/main/scripts/schema/config-schema.json#L98-L102
- `Ground` 在配置解析中进入同一个 PEC 数据结构：`PEC can be specified as "PEC" or "Ground"`：https://github.com/awslabs/palace/blob/main/palace/utils/configfile.cpp#L910-L922
- Palace 内部边界 cracking 注释写明会 split/crack 内部 boundary elements 以 decouple 两侧单元：https://github.com/awslabs/palace/blob/main/palace/utils/configfile.hpp#L185-L195
- cracking 实现会检查 boundary face 两侧是否都有体单元，若有则加入 crack 集合：https://github.com/awslabs/palace/blob/main/palace/utils/geodata.cpp#L2852-L2877
- Electrostatic 求解器把 `Ground/PEC` 与 `Terminal` 都加入 essential Dirichlet 边界，并对当前 terminal 投影 `V=1`，其他 terminal/ground 为 `0`：https://github.com/awslabs/palace/blob/main/palace/models/laplaceoperator.cpp#L59-L124 ，https://github.com/awslabs/palace/blob/main/palace/models/laplaceoperator.cpp#L225-L239
- 关键 caveat：`BoundaryData::attributes` 收集 PEC/PMC/FarField/ports/current 等，但没有收集 `terminal`，而 cracking 从这个集合出发：https://github.com/awslabs/palace/blob/main/palace/utils/configfile.cpp#L1007-L1048 ，https://github.com/awslabs/palace/blob/main/palace/utils/geodata.cpp#L2818-L2836
- Palace 文档只明确说 wave port 不能是内部边界；没有同样禁止 Terminal/Ground：https://github.com/awslabs/palace/blob/main/docs/src/guide/boundaries.md#L146-L149
- issues 里能看到内部 cracking 的维护者讨论，但没有找到“electrostatic Terminal on internal boundary”的明确答复。相关例子：#319 说问题 traced back to mesh cracking，`CrackInternalBoundaryElements=false` 可过：https://github.com/awslabs/palace/issues/319#issuecomment-2556740713 ；#773 是 internal PEC strip cracking 与 periodic seam 冲突：https://github.com/awslabs/palace/issues/773
- MFEM 底层支持按 boundary attribute 取 essential true dofs：https://github.com/mfem/mfem/blob/master/fem/fespace.hpp#L1366-L1372 ；也有 internal boundary elements 概念，`RemoveInternalBoundaries` 会移除“两侧都有相邻面”的内部 boundary element：https://github.com/mfem/mfem/blob/master/mesh/mesh.hpp#L1213-L1215

**2. Palace 官方示例怎么建模金属**
结论：Palace 官方相关示例没有把理想金属作为需要求解的实体材料域；静电 spheres 用“挖空导体表面”挂 Terminal/Ground，CPW/Transmon 用零厚度或可选挖空的 PEC 边界面。

- `spheres` 静电例：文档说每个球表面是 `Terminal`，远处外边界是 `Ground`，`Order=3`：https://github.com/awslabs/palace/blob/main/docs/src/examples/spheres.md#L57-L63
- `spheres.json`：`Ground.Attributes=[2]`，`Terminal` 分别挂 `[3]`、`[4]`：https://github.com/awslabs/palace/blob/main/examples/spheres/spheres.json#L45-L61
- `spheres` 网格脚本：创建两个内球和远场球，然后从大球体积中 subtract 两个内球，只网格化球外域；physical groups 是 3D domain 与 2D farfield/sphere surfaces：https://github.com/awslabs/palace/blob/main/examples/spheres/mesh/mesh.jl#L101-L110 ，https://github.com/awslabs/palace/blob/main/examples/spheres/mesh/mesh.jl#L157-L163
- `cpw` 文档直接写金属为 “infinitely thin, perfectly conducting boundary surface”：https://github.com/awslabs/palace/blob/main/docs/src/examples/cpw.md#L19-L20
- `cpw` 默认网格是 `_0.msh`，同时提供带金属厚度版本：https://github.com/awslabs/palace/blob/main/docs/src/examples/cpw.md#L46-L56
- `cpw` 网格脚本默认 `metal_height_μm=0.0`、`remove_metal_vol=true`；若厚度大于 0 则 extrude，之后可 remove metal volume：https://github.com/awslabs/palace/blob/main/examples/cpw/mesh/mesh.jl#L20-L27 ，https://github.com/awslabs/palace/blob/main/examples/cpw/mesh/mesh.jl#L118-L125 ，https://github.com/awslabs/palace/blob/main/examples/cpw/mesh/mesh.jl#L253-L275
- `cpw_lumped_uniform.json` 使用 `mesh/cpw_lumped_0.msh`，`L0=1e-6`，材料只有 air/sapphire，`PEC.Attributes=[13]` 是 metal trace；`SurfaceFlux` 对该面设 `TwoSided=true`：https://github.com/awslabs/palace/blob/main/examples/cpw/cpw_lumped_uniform.json#L8-L31 ，https://github.com/awslabs/palace/blob/main/examples/cpw/cpw_lumped_uniform.json#L54-L59 ，https://github.com/awslabs/palace/blob/main/examples/cpw/cpw_lumped_uniform.json#L137-L144
- `transmon` 文档说 metal conductors modeled as PEC；配置里 `PEC.Attributes=[5]`，材料只有 vacuum/substrate，没有 metal material：https://github.com/awslabs/palace/blob/main/docs/src/examples/transmon.md#L57-L68 ，https://github.com/awslabs/palace/blob/main/examples/transmon/transmon_coarse.json#L38-L42 ，https://github.com/awslabs/palace/blob/main/examples/transmon/transmon_coarse.json#L68-L113

**3. 业界同类流程**
结论：公开流程的主流做法是把超导金属作为 PEC/Capacitance Body 边界面或 thin conductor 边界属性，而不是把 100-200 nm 金属实体网格化求解；膜厚影响在 CPW 公式中是 percent-level 量级，但我没找到公开文献直接量化“100-200 nm 对任意 transmon fF 电容矩阵”的统一偏差。

- Qiskit Metal 说明 Elmer FEM 用于 LOM capacitance，Gmsh 是 mesh generator：https://github.com/qiskit-community/qiskit-metal/blob/main/docs/ecosystem.rst#L113-L119
- Qiskit Metal planar design 是单 dielectric/metal stack 的 2D planar design，默认芯片 9 mm x 6 mm、硅厚 750 µm、sample holder top/bottom 890/1650 µm：https://github.com/qiskit-community/qiskit-metal/blob/main/src/qiskit_metal/designs/design_planar.py#L20-L32 ，https://github.com/qiskit-community/qiskit-metal/blob/main/src/qiskit_metal/designs/design_planar.py#L100-L109
- Qiskit Gmsh renderer：厚度为 0 时 `addRectangle`，厚度非零时 `addBox`；subtraction 维度也随厚度在 2D/3D 间切换：https://github.com/qiskit-community/qiskit-metal/blob/main/src/qiskit_metal/renderers/renderer_gmsh/gmsh_renderer.py#L785-L801 ，https://github.com/qiskit-community/qiskit-metal/blob/main/src/qiskit_metal/renderers/renderer_gmsh/gmsh_renderer.py#L820-L828
- Qiskit Elmer renderer 默认材料是 vacuum/silicon；非 ground nets 加 `Capacitance Body`，ground plane 是 `Capacitance Body:0`，far field 加 `Electric Infinity BC`：https://github.com/qiskit-community/qiskit-metal/blob/main/src/qiskit_metal/renderers/renderer_elmer/elmer_renderer.py#L91-L113 ，https://github.com/qiskit-community/qiskit-metal/blob/main/src/qiskit_metal/renderers/renderer_elmer/elmer_renderer.py#L634-L657
- Qiskit Ansys Q3D renderer 默认 `material_type="pec"`、`material_thickness="200nm"`，并对 2D exported shapes 调 `AssignThinConductor`：https://github.com/qiskit-community/qiskit-metal/blob/main/src/qiskit_metal/renderers/renderer_ansys/q3d_renderer.py#L67-L68 ，https://github.com/qiskit-community/qiskit-metal/blob/main/src/qiskit_metal/renderers/renderer_ansys/q3d_renderer.py#L161-L183
- KQCircuits 文档/源码明确：`metal_height=0` 表示 metal layer modeled as infinitely thin sheet；默认 `metal_height=[0.0]`：https://github.com/iqm-finland/KQCircuits/blob/main/docs/user_guide/simulation/simulation_objects.rst#L127-L133 ，https://github.com/iqm-finland/KQCircuits/blob/main/klayout_package/python/kqcircuits/simulations/simulation.py#L110-L114 ，https://github.com/iqm-finland/KQCircuits/blob/main/klayout_package/python/kqcircuits/simulations/simulation.py#L217-L219
- KQCircuits Elmer/Gmsh：先把金属多边形转 plane surface，只有 thickness 非零才 extrude；excitation boundary 是 2D metal boundaries；Elmer SIF 中 ground 是 `Potential=0`，signal 是 `Capacitance Body=N`：https://github.com/iqm-finland/KQCircuits/blob/main/klayout_package/python/scripts/simulations/elmer/gmsh_helpers.py#L96-L129 ，https://github.com/iqm-finland/KQCircuits/blob/main/klayout_package/python/scripts/simulations/elmer/gmsh_helpers.py#L185-L205 ，https://github.com/iqm-finland/KQCircuits/blob/main/klayout_package/python/scripts/simulations/elmer/elmer_helpers.py#L1222-L1240
- SQDMetal 2026 Palace/COMSOL/Ansys benchmark 明确说 superconducting regions modeled as zero-thickness PEC surfaces；box 高度为 chip 的 2 倍、宽长比 chip 大 20%，边界 PEC 模拟金属 sample holder：https://arxiv.org/html/2511.01220v2#L110-L112
- CPW 有有限厚度一阶修正：`s_e=s-Delta`、`W_e=W+Delta`、`Delta=(1.25t/pi)(1+ln(4piW/t))`：https://qucs.sourceforge.net/tech/node86.html#SECTION001313000000000000000 。用 Palace CPW 的 `W=30 µm, s=18 µm` 估算，100 nm/200 nm 给 `Delta≈0.37/0.68 µm`，只看 CPW 椭圆积分几何因子约增加 1.0%/1.8%；1 µm 人工厚度约 7.6%，所以 1-2 µm void 不是“近似真实 100-200 nm”的无害替代。
- 开放边界/接地盒没有统一惯例：Qiskit Elmer 用 `Electric Infinity BC`；KQCircuits 默认 `electric_infinity_bc=false`，启用时对 `domain_boundary` 加 Electric Infinity BC；Palace spheres 用远场球外边界接地，默认半径 `15*center_d`：https://github.com/qiskit-community/qiskit-metal/blob/main/src/qiskit_metal/renderers/renderer_elmer/elmer_renderer.py#L653-L657 ，https://github.com/iqm-finland/KQCircuits/blob/main/klayout_package/python/kqcircuits/simulations/export/elmer/elmer_solution.py#L191-L206 ，https://github.com/iqm-finland/KQCircuits/blob/main/klayout_package/python/scripts/simulations/elmer/elmer_helpers.py#L1261-L1267 ，https://github.com/awslabs/palace/blob/main/examples/spheres/mesh/mesh.jl#L48-L76

**4. 数值收敛常识**
结论：导体边缘/角点的电荷和场奇异性会主导电容误差，工程上应在边缘做 h/AMR 加密，p=2/3 比 p=1 在光滑区域收益明显，但单纯升阶不能替代边缘加密。

- 静电 edge/corner 文献指出 plate/cube/L-shaped conductors 存在不同阶数的 edge/corner singularities，仍可准确估计 capacitance 和边缘 charge density，但需要谨慎数值处理：https://ar5iv.labs.arxiv.org/html/0805.1462
- hp-FEM 文献总结：光滑解中 p-refinement 可指数收敛，靠近 singularities 时 p-refinement 不如 h-refinement 有效；见 NIST hp-adaptive survey PDF：https://math.nist.gov/~WMitchell/papers/easpaper.pdf
- SQDMetal/Palace benchmark 也把精度提升拆成两项：减小 mesh elements 和提高 basis order；AMR 通过局部误差指标细分高误差单元：https://arxiv.org/html/2511.01220v2#L115-L140
- Palace CPW 文档说把 `p=2` 提到 `p=4` 相当于有效加倍空间分辨率，并降低 lumped port 反射误差：https://github.com/awslabs/palace/blob/main/docs/src/examples/cpw.md#L109-L115
- Palace transmon 脚本注释：`solver_order` 是 finite element order，higher order gives better accuracy but increases cost：https://github.com/awslabs/palace/blob/main/examples/transmon/transmon.jl#L76-L81
- 公开精度参照：Palace spheres 静电例对解析解误差为 0.57%、1.9%、3.5%：https://github.com/awslabs/palace/blob/main/docs/src/examples/spheres.md#L82-L84 ；Qiskit Q3D setup 默认 `percent_error=0.5`：https://github.com/qiskit-community/qiskit-metal/blob/main/src/qiskit_metal/renderers/renderer_ansys/q3d_renderer.py#L282-L288 ；KQCircuits Elmer 默认 `p_element_order=3`、`percent_error=0.005`：https://github.com/iqm-finland/KQCircuits/blob/main/klayout_package/python/kqcircuits/simulations/export/elmer/elmer_solution.py#L91-L109 ，https://github.com/iqm-finland/KQCircuits/blob/main/klayout_package/python/kqcircuits/simulations/export/elmer/elmer_solution.py#L191-L206
- Palace 与商业求解器交叉验证：SQDMetal 的 transmon-resonator 电容提取中，Palace/COMSOL/Ansys Q3D 最终各电容差异都低于 0.3%：https://arxiv.org/html/2511.01220v2#L192-L205 。同文实验对比则更差，qubit/resonator 频率 RMSE 约 5.99%/3.54%，`g` RMSE 24.53%，作者归因于材料、几何、制程和省略物理效应：https://arxiv.org/html/2511.01220v2#L272-L284

**5. Palace 配置语义**
结论：`Model.L0` 是网格坐标单位相对米的比例，`Solver.Order` 是有限元多项式阶数；`terminal-C.csv` 是 Maxwell 电容矩阵，`terminal-Cm.csv` 是 mutual/self-to-ground 形式，off-diagonal 为 `-C_ij`。

- `Model.L0` 官方说明：mesh length units relative to 1 meter；`1e-6` 表示 mesh 坐标是 µm，其他长度量用 `L0 m`：https://github.com/awslabs/palace/blob/main/docs/src/guide/model.md#L12-L19 ，schema 同义说明：https://github.com/awslabs/palace/blob/main/scripts/schema/config-schema.json#L57-L61
- `Solver.Order` schema：finite element order/degree，支持任意 high-order spaces，默认 1：https://github.com/awslabs/palace/blob/main/scripts/schema/config-schema.json#L340-L345
- Electrostatic 参考文档：对每个 terminal `Γ_i` 解 Laplace，`V_i=1`，其他 terminal 为 0，再由场能计算 Maxwell `C_ij`：https://github.com/awslabs/palace/blob/main/docs/src/reference.md#L593-L617
- 源码输出约定：`C(i,i)` 为能量法 diagonal；off-diagonal `C(i,j)=V_j^T K V_i`；`Cm(i,j)=-C(i,j)`，diagonal 再减去所有 mutual；最后写 `terminal-C.csv`、`terminal-Cinv.csv`、`terminal-Cm.csv`：https://github.com/awslabs/palace/blob/main/palace/drivers/electrostaticsolver.cpp#L111-L138 ，https://github.com/awslabs/palace/blob/main/palace/drivers/electrostaticsolver.cpp#L174-L177
- 后处理单位：fields 写 SI，post-processing mesh 仍用 `Model.L0` 对应单位：https://github.com/awslabs/palace/blob/main/docs/src/guide/postprocessing.md#L125-L126

**对候选 (a)/(b)/(c) 的裁决建议**
首选 (a) 零厚度金属面，作为生产默认建模。它符合 Palace CPW/transmon 示例、KQCircuits/Elmer 默认、SQDMetal Palace benchmark，以及 Q3D thin-conductor 的行业习惯。实现时必须保证 Gmsh 导出真实 2D boundary elements 和独立 attributes；对 Palace `Terminal` 内部面做一个最小两垫片回归，比较 `CrackInternalBoundaryElements`、预 crack 网格、以及外边界/ground 处理。

(b) 薄板 void 可作为保守 fallback，尤其在你不想依赖 Palace 对 internal Terminal 的隐式行为时使用；但不要用 1-2 µm 代表 100-200 nm 膜厚，CPW 量级估算显示这会引入数个百分点到十个百分点的几何偏差。若必须用 void，应使用真实膜厚或把厚度作为收敛/校准维度。

(c) 金属实体域不建议作为 Maxwell 电容矩阵主路线。理想导体内部不需要解 Laplace，100-200 nm 实体会制造高 aspect-ratio 网格和大量无效 DoF；只有在要建有限电导、London penetration、kinetic inductance 或材料参与等特殊物理时才考虑。