# quantum_dsl (v4)

超导量子芯片版图 DSL — native Gmsh `.geo`(µm)+ `*.meta.yaml` →
{ **GDS**(gdstk)· **mesh**(gmsh)→ **Palace** 静电 → 电容矩阵 } →
拼装(共享节点 + Schur)→ 电路模型(逆电容 LOM / SQUID / TL 谐振器 + χ / CPW)。

**状态: greenfield 重写进行中(TDD)。** 契约见 [SPEC.md](SPEC.md);
可执行需求 = [`tests/test_spec.py`](tests/test_spec.py)(全绿 = 完成)。

```bash
python -m pytest tests/ -q                      # 契约套件 (Python ≥ 3.13)
QDSL_RUN_PALACE=1 python -m pytest tests/ -q    # 含 live Palace 解
```
