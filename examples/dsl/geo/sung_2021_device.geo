// =====================================================================
// sung_2021_device.geo
<<<<<<< Updated upstream
// Native Gmsh .geo — simplified reproduction of the 3-body tunable-coupler
// device of Sung et al., Phys. Rev. X 11, 021058 (2021) / arXiv:2011.01261.
// Paper reference values + what this layout actually measures: see the header
// of sung_2021_device.meta.yaml (do not restate them here — one source only).
//
// Topology: QB1 — CPLR — QB2 in a row, each a FLOATING (differential) transmon
// = two identical pads with the junction bridging them; no pad touches ground.
//
// Two things the geometry has to get right, and how:
//   * C_Σ ≈ 99 / 228 / 102 fF is LARGE, so the pads are large and the gap to
//     ground above/below them is tight (m_y): C_Σ ≈ C_pad-pad + ½·C_pad-gnd,
//     and both terms grow with pad perimeter / shrink with gap.
//   * C_1c = C_2c = 5.36 fF needs the qubit and coupler pads to face each other
//     DIRECTLY: adjacent pockets are carved so that they OVERLAP in x
//     (dx < q_mx + c_mx), leaving no ground metal in the qubit↔coupler channel.
//     A ground trench between them instead makes the top/bottom pads look alike
//     from a distance and the differential coupling
//     ¼|c_tt + c_bb − c_tb − c_bt| collapses (that was the 20× error here).
//   dx (island↔island gap) is the coupling knob; m_x is the C_Σ trim knob.
//
// CAUTION when re-tuning: the pockets must overlap by a COMFORTABLE margin.
// Measured on gmsh 4.11.1 at the default QDSL_FRAGMENT_SCALE=1e2, everything
// else held fixed: overlap 30 µm (dx=30) and 40 µm (dx=50, m_x=45) fragment
// clean, overlap 10 µm (dx=50, m_x=30) and no overlap at all (dx=100) both die
// in occ.fragment with "Boolean fragments failed" — at every scale in
// {1, 1e2, 1e3}, so it is the near-degenerate boolean, not the conditioning.
=======
// Paper-inspired native Gmsh .geo for the 3-body tunable coupler device
// from Sung et al., Phys. Rev. X 11, 021058 (2021).
//
// The published device is a coplanar three-body layout: QB1 and QB2 are
// transmon-like islands, and the center element is a larger tunable coupler.
// This example keeps that overall arrangement but uses the repo's proven
// mesher-safe pocketed-island construction rather than photo-accurate meanders.
>>>>>>> Stashed changes
// =====================================================================

SetFactory("OpenCASCADE");
Include "qlib.geo";

<<<<<<< Updated upstream
// ---- Device geometry parameters (µm) --------------------------------
// Qubit transmons (QB1, QB2)
q_pad_w  = 360;   // pad width
q_pad_h  = 180;   // pad height (per pad; island is 2*h + sep tall)
q_pad_sep= 8;     // slot between the two pads (the junction bridges it)
q_mx     = 30;    // pad→ground gap, left/right
q_my     = 8;     // pad→ground gap, top/bottom

// Tunable coupler (CPLR) — same topology, ~2x linear size for C_c ≈ 2.3 C_1
c_pad_w  = 720;
c_pad_h  = 360;
c_pad_sep= 8;
c_mx     = 30;
c_my     = 8;
=======
// ---- Device Geometry Parameters (µm) --------------------------------
q1_cx   = -320;   // QB1 center X
c_cx    = 0;      // CPLR center X
q2_cx   = 320;    // QB2 center X
q_cy    = 0;      // Global center Y

// Transmon dimensions (paper-inspired coplanar approximation)
pad_w   = 120;    // QB pad width
pad_h   = 80;     // QB pad height
c_pad_w = 160;    // Coupler pad width (larger than qubits)
c_pad_h = 120;    // Coupler pad height
pad_sep = 30;     // Gap between top and bottom pads
jj_w    = 2;      // JJ width

// Ground isolation
pkt_gap = 25;     // Vacuum gap surrounding the islands
>>>>>>> Stashed changes

dx       = 30;    // qubit pad ↔ coupler pad gap (sets C_1c / C_2c)
jj_w     = 2;     // JJ width (lumped element: GDS layer 20, not meshed)

