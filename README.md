# quantum_dsl (v4)

超导量子芯片版图 DSL — native Gmsh `.geo`(µm)+ `*.meta.yaml` →
{ **GDS**(gdstk)· **mesh**(gmsh)→ **Palace** 静电 → 电容矩阵 } →
拼装(共享节点 + Schur)→ 电路模型(逆电容 LOM / SQUID / TL 谐振器 + χ / CPW)。

**状态: v4 完成(2026-08-25)。** 契约见 [SPEC.md](SPEC.md);可执行需求 =
[`tests/test_spec.py`](tests/test_spec.py)——N0–N14 全绿, N7(two_pads
回归锚)与 N15(Sung et al. PRX 11.021058 外部物理锚)live 实测通过。

```bash
python -m pytest tests/ -q                      # 契约套件 (Python ≥ 3.13)
QDSL_RUN_PALACE=1 python -m pytest tests/ -q    # 含 live Palace 解 (分钟级)
# N15 (sung 整片 order-2, 18.5M 未知量, 峰值内存 ~154G — 上大内存机):
QDSL_RUN_PALACE_SUNG=1 PALACE_BIN=.claude/proto/palace_remote.sh \
  QDSL_REMOTE_HOST=<主机> QDSL_PALACE_NP=32 python -m pytest tests/ -q
```
