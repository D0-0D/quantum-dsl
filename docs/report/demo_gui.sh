#!/usr/bin/env bash
# =====================================================================
# demo_gui.sh — quantum_dsl 汇报现场演示助手（WSL + WSLg）
#
# 用法（在仓库根目录运行）：
#   bash docs/report/demo_gui.sh <子命令> [参数]
#
# 子命令：
#   check                 自检：conda 环境 / 关键依赖 / Palace / 显示
#   build-chip            跑手写 .geo 示例 chip_layout（GDS+网格+JSON+PNG）
#   build-cells           跑 emit_geo cell 桥示例 cells_2q（自动生成 .geo）
#   solve-twopads         跑 two_pads 真实 Palace 求解（C 矩阵 + 哈密顿量；约 2-3 分钟）
#   gmsh   <stem>         打开 Gmsh GUI 看 3D 网格   (stem: chip_layout|cells_2q|two_pads)
#   geo    <stem>         打开 Gmsh GUI 看几何（网格前）
#   gds    <stem>         用 GDSFactory 打开版图交互窗口（matplotlib 渲染）
#   png    <stem>         用图片查看器打开预览 PNG
#
# 典型流程：build-chip → gmsh chip_layout → gds chip_layout
#           build-cells → geo cells_2q（看生成的 .geo）→ gmsh cells_2q
#           solve-twopads → 查看 build/report_two_pads/chip.results.yaml
# =====================================================================
# 注意: 不用 `set -u`(nounset) — conda 的 deactivate.d 脚本含未绑定变量会崩
set -eo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO"

# --- 激活 conda metal-env + PYTHONPATH ---------------------------------
# shellcheck disable=SC1091
source ~/miniconda3/etc/profile.d/conda.sh
conda activate metal-env
export PYTHONPATH="src"
# WSLg 下 Qt 的 wayland 插件常缺失，强制走 X11(xcb)，gmsh GUI / matplotlib 窗口都生效
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-xcb}"

OUT_PREFIX="build/report"   # 与 03-汇报流程文档里的输出目录一致

meta_of() {  # stem -> meta.yaml 路径
  case "$1" in
    chip_layout) echo "examples/dsl/geo/chip_layout.meta.yaml" ;;
    cells_2q)    echo "examples/dsl/geo/cells_2q.meta.yaml" ;;
    two_pads)    echo "tests/fixtures/two_pads.meta.yaml" ;;
    *) echo "UNKNOWN" ;;
  esac
}

geo_src_of() {  # stem -> 用于 `geo` 子命令打开的 .geo
  case "$1" in
    chip_layout) echo "examples/dsl/geo/chip_layout.geo" ;;
    cells_2q)    echo "$OUT_PREFIX""_cells_2q/cells_2q.elaborated.geo" ;;  # 由 build-cells 生成
    two_pads)    echo "tests/fixtures/two_pads.geo" ;;
    *) echo "UNKNOWN" ;;
  esac
}

cmd="${1:-help}"; shift || true

case "$cmd" in
  check)
    echo "== conda =="; conda env list | grep -E '\*|metal-env' || true
    echo "== python =="; python --version
    echo "== deps =="
    python - <<'PY'
import importlib
for m in ["gmsh","gdstk","gdsfactory","shapely","matplotlib","yaml"]:
    try:
        mod = importlib.import_module(m)
        print(f"  {m:12s} {getattr(mod,'__version__','?')}")
    except Exception as e:
        print(f"  {m:12s} MISSING ({e})")
PY
    echo "== palace =="; echo "  PALACE_BIN=${PALACE_BIN:-<unset>}"
    echo "== display =="; echo "  DISPLAY=$DISPLAY  WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-}  QT_QPA_PLATFORM=$QT_QPA_PLATFORM"
    echo "== gmsh GUI 自检（无头截图）=="
    python - <<'PY'
