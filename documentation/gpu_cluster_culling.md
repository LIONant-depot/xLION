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

## As built (milestones c and d)

- Occlusion, two passes: `gpu_cull::Cull` (mode 0) keeps the clusters in the view that were visible last frame. The scene pass
  lays their depth (with the CPU path's prepass) and ends. `gpu_cull::Occlude` builds the Hi-Z pyramid
  in one dispatch straight from the depth texture (`xlionrender_hiz_comp.glsl`, in the manner of AMD's single pass downsampler: no
  copy, level 0 at half the view's size, a work group's 128 x 128 pixels to levels 0-6 through shared memory, the last group - an
  atomic counter - the levels past 6; the farthest depth of 2x2, sizes rounded up so a texel of level L covers 2^(L+1) pixels; no
  subgroup operations, so no fallback is needed; xGPU compute can now sample textures: `compute::setup::m_nTextures`), and tests
  every cluster in the view against it (mode 1). The test takes the box's 8 corners to the screen and compares the nearest depth with the farthest Hi-Z
  depth, at the level where the box covers at most 2x2 texels; a box crossing the near plane is visible. Mode 1 writes the
  visibility for the next frame, and the visible clusters that pass 1 did not draw go into pass 2's lists. The scene pass is loaded
  again (`render_view::m_ScenePassLoad`): pass 2's depth, then the shading of both passes' lists.
- Visibility: one uint per (instance slot, cluster), with a range per slot kept while the slot keeps its cluster count. When the
  1M entries are used up, everything starts again (one frame mostly in pass 2). Visibility only picks the pass that draws a cluster;
  it never changes the picture.
- The editor's frame budget (on by default) and GPU culling work together: the GPU culls the clusters the budget keeps. Only the
  boxes-only view stays on the CPU path.
- Freeze (`instance::m_bFreezeCull`): no cull, no Hi-Z; the last cull's lists are drawn again (both passes' lists) from wherever the
  camera goes, so what was culled shows as missing. Ignored when the scene's runs change.
- Editor: the Level editor's toolbar has Cull, Occl and Freeze (`xeditor::mesh_budget::CullButtons`; `view_options` m_bNoGPUCull,
  m_bNoGPUOcclusion, m_bFreezeCull; xRenderEditor version 12). Their hints and `DescribeScene` give the GPUCull numbers:
  candidates, runs, clusters drawn (prepass, pass 2) and triangles shaded, read back three frames late.
- Adaptive occlusion (`gpu_cull::WantOcclusion`): when it hides under 10% of what pass 2 tests for 30 frames in a row, it is skipped for
  120 frames (pass 1 then draws every cluster in the view - never a pop); the share is of triangles, not clusters, then tried again; a camera cut (2 m, 45 degrees) tries it
  at once. Stats: OcclusionSkipped, OccludedShare; GPU times of pass 1's cull and of the pyramid + pass 2 (XLION_GPU_TIMES: CULLGPU).
- Switches: XLION_NO_GPU_CULL=1 (the CPU path), XLION_NO_GPU_OCCLUSION=1 (the frustum only).
- Tests (xlionrender_test_culling): an occluder sphere in front of the field. With the camera moving, every one of 12 frames
  matches the CPU path's picture exactly: nothing appears a frame late. With the camera still, 12 clusters are drawn against 30 for
  the frustum alone, and pass 2 draws nothing. Also covered: the triangle count, the frame budget, and freeze.

## Measured (2026-10-26, Debug editor maximized 3778x1600, no validation, no frame budget, nothing compiling)

GPU = shadows + scene (cull, pyramid, both passes) + tone map, ms (XLION_GPU_TIMES). Paths: GPU culling with occlusion, the CPU path
(XLION_NO_GPU_CULL), GPU culling frustum only (XLION_NO_GPU_OCCLUSION).

| View | GPU: occlusion / CPU path / frustum | pyramid + pass 2 | CPU scene pass: occlusion / CPU path | Triangles shaded: occlusion / frustum | CPU draws |
|---|---|---|---|---|---|
| Police level (inside) | 0.88 / 0.85 / 0.86 | adaptive: skipped (hides 3%) | 0.69 / 0.55 | 74k-167k / 167k | 2 / 57 |
| Bistro preview (outside) | 0.94 / 1.04 / 1.08 | 0.062 | 0.72 / 0.84 | 1.73M / 2.02M (588 / 2140 clusters) | 176 / 2316 |
| Bistro preview (street) | 1.16 / 1.28 / 1.05 | 0.074 | 0.71 / 0.77 | 726k / 768k (344 / 939 clusters) | 176 / 2316 |

The GPU path is within noise of the CPU path on Police and 0.10-0.12 ms faster on the Bistro. Occlusion pays where what it hides is big
(outside: -0.14 ms against the frustum only) and costs ~0.1 ms where it hides many small clusters (street: 63% of the clusters, 5% of
the triangles). The adaptive rule now uses the share of triangles hidden: re-measured, the street view skips occlusion (it hides 5%):
GPU 0.99 ms against 1.16 frustum only and 1.24 the CPU path; from outside it stays on (14%): 1.08 against 1.13 frustum only, the CPU
path 0.89 in that run (1.04 in the one before) - run-to-run noise is about 0.15 ms: single runs decide nothing finer. The 176 CPU
draws: the Bistro's blended and double-sided parts.

