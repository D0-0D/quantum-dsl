1. Gmsh DSL: (Yunkai Deng)
   1. Physical groups
   2. Mesh size control (distance, size ,dist min/max)
   3. Mesh structure, options
   4. Geo support directly plot
2. Full workflow(Yanming Huang)
   1. YAML (with only global configurations and simulations), YAML include Gmsh DSL (geometry)
      1. YAML defined a metal layer and a substrate layer; JJ automatically to another layer
   2. Unit unified with Geo file, (micrometer without unit)
   3. A unified naming convention for components
      1. Map between Geo name <-> Palace group name 
   4. Workflow: single entry point geo_build
3. Qubit To Palace (Yanming Huang) not finished yet
4. Palace Demo (Yanming Huang)
   1. YAML + Geo -> one transmon two metal pad, already works
   2. Output result yaml

Question:

Hui-hai: GDS should support multiple layers for fab (they may differ)

TODO:

1. Geo file is not good for template library (no physical information), require further design
2. Improve the YAML+Geo -> Palace interface with qubits