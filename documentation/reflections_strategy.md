# Reflections strategy (design, 2026-10-28 - not built; reviewed with Fable the same day, sec. 9)

Tomas (2026-10-27): "the diffuse seems working but specular / reflection proves is lacking ... lets design it first, make sure we aim to
leap over our competition again". This is the design for the whole specular path that is not a light's direct highlight: what a glossy
floor, a mirror, a rough metal, a window and water show of the world. It reuses what lighting and the GI already built (sec. 4).
`R/` = `example.lionprj/Cache/dependencies/xLIONRender/src/`.

## 1. What we have today (the code)

| Piece | Where | What it does | Its limit |
|---|---|---|---|
| Direct specular of the lights | `R/shaders/xlionrender_local_lights.glsl`, `xlionrender_shadow_vsm.glsl`, the screen tail | Every light's GGX highlight, shadowed (sun pages, local pages, the tail's RIS + screen trace + BVH ray) | Complete for lights; emitters only with GIEmitterLights |
| Sky environment | `R/shaders/xlionrender_environment.glsl` `EnvSample` | Split-sum: an octahedral atlas of prefiltered levels by roughness, the DFG table | Infinitely far, no occlusion of its own |
| Reflection probes | same file, `ProbeAdd` / `ProbeBoxProject`; captures in `plan_forward.cpp` (`updateProbes`) | Box-projected (parallax) cube captures in an octahedral atlas, nested by size, found through the light cells | Static captures (stale when lights or objects change), no dynamic objects, planar errors away from the box, fading to the sky at a room's walls (§7b item 3) |
| GI reflections, layer 1 | `GIPixelGI` (`mb_standard_pbr.frag`), the half-size GI pass (`xlionrender_gi_screen_frag.glsl`) | The surfels' 3 basis colors weighed toward R (`g_GIRefl`): normalizes the probes' reflection by the local light; takes over from roughness 0.3 to 0.7 | A cosine-wide lobe: rough only; half resolution and reused over frames (approximate for a view-dependent term) |
| Specular occlusion | `EnvLighting` | The GI's light ratio along R (layer 1) or overall (vertex read) | A heuristic, not visibility (§7b item 1) |
| Screen-space reflections | - | **none** | - |
| Traced reflections | - | **none** (the GI's BVH and its rays exist since P4) | - |

**What it looks like** (pictures in the lighting thread, 2026-10-28): Lily stands on Police's polished checkered floor and the floor shows
neither her nor the walls (`play_b_Debug.png`), only the probes' and the sky's blur; a moving object never appears in any reflection;
a mirror is impossible (a box projection is exact only on the box); the probes do not change when a lamp is switched off.

**The GI thread's notes for this design** (2026-10-27, it will not do reflection work):
1. Only layer 1 is built; with 3 basis directions it is rough reflections only.
2. `g_GIRefl` comes from the half-size GI pass (word z + the low 16 bits of w, bit 31 "read"), upsampled by depth and normal and reused
   across frames (8x8 tiles, 1 in 4 fresh): approximate for a view-dependent term - a sharp, view-correct design must not rely on it. If
   lighting takes the reflection term over, the half pass can drop those bits.
3. Layer 2 as planned there: rays ending on the surfel cache (SurfelPlus-style GGX candidates) for medium roughness. `getBvh` makes the
   rays possible; missing: the hit's surfel light addressable in compute (`GIBvhInstances[].m_Info.y` is the world instance; the
   per-instance records are in `gpu_trace::m_DataB`).
4. The 9 open probe items of `gi_dynamic_master_plan.md` §7b (specular occlusion, blend order, fading to the sky, SH9 diffuse, split AO,
   atlas seams, the capture contract, typed records, tests) are all still open.

## 2. The competition (read in E:\source_code and the papers)

