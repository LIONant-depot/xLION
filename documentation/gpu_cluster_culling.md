# GPU per-cluster culling (xGPU plan, step 4)

Goal: the main view's opaque rigid clusters are culled on the GPU - frustum, then occlusion against a Hi-Z pyramid made from the depth
prepass, in two passes so that nothing appears a frame late - and drawn with indirect draws, one per shared pipeline, geometry and
material. Agreed with Tomas on 2026-10-25: two-pass occlusion on the depth prepass (no inflated boxes), per-cluster local boxes
transformed per instance each frame, no normal-cone test (our clusters are big, up to 65K indices), vkCmdDrawIndexedIndirectCount,
bindless and XGPU_NO_BINDLESS, material overrides.

## What the others do

| Engine | Hi-Z | Occlusion passes | Visibility kept between frames | Shadows | Granularity |
|---|---|---|---|---|---|
| Unreal (Nanite, NaniteClusterCulling.usf) | HZB from the scene depth (HZB.usf), mip 0 is a power of two | Main pass against the previous frame's HZB (previous transforms), post pass against the new HZB for what main culled (`CULLING_PASS_OCCLUSION_POST`) | Implicit: the previous HZB | Virtual shadow maps, their own HZB per page | Instances, then a cluster hierarchy (persistent threads) |
| Bevy meshlets (cull_instances / cull_clusters, depth.rs) | Single-pass downsampling (SPD) with a min filter, up to 4096 | Early pass: last frame's visible set, build the pyramid, late pass: retest the rest | A previous-occlusion bitset per instance and meshlet | Frustum only for shadow views | Instances, then meshlets |
| Niagara (zeux, reference talk) | Min pyramid; mip 0 = the previous power of two of the screen, sampler reduction MIN | Two passes like Bevy | Per draw / per meshlet visibility bits | n/a | Draws, then meshlets |
| Wicked (wiRenderer.cpp OcclusionCulling_*) | none | GPU occlusion queries per object, read a frame late (pop on disocclusion) | Query results | Frustum only | Objects |
| Godot (renderer_scene_occlusion_cull.h) | CPU raster of occluder meshes (Embree) | One, on the CPU | none | Frustum only | Instances |
| o3de (RPI Culling.cpp) | CPU masked occlusion (Intel MOC) | One, on the CPU | none | Frustum only | Objects |

What they agree on: the occlusion test is a projected box against a min-depth pyramid, sampling the mip where the box covers
about 2x2 texels; "inside the box" (near plane crossed) is always visible; shadows are frustum-culled only (the camera's Hi-Z says
nothing about a light's view); a camera cut costs one slow frame (pass 1 draws little, pass 2 finds the rest) instead of a pop.

## Our pick

| Choice | Pick | Why |
|---|---|---|
| Passes | Two: (1) clusters visible last frame, frustum-tested, into the depth prepass; Hi-Z from it; (2) every other frustum-visible cluster tested against the Hi-Z, the visible ones into the prepass too; then the shading pass draws both lists | The agreed rule: nothing a frame late. Our depth prepass already exists; the shading pass reads its depth (LESS_EQUAL) |
| Hi-Z | Min (far) depth pyramid of the prepass depth, mip 0 = previous power of two of the view (Niagara), one compute pass per mip at first (SPD later if it shows) | Simple, robust for non-power-of-two views; reversed-Z aware (conservative = the farthest depth) |
| Test | The cluster's local box through local-to-clip (8 corners), screen rectangle and nearest depth; inside the near plane: visible; 4 samples of the mip where the rectangle is 2x2 texels | zeux's approximate projected bounds, Bevy's project_aabb |
| Visibility between frames | One bit per (instance slot, cluster): instance slots are already persistent (instance_slots), each gets a cluster range | Moving and dynamic objects keep their bits; a new instance starts "not visible": pass 2 draws it the first frame |
| Granularity | Instance frustum test, then clusters (one thread per cluster of a visible instance) | Many small dynamic objects (Tomas's game case) are rejected whole |
| Draws | Per (pipeline, geometry, material) a run of VkDrawIndexedIndirectCommand plus a record (cluster, slot, GI, material base) per draw; the vertex shader's XLION_RECORDS variant reads the record by its first instance; vkCmdDrawIndexedIndirectCount with a GPU count | Material fragment shaders only read the material base from push constants: set once per run - no material recompile |
| Shadows, reflections, GI | Unchanged for now (CPU path); shadows are frustum-only later | The camera's Hi-Z is not theirs |
| Fallback | XLION_NO_GPU_CULL=1: today's CPU path; also used for blended, masked, double sided, skinned, the frame-budget boxes mode | Same pictures, measurable |
| Debug | Stats (tested, frustum-culled, occluded, drawn per pass), a freeze-culling toggle, a view of the culled clusters | |

## Our constraints

- Cluster bounds: already compiled (cluster_geom::cluster::m_BBox, local); uploaded once per geometry - no recompile.
- GI: the GI capture and the surfel passes draw their own clusters (unchanged); the GI screen pass already uses records and
  DrawIndexedIndirect - the same record layout.
- Editor picking: a CPU ray against the entities' boxes (not the draw lists); selection outline: its own pass. Unchanged.
- Material overrides: an override material is another material id with the same pipeline: another run (bindless: no extra binds).
- Skinned geometry (later): a cluster's box moves with the bones - a bound per bone or a pose-inflated box; noted, not solved here
  (skinned draws stay on the CPU path).

## As built (milestones a and b)

- `features/cull/xlionrender_gpu_cull.h` and `shaders/xlionrender_cull_comp.glsl`. Each frame the CPU writes one 96-byte candidate per
  opaque rigid cluster of the visible draws: its run, its prepass run, its draw command, its record, and its local box. It also writes
  each draw's local-to-clip matrix (W2C x ToEye x L2W). The compute pass tests the box against the six clip planes (centre plus the
  absolute half axes, no 8-corner loop) and appends a command and a record to the cluster's run and to its prepass run. Milestone a's
  persistent cluster-box buffer was not needed: the boxes ride in the candidates. ponytail: the candidates are rebuilt every frame on
  the CPU; cache them per draw if the CPU time shows up.
- Runs are keyed by (records pipeline instance, material, geometry, GI buffer); prepass runs are keyed by geometry. The scene pass
  draws them sorted by bind state and binds a shared state once (texture-table materials of one pipeline: one bind, then the table
  and the material base).
- The records path is a fourth material pipeline path (`instance::records_path_v`, `getRecordsInstance`): the rigid vertex shader's
  XLION_RECORDS variant plus binding 12. The prepass uses the GI screen pass's depth pipeline, which already reads records.
- `instance::m_bGPUCull` (runtime) and XLION_NO_GPU_CULL=1 select the CPU path; `getCullStats()` reports candidates, runs and, read
  back three frames later, the clusters kept (shaded, prepass).
- Left on the CPU path (the depth prepass's own test): blended, double-sided, wireframe, no depth write or test, the constant material (no material),
  skinned meshes, the editor's frame-budget and boxes-only modes, every view other than the main one.
- Test: xlionrender_test_culling's field of cluster spheres. With the draws' own culling off, the GPU cull's image matches the CPU
  path's exactly, and it keeps exactly the spheres in the view.

## Milestones

a) Cluster boxes and the instance/cluster buffers on the GPU. b) Frustum culling and indirect draws per run (pass 1 only, no
occlusion). c) Hi-Z and the two passes. d) Stats, debug view, freeze, XLION_NO_GPU_CULL. Each: ctest in the 3 modes, render_smoke,
committed locally.
