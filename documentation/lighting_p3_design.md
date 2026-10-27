# Lighting P3: the tail's reconstruction (design note, 2026-10-27 - waits for Tomas's decision)

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

So before a denoiser can pay, three pipeline changes would (each its own decision, none built): **the tail's candidates by binary search**
of the cumulative probabilities (O(log n), not the list walk); **the cells built on the GPU** (P2's plan: the CPU build is linear); **a
larger or adaptive cell buffer** (no EXACT fallback at 4096 lights). With those, SAMPLED's cost stops growing with the density and the
denoiser turns its noise into a usable image.

## Recommendation

1. Keep CELLS the default until a scene shows lists long enough for SAMPLED to pay (measure: the ledger's direct-shading row, CELLS vs
   SAMPLED, on Tomas's densest light rig).
2. When it pays: **A at half resolution, camera reprojection first** (~61 MB at 4.6 M pixels), demodulated, temporal (12 frames, clamp)
   then spatial (4 samples, depth weighted); velocity for moving objects second.
3. The screen trace (contact shadows for the tail's unshadowed lights) after A: it reads the same depth.

## Decisions (Tomas)

1. Do we add the tail targets to every lit material's output (A) - the material compiler's templates change, every material recompiles?
2. The memory budget: ~61 MB at half resolution on a 4.6 M-pixel view (~245 MB at full)?
3. Motion: camera-only first, a velocity target later - or both at once?
4. Priority: after or before other work (the denoiser pays only with dense light rigs; today CELLS is exact and as fast)?