| Engine / technique | Smooth (mirror, glossy) | Rough | Hit lighting | Fallback | Denoising | Dynamic objects | Translucent / water | No ray tracing |
|---|---|---|---|---|---|---|---|---|
| **Unreal Lumen** (`Lumen/LumenReflections*.cpp/.usf`) | Dedicated rays up to `MaxRoughnessToTrace` (PPV 0.4), faded over 0.1 (`RoughnessFadeLength`) into the screen-probe gather's rough specular; full-res while the reflection quality is above 0.25 (`DownsampleFactor` 1; scalability drops it to 2), GGX sampling | Rays shortened from 0.2, the radiance cache from 0.35 (fade 0.05); above 0.4 the screen probes' gather | Surface cache (cards: albedo, direct light from every light with its shadows - VSM, SDF or HW traced - plus indirect; card resolution, an update budget: lagging) or HW RT hit lighting (lights and shadows at the hit, the real materials: slow, divergent) | Screen trace (HZB) -> mesh SDF / global SDF or HW RT -> sky / radiance cache | Temporal (12 frames, neighborhood clamp), BRDF-reweighted screen-space reconstruction (rays shared by neighbors), bilateral; ray intensity clamped (40) | In the SDF / HW BVH; skinned only through HW RT or screen | Front layer translucency: one traced layer; single layer water | SW tracing on SDFs (low detail, leaks on thin geometry) |
| **Frostbite SSSR** (Stachowiak 2015) | Stochastic SSR: half res, GGX importance sampling, rays reused by neighbors weighted by the BRDF/pdf | Same rays, reuse widens | The screen's colors (last frame) | Probes | Temporal + the ray reuse | Only what is on screen | - | Its baseline |
| **AMD FidelityFX SSSR** | Hierarchical depth traversal (min-Z pyramid); one ray per 2 x 2 quad where the temporal variance is low (any roughness), rays skipped above a roughness threshold | Above the threshold: probes | Last frame's color | Probes | Spatio-temporal, variance-guided | Screen only | - | Yes (SSR only) |
| **NVIDIA ReBLUR / ReLAX** (NRD) | - (denoisers) | - | - | - | Hit-distance-aware blur radius (sharp contact, wide far); specular history from a blend of virtual motion (the reflected point's reprojection) and surface motion by roughness and an estimated surface curvature, the virtual history limited by its confidence; specular history by roughness | - | - | - |
| **Unity HDRP** | SSR (or RT reflections), planar reflection probes | Probes | Screen color / RT hit shading | Reflection probes (box/sphere), sky | Its own temporal / RT denoiser | RT or screen | Transparent SSR (one layer) | SSR + probes |
| **Godot 4** (`renderer_rd/effects`, SDFGI) | SSR (roughness-filtered), roughness limiter | SDFGI cascades' cone traces, VoxelGI cones | The SDF/voxel radiance | Probes, sky | Light | Voxels re-voxelized; screen | - | SSR + probes |
| **AMD Capsaicin GI-1.0** (`gi1/glossy_reflections.hlsl`) | Traced glossy rays (HW RT), low/high roughness thresholds, half-res option | The GI's screen probes | The hash-grid radiance cache (world space) | Sky | Firefly marking + à-trous passes | HW BVH | - | - |
| **Activision / id** (CoD GTAO + specular occlusion, Doom Eternal) | SSR + probes | Probes with specular occlusion from the visibility cone (GTSO) | Screen / probes | Probes | Temporal | Screen | - | Their baseline |

**What none of them does well (the room to leap):**
1. **Hit lighting is either low-res and lagging or right and expensive.** Lumen's SW surface cache is card resolution, lit on an update
   budget, and misses dynamic and thin objects; HW hit lighting is right but runs the materials and the lights per hit (slow, divergent).
   Capsaicin's hash grid is coarse.
2. **The two sides of the rough/smooth handoff disagree in energy and color**: Lumen fades the traced result into the screen probes'
   gather over 0.3-0.4, SSSR into probes past its threshold - a fade between two different estimators of the same integral, not one
   estimator.
3. **Dynamic and skinned objects** fall out of everything but the screen (SW Lumen, SSR) or need HW RT.
4. **The many-lights direct light at the hit** - a reflected street with 4096 lamps - is the cache's (low-res, lagging) in SW Lumen and
   Capsaicin, and per-light cost in HW hit lighting.
5. **Specular occlusion** is a heuristic (GTSO cones, AO maps) except where rays are traced.
6. **Without HW RT** quality collapses to SSR + static probes.

## 3. The goal, measurable

At 1080p and 4.6 MP, Police, Bistro and the many-light rig:
- **Correct within 10% of a path-traced reference** (sec. 6) on the reflection term for roughness 0 .. 1 - one estimator, no handoff
  between two (needs the multiple-scattering compensation, sec. 4.10).
- **Every visible light in a reflection** shades the reflected point as it shades the main view (its shadow included), not a cache's guess.
- **Dynamic and skinned objects** appear in reflections (on screen exactly; off screen as approximations, labelled).
- **Stable**: per-frame flicker and the moving-camera error under the screen tail's (P3) numbers; no ghosting on movers.
- **Budget**: a target of 1.0 ms at 1080p and 2.5 ms at 4.6 MP on the test machine, at most 40 MB at 4.6 MP - **to be set by R0's
  measurement** of long incoherent closest-hit rays on the GI's BVH (the review expects the world trace alone at 1.5-3 ms at 4.6 MP; P4's
  +0.2 ms was any-hit on short coherent shadow rays).
