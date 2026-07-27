// =====================================================================
// sung_2021_device.geo 
// Native Gmsh .geo representing the 3-body tunable coupler device 
// from Sung et al., Phys. Rev. X 11, 021058 (2021).
// =====================================================================

SetFactory("OpenCASCADE");
Include "qlib.geo";

// ---- Device Geometry Parameters (µm) --------------------------------
// Placements
q1_cx   = -300;   // QB1 center X
c_cx    = 0;      // CPLR center X
q2_cx   = 300;    // QB2 center X
q_cy    = 0;      // Global center Y

// Transmon dimensions
pad_w   = 120;    // Qubit pad width
pad_h   = 80;     // Qubit pad height
c_pad_w = 160;    // Coupler pad width (larger for Cc = 228 fF)
c_pad_h = 120;    // Coupler pad height
pad_sep = 30;     // Gap between top and bottom pads
jj_w    = 2;      // JJ width
pkt_gap = 25;     // Vacuum gap surrounding the islands

// ---- 1) QB1 (Left Transmon) -----------------------------------------
cx = q1_cx; cy = q_cy + (pad_h + pad_sep)/2; w = pad_w; h = pad_h;
Call PAD;
Physical Surface("metal::1::QB1::pad_top") = { sret };

cx = q1_cx; cy = q_cy - (pad_h + pad_sep)/2; w = pad_w; h = pad_h;
Call PAD;
Physical Surface("metal::1::QB1::pad_bot") = { sret };

x1 = q1_cx; y1 = q_cy - pad_sep/2; x2 = q1_cx; y2 = q_cy + pad_sep/2; width = jj_w;
Call JUNCTION;
Physical Surface("jj::1::QB1::jj") = { sret };

// ---- 2) CPLR (Center Tunable Coupler) -------------------------------
cx = c_cx; cy = q_cy + (c_pad_h + pad_sep)/2; w = c_pad_w; h = c_pad_h;
Call PAD;
Physical Surface("metal::1::CPLR::pad_top") = { sret };

cx = c_cx; cy = q_cy - (c_pad_h + pad_sep)/2; w = c_pad_w; h = c_pad_h;
Call PAD;
Physical Surface("metal::1::CPLR::pad_bot") = { sret };

x1 = c_cx; y1 = q_cy - pad_sep/2; x2 = c_cx; y2 = q_cy + pad_sep/2; width = jj_w;
Call JUNCTION;
Physical Surface("jj::1::CPLR::jj") = { sret };

// ---- 3) QB2 (Right Transmon) ----------------------------------------
cx = q2_cx; cy = q_cy + (pad_h + pad_sep)/2; w = pad_w; h = pad_h;
Call PAD;
Physical Surface("metal::1::QB2::pad_top") = { sret };

cx = q2_cx; cy = q_cy - (pad_h + pad_sep)/2; w = pad_w; h = pad_h;
Call PAD;
Physical Surface("metal::1::QB2::pad_bot") = { sret };

x1 = q2_cx; y1 = q_cy - pad_sep/2; x2 = q2_cx; y2 = q_cy + pad_sep/2; width = jj_w;
Call JUNCTION;
Physical Surface("jj::1::QB2::jj") = { sret };

// ---- 4) Ground Sheet with Vacuum Pockets and Coupling Trenches ------
g_x0 = -600; g_y0 = -300; g_w = 1200; g_h = 600;
gs = news;
Rectangle(gs) = { g_x0, g_y0, 0, g_w, g_h };
sground = gs;

// Carve pockets around each island
pkt_cx = q1_cx; pkt_cy = q_cy; pkt_w = pad_w + 2*pkt_gap; pkt_h = 2*pad_h + pad_sep + 2*pkt_gap;
Call GROUND_POCKET;
sground = sret;

pkt_cx = c_cx; pkt_cy = q_cy; pkt_w = c_pad_w + 2*pkt_gap; pkt_h = 2*c_pad_h + pad_sep + 2*pkt_gap;
Call GROUND_POCKET;
sground = sret;

pkt_cx = q2_cx; pkt_cy = q_cy; pkt_w = pad_w + 2*pkt_gap; pkt_h = 2*pad_h + pad_sep + 2*pkt_gap;
Call GROUND_POCKET;
sground = sret;

// Carve vacuum coupling trenches between QB1 <-> CPLR and CPLR <-> QB2 
// (These permit the capacitive interactions C_1c and C_2c)
gx1 = q1_cx + pad_w/2; gy1 = q_cy; gx2 = c_cx - c_pad_w/2; gy2 = q_cy; gw = pad_h;
Call GROUND_CUTOUT;
sground = sret;

gx1 = c_cx + c_pad_w/2; gy1 = q_cy; gx2 = q2_cx - pad_w/2; gy2 = q_cy; gw = pad_h;
Call GROUND_CUTOUT;
sground = sret;

Physical Surface("ground::1::chip::gnd") = { sret };