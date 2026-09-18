# -*- coding: utf-8 -*-
"""版图编排器 (契约「版图编排」): ``*.layout.yaml`` 有序步骤 → 一个 gmsh 模型 + 记账。

设计稿 ``docs/design/component-library.md`` (v3.1)。要点:

* **版图 = 一个 gmsh 模型**。三种步骤按顺序写进同一模型: ``template`` (模板实例:
  放置型 ``at/rot/mirror`` 或连接型 ``from/to``), ``geo`` (手写 ``.geo``, 只增不改),
  ``route`` (= 连接型 template 的别名)。最后 ``ground: {sheet: …}`` 建地并减去全部蚀刻工具面。
* **模板 = 局部坐标 ``.geo`` (不打 Physical 名) + 同名 ``.yaml`` 接口** (params / layers 槽位 /
  islands / external / etch / junction / ports / outputs / steps)。编排器 = 调用点: 置毒输出变量
  → 设参数 → ``merge`` → 差集拿新面 → 按位姿 ``affineTransform`` → 读输出变量 → 层槽位映射到
  芯片层 → 按实例名挂 Physical。模板可嵌套 (``steps:``), 端口 / 外挂面可再导出。
* **层是模板的局部命名空间**: 槽位只声明 kind 要求, 实例上 ``layers: {slot: chip_layer}`` 重定位
  (同名兼容可省), 层性质由 meta ``layers:`` 表决定。
* **端口** = 端面中点 + 外法向 (rad) + 宽 + 层 + 等效长度; 路由只接端口, 宽度继承, 两口必须正对
  (``planner: cpw`` 模板除外: ``route.plan_cpw`` 在芯片坐标里规划直段 + 圆弧 (曼哈顿框架或 Dubins), 位姿恒等, 原语按列表变量注入)。
  **路由是电连接**: 两端外挂面 + 路由自身面并成一个 net; net 名来自岛 (恰一个岛端 → 该岛;
  零岛端 → 步骤名; 两岛端 → raise)。
* **纪律** (全部 raise, 不静默): 输出变量 NaN 置毒; 手写步骤前后已有面原样存在 (增量原则);
  Physical 全名唯一; 每块面恰被一个 net 认领; 未连接的外挂面; 层槽位存在且 kind 兼容; role 与层
  kind 一致; 不同 net 同层导体面相交 (``occ.getDistance == 0``) = 短路。

角度: YAML 里 ``rot`` 写**度**; 模板输出的端口法向是 ``.geo`` 算的 **rad**。长度一律 µm。
gmsh 惰性 import (import 纯度): 本模块只在 ``Layout`` 被调用时用到 gmsh。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from .errors import QuantumDslError
from .geo import parse_physical_name
from .units import parse_length, parse_quantity

__all__ = ["Port", "Layout", "compile_layout"]

LAYOUT_SCHEMA = "quantum-dsl/layout/1"
TEMPLATE_SCHEMA = "quantum-dsl/template/1"
LAYER_KINDS = frozenset({"conductor", "junction", "drawing"})
_ROLE_KIND = {"metal": "conductor", "ground": "conductor", "jj": "junction"}

_LAYOUT_KEYS = frozenset({"schema", "templates", "steps", "ground"})
_TEMPLATE_KEYS = frozenset({"schema", "kind", "params", "layers", "islands", "external",
                            "etch", "junction", "ports", "outputs", "body", "steps", "planner"})
_TPL_STEP_KEYS = frozenset({"template", "route", "name", "at", "rot", "mirror", "from", "to",
                            "params", "layers", "length", "E_J", "L_J", "squid", "region", "axis"})
_PLANNER_PARAMS = ("R", "n_legs", "gap", "lead")   # planner: cpw 模板必须声明的参数 (最小弯半径 / 腿数 / 缝宽 / 端口引出直段)
_GEO_STEP_KEYS = frozenset({"geo", "frame", "ports", "etch", "layers", "connect"})
_ENTRY_KEYS = {          # 模板各段每条目的合法键 (拼错 = 静默丢语义, 必须查)
    "islands": frozenset({"faces", "layer"}),
    "external": frozenset({"faces", "layer", "if", "inst"}),
    "etch": frozenset({"faces", "layer", "if"}),
    "ports": frozenset({"port", "x", "y", "a", "w", "layer", "leq", "if", "island"}),
    "junction": frozenset({"a", "b", "x1", "y1", "x2", "y2", "width", "layer"}),
}
_REF = re.compile(r"^([A-Za-z_]\w*)(?:\((\d*)\))?$")
_INCLUDE = re.compile(r'(?m)^\s*Include\s+"([^"]+)"')
_MACRO = re.compile(r"(?m)^\s*(Macro|Function)\b")
_TOL = 1e-6          # µm; 面快照 / 端口正对 / 相交判定的公差

_ID = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)    # 2D 仿射 (a, b, c, d, tx, ty): x' = a x + b y + tx


@dataclass(frozen=True)
class Port:
    """端口: 端面中点 (µm) + 外法向 (rad) + 宽 + 层 + 等效长度; ``net`` = 所属 component,
    ``None`` 表示外挂面 (待连接步骤认领, ``ext`` = (实例, 外挂键))。"""

    x: float
    y: float
    a: float
    w: float
    layer: object
    leq: float = 0.0
    net: str | None = None
    ext: tuple[str, str] | None = None


@dataclass
class _Face:
    role: str
    layer: object
    component: str | None        # None = 外挂面待认领
    primitive: str
    ext: tuple[str, str] | None = None
    named: bool = False          # True = 手写 .geo 自己挂了 Physical 名


@dataclass(frozen=True)
class _Template:
    name: str
    path: Path                   # yaml
    geo: Path | None
    doc: dict


@dataclass
class _Ctx:
    prefix: tuple[str, ...]
    pose: tuple
    layer_map: dict | None       # 父模板 slot → 芯片层 (顶层 None)
    base_dir: Path
    tdirs: tuple[Path, ...]


# ----------------------------------------------------------------------------- 仿射
def _pose(at, rot_deg, mirror) -> tuple:
    c, s = math.cos(math.radians(rot_deg)), math.sin(math.radians(rot_deg))
    mx, my = 1.0, 1.0
    if mirror == "x":
        my = -1.0
    elif mirror == "y":
        mx = -1.0
    elif mirror not in (None, False):
        raise QuantumDslError(f"layout: mirror must be 'x' or 'y', got {mirror!r}")
    # R · M: 先镜像 (局部), 再转
    return (c * mx, -s * my, s * mx, c * my, float(at[0]), float(at[1]))


def _compose(outer, inner) -> tuple:
    a, b, c, d, tx, ty = outer
    e, f, g, h, ux, uy = inner
    return (a * e + b * g, a * f + b * h, c * e + d * g, c * f + d * h,
            a * ux + b * uy + tx, c * ux + d * uy + ty)


def _apply(p, x, y):
    a, b, c, d, tx, ty = p
    return a * x + b * y + tx, c * x + d * y + ty


def _apply_angle(p, ang):
    a, b, c, d, _, _ = p
    vx, vy = math.cos(ang), math.sin(ang)
    return math.atan2(c * vx + d * vy, a * vx + b * vy)


def _angles_equal(u, v) -> bool:
    return abs(math.sin(u - v)) < 1e-9 and math.cos(u - v) > 0


# ----------------------------------------------------------------------------- 加载
def _yaml(path: Path, what: str) -> dict:
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise QuantumDslError(f"{what}: cannot read {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise QuantumDslError(f"{what}: invalid YAML in {path}: {exc}") from exc
    if not isinstance(doc, dict):
        raise QuantumDslError(f"{what}: {path} is not a YAML mapping")
    return doc


def _check_keys(doc: dict, allowed, where: str) -> None:
    unknown = sorted(set(doc) - allowed)
    if unknown:
        raise QuantumDslError(f"{where}: unknown key(s) {unknown} (known: {sorted(allowed)})")


def _load_template(name: str, tdirs) -> _Template:
    for d in tdirs:
        for yml in (d / f"{name}.yaml", d / name / f"{name}.yaml"):
            if yml.is_file():
                doc = _yaml(yml, f"template {name}")
                _check_keys(doc, _TEMPLATE_KEYS, f"template {yml}")
                if doc.get("schema") != TEMPLATE_SCHEMA:
                    raise QuantumDslError(
                        f"template {yml}: schema {doc.get('schema')!r} != {TEMPLATE_SCHEMA!r}")
                geo = yml.with_suffix(".geo")
                geo = geo if geo.is_file() else None
                if geo is None and not doc.get("steps"):
                    raise QuantumDslError(
                        f"template {yml}: needs {yml.with_suffix('.geo').name} or steps:")
                if doc.get("kind") not in (None, "connect"):
                    raise QuantumDslError(
                        f"template {yml}: kind {doc['kind']!r} must be 'connect' (a placement "
                        f"template omits kind:)")
                if doc.get("planner") is not None:
                    if doc["planner"] != "cpw" or doc.get("kind") != "connect":
                        raise QuantumDslError(
                            f"template {yml}: planner: {doc['planner']!r} — the only planner is 'cpw' and it "
                            f"needs kind: connect")
                    missing = [k for k in _PLANNER_PARAMS if k not in (doc.get("params") or {})]
                    if missing:
                        raise QuantumDslError(f"template {yml}: planner: cpw needs params {list(_PLANNER_PARAMS)}, "
                                              f"missing {missing}")
                for sec, allowed in _ENTRY_KEYS.items():
                    val = doc.get(sec)
                    if isinstance(val, dict) and sec == "junction":
                        _check_keys(val, allowed, f"template {yml}: junction")
                    elif isinstance(val, (dict, list)):
                        items = val.items() if isinstance(val, dict) else enumerate(val)
                        for key, spec in items:
                            if isinstance(spec, dict):
                                _check_keys(spec, allowed, f"template {yml}: {sec}.{key}")
                for slot, kind in (doc.get("layers") or {}).items():
                    if kind not in LAYER_KINDS:
                        raise QuantumDslError(
                            f"template {yml}: layer slot {slot!r} kind {kind!r} not in "
                            f"{sorted(LAYER_KINDS)}")
                return _Template(name=name, path=yml, geo=geo, doc=doc)
    raise QuantumDslError(
        f"layout: template {name!r} not found (looked for {name}.yaml in "
        f"{[str(d) for d in tdirs]})")


def _refs(value) -> list[str]:
    """YAML 值里引用的 .geo 变量名 (供置毒)。"""
    if isinstance(value, str):
        m = _REF.match(value.strip())
        return [m.group(1)] if m else []
    if isinstance(value, dict):
        return [n for v in value.values() for n in _refs(v)]
    if isinstance(value, list):
        return [n for v in value for n in _refs(v)]
    return []


def _included(geo: Path, seen: set[Path]) -> list[Path]:
    """``.geo`` 递归 ``Include`` 到的文件: 宏库也是几何来源, 必须进 manifest 溯源。"""
    out: list[Path] = []
    try:
        text = geo.read_text(encoding="utf-8")
    except OSError:
        return out
    for m in _INCLUDE.finditer(text):
        q = (geo.parent / m.group(1)).resolve()
        if q in seen or not q.is_file():
            continue
        seen.add(q)
        out.append(q)
        out += _included(q, seen)
    return out


def _port_refs(ports) -> list[str]:
    """``ports:`` 段真正读回的 .geo 变量名: 先展开 ``port(i)`` 简写 (否则简写逃过置毒,
    模板条件赋值时会读到上一个实例的坐标)。"""
    out: list[str] = []
    for spec in (ports or {}).values():
        if isinstance(spec, str) and "." in spec:
            continue                       # 嵌套再导出 (子实例端口), 不是 .geo 变量
        out += _refs({k: v for k, v in _port_spec(spec).items()
                      if k not in ("net", "island")})
    return out


def _port_spec(spec) -> dict:
    """``"port(0)"`` 简写 → ``{x: port_x(0), y: port_y(0), a: port_a(0), w: port_w(0)}``。"""
    if isinstance(spec, str):
        m = _REF.match(spec.strip())
        if not m or m.group(2) is None:
            raise QuantumDslError(f"layout: port shorthand {spec!r} must look like 'port(0)'")
        base, i = m.group(1), m.group(2)
        return {k: f"{base}_{k}({i})" for k in "xyaw"}
    if isinstance(spec, dict):
        if "port" in spec:
            return {**_port_spec(spec["port"]), **{k: v for k, v in spec.items() if k != "port"}}
        return dict(spec)
    raise QuantumDslError(f"layout: port spec must be a string or mapping, got {spec!r}")


# ----------------------------------------------------------------------------- 编排器
class Layout:
    """已编译的版图: 可调用 (``geo_model(layout)`` 在当前 gmsh 模型里重放全部步骤),
    并带记账: ``qubits`` (生成的 circuit_model 条目), ``subsystems`` (谐振器长度),
    ``inputs`` (全部输入文件, 供 manifest), ``ports``。"""

    def __init__(self, meta):
        if meta.layout_path is None:
            raise QuantumDslError("compile_layout: meta has no 'layout:'")
        if not meta.layers:
            raise QuantumDslError(
                f"compile_layout: {meta.path}: 'layout:' requires a 'layers:' table "
                f"(template layer slots must map onto chip layers)")
        self.meta = meta
        self.path = Path(meta.layout_path)
        self.doc = _yaml(self.path, "layout")
        _check_keys(self.doc, _LAYOUT_KEYS, f"layout {self.path}")
        if self.doc.get("schema") != LAYOUT_SCHEMA:
            raise QuantumDslError(
                f"layout {self.path}: schema {self.doc.get('schema')!r} != {LAYOUT_SCHEMA!r}")
        if not isinstance(self.doc.get("steps"), list) or not self.doc["steps"]:
            raise QuantumDslError(f"layout {self.path}: 'steps' must be a non-empty list")
        tdirs = self.doc.get("templates") or ["."]
        self.tdirs = tuple((self.path.parent / d).resolve() for d in tdirs)
        self.keep = None
        self.qubits: list[dict] = []
        self.subsystems: list[dict] = []
        self.inputs: list[Path] = []
        self.ports: dict[str, Port] = {}

    def _add_input(self, path: Path | None) -> None:
        if path is None:
            return
        extra = _included(path, {path.resolve()}) if path.suffix == ".geo" else []
        for q in [path] + extra:
            if q not in self.inputs:
                self.inputs.append(q)

    def for_block(self, components) -> "Layout":
        """分块: 只给 ``components`` 里的 component 挂 Physical 名 (其余面成孤儿, build_mesh 清)。"""
        blk = Layout.__new__(Layout)
        blk.__dict__.update(self.__dict__)
        blk.keep = frozenset(components)
        return blk

    # ---- 入口: geo_model 回调 ----------------------------------------------------
    def __call__(self, gmsh) -> None:
        self.gmsh, self.occ, self.P = gmsh, gmsh.model.occ, gmsh.parser
        self.faces: dict[int, _Face] = {}
        self.etch: list[tuple[object, int]] = []        # (芯片层, 面 tag)
        self.names: set[str] = set()
        self.poses: dict[str, tuple] = {}
        self.used: set[str] = set()                     # 已被连接步骤消费的端口
        self.ports = {}
        self.qubits, self.subsystems, self.inputs = [], [], [self.path]
        ctx = _Ctx(prefix=(), pose=_ID, layer_map=None, base_dir=self.path.parent,
                   tdirs=self.tdirs)
        self._steps(self.doc["steps"], ctx, f"layout {self.path.name}")
        self._ground()
        self._finish()

    # ---- 步骤 --------------------------------------------------------------------
    def _steps(self, steps, ctx: _Ctx, where: str) -> None:
        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                raise QuantumDslError(f"{where}: step #{i} is not a mapping: {step!r}")
            if "geo" in step:
                _check_keys(step, _GEO_STEP_KEYS, f"{where} step #{i} (geo step)")
                self._geo_step(step, ctx, f"{where} step #{i}")
            elif "template" in step or "route" in step:
                _check_keys(step, _TPL_STEP_KEYS, f"{where} step #{i} (template step)")
                self._template_step(step, ctx, f"{where} step #{i}")
            else:
                raise QuantumDslError(f"{where} step #{i}: needs template:, route: or geo:")

    # ---- 变量通道 ----------------------------------------------------------------
    def _inject_ports(self) -> None:
        for key, p in self.ports.items():
            base = key.replace(".", "_")
            for k, v in (("x", p.x), ("y", p.y), ("a", p.a), ("w", p.w)):
                self.P.setNumber(f"{base}_{k}", [v])

    def _merge(self, path: Path, where: str) -> tuple[list[int], list[tuple[int, int]]]:
        """merge 一个 .geo, 返回 (新面 tags, 新 Physical 组)。"""
        # merge 的文件解析完即关闭, 里面定义的 Macro 随之失效: 同进程第二次跑版图 (出 GDS / 网格 / 分块) 时守卫跳过定义、
        # Call 读已关闭的文件 → gmsh 段错误 (2026-09-16 实测)。Include 的文件 gmsh 不关, 宏库走 Include (lib/cpw_macros.geo)。
        if _MACRO.search(path.read_text(encoding="utf-8", errors="replace")):
            raise QuantumDslError(
                f"{where}: {path.name} defines a Macro — a merged file is closed after parsing and its "
                f"macros die with it (the next run of this layout in the same process crashes gmsh); "
                f"put macros in a separate file with an If (!Exists(...)) guard and Include it")
        before = {t for _, t in self.gmsh.model.getEntities(2)}
        pbefore = set(self.gmsh.model.getPhysicalGroups(2))
        try:
            self.gmsh.merge(str(path))
        except Exception as exc:
            raise QuantumDslError(f"{where}: gmsh cannot parse {path.name}: {exc}") from exc
        self.occ.synchronize()
        new = sorted(t for _, t in self.gmsh.model.getEntities(2) if t not in before)
        pnew = sorted(set(self.gmsh.model.getPhysicalGroups(2)) - pbefore)
        return new, pnew

    def _num(self, value, where: str) -> float:
        if isinstance(value, bool):
            raise QuantumDslError(f"{where}: expected a number or .geo variable, got {value!r}")
        if isinstance(value, (int, float)):
            return float(value)
        m = _REF.match(str(value).strip()) if isinstance(value, str) else None
        if not m:
            raise QuantumDslError(f"{where}: expected a number or .geo variable, got {value!r}")
        name, idx = m.group(1), m.group(2)
        vals = list(self.P.getNumber(name))
        i = int(idx) if idx else 0
        if not vals or i >= len(vals):
            raise QuantumDslError(f"{where}: .geo did not set output variable {value!r}")
        if math.isnan(vals[i]):
            raise QuantumDslError(f"{where}: .geo left output variable {value!r} unset (NaN)")
        return float(vals[i])

    def _tags(self, value, new: list[int], where: str) -> list[int]:
        m = _REF.match(str(value).strip()) if isinstance(value, str) else None
        if not m:
            raise QuantumDslError(f"{where}: faces must name a .geo list variable like "
                                  f"'faces()', got {value!r}")
        vals = list(self.P.getNumber(m.group(1)))
        if not vals or any(math.isnan(v) for v in vals):
            raise QuantumDslError(f"{where}: .geo left face list {value!r} unset (NaN/empty)")
        tags = [int(v) for v in vals]
        bad = [t for t in tags if t not in new]
        if bad:
            raise QuantumDslError(
                f"{where}: face list {value!r} names tag(s) {bad} that this .geo did not "
                f"create (templates may only export their own faces)")
        return tags

    def _transform(self, pose, tags) -> None:
        if pose == _ID or not tags:
            return
        a, b, c, d, tx, ty = pose
        self.occ.affineTransform([(2, t) for t in tags],
                                 [a, b, 0, tx, c, d, 0, ty, 0, 0, 1, 0, 0, 0, 0, 1])
        self.occ.synchronize()

    # ---- 层 ----------------------------------------------------------------------
    def _chip_layer(self, layer, where: str) -> dict:
        tbl = self.meta.layers
        if layer not in tbl:
            raise QuantumDslError(
                f"{where}: layer {layer!r} not in meta.layers {sorted(map(str, tbl))}")
        return tbl[layer]

    def _layer_map(self, step, tpl: _Template, ctx: _Ctx, where: str) -> dict:
        slots = tpl.doc.get("layers") or {}
        given = step.get("layers") or {}
        unknown = sorted(set(given) - set(slots))
        if unknown:
            raise QuantumDslError(
                f"{where}: layers maps unknown slot(s) {unknown}; template {tpl.name} "
                f"declares {sorted(slots)}")
        out = {}
        for slot, kind in slots.items():
            target = given.get(slot, slot)
            if ctx.layer_map is not None and target in ctx.layer_map:
                target = ctx.layer_map[target]
            if slot not in given and target not in self.meta.layers:
                # 省略映射: 同名芯片层不存在时, 若该 kind 的芯片层唯一则取它 (无歧义), 否则必须显式写
                same = [lid for lid, sp in self.meta.layers.items() if sp["kind"] == kind]
                if len(same) != 1:
                    raise QuantumDslError(
                        f"{where}: slot {slot!r} ({kind}) has no same-named chip layer and the "
                        f"chip has {len(same)} {kind} layers {same} — write layers: {{{slot}: <id>}}")
                target = same[0]
            chip = self._chip_layer(target, f"{where}: slot {slot!r}")
            if chip["kind"] != kind:
                raise QuantumDslError(
                    f"{where}: slot {slot!r} needs a {kind} layer but chip layer "
                    f"{target!r} is {chip['kind']}")
            out[slot] = target
        return out

    # ---- 模板步骤 -----------------------------------------------------------------
    def _template_step(self, step, ctx: _Ctx, where: str) -> None:
        tname = step.get("template") or step.get("route")
        name = step.get("name")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_]\w*", name):
            raise QuantumDslError(f"{where}: template step needs an identifier 'name', got {name!r}")
        tpl = _load_template(tname, ctx.tdirs)
        inst = ctx.prefix + (name,)
        full = "_".join(inst)
        where = f"{where} {full} ({tpl.path.name})"
        if full in self.poses:
            raise QuantumDslError(f"{where}: instance name {full!r} used twice")
        for f in (tpl.path, tpl.geo):
            self._add_input(f)

        params = dict(tpl.doc.get("params") or {})
        extra = sorted(set(step.get("params") or {}) - set(params))
        if extra:
            raise QuantumDslError(f"{where}: unknown param(s) {extra}; template declares "
                                  f"{sorted(params)}")
        params.update(step.get("params") or {})
        for k, v in params.items():
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                raise QuantumDslError(f"{where}: param {k!r} must be a finite number, got {v!r}")
        lmap = self._layer_map(step, tpl, ctx, where)

        connect = tpl.doc.get("kind") == "connect"
        if connect != ("from" in step or "to" in step):
            raise QuantumDslError(
                f"{where}: template kind {'connect' if connect else 'place'} "
                f"{'needs from:/to:' if connect else 'takes at:/rot:/mirror:, not from:/to:'}")
        planner = tpl.doc.get("planner") is not None
        for key in ("region", "axis"):
            if key in step and not planner:
                raise QuantumDslError(f"{where}: {key}: is only for planner templates (planner: cpw); "
                                      f"{tpl.name} draws in the from->to frame and needs facing ports")
        ends: tuple[tuple[str, Port], tuple[str, Port]] | None = None
        inject: dict = {}
        target = None
        if connect:
            bad = sorted({"at", "rot"} & set(step))
            if bad:
                raise QuantumDslError(f"{where}: connect steps take from:/to:/mirror:, not "
                                      f"{bad} — the pose comes from the two ports")
            ends, pose, D, w = self._connect_pose(step, where, planner)
            net = self._net(ends, full, where)          # 路由体的 component = net, 结记账前就定
            for k in ("D", "w", "L"):
                if k in params:
                    raise QuantumDslError(f"{where}: connect templates get {k!r} injected; "
                                          f"rename the param")
            inject = {"D": D, "w": w}
            if "length" in step:
                target = self._length(step["length"], w, params, ends, where)
                inject["L"] = target["length_drawn_um"]
            if planner:                                 # 规划在芯片坐标里 (位姿恒等), 原语当列表变量注入
                prims = self._plan(step, params, ends, w, inject.get("L"), where)
                inject.update(prims)
                if target is not None:
                    target["route_primitives"] = int(prims["_rt_n"])
        else:
            at = step.get("at", [0, 0])
            if not (isinstance(at, list) and len(at) == 2):
                raise QuantumDslError(f"{where}: at must be [x, y] (um), got {at!r}")
            pose = _compose(ctx.pose, _pose(at, float(step.get("rot", 0)), step.get("mirror")))
        self.poses[full] = pose

        islands = tpl.doc.get("islands") or {}
        comps: dict[str, str] = {}          # 岛键 → component 名
        single = len(islands) == 1
        for key in islands:
            comps[key] = full if single else f"{full}_{key}"
        body = tpl.doc.get("body")
        if body is None and single:
            body = next(iter(islands))
        if body is not None and body not in islands:
            raise QuantumDslError(f"{where}: body: {body!r} is not an island key of "
                                  f"{tpl.name} {sorted(islands)}")
        if connect:
            if body is None:
                raise QuantumDslError(f"{where}: connect template with {len(islands)} islands "
                                      f"needs body: <island key>")
            comps[body] = net

        out: dict[str, float] = {}
        new: list[int] = []
        if tpl.geo:
            new = self._run_geo(tpl, params, inject, pose, where)

            def enabled(spec, what):      # 可选部件: if: <param> 非零才读
                g = spec.get("if")
                if g is None:
                    return True
                if g not in params:
                    raise QuantumDslError(f"{where}: {what} if: {g!r} is not a param of "
                                          f"{tpl.name} {sorted(params)}")
                return params[g] != 0
            for key, spec in islands.items():
                for t in self._tags(spec.get("faces"), new, f"{where} islands.{key}"):
                    self._claim(t, "metal", lmap, spec, comps[key], key, where)
            for key, spec in (tpl.doc.get("external") or {}).items():
                if enabled(spec, f"external.{key}"):
                    for t in self._tags(spec.get("faces"), new, f"{where} external.{key}"):
                        self._claim(t, "metal", lmap, spec, None, key, where, ext=(full, key))
            for i, spec in enumerate(tpl.doc.get("etch") or []):
                if enabled(spec, f"etch[{i}]"):
                    layer = self._slot(spec, lmap, where)
                    for t in self._tags(spec.get("faces"), new, f"{where} etch"):
                        self.etch.append((layer, t))
            for key, spec in (tpl.doc.get("ports") or {}).items():
                spec = _port_spec(spec)
                if not enabled(spec, f"ports.{key}"):
                    continue
                x, y = _apply(pose, self._num(spec["x"], where), self._num(spec["y"], where))
                ext = (full, key) if key in (tpl.doc.get("external") or {}) else None
                pnet = None                      # 端口所属岛; 不要遮蔽路由体的 net
                if ext is None:
                    ikey = spec.get("island", body)
                    if ikey not in comps:
                        raise QuantumDslError(f"{where}: port {key!r} needs island: <key> "
                                              f"(template has islands {sorted(comps)})")
                    pnet = comps[ikey]
                self.ports[f"{full}.{key}"] = Port(
                    x=x, y=y, a=_apply_angle(pose, self._num(spec["a"], where)),
                    w=self._num(spec["w"], where), layer=self._slot(spec, lmap, where,
                                                                    default=lmap and next(iter(lmap))),
                    leq=self._num(spec.get("leq", 0), where), net=pnet, ext=ext)
            for key, ref in (tpl.doc.get("outputs") or {}).items():
                out[key] = self._num(ref, where)
            j = tpl.doc.get("junction")
            if j:
                self._junction(j, step, pose, lmap, comps, full, where)

        if tpl.doc.get("steps"):          # 嵌套: 子步骤在父 .geo 之后; 再导出见 _reexport
            sub = _Ctx(prefix=inst, pose=pose, layer_map=lmap, base_dir=tpl.path.parent,
                       tdirs=(tpl.path.parent,) + ctx.tdirs)
            self._steps(tpl.doc["steps"], sub, where)
            self._reexport(tpl, full, comps, where)

        if connect:
            self._connect(ends, net, [t for t in new if t in self.faces and
                                      self.faces[t].component == net], where)
        if target is not None:
            drawn = out.get("length")
            if drawn is None:
                raise QuantumDslError(f"{where}: length: given but template declares no "
                                      f"outputs.length")
            if abs(drawn - target["length_drawn_um"]) > _TOL * max(1.0, drawn):
                raise QuantumDslError(
                    f"{where}: template drew {drawn:.6g} um, target {target['length_drawn_um']:.6g}")
            self.subsystems.append({"name": net, "route": full, **target})

    def _slot(self, spec, lmap, where, default=None):
        slot = spec.get("layer", default)
        if slot not in lmap:
            raise QuantumDslError(f"{where}: layer slot {slot!r} not declared in template "
                                  f"layers {sorted(lmap)}")
        return lmap[slot]

    def _claim(self, tag, role, lmap, spec, component, primitive, where, ext=None) -> None:
        if tag in self.faces:
            raise QuantumDslError(f"{where}: face {tag} claimed twice")
        layer = self._slot(spec, lmap, where)
        self.faces[tag] = _Face(role=role, layer=layer, component=component,
                                primitive=primitive, ext=ext)

    def _run_geo(self, tpl: _Template, params, inject, pose, where) -> list[int]:
        doc = tpl.doc
        poison = set()
        for section in ("islands", "external", "etch", "junction", "outputs"):
            poison.update(_refs(doc.get(section)))
        poison.update(_port_refs(doc.get("ports")))
        poison -= set(params) | set(inject)
        nan = float("nan")
        for v in poison:
            self.P.setNumber(v, [nan])
        for k, v in {**params, **inject}.items():        # 标量或列表 (planner 的 _rt_* 原语表), 列表整体替换
            self.P.setNumber(k, [float(x) for x in v] if isinstance(v, (list, tuple)) else [float(v)])
        new, pnew = self._merge(tpl.geo, where)
        if pnew:
            raise QuantumDslError(
                f"{where}: template .geo must not create Physical groups (got "
                f"{[self.gmsh.model.getPhysicalName(2, t) for _, t in pnew]}); the "
                f"orchestrator names faces from the template yaml")
        self._transform(pose, new)
        return new

    def _junction(self, j, step, pose, lmap, comps, full, where) -> None:
        for k in ("a", "b", "x1", "y1", "x2", "y2", "width"):
            if k not in j:
                raise QuantumDslError(f"{where}: junction needs {k!r}")
        a, b = j["a"], j["b"]
        if a not in comps or (b != "ground" and b not in comps):
            raise QuantumDslError(f"{where}: junction islands {a!r}/{b!r} must be island keys "
                                  f"{sorted(comps)} (b may be 'ground')")
        x1, y1 = _apply(pose, self._num(j["x1"], where), self._num(j["y1"], where))
        x2, y2 = _apply(pose, self._num(j["x2"], where), self._num(j["y2"], where))
        hw = self._num(j["width"], where) / 2
        L = math.hypot(x2 - x1, y2 - y1)
        if not L > 0 or not hw > 0:
            raise QuantumDslError(f"{where}: degenerate junction (length {L}, width {2*hw})")
        nx, ny = -(y2 - y1) / L * hw, (x2 - x1) / L * hw
        pts = [self.occ.addPoint(px, py, 0) for px, py in
               ((x1 + nx, y1 + ny), (x2 + nx, y2 + ny), (x2 - nx, y2 - ny), (x1 - nx, y1 - ny))]
        lines = [self.occ.addLine(pts[i], pts[(i + 1) % 4]) for i in range(4)]
        face = self.occ.addPlaneSurface([self.occ.addCurveLoop(lines)])
        self.occ.synchronize()
        layer = self._slot(j, lmap, where)
        if self._chip_layer(layer, where)["kind"] != "junction":
            raise QuantumDslError(f"{where}: junction layer {layer!r} is not kind junction")
        self.faces[face] = _Face(role="jj", layer=layer, component=full, primitive="jj")
        energy = {k: step[k] for k in ("E_J", "L_J", "squid") if k in step}
        if len(energy) != 1:
            raise QuantumDslError(
                f"{where}: template has a junction — give exactly one of E_J / L_J / squid "
                f"on the step (got {sorted(energy) or 'none'})")
        q: dict = {"name": full}
        if b == "ground":
            q["island"] = comps[a]
        else:
            q["islands"] = [comps[a], comps[b]]
        if "L_J" in energy:
            q["L_J"] = parse_quantity(energy["L_J"])
        if "E_J" in energy:
            q["E_J"] = parse_quantity(energy["E_J"])
        if "squid" in energy:
            s = dict(energy["squid"])
            q["squid"] = {"E_J1": parse_quantity(s["E_J1"]), "E_J2": parse_quantity(s["E_J2"]),
                          "flux": float(s.get("flux", 0.0))}
        self.qubits.append(q)

    def _reexport(self, tpl: _Template, full, comps, where) -> None:
        """嵌套模板: ``ports: {E: claw_E.E}`` / ``external: {E: {inst: claw_E}}`` 引用子步骤。"""
        if tpl.geo is None:
            for key, spec in (tpl.doc.get("external") or {}).items():
                child = f"{full}_{spec.get('inst')}"
                hit = [t for t, f in self.faces.items() if f.component == child]
                if not hit:
                    raise QuantumDslError(f"{where}: external {key!r} refers to child "
                                          f"{spec.get('inst')!r} with no island faces")
                for t in hit:
                    f = self.faces[t]
                    self.faces[t] = _Face(role=f.role, layer=f.layer, component=None,
                                          primitive=key, ext=(full, key))
                for pk, p in list(self.ports.items()):
                    if p.net == child:
                        self.ports[pk] = Port(p.x, p.y, p.a, p.w, p.layer, p.leq, None,
                                              (full, key))
        for key, ref in (tpl.doc.get("ports") or {}).items():
            if isinstance(ref, str) and "." in ref and tpl.geo is None:
                src = f"{full}_{ref}"
                if src not in self.ports:
                    raise QuantumDslError(f"{where}: port {key!r} re-exports unknown {ref!r}")
                self.ports[f"{full}.{key}"] = self.ports.pop(src)

    # ---- 连接 --------------------------------------------------------------------
    def _port(self, ref, where) -> Port:
        if ref not in self.ports:
            raise QuantumDslError(f"{where}: port {ref!r} unknown (known: {sorted(self.ports)})")
        return self.ports[ref]

    def _connect_pose(self, step, where, planner=False):
        for k in ("from", "to"):
            if k not in step:
                raise QuantumDslError(f"{where}: connect step needs {k}:")
        p, q = self._port(step["from"], where), self._port(step["to"], where)
        D = math.hypot(q.x - p.x, q.y - p.y)
        if not D > 0:
            raise QuantumDslError(f"{where}: ports {step['from']} and {step['to']} coincide")
        if abs(p.w - q.w) > _TOL:
            raise QuantumDslError(f"{where}: port widths differ ({p.w} vs {q.w} um); "
                                  f"a taper is not implemented — match the widths")
        if p.layer != q.layer:
            raise QuantumDslError(f"{where}: ports on different layers ({p.layer!r} vs {q.layer!r})")
        mirror = step.get("mirror")
        if planner:                                    # 规划器在芯片坐标里自己找路: 位姿恒等, 不要求正对, 镜像无意义
            if mirror not in (None, False):
                raise QuantumDslError(f"{where}: mirror: has no meaning for a planner template (the route is "
                                      f"planned in chip coordinates); drop it or use region:")
            return ((step["from"], p), (step["to"], q)), _ID, D, p.w
        axis = math.atan2(q.y - p.y, q.x - p.x)
        if not (_angles_equal(p.a, axis) and _angles_equal(q.a, axis + math.pi)):
            raise QuantumDslError(
                f"{where}: ports must face each other along the axis (from normal "
                f"{math.degrees(p.a):.3f} deg, axis {math.degrees(axis):.3f} deg, to normal "
                f"{math.degrees(q.a):.3f} deg) — use cpw_route (planner: cpw) or hand-write the .geo")
        if mirror not in (None, False, "x"):
            raise QuantumDslError(
                f"{where}: connect steps only take mirror: x (flip across the from->to axis); "
                f"mirror: {mirror!r} would reverse the axis itself and draw away from {step['to']}")
        pose = _compose((1, 0, 0, 1, p.x, p.y),
                        _pose([0, 0], math.degrees(axis), mirror))   # mirror: x 翻到轴另一侧
        return ((step["from"], p), (step["to"], q)), pose, D, p.w

    def _plan(self, step, params, ends, w, L, where) -> dict:
        """planner: cpw —— 两口 (不必正对) 之间在芯片坐标里规划中心线 (``route.plan_cpw``), 原语按列展开成
        gmsh 列表变量: ``_rt_n`` 段数, ``_rt_kind(k)`` 0 直段 / 1 弧, ``_rt_p0(k)..._rt_p4(k)`` =
        直段 (x1, y1, x2, y2, 0) / 弧 (cx, cy, R, a0, a1); 模板 ``.geo`` 用 For 循环逐段 Call 宏。"""
        from .route import plan_cpw
        (_, p), (_, q) = ends
        if L is None and "n_legs" in (step.get("params") or {}):
            raise QuantumDslError(f"{where}: n_legs: given but no length: — without a target length the route is the "
                                  f"shortest path and has no meander; drop n_legs or give length:")
        try:
            prims = plan_cpw((p.x, p.y, p.a), (q.x, q.y, q.a + math.pi), params["R"], length=L,
                             region=step.get("region"), n_legs=params["n_legs"], width=w + 2 * params["gap"],
                             lead=params["lead"], axis=step.get("axis", 0.0))
        except QuantumDslError as exc:
            raise QuantumDslError(f"{where}: {exc}") from exc
        cols: dict[str, list[float]] = {f"_rt_p{i}": [] for i in range(5)}
        cols["_rt_kind"] = []
        for pr in prims:
            vals = list(pr[1:]) + ([0.0] if pr[0] == "line" else [])
            cols["_rt_kind"].append(0.0 if pr[0] == "line" else 1.0)
            for i in range(5):
                cols[f"_rt_p{i}"].append(vals[i])
        return {"_rt_n": len(prims), **cols}

    def _length(self, spec, w, params, ends, where) -> dict:
        if not isinstance(spec, dict) or "mode" not in spec:
            raise QuantumDslError(f"{where}: length must be {{mode: quarter_wave|half_wave|fixed, ...}}")
        mode = spec["mode"]
        leq = sum(p.leq for _, p in ends)
        if mode == "fixed":
            total = parse_length(spec.get("L"))
            rec = {"mode": mode}
        elif mode in ("quarter_wave", "half_wave"):
            from .cpw import guided_wavelength
            for k in ("f_r", "film_nm"):
                if k not in spec:
                    raise QuantumDslError(f"{where}: length.{mode} needs {k}")
            if "gap" not in params:
                raise QuantumDslError(f"{where}: wave-length targeting needs a template param "
                                      f"'gap' (CPW slot width)")
            sub = self.meta.materials.get("substrate") or {}
            for k in ("eps_r", "thickness_um"):
                if k not in sub:
                    raise QuantumDslError(f"{where}: length.{mode} needs meta.materials.substrate.{k}")
            f = parse_quantity(spec["f_r"])
            lam = guided_wavelength(f, w * 1e-6, params["gap"] * 1e-6,
                                    float(sub["thickness_um"]) * 1e-6,
                                    float(spec["film_nm"]) * 1e-9,
                                    eps_r=float(sub["eps_r"])).lambda_g * 1e6
            total = lam / (4 if mode == "quarter_wave" else 2)
            rec = {"mode": mode, "f_r_hz": f, "lambda_g_um": lam, "gap_um": params["gap"],
                   "film_nm": float(spec["film_nm"])}
        else:
            raise QuantumDslError(f"{where}: length.mode {mode!r} unknown")
        drawn = total - leq
        if not drawn > 0:
            raise QuantumDslError(f"{where}: equivalent length {leq} um exceeds target {total} um")
        return {"kind": "cpw_resonator", "width_um": w, **rec,
                "length_total_um": total, "equiv_length_um": leq, "length_drawn_um": drawn}

    def _net(self, ends, full, where) -> str:
        """连接的 net 名: 恰一个岛端 → 该岛; 零岛端 → 步骤名; 两岛端 → raise。"""
        island_ends = [(ref, p) for ref, p in ends if p.net is not None]
        if len(island_ends) == 2:
            raise QuantumDslError(
                f"{where}: both ends are islands ({island_ends[0][0]} = "
                f"{island_ends[0][1].net!r}, {island_ends[1][0]} = {island_ends[1][1].net!r}) — "
                f"a galvanic join of two named islands has no unique net name; make one an "
                f"external or draw them as one instance")
        return island_ends[0][1].net if island_ends else full

    def _connect(self, ends, net, body, where) -> None:
        """两端并入 net: 外挂面 (与其端口) 改挂 net, 岛端只记账。``body`` = 本步骤画的 net 金属面,
        每一端都必须被它碰到 (否则爪 / 岛与路由体之间隔着缝, 却已记成同一 net); 端口只能连一次。"""
        def touches(tags):
            return any(self.occ.getDistance(2, u, 2, v)[0] <= _TOL for u in body for v in tags)
        for ref, _ in ends:                   # 端口留在表里 (供手写步骤读变量), 但只能连一次 (同一表里重复也算)
            if ref in self.used:
                raise QuantumDslError(f"{where}: port {ref!r} already used by another connection")
            self.used.add(ref)
        for ref, p in ends:
            if p.ext is None:
                far = [t for t, f in self.faces.items()
                       if f.component == p.net and f.role == "metal" and t not in body]
                if not touches(far):
                    raise QuantumDslError(
                        f"{where}: the {net!r} metal drawn here does not touch island {p.net!r} "
                        f"at port {ref!r} — gap between body and port?")
                continue
            hit = [t for t, f in self.faces.items() if f.ext == p.ext]
            if not hit:
                raise QuantumDslError(
                    f"{where}: port {ref!r} is external but no face was drawn behind it — the "
                    f"port's if: guard and the external part's if: guard disagree")
            if not touches(hit):
                raise QuantumDslError(
                    f"{where}: external face(s) {hit} behind port {ref!r} are not touched by the "
                    f"{net!r} metal drawn here — gap between body and port, or wrong connect:?")
            for t in hit:
                f = self.faces[t]
                self.faces[t] = _Face(f.role, f.layer, net, f.primitive)
            for pk, q in list(self.ports.items()):
                if q.ext == p.ext:
                    self.ports[pk] = Port(q.x, q.y, q.a, q.w, q.layer, q.leq, net, None)

    # ---- 手写 .geo 步骤 ------------------------------------------------------------
    def _geo_step(self, step, ctx: _Ctx, where: str) -> None:
        path = (ctx.base_dir / step["geo"]).resolve()
        if not path.is_file():
            raise QuantumDslError(f"{where}: no such file: {path}")
        where = f"{where} ({path.name})"
        self._add_input(path)
        pose = ctx.pose
        if "frame" in step:
            if step["frame"] not in self.poses:
                raise QuantumDslError(f"{where}: frame {step['frame']!r} is not an instance "
                                      f"placed before this step")
            pose = self.poses[step["frame"]]
        self._inject_ports()
        snap = {t: (self.occ.getMass(2, t), self.gmsh.model.getBoundingBox(2, t))
                for _, t in self.gmsh.model.getEntities(2)}
        for v in _refs(step.get("etch")) + _port_refs(step.get("ports")):
            self.P.setNumber(v, [float("nan")])
        new, pnew = self._merge(path, where)
        for t, (mass, bb) in snap.items():
            try:
                same = (abs(self.occ.getMass(2, t) - mass) <= _TOL * max(1.0, mass) and
                        all(abs(u - v) <= _TOL for u, v in
                            zip(self.gmsh.model.getBoundingBox(2, t), bb)))
            except Exception:
                same = False
            if not same:
                raise QuantumDslError(
                    f"{where}: hand-written .geo modified or deleted existing face {t} — "
                    f"geo steps may only ADD geometry (no Delete / booleans on template "
                    f"faces); parametrize the template instead")
        self._transform(pose, new)
        claimed = set()
        for dim, ptag in pnew:
            pname = self.gmsh.model.getPhysicalName(dim, ptag)
            phys = parse_physical_name(pname)
            if pname in self.names:
                raise QuantumDslError(f"{where}: Physical name {pname!r} already exists")
            self.names.add(pname)
            chip = self._chip_layer(phys.layer, f"{where}: {pname!r}")
            if chip["kind"] != "drawing" and _ROLE_KIND.get(phys.role) != chip["kind"]:
                raise QuantumDslError(
                    f"{where}: {pname!r}: role {phys.role!r} on a {chip['kind']} layer")
            for t in self.gmsh.model.getEntitiesForPhysicalGroup(dim, ptag):
                t = int(t)
                if t not in new:
                    raise QuantumDslError(f"{where}: {pname!r} claims face {t} not created here")
                if t in claimed:
                    raise QuantumDslError(f"{where}: face {t} in two Physical groups")
                claimed.add(t)
                self.faces[t] = _Face(role=phys.role, layer=phys.layer, component=phys.component,
                                      primitive=phys.primitive, named=True)
        if "etch" in step:
            layer = step.get("layers")
            if layer is not None:
                self._chip_layer(layer, f"{where} etch layers:")
            for t in self._tags(step["etch"], new, f"{where} etch"):
                if t in claimed:
                    raise QuantumDslError(f"{where}: etch face {t} also carries a Physical name")
                claimed.add(t)
                # 蚀刻工具面的层: 用该步骤唯一的导体层, 多层时须显式 layers: <id>
                layers = {f.layer for f in (self.faces[c] for c in claimed if c in self.faces)}
                if layer is None and len(layers) != 1:
                    raise QuantumDslError(f"{where}: etch needs layers: <chip layer> (step "
                                          f"names faces on {sorted(map(str, layers))})")
                self.etch.append((layer if layer is not None else next(iter(layers)), t))
        connect = step.get("connect") or {}
        if not isinstance(connect, dict):
            raise QuantumDslError(f"{where}: connect must be {{<component>: [<port>, ...]}}")
        for net, refs in connect.items():        # 手写金属认领模板画的外挂面 (爪), 与连接型模板同一条路
            body = [t for t in claimed if t in self.faces and self.faces[t].component == net
                    and self.faces[t].role == "metal"]
            if not body:
                raise QuantumDslError(f"{where}: connect: {net!r} is not a metal component named "
                                      f"by this step's Physical names")
            if not isinstance(refs, list) or not refs:
                raise QuantumDslError(f"{where}: connect: {net!r} needs a list of ports, got {refs!r}")
            ends = []
            for ref in refs:
                p = self._port(ref, where)
                if p.net is not None and p.net != net:
                    raise QuantumDslError(
                        f"{where}: connect: port {ref!r} belongs to island {p.net!r}; to join it, "
                        f"name the faces metal::<layer>::{p.net}::<prim> instead of {net!r}")
                if any(self.faces[t].layer != p.layer for t in body):
                    raise QuantumDslError(f"{where}: connect: port {ref!r} is on layer {p.layer!r} "
                                          f"but {net!r} is drawn on another layer")
                ends.append((ref, p))
            self._connect(ends, net, body, where)
        for key, spec in (step.get("ports") or {}).items():
            spec = _port_spec(spec)
            net = spec.get("net")
            if net is None:
                raise QuantumDslError(f"{where}: port {key!r} needs net: <component>")
            layers = {f.layer for f in self.faces.values() if f.component == net}
            if len(layers) != 1:
                raise QuantumDslError(f"{where}: port {key!r} net {net!r} has faces on "
                                      f"{len(layers)} layers; expected exactly 1")
            x, y = _apply(pose, self._num(spec["x"], where), self._num(spec["y"], where))
            if key in self.ports:
                raise QuantumDslError(f"{where}: port {key!r} already exists")
            self.ports[key] = Port(x=x, y=y, a=_apply_angle(pose, self._num(spec["a"], where)),
                                   w=self._num(spec["w"], where), layer=next(iter(layers)),
                                   leq=self._num(spec.get("leq", 0), where), net=net)

    # ---- 地 ----------------------------------------------------------------------
    def _ground(self) -> None:
        g = self.doc.get("ground", "none")
        sheets = []
        if g != "none":
            if not isinstance(g, dict) or set(g) != {"sheet"}:
                raise QuantumDslError(f"layout: ground must be 'none' or {{sheet: {{layer, margin_um}}}}")
            sheets = g["sheet"] if isinstance(g["sheet"], list) else [g["sheet"]]
        done_layers = set()
        for sh in sheets:
            layer, margin = sh.get("layer"), float(sh.get("margin_um", 0))
            if self._chip_layer(layer, "layout ground.sheet")["kind"] != "conductor":
                raise QuantumDslError(f"layout ground.sheet: layer {layer!r} is not a conductor layer")
            cond = [t for t, f in self.faces.items() if f.layer == layer and f.role == "metal"]
            if not cond:
                raise QuantumDslError(f"layout ground.sheet: no metal faces on layer {layer!r}")
            inf = float("inf")
            x0, y0, x1, y1 = inf, inf, -inf, -inf
            for t in cond:
                bb = self.gmsh.model.getBoundingBox(2, t)
                x0, y0, x1, y1 = min(x0, bb[0]), min(y0, bb[1]), max(x1, bb[3]), max(y1, bb[4])
            rect = self.occ.addRectangle(x0 - margin, y0 - margin, 0,
                                         (x1 - x0) + 2 * margin, (y1 - y0) + 2 * margin)
            tools = [(2, t) for lay, t in self.etch if lay == layer]
            if tools:
                out, _ = self.occ.cut([(2, rect)], tools, removeObject=True, removeTool=True)
                faces = [t for d, t in out if d == 2]
            else:
                faces = [rect]
            self.occ.synchronize()
            if not faces:
                raise QuantumDslError("layout ground.sheet: etch consumed the whole sheet")
            for t in faces:
                self.faces[t] = _Face(role="ground", layer=layer, component="GND", primitive="sheet")
            done_layers.add(layer)
        stale = [(2, t) for lay, t in self.etch if lay not in done_layers]
        if stale:
            self.occ.remove(stale, recursive=True)
            self.occ.synchronize()

    # ---- 收尾: 校验 + 挂名 ------------------------------------------------------------
    def _finish(self) -> None:
        pending = sorted({f.ext for f in self.faces.values() if f.component is None})
        if pending:
            raise QuantumDslError(
                f"layout: external face(s) {[f'{i}.{k}' for i, k in pending]} were drawn but "
                f"nothing connects to them — route to the port or disable the part")
        # 面归属: 模型里每块面必须被认领
        orphans = [t for _, t in self.gmsh.model.getEntities(2) if t not in self.faces]
        if orphans:
            raise QuantumDslError(
                f"layout: face(s) {orphans} are not claimed by any island/external/etch/"
                f"junction/Physical name — templates must export or delete every face")
        # 短路: 不同 net 的导体面同层相交
        cond = [(t, f) for t, f in self.faces.items()
                if f.role in ("metal", "ground") and
                self.meta.layers[f.layer]["kind"] == "conductor"]
        bbs = {t: self.gmsh.model.getBoundingBox(2, t) for t, _ in cond}
        for i, (t1, f1) in enumerate(cond):
            for t2, f2 in cond[i + 1:]:
                if f1.layer != f2.layer or f1.component == f2.component:
                    continue
                a, b = bbs[t1], bbs[t2]
                if a[0] > b[3] + _TOL or b[0] > a[3] + _TOL or a[1] > b[4] + _TOL or b[1] > a[4] + _TOL:
                    continue
                if self.occ.getDistance(2, t1, 2, t2)[0] <= _TOL:
                    raise QuantumDslError(
                        f"layout: conductors {f1.component!r} and {f2.component!r} touch/overlap "
                        f"on layer {f1.layer!r} (faces {t1}, {t2}) — a short. Missing etch/gap?")
        # 挂名: 编排器生成的组按 keep 挂; 手写组在 merge 时就已建好, 分块时整体拆掉再按 keep 重挂
        # (逐组 removePhysicalGroups 只拆块外的, 之后出网格 gmsh 段错误 —— 2026-09-16 chen_2025_3x3_hand 实测)
        gen: dict[str, list[int]] = {}
        hand: dict[str, list[int]] = {}
        for t, f in self.faces.items():
            if self.keep is not None and f.component not in self.keep:
                continue
            (hand if f.named else gen).setdefault(
                f"{f.role}::{f.layer}::{f.component}::{f.primitive}", []).append(t)
        clash = sorted(set(gen) & self.names)
        if clash:
            raise QuantumDslError(f"layout: Physical name(s) {clash} clash with hand-written ones")
        if self.keep is not None:
            self.gmsh.model.removePhysicalGroups()
            for name in self.names:          # 名字表与组分开存: 不删, 重挂的组拿不到名字 (读回 ''), 残留名让出网格时 gmsh 崩
                self.gmsh.model.removePhysicalName(name)
            for name, tags in hand.items():
                self.gmsh.model.addPhysicalGroup(2, sorted(tags), name=name)
        for name, tags in gen.items():
            parse_physical_name(name)
            self.names.add(name)
            self.gmsh.model.addPhysicalGroup(2, sorted(tags), name=name)
        self.occ.synchronize()


def compile_layout(meta) -> Layout:
    """meta (含 ``layout:`` 与 ``layers:``) → :class:`Layout`。编译一遍 (一次性 gmsh 模型)
    做全部校验并填记账; 之后把返回值当 ``geo_model`` 的几何源重放。"""
    lay = Layout(meta)
    from ._gmsh import geo_model

    with geo_model(lay):
        pass
    return lay
