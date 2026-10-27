# Lighting P3: the tail's reconstruction (design note, 2026-10-27 - decided: "The decision" below; being built)

`lighting_strategy.md` P3: "`EvaluateDirectAtReceivers`; screen trace (blocked-only); short-history denoiser; the global preparation
budget" - gate: "key lights shadowed by pages, tail contact-shadowed; reconstruction error separate". Nothing here is built; two of
its choices change every material and the frame's memory, so they are Tomas's (sec. "Decisions").

## Where we stand

- **SAMPLED** (head exact + a sampled tail) is unbiased. Since 2026-10-27 its tail is resampled per pixel: 8 candidates weighed by
  their unshadowed contribution and their one-tap visibility, one shaded (RIS). Per-frame relative error: the dense lab 0.41, lights
  behind a wall 0.26, the glossy floor's highlights 0.021 (`R/tests/xlionrender_test_light_lab.cpp`).
- **CELLS** (every light that reaches the cell, exact) is the default: on the stress city's street SAMPLED costs the same (1.50 ms
  both), so today nothing pays for a denoiser. It pays when a cell holds many more lights than the head (dense light rigs: hundreds of
  lights in reach of a pixel), where CELLS' cost grows with the list and SAMPLED's does not.
- No history buffers or motion vectors exist outside the GI's screen pass (camera reprojection only:
  `R/shaders/xlionrender_gi_screen_frag.glsl`, `render_view::m_GIScreenPrevW2C`).

## The competitor (read in E:\source_code, 2026-10-27)

**Unreal MegaLights** (`Engine/Shaders/Private/MegaLights/*`, `Renderer/Private/MegaLights/MegaLightsDenoising.cpp`) - deferred:
- Samples per *downsampled* pixel (`r.MegaLights.NumSamplesPerPixel` 4, half resolution), visibility traced per sample (VSM marching
  or hardware rays), a light-power and visible-light-hash history to guide the next frame's selection.
- **Temporal** (`MegaLightsDenoiserTemporal.usf`): diffuse and specular lighting histories (separate targets, the scene's format:
  RGBA16F or R11G11B10), lighting moments (RGBA16F), frames accumulated (R8, up to `Temporal.MaxFramesAccumulated` 12), a depth
  history for rejection, a neighbourhood clamp (scale 1).
- **Spatial** (`MegaLightsDenoiserSpatial.usf`): `Spatial.NumSamples` 4 in `Spatial.KernelRadius` 8 px, depth-weighted, stronger for
  `MaxDisocclusionFrames` 2 after a disocclusion, driven by the history's variance.
- Lighting is demodulated (divided by albedo / specular albedo) before denoising and remodulated after - textures survive the filter.

GigaLights (`E:\source_code\gigalights`, learning only, never copied) also ships a separate denoiser package; AMD Capsaicin's GI-1.0
denoises its own GI, not direct lights.

## What changes for us (forward renderer)

The MegaLights model needs per-pixel inputs a forward renderer does not keep (normal, roughness, albedo after the shading). Two ways:

