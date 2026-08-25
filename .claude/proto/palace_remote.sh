#!/usr/bin/env bash
# Palace 远端执行垫片 —— 以 PALACE_BIN 形态接入 build()._run_palace()。
# 产品代码不感知远端: _run_palace 照常调 `$PALACE_BIN -np N <cfg>`
# (cwd = config 目录), 本脚本把 config+mesh 送到远端机、在那边跑、拉回 postpro。
#
# 用途: N15 sung 整片 order-2 重解 (~18M 未知量) 超出 WSL 15G 内存,
# 按 plan.md「可在多核真机跑」上 64C/128G 云机 (SPEC 验收第 3 条)。
# 用法:
#   PALACE_BIN=.claude/proto/palace_remote.sh QDSL_PALACE_NP=32 \
#     QDSL_RUN_PALACE_SUNG=1 pytest tests/test_spec.py::TestN15SungPaper
# 环境: QDSL_REMOTE_HOST (默认 c24a1), QDSL_REMOTE_PALACE (远端二进制路径)
set -euo pipefail

host="${QDSL_REMOTE_HOST:-c24a1}"
rbin="${QDSL_REMOTE_PALACE:-/root/spack/opt/spack/linux-x86_64_v4/palace-0.16.0-f3k3qw7flgv5s4bcfbeg4vv2uvurzuww/bin/palace}"
cfg="${@: -1}"                       # 调用形态: -np N <cfg>
mesh=$(sed -n 's/.*"Mesh": *"\([^"]*\)".*/\1/p' "$cfg")
rdir="/root/qdsl_run_$$_$(date +%s)"

echo "[palace_remote] ship $cfg + $mesh ($(du -h "$mesh" | cut -f1)) -> $host:$rdir" >&2
ssh "$host" "mkdir -p $rdir"
tar cf - "$cfg" "$mesh" | gzip -1 | ssh "$host" "gzip -d | tar xf - -C $rdir"

# 非交互 ssh 无 spack env: mpirun 要显式进 PATH (palace 靠它拉起 MPI)
mpibin="${QDSL_REMOTE_MPIBIN:-/root/spack/opt/spack/linux-x86_64_v4/openmpi-5.0.10-6y2jevipmwntrxem4x5a3o2jgv265bbn/bin}"
rc=0
ssh "$host" "cd $rdir && PATH=$mpibin:\$PATH \
    OMPI_ALLOW_RUN_AS_ROOT=1 OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1 \
    PRTE_MCA_rmaps_default_mapping_policy=:oversubscribe $rbin $*" || rc=$?
if [ "$rc" -eq 0 ]; then
    ssh "$host" "tar cf - -C $rdir postpro" | tar xf -
fi
ssh "$host" "rm -rf $rdir"
exit "$rc"