- **No HW RT required** (compute only, the GI's BVH); HW RT an optional accelerator later.

## 4. The design

### 4.1 One specular-ray pipeline beside the screen tail
The screen tail (P3) already has a half-size thin G-buffer (octahedral normal, roughness, depth, motion), a fullscreen pass with the
lights' code, a denoiser framework and the materials' remodulation (binding 14). Reflections join it:
1. **Ray generation** at half size (full size below roughness 0.1, sec. 4.4): per texel one GGX VNDF sample of the reflected direction,
   blue-noise per frame. Rays where the material's specular matters (`F0`-weighted luminance of the view: skip a dark diffuse wall).
2. **Trace order** (each step only for what the last left open):
   a. **Screen trace** - new, not P3's (that one is a 1 m, 12-step jittered march): a min-depth pyramid over the half-size depth (SSSR's
      hierarchical traversal), a constant thickness tuned against the reference, a maximum ray distance, a screen-edge fade; a miss
      leaves the screen at a point the world trace **resumes from** (not from the surface). **Hit lighting from the screen**: not the
      composited color (it holds last frame's reflections - a mirror facing a mirror feeds back -, the main view's specular from the wrong
      view, exposure state): the screen tail's demodulated diffuse record at the hit times the hit's albedo, plus its emission and its
      lights' direct diffuse - view-independent, as a world hit's.
   b. **World trace** through the GI's BVH (`gi::gpu_trace::getBvh`, P4's any-hit reused as a closest-hit `GICast`) for what leaves the
      screen or is hidden behind the first surface.
   c. **Fallback**: the reflection probes (box-projected, the §7b fixes) and the sky.
3. **Hit lighting in the world** (step b) - the leap:
   - **Indirect at the hit:** the surfel cache's radiance at the hit point (the GI's own read at the hit triangle: view-independent
     diffuse, what Lumen's surface cache gives, but at the surfels' resolution and always current). Needs the GI thread's small accessor
     (its note 3: the hit instance's surfel data addressable in compute).
   - **Direct at the hit, tiered** (the review): the surfel radiance above already holds the lights' direct light (the GI lights its
     surfels) - what more costs buys is resolution, measured before it is built (R3b). Where it is built: the many-lights machinery at the
     hit (the cell's head exactly, the tail by RIS, `LocalLightDemod`) - our cells are a camera-centred **world** clipmap, so a hit behind
     the camera has its cell while it is inside the windows; shadowed by the virtual shadow pages only where they exist (the main view
     requested them) - reflection hits feeding page requests is a measured option (a frame late, a bigger page budget). Outside the
     windows or unpaged: the surfel radiance alone. Mirrors take the deterministic part only (the head, a hashed seed for the tail): a
     mirror cannot be denoised without blurring it.
   - **The hit's material:** its albedo and emission from the GI's captured surfel colors (the triangles' albedo, `SurfaceAt`) - no
     material shader at the hit (Lumen's surface cache idea, our capture). Glossy-at-the-hit (a mirror in a mirror) is one bounce only:
     the hit is shaded diffuse + its emission (labelled).
4. **Resolve and denoise** (sec. 4.3) into a demodulated specular buffer the materials read (the screen tail's binding 14 record grows
   a reflection RGB, or a second record), remodulated by the material's own `F0 * DFG.x + DFG.y` (the split-sum's environment BRDF).

### 4.2 Roughness without a band
One estimator over the whole range, the ray budget shifting smoothly:
- **0 .. 0.1 (mirror-like):** full-size rays, one per pixel, in tiles - they need a full-size normal/roughness source (the thin
  G-buffer is half size): the depth prepass writes the normal and roughness too where the tile list asks (R4); no spatial reuse (it
  would blur); temporal reuse with virtual motion; deterministic hit lighting (above).
- **0.1 .. 0.5 (glossy):** half-size rays; **BRDF-reweighted spatial reuse** of neighbors' hits (Frostbite's ray reuse, Lumen's
  reconstruction) - no ReSTIR re-validation (a visibility ray per reused candidate would cost the whole budget, and reusing a hit point
  needs the reconnection Jacobian, which degenerates toward mirrors); its bias measured against the reference, temporal reservoirs only
  if a gate asks.
- **0.5 .. 1 (rough):** fewer rays (1 in 4 texels, rotating), the reuse wider, with a **real control variate** sharing the rays: per ray f
  = the full hit lighting and c = the surfel radiance at the same hit (the same visibility); the estimate is C + mean(f - c), with C the
  integral of the surfels' radiance over the lobe (GI layer 1's value, or better a cache read along the dominant direction). The rays
  only carry the difference between the full and the cached hit lighting - small, low variance -; no "same energy by construction"
  claim: it is measured (R4). Layer 1's half-size, reused value is C only (the GI thread's note 2), never the sharp term.