## Benchmark (smoke/bench_cull.py: 3 launches x 7 samples of 120-frame means each, compile-idle checked, switches interleaved)

GPU ms = shadows + scene + tone map; CPU = the scene pass's CPU time (Debug, maximized 3778x1600, no validation).

| View | Switch | GPU ms median (min-max) | CPU scene pass ms median (min-max) | launches kept |
|---|---|---|---|---|
| police | gpu | 0.960 (0.930-1.000) | 0.640 (0.610-0.720) | 3 of 3 |
| police | frustum | 0.870 (0.840-0.890) | 0.620 (0.590-0.700) | 3 of 3 |
| police | cpu | 0.860 (0.830-0.900) | 0.520 (0.490-0.700) | 3 of 3 |
| bistro | gpu | 0.960 (0.910-1.060) | 0.720 (0.700-0.800) | 3 of 3 |
| bistro | frustum | 0.990 (0.920-1.050) | 0.710 (0.680-0.830) | 3 of 3 |
| bistro | cpu | 0.890 (0.840-1.030) | 0.740 (0.720-0.830) | 3 of 3 |
| bistro_street | gpu | 0.840 (0.670-0.940) | 0.720 (0.680-1.070) | 3 of 3 |
| bistro_street | frustum | 0.870 (0.690-0.920) | 0.710 (0.690-0.740) | 3 of 3 |
| bistro_street | cpu | 0.850 (0.810-1.070) | 0.750 (0.710-0.910) | 3 of 3 |

Beyond noise: Police with occlusion, +0.10 ms over the CPU path (every sample) - the pyramid and the split pass cost more than hiding 56% of
its 167k cheap triangles saves (frustum only = the CPU path); and the Bistro from outside frustum only, +0.10 ms (84% of the sample pairs)
- on the shading side (0.14 ms with the prepass off). Not the cause: the cull (0.018 ms), the draws' order inside a run (an ordered
variant changed nothing), the record read per vertex (gl_BaseInstance changed nothing) - both experiments reverted. Open: a GPU profile.
The Bistro street view: all three paths equal.

## Benchmark in Release (2026-10-26: validation off by default in Release; the view-size rule)

The adaptive occlusion also skips a view of under 500k triangles in the frustum (`instance::m_GPUOcclusionMinTriangles`): the pyramid and
pass 2 cost more than hiding part of so few triangles saves. Police then equals the CPU path.

| View | Switch | GPU ms median (min-max) | CPU scene pass ms median (min-max) | prepass / rest of the scene pass, GPU ms | launches kept |
|---|---|---|---|---|---|
| police | gpu | 0.880 (0.870-0.920) | 0.130 (0.110-0.200) | 0.016 / 0.423 | 3 of 3 |
| police | frustum | 0.880 (0.860-0.900) | 0.120 (0.110-0.220) | 0.016 / 0.425 | 3 of 3 |
| police | cpu | 0.880 (0.860-0.910) | 0.110 (0.090-0.140) | 0.014 / 0.440 | 3 of 3 |
| bistro | gpu | 0.860 (0.840-0.910) | 0.170 (0.140-0.270) | 0.139 / 0.509 | 3 of 3 |
| bistro | frustum | 0.860 (0.840-0.940) | 0.140 (0.130-0.230) | 0.160 / 0.480 | 3 of 3 |
| bistro | cpu | 0.780 (0.740-0.830) | 0.470 (0.270-0.590) | 0.146 / 0.403 | 3 of 3 |
| bistro_street | gpu | 0.620 (0.600-0.640) | 0.130 (0.130-0.200) | 0.036 / 0.364 | 3 of 3 |
| bistro_street | frustum | 0.610 (0.590-0.630) | 0.130 (0.130-0.160) | 0.036 / 0.355 | 3 of 3 |
| bistro_street | cpu | 0.780 (0.760-0.810) | 0.280 (0.260-0.410) | 0.120 / 0.455 | 3 of 3 |

Beyond noise: only the Bistro from outside, +0.08 ms (every sample), all of it in the shading part of the scene pass. The prepass is
equal, so not the per-draw cost of indirect draws or the record read in the vertex shader; not the order inside a run (an ordered
variant measured the same in Release); not the cull (0.018 ms). Open: the order across runs and the hardware's coarse depth test, or the
records pipelines themselves - it needs a GPU frame profiler (Nsight Graphics or RenderDoc: neither is installed). The street view: the
GPU path is 0.16 ms faster; the CPU scene pass is half the CPU path's on the Bistro. SCENESPLIT (XLION_GPU_TIMES): the scene pass's
prepass and the rest, per 120 frames.

## Milestones

a) Cluster boxes and the instance/cluster buffers on the GPU. b) Frustum culling and indirect draws per run (pass 1 only, no
occlusion). c) Hi-Z and the two passes. d) Stats, debug view, freeze, XLION_NO_GPU_CULL. Each: ctest in the 3 modes, render_smoke,
committed locally.