| | A: tail in its own targets, a denoise pass (MegaLights' shape) | B: temporal reuse inside the material (no new pass) |
|---|---|---|
| Material change | Every lit material writes 2 more targets: the tail's diffuse and specular, demodulated; plus normal/roughness for the spatial weights (a 4th target, or reuse the depth prepass) | Every lit material reads last frame's tail target at its reprojected position and writes this frame's (1-2 targets) |
| Passes | Temporal + spatial compute after the scene pass, then a composite (final = scene without tail + denoised tail x albedo) | None (a blend in the shader); spatial: none, or a cheap 3x3 in the composite |
| Quality | MegaLights-grade (variance-guided spatial, disocclusion handling) | Temporal only: ghosting on disocclusion, slower convergence where history is lost |
| Risk | The forward pass gains MRT outputs and a composite: blended materials need a rule (sec. 8: they keep full-cell shading, never the denoised tail) | Simpler; reading and writing the same history needs ping-pong targets |

**Motion:** camera reprojection from depth first (static scenes, a moving camera - the GI's screen pass does it); moving objects need
a velocity target (per-instance previous transforms: the instance slots hold them for one frame only today) - without it, a moving
object's tail ghosts until the history clamp drops it.

## Memory and cost (estimates, 3093 x 1493 = 4.6 M pixels, Tomas's Bistro view)

| Target | Format | Full resolution | Half resolution (MegaLights' default) |
|---|---|---|---|
| Tail diffuse + specular (this frame) | 2 x RGBA16F | 74 MB | 18 MB |
| Their histories | 2 x RGBA16F | 74 MB | 18 MB |
| Moments | RGBA16F | 37 MB | 9 MB |
| Frames accumulated | R8 | 5 MB | 1 MB |
| Depth history (rejection) | R32F | 18 MB | 5 MB |
| Normal + roughness (A only) | RGB10A2 | 18 MB | 5 MB |
| Velocity (moving objects) | RG16F | 18 MB | 5 MB |
| **Total** | | **~245 MB** | **~61 MB** |

GPU time: not estimated from others' numbers - measured in the ledger's "reconstruction" row once a prototype exists (the work per
pixel: a temporal pass reading ~4 history texels and a spatial pass of 4 samples, at a quarter of the pixels). Shading would also change: the tail sampled at
half resolution (1 sample per 2x2) cuts its cost about 4x.

## The evidence: the dense many-light rig (2026-10-27)

`R/tools/bench_many_lights/xlionrender_bench_many_lights.cpp` (xLIONRender 957dd8a - `Build/test/vs2022/Release/xlionrender_bench_many_lights.exe`):
a 30 x 30 m night market street, walls, stalls and pillars; 75% string lights (2-3 m reach, dim), 20% neon (4-6 m), 5% torches (6-8 m,
the first 32 shadowed). GPU scene pass ms (mean of 60 warmed frames); SAMPLED's per-frame error against CELLS (mean |a - b| / mean b);
`*`: the cell buffer was full and the whole render fell back to EXACT.

| View | Lights | Overflow cells | CPU cell build | CELLS | SAMPLED plain | resampled | resampled + visibility | error plain | error resampled |
|---|---|---|---|---|---|---|---|---|---|
| 1920x1080 | 64 | 0 | 0.15 | 0.19 | 0.20 | 0.22 | 0.22 | 0.057 | 0.011 |
| 1920x1080 | 256 | 0 | 0.48 | 0.50 | 0.59 | 0.71 | 0.72 | 0.310 | 0.115 |
| 1920x1080 | 1024 | 12 | 1.80 | 1.87 | **1.33** | 2.44 | 2.51 | 0.645 | 0.302 |
| 1920x1080 | 2048 | 66 | 3.67 | 5.66 | **4.40** | 6.03 | 6.12 | 0.737 | 0.290 |
| 1920x1080 | 4096 | 0 | 6.99 | 47.9* | 48.0* | 48.2* | 48.1* | - | - |
| 3093x1493 | 64 | 0 | 0.16 | 0.37 | 0.41 | 0.44 | 0.69 | 0.055 | 0.010 |
| 3093x1493 | 256 | 0 | 0.50 | 1.29 | **1.21** | 1.43 | 1.46 | 0.332 | 0.110 |
| 3093x1493 | 1024 | 12 | 1.85 | 3.86 | **2.89** | 5.27 | 5.42 | 0.653 | 0.307 |
| 3093x1493 | 2048 | 66 | 3.73 | 10.86 | **7.82** | 12.03 | 12.22 | 0.762 | 0.303 |
| 3093x1493 | 4096 | 0 | 7.17 | 104.7* | 104.7* | 104.7* | 104.6* | - | - |

What it says:
- **SAMPLED beats CELLS only with the plain tail samples, from ~1000 lights in reach** (1024: 1.87 -> 1.33 ms at 1080p, 3.86 -> 2.89 at
  4.6 MP; 2048: -22% / -28%), and then its per-frame error is 65-76%: unusable without the denoiser. The resampled tail (error 29-31%)
  costs more than CELLS at every density: its 8 candidates are each a full light evaluation, and every SAMPLED variant still walks the
  cell's whole list for its cumulative probabilities (O(n) reads, the same order as CELLS' loop).
- **The lists' cost grows linearly** (CELLS 0.50 -> 1.87 -> 5.66 ms at 256 / 1024 / 2048 lights, 1080p), and so does the **CPU cell
  build** (0.48 -> 1.80 -> 3.67 -> 7.0 ms): at game densities the CPU build is as large as the shading.
- **At 4096 lights the cell buffer overflows and the whole render falls back to EXACT** (48 ms at 1080p, 105 ms at 4.6 MP).
- The visibility in the resampling weights changes nothing here (the shadowed torches land in the heads); it pays behind walls
  (the lab: 0.41 -> 0.26).

### After the fixes (2026-10-27)

**1. No overflow** (xLIONRender 9abc3bf): 2-uint cell headers (a cell never shades every light) and a cell ring that grows (no EXACT
fallback; 6.5 MB at first, 9 MB at 4096 lights on the big view). **2. The tail's samples by binary search** (9fc94ea): bitwise the same
images. GPU scene ms, 1920x1080 / 3093x1493:

| Lights | CELLS | SAMPLED plain | resampled | resampled + visibility | error plain / resampled |
|---|---|---|---|---|---|
| 64 | 0.18 / 1.00 | 0.17 / 0.39 | 0.23 / 0.49 | 0.23 / 0.50 | 0.057 / 0.011 |
| 256 | 0.50 / 1.21 | 0.31 / 0.50 | 0.81 / 1.15 | 0.88 / 1.62 | 0.31 / 0.115 |
| 1024 | 2.42 / 3.82 | **0.27 / 0.57** | **0.69 / 1.48** | **0.75 / 1.99** | 0.65 / 0.30 |
| 2048 | 3.78 / 7.81 | **0.30 / 0.60** | **1.15 / 2.71** | **1.81 / 3.65** | 0.78 / 0.31 |
| 4096 | 6.95 / 14.78 | **0.34 / 0.84** | **2.56 / 5.47** | **3.21 / 4.57** | 0.88 / 0.40 |

**Where SAMPLED wins now:** the plain tail from 64 lights up (flat: 0.3 ms at 1080p whatever the density, but 30-90% noise per frame);
the resampled tail from ~1000 lights in reach (3.5x faster than CELLS at 1024, 2.7x at 4096; 30-40% noise per frame). Below ~500
lights CELLS (exact) is as fast or faster. The CPU cell build (0.5 - 7 ms) is now the largest cost at high densities: change 3 (the GPU
build) is next. A denoiser would turn the resampled tail's 30-40% into a usable image; it pays from ~1000 lights in reach.

**3. The cells built on the GPU** (`R/shaders/xlionrender_light_cells_comp.glsl`, default `m_bLightCellsGPU`): a count pass (a thread a
cell, a workgroup a 4^3 block; each 64-light chunk's ranges and lights in shared memory, the lights whose range misses the block
skipped), a scan, a fill that also keeps the cell's head and the tail's largest in registers, then the head/tail split in two passes. It
runs in a device-local scratch (the cell ring is host memory: the first version, built in place, took 4.2 ms for 256 lights) and is
copied into the ring; the CPU keeps the windows, an upper bound of the entries (for the ring's size) and the probes' boxes (0.004 -
0.2 ms). Measured against the CPU's Build in `R/tests/xlionrender_test_light_lab.cpp` (256 lights, 30% spots): the same counts, heads and
light order in every cell; CELLS' image bitwise; the tail's cumulative probabilities within 7.6e-6 (gate 5e-5: the GPU's sqrt and
division are not correctly rounded, and the tail is summed from its end) - a few stratified samples pick the neighbouring light, so
SAMPLED's images moved by ~10-20 values an image (saved images refreshed: `Build/lighting_baseline/f_gpu_cells`). **Both builders now
skip the hidden cells**: a coarse level's cell that the finer window covers is never read (the shader shades with the finest level
holding the point) - those were the cells next to the camera where every light reaches (a power of two cell size only: the levels'
floors then nest exactly). The CPU's Build went 6.9 -> 5.8 ms at 4096 lights from that alone.

| Lights | CPU Build | GPU build CELLS / SAMPLED | CELLS | SAMPLED plain | resampled | resampled + visibility |
|---|---|---|---|---|---|---|
| 64 | 0.13 | 0.12 / 0.13 | 0.18 / 0.36 | 0.17 / 0.34 | 0.23 / 0.47 | 0.23 / 0.52 |
| 256 | 0.44 | 0.17 / 0.20 | 0.50 / 1.29 | 0.22 / 0.50 | 0.52 / 1.15 | 0.54 / 1.17 |
| 1024 | 1.52 | 0.33 / 0.45 | 1.81 / 3.82 | **0.25 / 0.56** | **0.66 / 1.47** | **0.68 / 1.51** |
| 2048 | 2.91 | 0.56 / 0.74 | 3.69 / 7.83 | **0.26 / 0.59** | **0.71 / 1.59** | **0.73 / 1.63** |
| 4096 | 5.80 | 0.97 / 1.33 | 6.96 / 14.91 | **0.28 / 0.64** | **0.78 / 1.76** | **0.81 / 1.81** |

(ms; the scene pass at 1920x1080 / 3093x1493; the build's GPU time is the same at both sizes. The errors are unchanged: 0.06 - 0.88
plain, 0.01 - 0.39 resampled.) SAMPLED's scene pass is faster than the table above shows at the same lists: with the CPU's build (`--cpu
1`) the resampled tail at 4096 lights costs 1.19 / 3.49 ms, 2.23 / 4.64 with visibility, against 0.78 / 1.76 and 0.81 / 1.81 here; CELLS
is unchanged (6.95). The likely cause - not isolated - is the GPU's clock: it idled while the CPU built 7-10 ms a frame. **Where SAMPLED
wins now:** resampled with visibility, from ~300 lights in reach (256: 0.54 against 0.50 at 1080p, 1.17 against 1.29 big; 1080p: 0.68 against 1.81 ms at 1024, 0.81 against 6.96 at 4096 - 8.6x);
its cost grows ~20% from 1024 to 4096 lights. With the GPU build at 4096 lights a frame's cells cost 1.33 ms of GPU and 0.2 ms of CPU
(was 5.8 - 7 ms of CPU). Next (none built): the build is latency bound - a thread walks every light of its block in series, with 640
warps on the GPU; a light-parallel count and fill or dirty cells would cut it further.

Before these fixes, three pipeline changes would (each its own decision, none built): **the tail's candidates by binary search**
of the cumulative probabilities (O(log n), not the list walk); **the cells built on the GPU** (P2's plan: the CPU build is linear); **a
larger or adaptive cell buffer** (no EXACT fallback at 4096 lights). With those, SAMPLED's cost stops growing with the density and the
denoiser turns its noise into a usable image.

## Recommendation

1. Keep CELLS the default until a scene shows lists long enough for SAMPLED to pay (measure: the ledger's direct-shading row, CELLS vs
   SAMPLED, on Tomas's densest light rig).
2. When it pays: **A at half resolution, camera reprojection first** (~61 MB at 4.6 M pixels), demodulated, temporal (12 frames, clamp)
   then spatial (4 samples, depth weighted); velocity for moving objects second.
3. The screen trace (contact shadows for the tail's unshadowed lights) after A: it reads the same depth.

## The decision (2026-10-27)

Tomas: build the denoiser (option A, half resolution), and "the right thing even if it requires more work at front" - the most
competitive, simple and expandable shape, not the cheapest. Reviewed with Fable (the four shapes: material MRT outputs, stores from the
material, last frame's result read by the material, a screen pass) and the coordinator. **Built: a half-resolution thin G-buffer, the
tail shaded and denoised in screen space, the material remodulating it.** Both the tail's diffuse and its specular are denoised (as
MegaLights does); the same screen data serves the GI, reflections and AO later.

1. **The thin G-buffer** (half resolution): every lit draw that is not blended - opaque, masked, double sided, skinned - drawn again into
   a half-size pass with its material's **G-buffer variant**: the xmaterial compiler compiles every material once more with
   `XLION_GBUFFER_OUTPUT` (data_file v7: plain and bindless, as the bindless HDR variant was added in v5), where `PBRLighting`
   (`R/shaders/mb_standard_pbr.frag`, which every lit material includes) returns the surface's octahedral normal and roughness and no
   lighting code is compiled in - the material's own code writes it as its color, a masked material discards in it. A material that does
   not include `mb_standard_pbr.frag` (unlit) has no such output and is left out. The variant serves the later attribute passes too
   (velocity, the GI's material capture). Its own depth. **Measured against writing the G-buffer from the depth prepass** (Release,
   maximized, `XLION_GPU_TIMES`: SCENESPLIT, SCREENSPLIT): the full-resolution depth prepass costs 0.088 ms on Bistro (0.017 Police),
   the GI's half-size depth redraw of the same clusters 0.076 ms (0.012) - a second geometry submission is cheap; the prepass route would
   evaluate the materials' normal and roughness for 4x the pixels (and its overdraw), keep ~37 MB of full-resolution targets, turn the
   prepass's one depth pipeline a geometry run into a material's, and change the exact path (masked, double sided and skinned are not
   prepassed today). Rejected also: new material outputs in the main pass (MRT: xGPU's independent blending, every material's outputs,
   unlit and blended materials' different sets) and stores from the material (no early depth test with `discard`).
2. **The tail screen pass** (half resolution, a full-screen pass with the materials' pipeline layout, so `xlionrender_local_lights.glsl`
   is shared, not copied): per pixel the world position from the G-buffer's depth, the normal and roughness from it; the cell's tail
   resampled (RIS with visibility, the head left out) and shaded **demodulated**: diffuse with albedo 1, specular with F = 1 - the
   material multiplies its own terms back, so nothing is divided (no fireflies on black or metal surfaces). Two targets: diffuse, specular.
3. **The denoiser** (compute, half resolution), MegaLights' shape: temporal - last frame's result reprojected by the camera (and by the
   movers' motion, the second step), rejected by distance and normal against last frame's records ("Built" below), clamped to the current neighbourhood,
   up to 12 frames accumulated -, then spatial - 4 taps weighted by depth, normal and roughness, wider where the history is short (a
   disocclusion). Specular's history is shorter where the surface is glossy (its lobe moves with the view).
4. **The material** (the main pass): with the screen tail on, the head is shaded exactly as before; the tail is the denoised result,
   upsampled from the 4 half-resolution texels around the pixel weighted by depth and normal (as the GI's screen read), times its own
   diffuse and specular terms. A pixel no half-resolution texel matches (a silhouette, a blended surface in front) shades the rest of its
   list exactly - blended surfaces always do.
5. **When:** a light count threshold set from the night-market rig (512) switches between CELLS (exact) and the screen tail
   (`light_mode::AUTO`); below it nothing of this runs and the images are bitwise what they were.

### Built (2026-10-27)

`light_mode::SCREEN` (`R/plans/forward/xlionrender_plan_forward.cpp` renderTail; `R/shaders/xlionrender_tail_screen_frag.glsl`,
`xlionrender_tail_denoise_comp.glsl`; the material side in `xlionrender_local_lights.glsl` LocalTailScreen; the G-buffer variant in
`mb_standard_pbr.frag` under `XLION_GBUFFER_OUTPUT`), and `light_mode::AUTO`, the default: CELLS below `m_LightScreenThreshold` (512)
lights, SCREEN from it. As built, against the plan above:

- **One G-buffer**, not two: last frame's distance and normal travel in the denoiser's records (a uvec4 a texel: the diffuse and the
  specular in halves; the distance, the normal at 4 + 4 bits and the frames in the last word), so last frame's targets are not kept.
- **The spatial pass's result is the history** (SVGF's first level, fed back): what the materials read and what the next frame
  reprojects - two record buffers, no third for the materials.
- **A pixel the screen tail does not cover** (a silhouette, a blended surface, a material without a G-buffer variant) shades the rest of
  its list **exactly**, not with the inline sample: no noise anywhere, and a scene whose materials have no variant yet looks as with CELLS.
- xGPU grew two formats (`A2B10G10R10_UNORM`, `B10G11R11_UFLOAT`, appended): the G-buffer and the tail pass's two targets.
- **Memory: 48 B a half-size texel - 52.9 MB at 3093 x 1493** (23.7 MB at 1920 x 1080): G-buffer 4 + depth 4, the tail 2 x 4, the
  records 2 x 16 (under the 61 MB target); with the movers' motion target (below) 56 B, 61.7 MB.

Measured (`R/tests/xlionrender_test_screen_tail.cpp`, the rig's street at 1024 lights, 640 x 360, against CELLS of the same frame in a
second view; Release, the same in Debug with Vulkan validation, no error):

| | inline SAMPLED (RIS + visibility) | SCREEN |
|---|---|---|
| per-frame error, still camera | 0.301 | 0.048 - 0.053 |
| flicker (frame to frame) | 0.397 | 0.018 - 0.023 |
| 16-frame mean's error (bias) | 0.074 | 0.043 (2.8% darker: the demodulation's approximations) |
| moving camera / moving lights / a box crossing (disocclusion) | 0.30 / 0.30 / 0.30 | 0.053 / 0.058 / 0.049 |

The rig (`R/tools/bench_many_lights`, 60 warmed frames; the scene pass with the head + the screen tail's passes; ms):

| Lights | CELLS 1080p / 4.6 MP | SCREEN: scene + G-buffer + tail + denoiser, 1080p | 4.6 MP | error: inline RIS / SCREEN |
|---|---|---|---|---|
| 256 | 0.52 / 1.04 | 0.42 + 0.01 + 0.08 + 0.06 = 0.57 | 1.20 + 0.02 + 0.23 + 0.18 = 1.63 | 0.115 / 0.023 |
| 1024 | 1.89 / 4.06 | 0.48 + 0.01 + 0.10 + 0.06 = 0.65 | 1.00 + 0.02 + 0.21 + 0.12 = 1.35 | 0.301 / 0.081 |
| 4096 | 7.41 / 15.75 | 0.57 + 0.01 + 0.13 + 0.06 = 0.76 | 1.17 + 0.02 + 0.28 + 0.12 = 1.59 | 0.386 / 0.093 |

CELLS costs less up to ~300 lights: the threshold 512. At 4096 lights SCREEN is ~10x faster than CELLS with a quarter of the inline
tail's per-frame error. **Not built yet:** the materials' compiled G-buffer variant (the xmaterial compiler's `XLION_GBUFFER_OUTPUT`
variant, data_file v7 - its recompile scope waits for Tomas: until then the project's materials shade their tail exactly in SCREEN; the
built-in constant materials and the tests have their variants); a skinned pose's own motion (its instance's is kept: "The bias and the
movers"); the specular's own denoising beyond the shared passes (its history is shorter on glossy surfaces).

### The bias and the movers (2026-10-27)

**The 16-frame mean was 2.8% darker than CELLS. The cause: the history's clamp** (measured, each step switched off in turn,
`R/tests/xlionrender_test_screen_tail.cpp`'s still camera):

| | brightness / CELLS' | per-frame error | 1 / 2 / 4 / 8 frames after half the lights went off |
|---|---|---|---|
| as built: clamp to the 3 x 3 neighbourhood, +-1.25 deviations | 0.972 | 0.048 | 0.307 / 0.218 / 0.140 / 0.082 |
| no denoiser (the tail pass, upsampled) | 1.004 | (noisy) | |
| no clamp | 1.005 | 0.035 | 0.918 / 0.841 / 0.708 / 0.501 |
| 3 x 3, +-2.5 deviations | 0.986 | 0.043 | 0.511 / 0.404 / 0.291 / 0.182 |
| the window at least 30 - 50% of the mean | 0.970 | 0.048 | 0.31 / 0.22 / 0.14 / 0.08 |
| a shorter history out of the window, the value kept | 0.961 - 0.996 | 0.043 - 0.093 | 0.15 - 0.79 / ... / 0.07 - 0.19 |
| 5 x 5, +-1.25 / 7 x 7, +-1.25 | 0.995 / 0.998 | 0.038 / 0.037 | 0.351 / ... / 0.140 - 0.364 / ... / 0.163 |
| **7 x 7, +-1.25, and far out (2 deviations): the history at most 2 frames** | **0.998** | **0.037** | **0.278 / 0.200 / 0.143 / 0.095** |

The demodulation and the upsampling are +0.4% (the tail pass alone: 1.004); the clamp took 3.2%. A 3 x 3 window over this many small
lights shaves their peaks (a texel brighter than its neighbours is clamped down; the valleys are broad): a wider or floored window did
not help, a larger neighbourhood did. Shortening the history instead of clamping is biased too (the decision follows this frame's noisy
sample). **Built: the 7 x 7 neighbourhood (read once per workgroup into shared memory), clamped at +-1.25 deviations, and a history
far out of it (2 deviations: an abrupt change) shortened to 2 frames** - the mean 0.2% under CELLS (the gate: 0.5%), and a light
switch followed as fast as before.

**Movers' motion:** an instance's last transform rides in its instance record (`details::instance_data`, 96 -> 144 B: instance_slots
keeps it; written again, equal to the current one, the frame after it stops); the vertex shaders give last frame's clip position, the
G-buffer variants write it into a fourth half-size target (last frame's screen position and view depth, RGBA16F) and the denoiser
reprojects those texels by it (the camera's reprojection elsewhere; the records' depths are now view depths, clip w). A skinned mesh moves
by its instance only (its pose's motion: not kept); a mesh without an instance id or a CreateMesh mesh: the camera's. A box crossing the
street at 12 cm a frame: 0.046 without its motion, 0.040 with it (inline 0.295). Memory: **61.7 MB at 3093 x 1493**.

## Decisions (Tomas)

1. Do we add the tail targets to every lit material's output (A) - the material compiler's templates change, every material recompiles?
2. The memory budget: ~61 MB at half resolution on a 4.6 M-pixel view (~245 MB at full)?
3. Motion: camera-only first, a velocity target later - or both at once?
4. Priority: after or before other work (the denoiser pays only with dense light rigs; today CELLS is exact and as fast)?