- **The estimator:** each VNDF sample carries `F(v.h) G2/G1` (the GGX VNDF weight); the result is divided by the material's environment
  BRDF (`F0 DFG.x + DFG.y`) for denoising and multiplied back after - with the multiple-scattering term (4.10) - so metals keep their
  tint. Ray generation and the virtual motion's hit distance use the **dominant (off-specular) direction** for rough lobes (Frostbite).

### 4.3 Denoising and stability
Built on the screen tail's denoiser (temporal 7x7 neighborhood clamp, spatial, records) with what specular needs (ReBLUR's lessons):
- **Virtual motion, curvature-aware** (ReBLUR): a reflection's history is fetched where the *reflected point* was last frame (its hit
  distance along the ray reprojected), blended toward the surface's motion by roughness and by the surface's curvature (from the normal's
  screen derivatives: on a sphere or Lily's jacket pure virtual motion smears), limited by a virtual-history confidence. Movers - rigid
  and skinned - carry their motion in the thin G-buffer already (P3, and the skinned pose motion of 2026-10-27).
- **Hit-distance-guided spatial filter:** the kernel shrinks with the hit distance (sharp contact reflections, wide far ones), and with
  roughness.
- **History by roughness and motion:** long for rough, short for mirrors (their virtual motion is exact); 4 frames for a moving texel
  (P3's lesson: a mover's history lags).
- **Fireflies:** the ray intensity clamped against the neighborhood (Capsaicin's marking), not a global constant.
- **Disocclusion:** short history plus a wider spatial pass for a few frames (ReBLUR).

### 4.4 Resolution and budget
- Rays: half size (1546 x 747 at 4.6 MP: 1.15 M rays), mirrors full size where the G-buffer says roughness < 0.1 (a tile list).
- Cost model - **R0 measures it first** (an hour's work: 1.15 M long random closest-hit rays on today's BVH decides the whole budget):
  screen trace ~0.15 ms / M rays (SSSR's class); the world trace is the unknown - P4's +0.2 ms was any-hit on short coherent shadow rays,
  long incoherent glossy rays are typically 3-10x (the review: R3 alone 1.5-3 ms at 4.6 MP); hit lighting with RIS at divergent hits more
  than the main view's (incoherent cell reads); denoise ~0.2 ms. The budget (sec. 3) is set from R0, not assumed.
- Memory at 4.6 MP at half size: ray hit + direction (8 B), radiance (8 B), history (16 B, or 8 B with 16-bit history) - ~35-45 MB with
  the pyramid; the full-size mirror tiles extra. Shared with the screen tail's records where the layouts allow.

### 4.5 Probes: the fallback, made right
They stay - the no-trace fallback, far reflections beyond the BVH, translucent fallback - with the §7b items done:
1. **Relit probes:** a probe captures its G-buffer once (albedo, normal, depth) and is **relit** every few frames from the lights (the
   same direct code) and the GI's surfels: no stale probe when a lamp goes off (the probe captures only on geometry change). Few engines
   do this (Frostbite's "dynamic probes" are a cousin).
2. Separate capture origin / projection box / influence; nested override vs peer blending, a stable order; an enclosing room probe so
   fading never falls back to the sky indoors.
3. The diffuse from SH9, not the roughest specular level; atlas seams and borders; the capture contract (HDR, pre-exposure, versioned).

### 4.6 Specular occlusion from visibility
The traced rays are their own occlusion. Where no ray is traced (rough, probe fallback) the specular occlusion comes from the GI's
moments along R (the surfels' visibility the reads already have) and the screen-space bent cone - the §7b item 1 measured against the
reference, the GI ratio kept as a labelled option.

### 4.7 Dynamic and skinned objects
- On screen: the screen trace has them (exact).
- Off screen / behind: the GI's BVH has rigid opaque GI meshes only. Phase R5 adds a **dynamic BVH** for movers and skinned meshes
  (refit per frame from the skinned pose's bone boxes - a coarse proxy per bone (capsule/box) shaded with the mesh's mean albedo),
  labelled approximate; HW RT replaces it where present.

### 4.8 Translucent surfaces and water
Forward-shaded translucents (glass, water) read the same reflection buffer when they are the **front layer** (a second thin G-buffer
layer for the nearest translucent, written by a nearest-translucent depth pre-pass before the reflection pass: Lumen's front layer
translucency), else probes. One layer only: glass over water reflects through the glass's layer, the water behind it takes probes.
Water's planar case gets the full-size rays (a mirror at grazing angles).

### 4.9 Fallback without compute / low end
Probes (relit) + GI layer 1 + the screen trace only; the same buffer, fewer steps.

### 4.10 Energy: multiple scattering
Single-scattering GGX loses 20-40% of a rough metal's energy; the 10% gate at roughness 1 is unreachable without the compensation
(Kulla-Conty / Turquin: the specular times `1 + F0 (1 / E(mu) - 1)`, E from the DFG table's sum) - in the main view's direct specular, the
probes' and the traced reflections alike (one change in the shared BRDF code, R1).

### 4.11 Misses, emission, out of scope
- **A ray that misses:** the sky - unfiltered per ray for mirrors, the roughness-prefiltered level for rough rays (their lobe already
  integrated by the samples' spread: the prefiltered level by the ray's cone, not the material's roughness twice).
- **Emission at a hit:** the surfels' captured emission (`SurfaceAt`, captured with the materials) - and the emitter lights at the hit.
- **Out of scope for now (said, not forgotten):** anisotropic GGX and the clearcoat second lobe (their reflections take the base lobe's
  until a material needs them).

## 5. What it reuses (and does not rebuild)
The thin G-buffer and its motion target (P3, with the skinned pose motion), the GI's BVH and `getBvh` (P4), the many-lights cells, head
and RIS (P2/P3), the virtual shadow pages (P1), the emitter lights, the denoiser framework (P3), the GI surfel cache (layer 1, the hit
read), the probes' atlas and capture, the materials' binding 14 remodulation. **Not reused:** P3's screen trace (a short contact march) -
the reflections' screen trace is a new pyramid traversal.

## 6. Tests and gates
- **The reference:** a CPU path tracer over the GI world's BVH (`gi::world::Cast`, the captured albedo) for the reflection term only:
  many GGX samples per pixel at low resolution, the hit lit by the same lights (exact, shadowed by rays) and the converged surfel cache
  for the rest. Error per roughness bucket (0, 0.1, 0.25, 0.5, 0.75, 1).
- **Scenes:** a mirror box (colored walls, a sphere), a glossy floor under a lamp row (the many-lights reflection), a rough metal ramp
  (spheres 0 .. 1), a moving box and a skinned mover in front of a glossy wall, the probes' §7b cases (bright doorway, dark room by the sky,
  two overlapping colored probes, atlas neighbors), Police and Bistro ledgers.
- **Gates per phase:** error vs the reference per bucket; flicker and moving-camera error (as P3's); ms and MB at 1080p and 4.6 MP; the
  existing lighting gates and bitwise baselines (reflections off: unchanged).

## 7. Phases

| Phase | Builds | Gate |
|---|---|---|
| **R0** Reference, tests, the ray cost | The CPU reflection reference, the scenes, the error per roughness bucket; today's numbers; **first: the measured cost of 1.15 M long random closest-hit rays on today's BVH** (sets the budget) | The table of today's errors (probes + layer 1); the ray cost |
| **R1** Screen-traced reflections | Ray generation (GGX VNDF, dominant direction, half size), the pyramid trace, the demodulated diffuse + emission as screen hit lighting, the resolve into a demodulated buffer, the materials reading it; the multiple-scattering compensation; probes / sky where the screen fails | Glossy floor and mirror box, on-screen hits (diffuse and emissive surfaces): error under 10%; ms at 1080p / 4.6 MP |
| **R3a** World trace, surfel hit lighting | `GICast` closest hit on the GI's BVH resumed from the screen exit, the surfel radiance at the hit (the GI accessor - the GI plan's layer 2), the hit's captured albedo/emission | Off-screen and behind-the-first-surface error under 15%; ms |
| **R2** Denoiser | Curvature-aware virtual motion, hit-distance filter, roughness/motion history, firefly clamp, BRDF-reweighted spatial reuse | Flicker and moving-camera error at P3's level; no ghosting on movers (rigid and skinned) |
| **R3b** Tiered direct light at the hit | Cells + RIS + pages where the hit is inside the windows and paged; reflection hits' page requests (measured option) | Measured gain over R3a; the lamp row's reflection has every lamp with its shadow |
| **R4** Roughness without a handoff | Mirror tiles at full size (the prepass writes their normal/roughness), deterministic mirror hit lighting, the rough range's control variate (f - c on shared rays), the specular occlusion | Error continuous across 0 .. 1; under 10% everywhere |
| **R5** Probes made right + dynamics | Relit probes, the §7b items, the dynamic BVH proxies for movers / skinned | A lamp switched off changes the probes within a few frames; a skinned mover off screen appears (approximate, labelled) |
| **R6** Translucent front layer, water | The front-layer G-buffer, water's mirror rays | Glass and water reflect the world, not only probes |

## 8. Open questions for Tomas
1. **The budget:** a target of 1.0 ms at 1080p / 2.5 ms at 4.6 MP and 40 MB, set for real by R0's ray-cost measurement (it may need to
   be 2-4 ms at 4.6 MP with the world trace) - acceptable to decide after R0?
2. **Hit lighting's quality bar:** surfel radiance at every hit first (R3a: it already holds the lights' direct light, at the surfels'
   resolution), the full per-light direct light at the hit (R3b) only where measured worth it - agreed?
3. **The GI accessor** for the hit's surfel light (the GI thread's note 3) - lighting writes it as with the BVH and emitter views?
4. **Dynamic BVH proxies** for skinned meshes (R5) - acceptable as an approximation, or wait for HW RT?
5. **HW ray tracing:** design for compute first (as here) and add HW RT as an accelerator later - agreed?
6. **Order:** R0 -> R1 -> R3a -> R2 -> R3b -> R4 -> R5 -> R6 (the review's: the world trace before the denoiser polish, the expensive
   per-light hit lighting last and measured) - agreed?

## 9. The review (Fable, 2026-10-28) and what changed
- Competitors corrected: Lumen fades (0.3-0.4) rather than switches; its surface cache is lit with shadows (low-res and lagging, not a
  guess); its full-res default holds above a quality setting; SSSR traces a ray per 2 x 2 quad where variance is low, not "mirrors once";
  ReBLUR blends virtual and surface motion by roughness and curvature.
- Design: the "control variate" on layer 1 was not one - replaced by f - c on shared rays (4.2); ReSTIR re-validation dropped for
  BRDF-reweighted reuse; screen hit lighting from the demodulated diffuse + emission, not the composited color; direct light at the hit
  tiered and measured (the surfel radiance already holds it); mirrors need a full-size normal source and deterministic hit lighting; P3's
  screen trace is not the reflections' (a new pyramid trace); the budget set by R0's measurement.
- Added: multiple scattering (4.10), the estimator's weights and the dominant direction (4.2), curvature-aware virtual motion (4.3),
  the screen trace's details (4.1), misses and emission (4.11), translucency ordering (4.8), anisotropy/clearcoat out of scope.
- Not taken from it: "the light cells are frustum-clustered" - ours are a camera-centred world clipmap (a hit behind the camera has its
  cell inside the windows); "skinned movers lack pose motion" - built 2026-10-27.
