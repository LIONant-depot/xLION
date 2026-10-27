# Reflections strategy (design v2.1, 2026-10-28 - not built)

Tomas (2026-10-27): "the diffuse seems working but specular / reflection proves is lacking ... lets design it first, make sure we aim to
leap over our competition again", then, after an external review of v1: "revise doc then try again to leap what we have ... iterate a
little to make sure we have the best design possible before spending a lot of tokens building it". Design only. v1 -> v2 -> v2.1:
sec. 13 (an external correctness review, then a Fable challenge "clearly better, not just correct").
`R/` = `example.lionprj/Cache/dependencies/xLIONRender/src/`.

**The contract every part below obeys:** every reflection sample has a declared transport model (sec. 4), a typed visibility result
(sec. 5), a precisely defined outgoing-radiance quantity at its hit (sec. 3), and approximation metadata (fresh / reused / fallback, the
cache's age). Expensive hit shading *replaces* a compatible cached term; it never adds overlapping light.

## 1. What we have today

| Piece | Where | What it does | Its limit |
|---|---|---|---|
| Direct specular of the lights | `R/shaders/xlionrender_local_lights.glsl`, `xlionrender_shadow_vsm.glsl`, the screen tail | Every light's GGX highlight, shadowed (sun and local pages, the tail's RIS + screen trace + BVH ray); emitter lights when GIEmitterLights is on | Complete for lights |
| Sky environment | `R/shaders/xlionrender_environment.glsl` `EnvSample` | Split-sum: an octahedral atlas prefiltered by roughness, the DFG table | Infinitely far, unoccluded |
| Reflection probes | same file, `ProbeAdd` / `ProbeBoxProject`; captures in `plan_forward.cpp` | Box-projected cube captures in an octahedral atlas, nested, found through the light cells | Static captures, no dynamic objects, exact only on the box, fade to the sky at a room's walls |
| GI reflections, layer 1 | `GIPixelGI` (`mb_standard_pbr.frag`), the half-size GI pass | The surfels' 3 basis colors weighed toward R (`g_GIRefl`): normalizes the probes by the local light; takes over from roughness 0.3 to 0.7 | Cosine-wide lobe: rough only; half size and reused over frames (approximate for a view-dependent term) |
| Specular occlusion | `EnvLighting` | The GI's light ratio along R | A heuristic |
| Screen-space reflections | - | **none** | - |
| Traced reflections | - | **none** (the GI's BVH and `getBvh` exist since P4) | - |

What it looks like (pictures in the lighting thread, 2026-10-28): Lily on Police's polished floor is not reflected, nor are the walls -
only the probes' and the sky's blur; movers never appear in a reflection; a mirror is impossible; the probes ignore a lamp switched off.
The GI plan's §7b probe items (specular occlusion, blend order, fading to the sky, SH9 diffuse, split AO, atlas seams, capture contract,
typed records, tests) are all open.

**What the GI already has that matters here** (read in its code): a surfel's shown light is **indirect irradiance only** - lighting
shades the direct term, the GI computes direct light fresh at its own ray hits (`Direct()` in `xlionrender_gi_pass_common.glsl`: the sun
and its point lights, a BVH shadow ray each); the captured albedo (per triangle and per surfel) and emission (`SurfaceAt`); the BVH.

## 2. The competition (read in E:\source_code and the papers; v1's corrections kept)

| Engine / technique | Smooth | Rough | Hit lighting | Fallback | Denoising | Dynamic | No RT |
|---|---|---|---|---|---|---|---|
| **Unreal Lumen** | Rays to `MaxRoughnessToTrace` (0.4), faded over 0.1 into the screen probes' gather; full res above quality 0.25 | Rays shortened from 0.2, radiance cache from 0.35 | SW: surface cache (cards: albedo, every light's direct light with shadows, indirect - card resolution, lagging); HW: real materials and lights at the hit (slow) | Screen (HZB) -> SDF / HW -> sky / radiance cache | Temporal 12 frames, BRDF-reweighted reconstruction, bilateral, intensity clamp 40 | SDF / HW BVH; skinned only via HW or screen | SDF tracing (leaks on thin geometry) |
| **Frostbite SSSR** (2015) | Half-res stochastic SSR, GGX samples, rays shared by neighbors (BRDF/pdf) | Same, wider | Screen color | Probes | Temporal + reuse | Screen | Its baseline |
| **AMD FidelityFX SSSR** | Min-Z pyramid traversal; 1 ray per 2x2 where variance is low; rays skipped past a roughness threshold | Probes | Last frame's color | Probes | Spatio-temporal, variance-guided | Screen | SSR only |
| **NVIDIA ReBLUR / ReLAX** | - | - | - | - | Hit-distance radius; virtual + surface motion blended by roughness and curvature, a virtual-history confidence; demodulation by the environment BRDF | - | - |
| **Unity HDRP** | SSR or RT; planar probes | Probes | Screen / RT shading | Probes, sky | Own | RT / screen | SSR + probes |
| **Godot 4** | SSR, roughness limiter | SDFGI / VoxelGI cones | SDF / voxel radiance | Probes | Light | Re-voxelize; screen | SSR + probes |
| **AMD Capsaicin GI-1.0** | Traced glossy rays, roughness thresholds, half-res option | Screen probes | Hash-grid radiance cache | Sky | Firefly marking + à-trous | HW BVH | - |
| **AMD hybrid reflections** (FidelityFX Hybrid Reflections) | SSR first, rays only where SSR fails; screen color or a re-shade of the hit | Probes | Screen color / re-shaded hit | Probes | Spatio-temporal | HW | - |