import gmsh, os
gmsh.initialize(); gmsh.open("tests/fixtures/two_pads.geo")
gmsh.model.occ.synchronize()
try:
    gmsh.fltk.initialize(); gmsh.fltk.update()
    gmsh.write("/tmp/_demo_selfcheck.png")
    print("  gmsh GUI 渲染 OK ->", os.path.getsize('/tmp/_demo_selfcheck.png'), "bytes")
except Exception as e:
    print("  gmsh GUI 渲染失败:", e)
gmsh.finalize()
PY
    ;;

  build-chip)
    echo ">> chip_layout（手写 .geo）"
    python -m quantum_dsl.dsl.geo_build "$(meta_of chip_layout)" \
        --out-dir "${OUT_PREFIX}_chip_layout" --png
    ;;

  build-cells)
    echo ">> cells_2q（emit_geo cell 桥，自动生成 .geo）"
    python -m quantum_dsl.dsl.geo_build "$(meta_of cells_2q)" \
        --out-dir "${OUT_PREFIX}_cells_2q" --png
    echo ">> 生成的几何在: ${OUT_PREFIX}_cells_2q/cells_2q.elaborated.geo"
    ;;

  solve-twopads)
    echo ">> two_pads 真实 Palace 求解（约 2-3 分钟）"
    QDSL_RUN_PALACE=1 python -m quantum_dsl.dsl.geo_build "$(meta_of two_pads)" \
        --out-dir "${OUT_PREFIX}_two_pads" --run-palace
    echo ">> 结果: ${OUT_PREFIX}_two_pads/chip.results.yaml"
    ;;

  gmsh)
    stem="${1:?用法: gmsh <chip_layout|cells_2q|two_pads>}"
    msh="${OUT_PREFIX}_${stem}/chip.msh"
    [ -f "$msh" ] || { echo "找不到 $msh — 先跑 build-${stem%%_*} 或对应 build 子命令"; exit 1; }
    echo ">> Gmsh GUI: $msh  （旋转拖拽查看；Tools>Options>Mesh 可调显示）"
    gmsh "$msh"
    ;;

  geo)
    stem="${1:?用法: geo <chip_layout|cells_2q|two_pads>}"
    geo="$(geo_src_of "$stem")"
    [ -f "$geo" ] || { echo "找不到 $geo — cells_2q 需先跑 build-cells"; exit 1; }
    echo ">> Gmsh GUI(几何): $geo"
    gmsh "$geo"
    ;;

  gds)
    stem="${1:?用法: gds <chip_layout|cells_2q|two_pads>}"
    gds="${OUT_PREFIX}_${stem}/chip.gds"
    [ -f "$gds" ] || { echo "找不到 $gds — 先跑对应 build 子命令"; exit 1; }
    echo ">> GDSFactory 交互窗口: $gds"
    python - "$gds" <<'PY'
import sys, matplotlib
matplotlib.use("QtAgg")
import matplotlib.pyplot as plt
from quantum_dsl.dsl.gds_viz import to_gdsfactory_component, read_gds_layers
path = sys.argv[1]
print("  layers:", read_gds_layers(path))
c = to_gdsfactory_component(path)   # = gf.import_gds(...)  (R5 桥)
print("  gdsfactory Component:", c.name)
c.plot()                            # gdsfactory 自己的 matplotlib 渲染
plt.show()                          # 阻塞，弹出窗口；关闭窗口即返回
PY
    ;;

  png)
    stem="${1:?用法: png <chip_layout|cells_2q|two_pads>}"
    png="${OUT_PREFIX}_${stem}/chip.png"
    [ -f "$png" ] || { echo "找不到 $png — build 时带 --png"; exit 1; }
    ( xdg-open "$png" >/dev/null 2>&1 || eog "$png" >/dev/null 2>&1 || \
      python -c "import matplotlib;matplotlib.use('QtAgg');import matplotlib.pyplot as p,matplotlib.image as i;p.imshow(i.imread('$png'));p.axis('off');p.show()" ) &
    echo ">> 已打开 $png"
    ;;

  help|*)
    sed -n '2,40p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    ;;
esac
