# Gmsh Domain Specific Language (DSL) Summary

Gmsh provides a built-in scripting language (`.geo` files) for defining geometries, meshing parameters, and post-processing operations. Here's a concise overview:

## Core Language Features

**Variables & Data Types**
- Variables are untyped and hold floating-point values: `lc = 0.1;`
- Lists use square brackets: `my_list[] = {1, 2, 3};`
- Access elements: `my_list[0]`, get size with `#my_list[]`

**Mathematical Functions**
- `Sqrt()`, `Sin()`, `Cos()`, `Hypot()`, `StrCat()`, `Sprintf()`, `Printf()`

**Control Flow**
- Conditionals: `If ... ElseIf ... Else ... EndIf`
- Loops: `For t In {1:5} ... EndFor`

**Macros** -> similar to functions but without parameters, used for code reuse:
```geo
Macro MacroName
  // commands
Return
Call MacroName;
```

## Geometry Definition

**Built-in CAD Kernel** (default)
- `Point(tag) = {x, y, z, lc};`
- `Line(tag) = {start_point, end_point};`
- `Circle(tag) = {start, center, end};`
- `Curve Loop(tag) = {curve_list};`
- `Plane Surface(tag) = {curve_loop_list};`
- `Surface Loop(tag) = {surface_list};`
- `Volume(tag) = {surface_loop_list};`

**OpenCASCADE Kernel**
- `SetFactory("OpenCASCADE");`
- Primitives: `Sphere()`, `Box()`, `Cylinder()`, `Torus()`
- Boolean operations: `BooleanIntersection()`, `BooleanUnion()`, `BooleanDifference()`, `BooleanFragments()`

## Transformations
- `Translate {dx, dy, dz} { entity_list };`
- `Rotate {{axis_x, axis_y, axis_z}, {point_x, point_y, point_z}, angle} { entity_list };`
- `Extrude {dx, dy, dz} { entity_list };` — creates geometry and optionally layered meshes
```geo
// 设置网格尺寸
lc = 0.1;

// 1. 定义一个圆盘（表面）
Point(1) = {0, 0, 0, lc};
Point(2) = {1, 0, 0, lc};
Point(3) = {0, 1, 0, lc};
Circle(1) = {2, 1, 3};
Circle(2) = {3, 1, 2};
Line(3) = {2, 3};
Curve Loop(1) = {1, 3, 2};
Plane Surface(1) = {1};

// 2. 沿 Z 轴拉伸该表面，生成体积
//    语法：Extrude {dx, dy, dz} { 表面列表 }
Extrude {0, 0, 2} { Surface{1}; }
```

## Physical Groups
Group elementary entities for solver output:
- `Physical Point(tag) = {point_list};`
- `Physical Curve(tag) = {curve_list};`
- `Physical Surface("name", tag) = {surface_list};`
- `Physical Volume(tag) = {volume_list};`

## Mesh Size Control

**Fields** (advanced size specification)
```geo
Field[1] = Distance;
Field[1].PointsList = {1, 2};
Field[2] = Threshold;
Field[2].InField = 1; //to read from Field[1] i.e. distance to points 1 and 2
Field[2].SizeMin = 0.01;
Field[2].SizeMax = 0.1;
Field[2].DistMin = 0.05;
Field[2].DistMax = 0.2; //defined a segmented linear function in essence
Background Field = 2;
```

Field types:
`Distance`, `MathEval`, `Box`,
`Min`, `Max`
`Threshold`, `Attractor`
`PostView`

**Structured Meshes**
- `Transfinite Curve{curve_list} = num_nodes [Using Progression ratio];` //control node distribution along curves
- `Transfinite Surface{surface} = {corner_points};`
//control node distribution on surfaces, requires corner points to be defined
- `Recombine Surface{surface};` — generate quads instead of triangles

## Mesh Options
- `Mesh.Algorithm = 5|6|8;` (Delaunay, Frontal-Delaunay, Frontal-Delaunay for quads)
- `Mesh.ElementOrder = 2;` — second-order elements (curved edges/faces)
- `Mesh.RecombinationAlgorithm = 2;` — full-quad recombination

## File Operations
- `Include "file.geo";` — include another script
- `Merge "file.msh";` — merge mesh or post-processing data
- `Save "output.msh";` — save mesh

## ONELAB Parameters
```geo
DefineConstant[ angle = {90, Min 0, Max 180, Step 1, Name "Parameters/Angle"} ];
```
Creates interactive GUI sliders and exchanges data with solvers.

## Post-Processing Views
Define scalar/vector/tensor datasets, manipulate via options, run plugins (Isosurface, CutPlane, etc.), and create animations.

## Special Variables
- `newp`, `newc`, `newcl`, `news`, `newsl`, `newv` — auto-assign new entity tags
- `Today` — current date string