q_cx     = dx + (q_pad_w + c_pad_w)/2;   // QB centre offset from the coupler
q_cy     = 0;

// Ground sheet — must stay a single connected sheet around the pockets.
g_w = 1900; g_h = 1100;
g_x0 = -g_w/2; g_y0 = -g_h/2;

// ---- 1) QB1 (left transmon) -----------------------------------------
cx = -q_cx; cy = q_cy + (q_pad_h + q_pad_sep)/2; w = q_pad_w; h = q_pad_h;
Call PAD;
Physical Surface("metal::1::QB1::pad_top") = { sret };

cx = -q_cx; cy = q_cy - (q_pad_h + q_pad_sep)/2; w = q_pad_w; h = q_pad_h;
Call PAD;
Physical Surface("metal::1::QB1::pad_bot") = { sret };

x1 = -q_cx; y1 = q_cy - q_pad_sep/2; x2 = -q_cx; y2 = q_cy + q_pad_sep/2;
width = jj_w;
Call JUNCTION;
Physical Surface("jj::1::QB1::jj") = { sret };

// ---- 2) CPLR (centre tunable coupler) -------------------------------
cx = 0; cy = q_cy + (c_pad_h + c_pad_sep)/2; w = c_pad_w; h = c_pad_h;
Call PAD;
Physical Surface("metal::1::CPLR::pad_top") = { sret };

cx = 0; cy = q_cy - (c_pad_h + c_pad_sep)/2; w = c_pad_w; h = c_pad_h;
Call PAD;
Physical Surface("metal::1::CPLR::pad_bot") = { sret };

x1 = 0; y1 = q_cy - c_pad_sep/2; x2 = 0; y2 = q_cy + c_pad_sep/2; width = jj_w;
Call JUNCTION;
Physical Surface("jj::1::CPLR::jj") = { sret };

// ---- 3) QB2 (right transmon) ----------------------------------------
cx = q_cx; cy = q_cy + (q_pad_h + q_pad_sep)/2; w = q_pad_w; h = q_pad_h;
Call PAD;
Physical Surface("metal::1::QB2::pad_top") = { sret };

cx = q_cx; cy = q_cy - (q_pad_h + q_pad_sep)/2; w = q_pad_w; h = q_pad_h;
Call PAD;
Physical Surface("metal::1::QB2::pad_bot") = { sret };

x1 = q_cx; y1 = q_cy - q_pad_sep/2; x2 = q_cx; y2 = q_cy + q_pad_sep/2;
width = jj_w;
Call JUNCTION;
Physical Surface("jj::1::QB2::jj") = { sret };

<<<<<<< Updated upstream
// ---- 4) Ground sheet with one merged vacuum pocket -------------------
=======
// ---- 4) Ground Sheet with Vacuum Pockets ----------------------------
// The real paper device is a coplanar layout: the coupling is through vacuum
// gaps between the three islands, not through a direct metal bridge. We keep
// that by carving one pocket around each island and leaving the inter-island
// separation open.
g_x0 = -760; g_y0 = -360; g_w = 1520; g_h = 720;
>>>>>>> Stashed changes
gs = news;
Rectangle(gs) = { g_x0, g_y0, 0, g_w, g_h };
sground = gs;

// One pocket per island = pad bbox inflated by (m_x, m_y).  Neighbouring
// pockets overlap by q_mx + c_mx − dx > 0, so the three carves merge into a
// single vacuum region with NO ground between qubit and coupler pads.
pkt_cx = -q_cx; pkt_cy = q_cy;
pkt_w = q_pad_w + 2*q_mx; pkt_h = 2*q_pad_h + q_pad_sep + 2*q_my;
Call GROUND_POCKET;
sground = sret;

pkt_cx = 0; pkt_cy = q_cy;
pkt_w = c_pad_w + 2*c_mx; pkt_h = 2*c_pad_h + c_pad_sep + 2*c_my;
Call GROUND_POCKET;
sground = sret;

pkt_cx = q_cx; pkt_cy = q_cy;
pkt_w = q_pad_w + 2*q_mx; pkt_h = 2*q_pad_h + q_pad_sep + 2*q_my;
Call GROUND_POCKET;
sground = sret;

<<<<<<< Updated upstream
Physical Surface("ground::1::chip::gnd") = { sground };
=======
Physical Surface("ground::1::chip::gnd") = { sret };
>>>>>>> Stashed changes
