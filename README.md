# quantum_dsl

超导量子芯片版图 DSL —— native Gmsh `.geo`（µm）+ `*.meta.yaml` →
{ **GDS**（gdstk）· **3D 网格**（gmsh）→ **Palace** 静电 → 电容矩阵 } →
拼装（共享节点 + Schur）→ 电路模型（逆电容 LOM / SQUID / TL 谐振器 + χ / CPW）。

纯 Python ≥ 3.13，核心依赖只有 `pyyaml` / `shapely`；`gmsh` / `gdstk` 为 optional extra；无 qiskit_metal。

**v4.0**（2026-08-26）。金属用**零厚度片 imprint** 表示（不是 v3 的挖空），整条链 1 950 行；
30 条测试；two_pads 回归锚实测**逐位复现**，Sung et al. PRX 11, 021058 论文器件 C_Σ 对论文在 ±8% 内。

## 安装与运行

```bash
pip install -e '.[gmsh,gds,test]'          # 或用本机 conda env qdsl313
export PYTHONPATH=src                       # 未 pip install 时

python -m pytest tests/ -q                  # 28 passed, 2 skipped (~12 s)
python -c "from quantum_dsl import build; print(build('examples/two_pads.meta.yaml', 'build/two_pads'))"
                                            # GDS + GDS 预览 PNG + 网格 + Palace config + manifest (~4 s, 不需要 Palace)

# 真实静电求解 (需要 Palace, PALACE_BIN 指向二进制; WSL 上 build() 自动注入 HWLOC_COMPONENTS=-gl)
QDSL_RUN_PALACE=1 python -m pytest tests/test_live.py -k two_pads -q     # ~2 min, C 对 golden <2%
# 论文器件 (18.5M 未知量, 峰值内存 ~154 G — 上 384G 机; tools/palace_remote.sh 是远端 PALACE_BIN 垫片)
QDSL_RUN_PALACE_SUNG=1 PALACE_BIN=tools/palace_remote.sh QDSL_REMOTE_HOST=<主机> QDSL_PALACE_NP=32 \
  python -m pytest tests/test_live.py -k sung -q
```

## 文档

| 想知道 | 看 |
|---|---|
| 怎么上手、文档地图 | [`docs/README.md`](docs/README.md) |
| 架构、模块地图、公共 API、`build()` 产物 | [`docs/architecture.md`](docs/architecture.md) |
| 为什么这么算、数值可信到哪一位、每条公式的出处 | [`docs/physics.md`](docs/physics.md) |
| `.geo` 与 `meta.yaml` 怎么写 | [`docs/grammar.md`](docs/grammar.md) |
| 例子（two_pads / 分块 / sung 论文器件 / 宏库） | [`examples/README.md`](examples/README.md) |
| 契约（N0–N15 ↔ 测试） | [`SPEC.md`](SPEC.md) |
| 汇报材料（展示 / 备问 / 演示手册） | [`docs/report/`](docs/report/README.md) |

## 分支

- `main` —— v4 产品分支（本 README）。
- `v3` —— 旧实现（qiskit_metal 时代），只读参考。
- `v4-dev` —— v4 的 TDD 开发痕迹与原始调研存档（session logs、文献取证、N15 原始 CSV、原型脚本）。

Apache-2.0。