**The room to leap:** hit lighting is low-res and lagging (Lumen SW, Capsaicin) or right and slow (HW hit lighting); the smooth/rough
handoff joins two different estimators; the many-lights direct light at a reflected point is a cache's or costs per light; dynamic and
skinned objects need HW RT off screen; without HW RT quality falls to SSR + static probes; none of them says what each reflection
sample's approximation is.

## 3. The hit contract: what a reflection ray returns

At a secondary hit y, seen along -w (toward the receiver):

    L_o(y, -w) = L_e(y) + rho_d(y) / pi * ( E_direct(y) + E_indirect(y) )                        [initial transport model]
               + f_s,y(-w, ...) terms                                                            [extended model, sec. 4]

**The cache (the GI's, extended - contract C3, separable with replacement):** per surfel the GI already holds `E_indirect` (its shown
light). v2 adds a **cached direct irradiance** `E_direct,cached` per surfel (the GI's `Direct()` at the surfel's centre, updated on the
GI's budget: the lights' change triggers the same relight the links' F has) - a cheap, low-resolution, lagging baseline. Then:

    E_direct(y) = E_direct,cached(y)                                   (the base: every hit, cheap)
    E_direct(y) = E_direct,fresh(y)          where selected (sec. 6)   (a replacement, never an addition)

The GI accessor (the GI thread's note 3) returns, per hit: `E_indirect`, `E_direct,cached`, `rho_d` (triangle albedo, else surfel), `L_e`,
and the epochs/ages of each (lighting, material, geometry). Screen hits and world hits use **one hit-lighting function** over this record
(sec. 6); a screen hit reads its record from the hit texel's instance and triangle (the thin G-buffer gains an instance + triangle id
target - R1), not the composited color.

**Emission exactly once.** Two transports see an emitter: (a) a reflection ray that hits it (`L_e`), (b) the emitter lights (GIEmitterLights)
- lighting's direct term at the receiver *and* at secondary hits. Rule:
- At a **secondary hit**, `E_direct` includes the emitter lights; `L_e(y)` is the hit surface's own emission. Different paths
  (emitter -> y -> receiver vs y's glow seen directly): no overlap.
- At the **receiver** (the first surface), the emitters' light reaches it by both (a) and (b). A partition of unity by the receiver's
  roughness r: weight `w(r)` (1 below 0.2, 0 above 0.4, smooth between - tuned against the reference) on the reflection rays' `L_e` of a
  surfel that is an emitter light (its id is in the emitter view) and `1 - w(r)` on the emitter lights' specular at the receiver; the
  emitter lights' diffuse is always lighting's. A mirror shows the sign's texture, a rough floor the lights' smooth highlight, and a
  roughness-mapped floor (wet patches) has no seam: the two estimates of the same light are weighted, never both whole. (MIS proper needs
  a pdf for the emitter lights' evaluation; a measured upgrade.)
- The sky: the sun is a light, not in the sky map - no overlap. A sky with a sun disc would take the same partition.

## 4. Transport models (declared per sample)

| Model | Secondary hit returns | Known missing | Where |
|---|---|---|---|
| **T0 initial** | `L_e + rho_d/pi (E_direct + E_indirect)` (diffuse + emission) **+ the hit's probe/sky specular** (its F0 x the probe or sky along the reflected direction at its roughness - from the secondary-material record; without it a metal in a reflection is black, rho_d = 0) | The hit's direct highlights; mirror-in-mirror; texture detail below the capture's resolution | R1 - R3a |
| **T1 extended** | T0 + the hit's **direct specular** toward the ray (its lights' GGX at the hit's roughness/F0, from a compact **secondary-material record**: normal, base color, metallic, roughness, emission, flags) + its indirect specular from the probes / layer 1 | Indirect specular of glossy hits is approximate; mirror-in-mirror one level | R3b |
| **T2 later** | A second reflection bounce for mirrors / near-mirrors seen in mirrors | - | measured need |

The secondary-material record is captured with the materials (the GI's capture already renders albedo/emission per surfel and triangle;
it gains roughness/metallic) - no material shader runs at a hit. Texture detail at a sharp reflection's hit is limited by the capture's
texel density: the record says so (an approximation flag), and R5's measured option is reading the material's textures at the hit's UV
for sharp receivers (the bindless table makes it possible).

## 5. Tracing and typed coverage

    TraceResult: HIT_SCREEN_APPROXIMATE | HIT_WORLD_SUPPORTED | MISS_WORLD_COMPLETE | UNKNOWN_COVERAGE | UNKNOWN_WORK_LIMIT

1. **Screen trace** (new, not P3's short march): a min-depth pyramid over the depth (the half-size depth for glossy rays, the full-size
   depth for sharp ones), a constant thickness tuned against the reference, a maximum distance, a screen-edge fade. An accepted hit is
   `HIT_SCREEN_APPROXIMATE` ("on screen through the supported screen-depth approximation": half resolution, thickness, first layer only).
2. **World trace** (the GI's BVH, closest hit): a ray the screen rejected or missed **restarts at its offset origin** - the screen depth
   does not certify the skipped segment (a blocker hidden behind a foreground object) - unless an empty interval is proven (none is, in
   v2). Hits are `HIT_WORLD_SUPPORTED` when the hit instance is in the BVH's coverage (opaque rigid GI meshes, sec. 9's proxies labelled).
3. **A world miss** is `MISS_WORLD_COMPLETE` only when the BVH is complete for the ray's extent (the scene's GI meshes resident, no
   coverage hole - the GI's coverage query, lighting strategy "spatial coverage"); then the sky. A miss through incomplete coverage is
   `UNKNOWN_COVERAGE` -> the probes (never the sky). A traversal cut by its step budget is `UNKNOWN_WORK_LIMIT` -> the probes.
4. **Probes and sky** are fallbacks with their own label; specular occlusion of the fallback from the GI's moments along R (§7b item 1).

## 6. The leap

The structure (trace -> hit records -> shade) is parity: Lumen HW and AMD's hybrid reflections already compact and sort before hit
lighting. What none of the compute-only pipelines has - and what this engine already owns - is below; it is the design's centre.

**6.1 Exact, shadowed many-lights at reflected points.** A reflected street with 4096 lamps shows every lamp's light at the reflected
point with *its own shadow*: the cell's head exactly and the tail by RIS (`LocalLightDemod`), the sun's and the local lights' **virtual
shadow pages** - reflection hits **request pages like the main view** (first-class demand, weighted by how visible the hit is through the
receiver's lobe; a frame late, its own page budget), BVH shadow rays where a page is not resident - and the emitter lights. Lumen SW has
it at card resolution (lagging), Lumen HW pays per light per hit, SSR-based pipelines have only the screen. This is the leap.

**6.2 Glossy reflection reservoirs (ReSTIR with reconnection).** The compute BVH makes rays the bottleneck, so samples are reused: each
half-size texel keeps a reservoir `{y, L_o(y), p, W, age}` - its hit, its outgoing radiance under the declared model, its pdf. Temporal
reuse reprojects it (virtual motion, sec. 8) and **reconnects** x -> y (the hit's diffuse-like T0 term makes the shift cheap); target
`f_s(x, y) L_o(y) cos`; spatial reuse from 3-5 neighbours with one visibility ray each (BVH), or none above roughness ~0.5 (biased,
measured). One ray per texel looks like 8-16; glossy reflections of movers stop boiling. Not for mirrors (a fixed direction gains nothing
from reuse) - they keep one ray and temporal reconstruction. Lumen reuses nothing but its denoiser. ~32 B per half-size texel, 1-3
extra visibility rays per texel; correlation the denoiser must tolerate (measured).

**6.3 Screen hits reuse the main view's shading.** The main pass already shaded every screen point exactly (every light, its shadow, the
GI). The materials write a **demodulated lit-diffuse target** - `rho_d/pi (E_direct + E_indirect)` divided by `rho_d`, plus `L_e` apart
(B10G11R11, full size: one more output of the materials' pass - a layout change and a recompile, the approved pattern) - and a
`HIT_SCREEN_APPROXIMATE` hit reads it times its albedo: exact T0 at no shading cost, and a floor's reflection agrees with the floor's own
shadow. The whole correction budget goes to world hits. (The instance/triangle id target stays for the hit identity, sec. 8.)

**6.4 Shade once per unique hit, not per ray.** World hits go to a per-frame **hit cache** keyed by surfel id (triangle for sharp hits):
the rays that hit one surfel pay one fresh `E_direct` (6.1) - a hash/atomic pass instead of a sort. The selective corrections become
affordable for glossy receivers, where many rays share hits.

**6.5 The cached base and the selection.** Every world hit starts from the cache (T0 with `E_direct,cached`); the fresh `E_direct`
replaces it where `visible secondary detail x hit-shading error` is high - visible detail from the **ray cone** at the hit (the receiver's
roughness and the hit distance against the surfel / page / texel size: also the hit's LOD - surfel, triangle albedo or a texture mip),
error from the cache's age, the lights' revisions since, a penumbra flag. With **hysteresis** (a hit selected stays selected a few
frames) and a history reset through the metadata when it flips - fresh and cached differ visibly, a moving boundary would flicker.

**6.6 Honest samples.** Every sample carries its TraceResult, transport model, fresh/reused/fallback state and its cache's age (sec. 5,
8): good engineering, not a picture by itself - it is what lets the references say *why* a pixel is wrong.

## 7. The estimator

- **Sampling:** GGX **VNDF** with the true shading normal and view (Heitz 2018); the weight `F(v.h) G2/G1`. The **dominant direction** is
  used only for reconstruction (hit-distance tracking, cache queries, the denoiser's virtual motion), never to rotate the sampling lobe.
- **Demodulation:** the resolved radiance divided by the receiver's environment BRDF (`F0 DFG.x + DFG.y`), floored at 1e-3 (a near-black
  factor), multiplied back after denoising - the receiver's factor only; the secondary surface's shading is the hit's (sec. 3/4).
- **BRDF for the correctness tests:** single-scattering GGX in the renderer and the references alike. **Multiple-scattering**
  compensation is a separate, measured BRDF change (R1b): **Turquin 2019** (the specular scaled by `1 + F0 (1/E(mu) - 1)`, E from the
  DFG table) - one formula in the shared BRDF code, the main view's direct specular, the probes and the reflections alike.
- **Roughness:** one sampling scheme over 0 .. 1; the ray budget by roughness (full-size sharp tiles below 0.1, half size above, 1 in 4
  texels rotating past 0.5), the reconstruction wider with roughness. Rough receivers (past ~0.6) may take GI layer 1 as a **labelled
  reconstruction prior**, not a correction.
- **No control variate.** v2 kept it as an experiment (f - c on shared rays, C the integral of c); the reservoirs (6.2) dominate it for
  the same rays, so it is dropped. (Were it ever tried: C must be the integral of c, signed residuals never clamped as radiance.)

## 8. Denoising and stability

The screen tail's machinery (allocation, dispatch, records, the temporal/spatial passes) with specular's own rules:
- **Virtual motion, curvature-aware, never "exact":** the history fetched where the reflection's correspondence was last frame - the hit
  point reprojected through the *reflecting* surface's motion and curvature (ReBLUR's blend of virtual and surface motion by roughness
  and curvature, a virtual-history confidence).
- **Secondary-hit identity:** a world hit carries its instance and that instance's previous transform (the instance slots keep it; the
  skinned pose motion too), so a moving reflected object is reprojected as itself; proxies (sec. 9) without correspondence are rejected
  conservatively (short history).
- **Mirrors:** temporal reconstruction without spatial blur.
- **History:** by roughness and motion (the 4-frame cap for moving texels is a measured setting, not a ghosting guarantee); disocclusion
  short history + a wider spatial pass for a few frames.
- **Fireflies:** clamped against the neighborhood's statistics (positive radiance only; residuals never).
- **Metadata per texel:** fresh / reused / fallback, the TraceResult class, the hit cache's age - accepted history never hides a stale
  cache (an age past its bound shortens the history).
- A hashed seed for the RIS tail at hits makes it repeatable, not exact (structured error): measured against a per-frame seed.

## 9. Backends, guides, dynamics

- **Full-size sharp guides from R1:** the depth prepass writes the normal and roughness at full size for materials classified sharp (by
  the material's roughness range, known before the frame - no current-frame tile list, no circular dependency); the sharp tiles come
  from that target.
- **Planar backend, benchmarked in R0** (for the Police floor likely the best picture per ms without HW RT, skinned movers exact): one bounded planar-reflection view (the scene rasterized mirrored, its own culling and shadow demand)
  for a large coherent planar receiver (a polished floor, water) - against the compute path on Police (ms, quality, skinned movers seen
  exactly). Chosen per receiver region where it wins; not universal.
- **Off-screen dynamics:** skinned/moving objects through a per-frame dynamic BVH of coarse proxies (bone capsules / boxes, the mesh's
  mean albedo), labelled approximate; the planar backend or HW RT where exact matters.
- **Translucent front layer and water:** a nearest-translucent depth pre-pass, one layer (glass over water: the water takes probes).

## 10. Probes: freshness split

They stay the fallback. Two freshness states to start (more when probes matter more): **geometry** (what it captured is still there: a
mover in its box, a door opened, a material recompiled -> recapture) and **lighting** (relit from its captured G-buffer by the lights and
the GI: a lamp off -> relight only; its prefiltered levels rebuilt after either). A probe
weighs nothing until published; its ages are visible. Plus the §7b items. "Surfel lighting is always current" becomes "the cache
publishes an update state and age".

## 11. References, metrics, budgets

- **Two references:**
  1. *Same-model reference*: many samples of exactly the declared transport model (T0/T1, the same cache and captured materials) - tests
     integration and reconstruction.
  2. *Independent small-scene reference*: a CPU path tracer with the real materials (analytic: the test scenes' constant materials and
     a textured one), analytic lights, explicit visibility, 3+ bounces - exposes what T0/T1 miss (glossy hits, texture detail, stale
     lighting, bounce limits).
- **The metric:** relative mean absolute error of the reflection term in **linear HDR**, normalized by the reference's mean over the
  region, pixels below 1e-3 of the region's mean excluded from the denominator, measured **before and after** denoising; per roughness
  bucket (0, 0.1, 0.25, 0.5, 0.75, 1) **and per object mask** (a missing reflected person is its own number, never averaged away).
- **Representative ray benchmarks (R0):** mirror-coherent and rough-incoherent rays; world-only and the SSR-failure distribution;
  traversal alone and with hit shading; warm and cold caches; dynamic BVH maintenance apart; full-size sharp coverage. The budget is
  set from these.
- **Memory ledger:** a resource-lifetime table (each target and buffer: size at 1080p / 4.6 MP, shared with the screen tail or not,
  alive when) and the peak concurrent - 40 MB at 4.6 MP is a hypothesis (32 B per half-size texel is ~37 MB before the pyramid,
  histories, guides, queues, scratch, sharp tiles).

## 12. Phases (never two correctness-changing pieces in one milestone)

| Phase | Builds | Gate |
|---|---|---|
| **R0** | The hit contract and the accessor's spec (with the GI thread), both references and the metric, the representative ray costs, the memory ledger, **the planar backend's benchmark on Police** | Today's error table; the costs; the ledger; planar vs compute |
| **R1** | Sharp guides (prepass), VNDF sampling, the pyramid screen trace, the materials' demodulated lit-diffuse target (6.3) and the id target, the common hit-lighting function (T0 with the hit's probe specular), the resolve, the materials reading it | Screen-hit error vs the same-model reference under 10% (glossy floor, mirror box, **a chrome object**); below the cache's error |
| **R1b** | Multiple-scattering compensation (Turquin), alone | Rough metal vs the independent reference |
| **R3a** | World closest hit from the origin, typed coverage, the cache accessor | Off-screen / behind-the-first-surface error; no sky through a coverage hole |
| **R2** | Specular temporal with secondary-hit identity, curvature-aware virtual motion, metadata | Flicker and moving-camera error at P3's level; movers rigid and skinned |
| **R3b** | The hit cache (6.4) and the fresh direct replacement by selection with the shadow pages' reflection demand (6.1, 6.5); then (separate milestone) T1's restricted secondary specular | Each measured against the references; penumbra error at hits |
| **R4** | Glossy reservoirs with reconnection (6.2); the adaptive budget across roughness | Error at equal ray count vs R3b; effective samples per roughness bucket; continuous error across 0 .. 1 |
| later | Planar backend (benchmark first), relit probes and freshness, off-screen proxies, translucency, water | each its own |

## 13. What changed from v1 and why

| v1 | v2 | Why |
|---|---|---|
| "The surfel radiance already holds direct light" | It holds **indirect only**; the hit contract (sec. 3) with a cached direct term replaced by fresh where selected | v1 was wrong about our GI and would have double counted (cached total + fresh direct) |
| Emission not accounted | Exactly once: secondary hits vs the receiver's partition by roughness (sec. 3) | Traced emission and emitter lights overlap at the receiver |
| Diffuse hit lighting as "correct" | Declared models T0/T1/T2 | Glossy objects seen in a reflection lose their highlights in T0 |
| A control variate on layer 1 (then f - c with C from layer 1) | An experiment with a convergence gate; layer 1 a labelled prior | C must be the integral of c; residuals are signed |
| World trace resumed at the screen exit | Restarts at the origin; typed TraceResult; misses through holes go to probes | The screen depth does not certify the skipped segment |
| Dominant direction for ray generation | Only for reconstruction; VNDF with the true normal | Rotating the lobe changes the pdf |
| MS compensation inside the first correctness phase (both names) | Turquin, its own milestone after single-scattering tests | One correctness change at a time |
| "Virtual motion exact", mirrors not denoisable, a fixed cap against ghosting | Curvature-aware, never exact; hit identity; mirrors temporal-only; metadata | Over-promises |
| Full-size mirror guides in R4 | From R1, from the prepass by material class | R1's mirror gate needed them |
| One reference (same cache) | Two, a defined metric, per-object masks | The same-cache reference cannot test the cache |
| One random-ray benchmark, 40 MB | Representative benchmarks; a lifetime ledger | The budget depends on the ray mix |
| Relit probes "never stale" | Four freshness states | Relighting cannot reveal geometry |
| The "one estimator" as the leap | Tracing separated from hit shading, selective corrections | Coherent shading, honest metadata |

**v2 -> v2.1 (Fable's challenge, 2026-10-28: "clearly better, not just correct"):**

| v2 | v2.1 | Why |
|---|---|---|
| The leap = hit records + sorting + selective corrections | The leap = **exact shadowed many-lights at reflected points** (6.1) + **glossy reservoirs** (6.2); records/sorting are parity | Lumen HW and AMD hybrid already sort; the shadowed many-lights at hits is what we own and they lack |
| Shadow pages at hits "a measured option" | First-class reflection demand on the pages, BVH rays where not resident | It is the differentiator |
| No sample reuse (stochastic VNDF + denoiser, 2015-class) | ReSTIR with reconnection for glossy; the control variate dropped | On a compute BVH rays are the bottleneck; reuse is 10-30x effective samples |
| Screen hits re-read the cache | The materials' demodulated lit-diffuse target: exact T0, free | The main view already shaded those points |
| A sort/bin pass | A hit cache keyed by surfel: one fresh evaluation per unique hit | Cheaper, and makes the corrections affordable |
| Emission partition at 0.3 | A blend band 0.2-0.4 (partition of unity) | A roughness-mapped floor showed a seam |
| Selection by error, no memory | Hysteresis + a history reset on a flip | Fresh vs cached differ visibly: flicker |
| T0 = diffuse + emission | + the hit's probe/sky specular | A metal in a reflection was black |
| Planar backend "later" | Benchmarked in R0 | Likely best per ms for Police's floor |
| Four probe freshness states | Two to start | Over-engineered before probes matter |
| Rejected from the challenge | Per-surfel specular lobes (spherical Gaussians), a point+direction reflection cache, hit-space denoising | Small terms for their memory/relight cost; the surfel cache is the world cache; virtual motion already covers it |

## 14. Open questions for Tomas
1. The hit contract C3 (a cached direct term per surfel, replaced by fresh where selected) needs the GI to cache `E_direct` per surfel -
   lighting writes that accessor as with the BVH and the emitter view?
2. The emission partition at the receiver as a roughness blend (0.2-0.4): acceptable until an MIS version is measured?
3. The planar backend as a benchmarked option (it renders skinned movers exactly in a floor or water) - worth the second view's cost?
4. Off-screen skinned movers: proxies (approximate) or wait for HW RT?
5. The budget set after R0's measurements (not promised before) - agreed?
6. The materials' extra output (the demodulated lit-diffuse target, 6.3: every material recompiled, ~18 MB at 4.6 MP) - worth it for
   exact, free screen hits?
7. The reservoirs (6.2) as R4's leap - accept their correlation artefacts (measured) for 8-16x effective samples?
