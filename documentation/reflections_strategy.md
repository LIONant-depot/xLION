# Reflections strategy (v4.1 - the implementation contract, 2026-10-28 - being built)

Tomas (2026-10-27): "the diffuse seems working but specular / reflection proves is lacking ... lets design it first, make sure we aim to
leap over our competition again"; (2026-10-28) "this is the last round of feedback ... after that we are ready to start". v1 -> v2 -> v2.1
-> v3 -> **v4**: v4 folds the final external review (sec. 13 lists each correction and where it landed) and freezes the architecture.
What is built is what this document says; a deviation is a change to this document first. `R/` =
`example.lionprj/Cache/dependencies/xLIONRender/src/`.

**The rule:** cache what is direction-independent, sample what is expensive with guaranteed support, re-evaluate what changed, never let
a supported hit pass for complete visibility, and never claim a decomposition the data does not hold. Every sample carries its transport
model (sec. 3), its hit and prefix classes (sec. 4), the quantity it returns and its approximation state (fresh / cached / fallback, ages).

**The target picture** (the acceptance of the whole): Lily correctly reflected in Police's floor; a chrome object keeping the secondary
highlights of the lights it reflects; a lamp switched off disappearing from every reflection within a measured number of frames and
without ghosts; a documented, bounded cost on the declared GPU.

## 1. What we have (facts) and what the competition does

| Piece | Where | Fact used here |
|---|---|---|
| Direct specular of the lights | `R/shaders/xlionrender_local_lights.glsl`, `xlionrender_shadow_vsm.glsl`, the screen tail (`xlionrender_tail_screen_frag.glsl`, `_denoise_comp.glsl`) | Every light's GGX at the first surface, shadowed: sun and local virtual shadow pages (request pass `xlionrender_vsm_request_comp.glsl` from a depth + clip-to-world), the tail by RIS over the cell's lights with a one-tap visibility, screen trace, BVH ray; the emitter lights (GIEmitterLights) |
| Light cells | `R/features/lights/xlionrender_light_cells.h`, `_comp.glsl` | A camera-centred **world** clipmap of light lists (head exact + tail distribution), GPU-built: any world point inside it has a cell |
| Sky, probes | `xlionrender_environment.glsl` `EnvSample`, `ProbeAdd` / `ProbeBoxProject` | Split-sum atlas + DFG; box-projected static captures that hold *everything* they saw (emitters, highlights, walls) - no transport decomposition |
| GI | `R/features/gi/xlionrender_surfel_gi*.h`, `gi_*.glsl` | Surfels hold indirect irradiance only; the links (E = D + F + T E) relight on light revisions / `m_FrameChanged`; the triangle BVH over opaque rigid GI meshes (`getBvh`), a spatial coverage query owed; captured albedo and emission per surfel and triangle; the emitter view; `Direct()` at a hit |
| Instances | `R/xlionrender_instance.h` | Slots keep the previous transform (motion), skinned previous bones; `m_FrameChanged` lists this frame's moved bounds (old and new boxes) |
| Reflections | - | **none**: probes and sky only. Lily is not in the floor; movers never reflect; a mirror is impossible; a probe keeps a lamp that is off |

Competition (read in E:\source_code and the papers; v2.1's table, kept short): Lumen traces to roughness 0.4 and lights hits from its
surface cache (card resolution, budgeted updates) or HW hit lighting; AMD / Frostbite SSSR and hybrid reflections take screen colour, then
probes; Capsaicin a hash-grid radiance cache; ReBLUR's virtual motion is the reconstruction reference; RTXDI has world-space light sampling
for secondary surfaces (ReGIR) and reservoir resampling. **No claim of beating anyone:** every comparison in this document is a measured
quality / time / memory number on the declared GPU (sec. 11). Our opportunity is the integration: one world light structure, one shadow
residency, one software BVH, one surfel cache with ages - at the first surface and at the hit alike.

## 2. The hit contract: D(y) + S(y, wo)

    L_o(y, -w) = D(y) + S(y, -w)
    D(y)       = L_e(y) + rho_d(y)/pi ( E_direct(y) + E_indirect(y) )        direction-independent: cached per surfel, shared by rays
    S(y, -w)   = SecondaryDirectSpecular(y, -w) + SecondaryIndirectSpecularApprox(y, -w)   re-evaluated toward the actual receiver

A stored total L_o is never reused across receivers. **E_direct(y)** (v4.1): B evaluates it **fresh at the hit** - the sun with one
BVH shadow ray, the hit cell's head lights shadowed from VALID resident pages at y (`LocalLightShadow`), else one capped BVH ray for the
brightest head light without a page, else omitted (a labelled under-count, never unshadowed); `E_indirect` from the GI surfel read at
the hit; `L_e` from the capture. `E_direct,cached` per surfel (the GI's `Direct()` at the centre, its own validity and age) is built in
E as the exhaustion fallback and the > 0.6 path's term. Replacement, never addition.

**Four records, one owner each:**
| Record | Fields | Owner |
|---|---|---|
| Surface | instance id + generation, triangle, barycentrics, Ng / Ns, the captured material approximation (base colour, metallic, roughness, emission, flags: see-through, emitter, proxy, deformed) | trace (the hit), the GI's capture (the material) |
| Lighting | `E_direct,cached`, `E_indirect`, `L_e`, state VALID / STALE / REBUILDING, ages (lighting, material, geometry epochs) | the GI |
| Directional evaluation | S(y, -w) for this receiver: the lights evaluated at the actual hit with their visibility class, the environment term with its label | hit lighting, per ray |
| Reflection sample | endpoint (finite: instance-local; or a true environment direction), estimator state (pdf, W, M, confidence), hit + prefix class, model, fresh / cached / fallback, current validity, history provenance | trace, reconstruction, (optional) reservoirs |

## 3. Transport models and radiance ownership

| Model | Secondary hit returns | Known missing |
|---|---|---|
| **T0** | D(y) + SecondaryIndirectSpecularApprox | the hit's direct highlights; mirror-in-mirror; texture below the capture's density (flagged) |
| **T1** | D(y) + **SecondaryDirectSpecular** (the hit's lights' GGX toward -w, shadowed as sec. 6) + SecondaryIndirectSpecularApprox | glossy hits' indirect specular approximate; one mirror level |
| T2 | a second specular bounce | earns its place (sec. 12) |

**Ownership (the review's main correction, adopted verbatim in substance):**
- *T1's secondary direct specular is evaluated explicitly.* The path receiver -> y -> lamp is secondary direct; receiver -> y -> another
  surface -> lamp is secondary indirect: different paths, no overlap between an explicit T1 and a *true* indirect term.
- *Secondary probe specular remains an approximate additional-bounce estimate* - a combined probe texel cannot be decomposed (an
  emitter's glow, a lamp's highlight on a wall, diffuse light, sky all mixed); **no per-light subtraction and no occlusion-ratio
  "decomposition" is claimed** from it. Its overlap with T1 (the probe also saw the lamp's highlight on y's neighbours, and the lamps
  themselves) is a **labelled overlap approximation**, reported as bias on the chrome and lamp scenes.
- **Diagnostic mode** `SecondaryProbeSpecular = off`: T1 alone (an under-count, labelled); the two modes bracket the reference. Should a
  capture with a transport decomposition (a separate emissive component) ever exist, it replaces the label - sec. 12.
- Restricted secondary specular from B: T1's lights at the hit are the hit's cell head (the sun + K key lights); the tail at the hit
  comes with sec. 6's sampling. The secondary-material record (roughness, metallic added to the GI's capture) comes with B; no material
  shader runs at a hit.
- **Turquin's compensation** `1 + F0 (1/E(mu) - 1)`: one formula in the shared BRDF, the main view, probes, secondary hits and references
  alike; its own milestone (B2). Until then single-scattering GGX everywhere, references included.

## 4. Tracing: hit class and prefix class, separate

    HitClass:    HIT_SCREEN_APPROXIMATE | HIT_WORLD_SUPPORTED | HIT_PLANAR_SUPPORTED | MISS_WORLD | NONE_WORK_LIMIT
    PrefixClass: PREFIX_COMPLETE | PREFIX_INCOMPLETE { coverage hole | unrepresented caster | screen-only | step budget | log expired }

1. **World trace** (the GI's BVH, closest hit from the ray's offset origin; a screen-rejected segment is never skipped). The prefix is
   `PREFIX_COMPLETE` only when the GI's coverage query says the extent is resident **and** the prefix crosses no box of an instance the
   BVH does not represent (sec. 7's change log holds those boxes).
2. **Screen trace** (min-depth pyramid, thickness, max distance, edge fade): an acceleration for glossy receivers only, always
   `PREFIX_INCOMPLETE (screen-only)`; never the mirror path. It is *not* a world hit: its Q is the screen texel's current material and
   normal, a world hit's record is the capture's - the **discrepancy is measured** (C), not assumed zero.
3. **Planar view** (sec. 8): `HIT_PLANAR_SUPPORTED` - geometrically complete for the mirrored view's frustum and depth range (its
   coverage limit, labelled); its shading carries the same approximations as the main view (coarse pages, the GI, finite resolution).
4. **Mirror path** (sharp receivers, r < 0.1) = a planar hit or `HIT_WORLD_SUPPORTED + PREFIX_COMPLETE`; anything else on a sharp
   receiver is approximate: short history, fallback weight.
5. **Misses:** `MISS_WORLD + PREFIX_COMPLETE` -> the sky (a true environment direction). `PREFIX_INCOMPLETE` or `NONE_WORK_LIMIT` ->
   the probes, **evaluated outside any reservoir** as a labelled fallback (receiver- and probe-dependent, not a path).
6. **`PREFIX_INCOMPLETE` changes confidence, history length and the fallback choice. It never attenuates radiance.**

## 5. The pass graph (no cycle) and the composite's units

    1  depth prepass + sharp guides (full-size normal, roughness, F0, flags for materials whose roughness range is sharp)
    2  VSM requests from the main depth -> admission -> page render                    [existing]
    3  GI update: surfels, links, BVH valid for the frame, coverage query, change log (sec. 7)
    4  the thin G-buffer (the tail's G-buffer variants: the mapped normal, roughness, depth, motion; Q in C)
    5  reflection trace: VNDF -> [screen] -> world -> Surface record, classes                          [before the scene pass]
    6  hit lighting: D fresh at the hit (sec. 2); S toward x; the planar view resolves into U where it covers
    7  reconstruction on (wL, w) (temporal with virtual motion, spatial), U = wL / w   [optional reservoirs: F]
    8  materials' pass (opaque): EnvLighting's specular = mix(probe, U, conf) x B at full res      [the one owner]

**Units (v4.1, the composite is EnvLighting).** `U(x)` = the lobe-mean incident radiance: `sum(w_i L_i) / sum(w_i)`, `w = G2/G1` of
the VNDF samples, F excluded; the trace stores `(wL, w)` (RGBA) and reconstruction filters both, dividing after (one ray a texel: a
filter of L alone converges to E[L], not E[wL]/E[w]). `B = F0 DFG.x + DFG.y` (the DFG table is E_VNDF[F G2/G1]) is applied **once**,
by the material at full resolution, so the receiver's normal, roughness and F0 are the material's own - no stored receiver state, no
division by B. The same-model reference integrates the same split form; the split's F-L correlation bias (zero for metals and sharp
lobes, a few % of a small term for rough dielectrics at grazing) is reported once on the independent reference. `conf` blends to the
probe where U is missing (depth / plane-distance mismatch in the upsample, blended materials, every view but the main one: probe
captures and the mirrored view bind a zero-conf U - sec. 8's no-feedback test). **Tests:** a constant environment of radiance L gives
U = L, `B L` on screen (the probes, the planar path and the traced path alike); a metal mirror's per-sample `B L` against `F G2/G1 L`
within 1e-3; the debug view shows `U B`.

**Q on metallic pixels:** Q is the irradiance sum whatever the material's rho_d; a material that skips its diffuse term still evaluates
and writes Q (its lights' irradiance, the GI's). Blended / translucent materials keep the probes in their shader, labelled; pass 9 is
for opaque. Any previous-frame source is flagged approximate.

**Estimator.** GGX VNDF with the true normal and view (Heitz 2018), weight `G2/G1` (F is B's); the dominant direction only for hit-distance
and virtual motion. Budget: sharp full-size tiles, one ray; glossy half size, one ray; past 0.6 one ray per 4 texels rotating with GI
layer 1 as a labelled prior. One scheme over 0..1.

## 6. Fresh lighting at the actual hit: support-guaranteed sampling

At a world hit y selected for the fresh term (selection: `visible detail x error` - the ray cone against the surfel radius, the
Lighting record's age and state, light revisions since, a penumbra flag; hysteresis of a few frames; a history reset on a flip):

- **Head:** the hit's cell head (the world clipmap gives any point inside it a cell: the main view's `LocalLightUnshadowed`, `SunShadow`,
  `LocalLightShadow` at y, unchanged code). Outside the clipmap: no cell -> the cached D only, labelled.
- **Tail, with guaranteed support.** The proposal is the known-pdf mixture
  `q_mix(l | y) = (1 - eps) q_shared(l | s) + eps q_safe(l | y)`: `q_shared` the cell tail's distribution at the hit (the existing RIS
  candidates' weights, or - optional, sec. 12 - a surfel's shared proposal), `q_safe` a distribution with **nonzero probability for
  every tail light that can contribute at y** (uniform over the cell's tail list), eps = 0.1 to start. Every contribution is divided by
  the **actual** `q_mix` - no light that is dark at a surfel's centre (a spot cone cutting the surfel, range, an opposite normal, centre
  shadowed, newly enabled) is lost; it is only sampled less often. Importance is evaluated **at the actual hit**.
- **Visibility is evidence only where measured:** the shadow at y from a VALID page or a BVH ray (sec. 9's limits). Cached centre
  visibility may *guide* the selection; it is **not** visibility at y. If the hit has no fresh visibility, the sample returns the
  light omitted, labelled (B) / the declared cached baseline (E: D with `E_direct,cached`) - no hybrid of a hit's falloff times the centre's shadow, unless declared as its
  own approximation and measured (not planned).
- A finalized reservoir's W is not a selection pdf; if a reservoir ever feeds a proposal (sec. 12), it follows RTXDI's combination
  rules, never `q_mix`'s division.

## 7. Visibility reuse: epochs and a bounded change log

Reusing a validated segment (a path's V(x, y), an environment direction's V_inf, a temporal history's correspondence) is safe only when:
the same segment, the same visibility semantics, no relevant scene change since its **last validation**, no change in representation
coverage. Mechanism, small first:
- A **visibility epoch** counter and a **bounded change log** (N frames deep) of every instance change relevant to reflection
  visibility - not only shadow casters: moved / deleted / created instances with **old and new bounds**, deformation (skinned: always
  changed), alpha-test or visibility-flag changes, streaming, a BVH coverage change, a see-through change. The log is the instance
  table's change list (`m_FrameChanged` extended), so it costs what the shadow pairs already pay.
- A sample stores the epoch of its last validation. Reuse: walk the log from that epoch; any box crossing the segment -> retrace (or the
  sample is dropped); if the epoch is older than the log -> **retrace** (`log expired`). Either endpoint moving changes the segment ->
  retrace, unless a conservative segment-equivalence rule is declared (none in B-E).
- **Two certificates**, separately: *geometry* (the segment unchanged) and *lighting* (the endpoint's Lighting record age and the light
  revisions since: a lamp switched off changes radiance with no box moving). A sample is reused only with both; a lighting change
  re-evaluates radiance without a retrace.
- The same log supplies sec. 4's "boxes of unrepresented instances" for the prefix class.

## 8. Backends: a complete path per receiver class

| Class | Trace | Lighting | Reconstruction | Dynamics | Fallback |
|---|---|---|---|---|---|
| **Planar, smooth** (Police floor, water; r < 0.1 over a plane) - **first** | the planar view: the scene rasterized mirrored in the plane and clipped to it, bounded to the receiver's screen extent, its own culling, its depth through the VSM request pass (sec. 9's limits) | the main view's materials at the mirrored pixels: T1 complete by construction; resolved into U (receiver point -> mirrored projection; nothing drawn -> conf 0); the mirrored view binds conf 0 (no feedback); the fetch is at the plane's mirror direction (a normal-mapped receiver's offset is rough planar's), labelled | a filter for the finite image (the main view's AA, no stochastic denoiser) | **skinned movers drawn** | - |
| Planar, rough | the same image filtered by the receiver's roughness and the mirrored depth | same | the filter | same | **after** a comparison with the world-ray reference (filtering an ideal image cannot reveal surfaces the ideal view lacks; it is an approximation, labelled) |
| **Sharp non-planar** (chrome) | full-size world rays from the guides | D fresh + restricted T1 (B) | temporal, no spatial blur | unrepresented -> `PREFIX_INCOMPLETE` | probes |
| **Glossy** (0.1..0.6) | half-size VNDF, [screen] then world | D fresh + S | temporal + spatial, virtual motion by roughness and curvature | sec. 7 | probes |
| Very rough (> 0.6) | 1 ray / 4 texels | D fresh (B), cached from E | wide spatial + layer 1 prior | - | layer 1 |
| Off-screen dynamics | the skinned triangle BVH **if** its benchmark passes (sec. 11) | - | - | explicit `PREFIX_INCOMPLETE (unrepresented caster)`; the planar view where the receiver is planar | probes, short history |

**Planar acceptance tests:** reflection-plane clipping (nothing behind the mirror plane drawn), mirrored winding / culling, and **no
feedback** (a reflective receiver drawn in the mirrored view takes its probes, never the reflection result). `HIT_PLANAR_SUPPORTED`
keeps geometry coverage (the frustum and depth range) and shading approximations as separate labels. Planar ships after B.

## 9. Shadow demand at hit positions: hard limits

The hit-position buffer (half size, the footprint from the ray cone) runs through the existing request shader a frame late. Per hit the
report records **desired LOD** (the projected reflection footprint), **admitted LOD** (budget, residency) and **the approximation
used**; coarse is a label, not a rule - a glossy receiver's near, high-contrast hit may desire a fine page.
1. Admission at most 25% of the frame's page budget (tunable), after the main view; its protected classes untouched.
2. Residency AND validity: a resident STALE page counts as absent.
3. Directional coverage: outside the finest resident levels -> the pinned coarse pages, labelled; no requests beyond the main view's levels.
4. Cold cache: a light without a VALID page at y takes the capped BVH ray or is omitted (B) / the cached term (E); fresh starts when its pages are VALID.
5. The sun's BVH ray per hit inside the frame's ray cap (N from A's benchmark); over it the hit is NONE_WORK_LIMIT.
6. Exhausted -> B: the probes via NONE_WORK_LIMIT; E: the cached term, labelled; never black, never unshadowed.

## 10. Emitters: ownership, exactly once

| Light source | At the receiver x | At a secondary hit y | Identity |
|---|---|---|---|
| Analytic lights | lighting's direct term; not in any reflection | E_direct (cached / fresh) + T1's S | `local_light::m_Handle` |
| Emissive geometry, **traced endpoint identified** (the hit is an emitter surfel) | traced `L_e(y)` weight `w(r)`; the emitter lights' specular weight `1 - w(r)` | E_direct includes the emitter lights; `L_e(y)` is y's own glow - different paths | the emitter view's surfel id, instance + material region |
| Emissive geometry, **not identifiable** (a probe fallback, the sky) | the emitter lights' specular whole; the probe keeps whatever glow it captured: a **labelled overlap approximation** - no w(r) on a probe, no global probe fade | the hit's probe term likewise | the capture's emitter generation; a probe older than the emitter view is STALE |
| Proxy replacement (if ever) | the proxy's mean emission, approximate | - | the proxy's instance |

`w(r)`: 1 below 0.2, 0 above 0.4, smooth between - **temporary**, a partition of unity, applied only to identifiable traced emissive
endpoints; its bias reported on the ramp test; MIS (a disc pdf for the emitter lights) earns its place (sec. 12). Tests: textured sign
in a mirror (texture visible, energy within 5% of the emitter light's); roughness ramp under the sign (no seam, the bias curve); near
field (10 cm); occlusion (a box between); switching (both legs off within the emitter generation's latency, in frames).

## 11. References, metrics, benchmarks - the declared GPU

Every number in reports states **GPU, resolution, scene, build (Release)**. The declared GPU is the development machine's (the lighting
RTX 4070 Ti SUPER, Vulkan 1.4); a gate passed on another GPU is recorded as such, not as passed.

- **References:** (1) *same-model*: many samples of the declared model with the **frozen approximation state** (the surfel cache, ages,
  page residency, captures snapshotted) - integration and reconstruction only; (2) *independent*: the CPU path tracer on small scenes
  (real materials, analytic lights, explicit visibility, 3+ bounces) - what the model misses.
- **RMAE** `= mean |a - r| / max(mean r, L_floor)`, dark pixels **included**, `L_floor` an absolute radiance per test (default 1e-3 of the
  test's exposure reference), linear HDR, before and after reconstruction, per roughness bucket and per object mask.
- **Dark-leak** over pixels with `r < L_floor`: `mean max(0, a - r) / L_floor`.
- **Bias vs variance:** bias = the mean over **repeated independent runs** (or a converged mean) minus the reference; variance apart;
  reconstruction error apart (before / after); the approximation state frozen for every estimator comparison. One residual is never a
  bias.
- **Temporal:** `E_t = A_t - R_t`; **flicker** `T_t = mean |E_t - W(E_t-1)|` with W the declared correspondence (the receiver's motion
  for surfaces, the virtual motion for the reflection); **lag** = frames after a switch until the error is under 1.5x the still error;
  **ghosting** = error inside the mover's previous mask. Sequences (120 frames): an orbit; a mover crossing; a **fixed-camera light
  switch**.
- **Invariants** (each a test): constant environment (sec. 5's units); light-intensity scaling (double a light -> double its unclamped
  reflection); zero radiance (no light in a black scene from fresh lighting, stale histories, probes or emitter ownership).
- **Adversarial scenes:** a big triangle across a hard shadow; two receivers seeing one shiny surface; an omitted skinned mover before a
  supported wall (`PREFIX_INCOMPLETE` on every ray through her box; coverage label only - her appearance is the planar path's test);
  a textured emitter on a ramp; a lamp off; off-screen geometry outside shadow coverage; tiny sharp roughness patches (the guides'
  tiles, the seam); page exhaustion.
- **Benchmarks (A):** mirror-coherent and rough-incoherent rays, world-only and after the screen trace, traversal alone and with hit
  lighting, warm and cold; the planar view's ms on Police; the sharp guides' prepass cost; **the skinned BVH's full cost**: skinning
  inputs, refit, TLAS update, sync, traversal quality (its leaf fatness) against the rays' cost - a target of 0.3 ms on the declared
  GPU for Lily alone, the whole chain counted; the memory ledger (each target at 1080p / 4.6 MP, shared with the tail or not, alive
  when; the peak).

## 12. Milestones (entry / exit on the declared GPU) and what earns its place

| | Builds | Entry | Exit gate |
|---|---|---|---|
| **A** Contracts, benchmarks | records and the GI accessor spec (with the GI thread); references, metrics, invariants, adversarial scenes; the pass graph in the plan; ray / planar / guides / skinned benchmarks; the ledger | this document | today's error table; the costs; planar vs compute on Police; the ledger; the budget numbers for B-E |
| **B** Planar + plain world reflection (**the baselines, preserved**) | the planar view (smooth receivers) with its three tests; sharp guides; VNDF; world closest hit; hit + prefix classes with the change log's boxes; D fresh at the hit (sec. 2); T0 + restricted T1; U into EnvLighting with its units (sec. 5); one ray per texel, no reuse | A's gates | chrome and mirror box < 10% RMAE vs same-model; dark-leak < 1%; invariants pass; the omitted mover labelled; **Lily in the floor** via planar; cost table. **Scope:** supported rigid geometry exact to the model, unsupported dynamics labelled; skinned accuracy is the planar path's or sec. 11's benchmark's |
| **B2** | Turquin, consistently | B | rough metal vs independent |
| **C** Screen acceleration | pyramid trace (glossy), Q from one material variant, id target | B | glossy floor at lower ms with the **screen / world discrepancy measured** and under the same-model gate; Q's per-material cost before any migration |
| **D** Reconstruction | specular temporal (virtual motion, secondary-hit identity), spatial, metadata, the roughness budget, the visibility epoch for histories | B (C independent) | flicker / lag / ghosting on the three sequences at P3's level; continuous error over 0..1 |
| **E** Fresh lighting at hits | `E_direct,cached` with validity and age (the exhaustion fallback); hit-position requests with the limits; `q_mix` with `q_safe`; selection with hysteresis; the lighting certificate | B, D | penumbra error vs independent at **equal total time** against D (visibility rays counted); exhaustion keeps the cached term; a lamp off disappears from every reflection within the measured lag, no ghost |

**Earns its place** (each optional; each only after the plain path is correct; each wins or is dropped at equal total GPU time):
| Candidate | Condition to build | Gate |
|---|---|---|
| Surfel light proposals (a per-surfel `q_shared`, RTXDI's ReGIR shape on our surfels) | E's per-hit RIS is the bottleneck on the dense lab | lower error at equal time; the centre-vs-hit bias on the big-triangle scene under the per-hit variance |
| Glossy path reservoirs (sec. 12.1) | D's plain path validated; the unresampled estimator passes B's gates | sec. 12.1's gate |
| Skinned triangle BVH | sec. 11's full-chain benchmark within 0.3 ms | off-screen Lily vs independent; else capsules as a distinct, labelled approximation |
| Rough planar | smooth planar shipped | vs the world-ray reference on Police's floor |
| Emitter MIS, textures at the hit, a decomposed probe capture, relit probes, T2 | a measured need | each its own |

**12.1 Glossy path reservoirs - the fenced experiment, specified so it can be judged.** Scheme: **GRIS / RTXDI ReSTIR PT** for one-vertex
paths x -> y, its normalization intact; every extra heuristic labelled below and measured on its own. **No blanket unbiasedness claim.**
- *Endpoints:* finite (instance-local: instance + generation, triangle, barycentrics) or a **true sky miss** (an environment direction).
  Probe fallbacks (unknown coverage) are **not** reservoir samples: evaluated outside, labelled.
- *Measures and targets.* VNDF pdf `q_w`; finite endpoints in area measure `q_A = q_w |n_y.-w| / |y - x|^2`. The RGB integrand
  `f_A(x, y) = f_s(x, wo, w) L_o,model(y, -w) V(x, y) |n_x.w| |n_y.-w| / |y - x|^2`; the **scalar target** `p^_A = lum(f_A)` (luminance
  informs the target; it is not the integrand), floored at `p^_min` (= 1e-6 of the receiver's mean) so a zero target gives weight 0 and no
  division. Sky directions keep solid angle: `f_w = f_s L_sky(w) V_inf |n_x.w|`, `p^_w = lum(f_w)`. The two domains never shift into each
  other.
- *Stored:* the endpoint, `W = (1/p^(Y)) sum_i w_i`, `w_i = m_i p^(y_i) / p_i`, M, confidence c, the validation epoch, current validity.
  *Reconstruction:* the RGB estimate is `f(Y) W` in Y's measure, converted to the composite's `R^` (the geometric terms cancel into the
  solid-angle integrand); `U = R^ / B` as sec. 5.
- *Shift:* reconnection x' -> x with y fixed - **Jacobian 1 only for a static endpoint or a rigid, area-preserving motion** (the
  instance's transform delta applied to y); non-uniform scale and deformation (skinned) are **rejected** as reuse candidates until their
  mapping is implemented and tested. The target is re-evaluated at x; V(x, y) by one BVH ray per spatial candidate, by sec. 7's log for
  the temporal one.
- *Four rejection cases, each with its own normalization:* (i) valid candidate, zero current contribution (newly occluded): kept in the
  MIS normalization with `p^ = 0`; (ii) invalid mapping (instance destroyed / regenerated): removed from the candidate set, its M not
  merged; (iii) outside the supported domain (deformed endpoint, a shift across domains): never a candidate; (iv) discarded by a
  numerical or compatibility heuristic (normal > 25 deg, depth > 10%, c < 0.25): **a labelled heuristic that biases**; measured with and
  without. M capped at 20 temporally, 3-5 spatial candidates.
- *Metadata:* **current validity** (endpoint alive, this frame's classes, the lighting certificate) separate from **history provenance**
  (the ages and classes merged over time, used only to limit trust, never to poison the current result).
- *Order:* the unresampled estimator first (B, D), temporal reuse, then spatial (RTXDI's advice).
- *Gate:* at equal total GPU time against D (reservoir passes and visibility rays counted): lower RMAE before and after reconstruction on
  the glossy floor, the mover crossing and the fixed-camera lamp switch; the error's autocorrelation at lags 1-4 reported; the two-receiver
  scene unbiased (repeated runs); the zero-radiance invariant. Fails -> dropped, D stays.

**12.2 Milestone A's results (2026-10-28; RTX 4070 Ti SUPER, Vulkan 1.4, Release, validation off).**
- **Built:** `tests/xlionrender_test_metrics.h` (RMAE with the absolute floor, dark-leak, the error's flicker, bias / noise from repeated
  runs; self-tested); `scene::m_bDebugReflection` (every lit pixel shows R^ = U B; bitwise neutral otherwise, A/B on seven test
  programs, 1023 + 861 + 24 + 16 + 12 + 4 + 3 images); `tests/xlionrender_test_reflections.cpp` (the invariant, the independent
  reference, today's table); `shaders/xlionrender_refl_trace_comp.glsl` + `instance::m_ReflTraceBench` (XLION_REFL_BENCH; the trace's
  skeleton, pass 5) and `smoke/bench_reflections.py`; the GI read spec (lighting_gi_interface_notice.md).
- **The constant-environment invariant holds today:** the renderer's sky / probe specular against L E[F G2/G1] (VNDF, 2048 samples a
  pixel), four spheres: chrome 0.38%, rough gold 0.36%, glossy dielectric 0.34%, rough dielectric 1.04% RMAE; mean ratio 0.996-1.000.
  The split-sum and its DFG table are right; no factor is missing or doubled.
- **The independent reference:** a CPU path tracer over the GI's BVH (the renderer's sky formula, sun, lamp falloff, BRDF), 64 samples
  a pixel in 0.6 s on one thread for the lab (128 x 128); its own runs agree within 3% (16 against 64 samples).
- **Today's error table** (the lab: a chrome sphere, a rough gold one, a glossy floor, coloured walls, a glowing sign, the sun, a lamp;
  RMAE of R^, dark-leak 0 everywhere):

  | Receiver | Sky only | Sky + one probe |
  |---|---|---|
  | floor | 1.23 | 0.52 |
  | chrome | 0.43 | 0.58 |
  | rough gold | 0.31 | 0.52 |
  | all | 0.64 | 0.55 |

  Nothing of the scene is reflected; the probe helps the floor and hurts the spheres (a probe in an open scene captures **black** where
  the sky is: the sky is drawn into a capture only when it is visible).
- **The world trace (pass 5's skeleton), Police maximized** (the trace half size, 1574 x 756 rays; nothing compiling):

  | Rays | GPU ms | Mrays/s | Hits | BVH visits a ray |
  |---|---|---|---|---|
  | mirror (coherent) | 1.12 | 1059 | 100% | 14.7 |
  | roughness 0.5 (incoherent) | 1.85 | 606 | 100% | 14.7 |
  | the materials' roughness | 1.87 | 483 | 100% | 14.5 |

  The budget for B: the closest hit plus the sun's ray at a hit (an any-hit walk, cheaper) about 3-4 ms half size on Police; sharp
  tiles at full size cost 4x their area. Bistro's preview reported no BVH (to see in B: the over-cap chunks or the placeholder BVH).
- **Found and fixed on the way:** `xprim_geom::uvsphere`'s normals were `(x R w S, y / S, z R w S)` - right only for a radius of 1, up
  to 37 degrees off for every test sphere (radius 0.5); now the ellipsoid's gradient, unit (a mirror's rays no longer re-enter it).
- **The memory ledger** (new targets; 1080p / maximized 3778 x 1600): the trace's (wL, w) RGBA16F half size 4.1 / 12.1 MB, its
  temporal history x2 8.3 / 24.2 MB, the hit record (16 B, fused into the hit lighting when it fits: 0) 8.3 / 24.2 MB, sharp tiles at
  full size worst case 16.6 / 48 MB (budgeted by tile), the planar view's HDR + depth worst case 24.9 / 72.5 MB (bounded to the
  receiver's extent). The thin G-buffer is the screen tail's (shared).
- **Not measured in A (owed):** the skinned refit (needs the refit; earns its place), the planar view's ms (it is B's first build), the
  sharp guides' prepass (B builds them).

**12.3 Milestone B's results (2026-10-28; the same GPU and settings).**
- **Built** (xLIONRender c0c9fba .. c572617): the world trace with fresh hit lighting from the GI's model (B1); the planar view -
  the scene mirrored in the floor's plane, oblique near plane, resolved 1:1 into the records (B2a), the floor found through the GI's
  geometry and the Environment's settings (B2b), its coverage-weighted pyramid for rough planar receivers (B2c); the hit's own
  specular (T1 restricted) and the sharp receivers at full size (B3); PREFIX_INCOMPLETE for rays crossing drawn things the BVH does not
  hold (B4). Police's test content: the floor's material more reflective, a sphere grid (dielectric / metal x roughness 0 .. 1).
- **The lab against the independent reference** (RMAE of R^ | dark-leak; xlionrender_test_reflections):

  | Receiver | today (probes / sky) | traced | + the floor's planar view |
  |---|---|---|---|
  | floor | 0.937 / 0 | 0.355 / 0 | **0.259** / 0 |
  | chrome | 0.429 / 0 | **0.094** / 0 | 0.095 / 0 |
  | rough gold | 0.302 / 0 | 0.302 / 0 | 0.302 / 0 (above the traced roughness: B2's) |
  | floor at roughness 0.3 | 0.760 | 0.422 (one ray a texel) | **0.310** (the pyramid) |

  Gates: chrome under 10% (9.4%); dark-leak 0; the invariants pass; Lily in the floor through the planar view. Not met: the floor's
  0.26 - the remaining error is the hit's lighting (the GI's model at the hit against the path-traced reference), not the
  reflection's geometry; it is the GI's error, measured in the lab's GI tests, and E's to reduce.
- **Bitwise neutral when off:** light_lab, screen_tail and probes (1023 + 861 + 4 images) at every step.
- **Cost on Police** (maximized 3778 x 1600, the trace at half size 1574 x 756; GPU ms of shadows + scene + tone map, the
  reflection pass alone in brackets):

  | View | off | traced to roughness 0.5 | traced + planar floor |
  |---|---|---|---|
  | the sphere grid | 2.66 | 4.48 (trace 1.45: 402k rays, 277 Mrays/s) | 5.52 (pass 1.02: 3k rays + 401k planar texels) |
  | Lily | 3.27 | 5.12 (trace 1.51: 569k rays, 377 Mrays/s) | 6.34 (pass 1.20: 64k rays + 508k planar texels) |

  The trace is within A's budget (3-4 ms). The planar view adds ~1.0-1.2 ms over the trace alone, and the reflection pass still costs
  1.0 ms when the planar view leaves it 3k rays: the planar texels' resolve (the pyramid's taps) runs in the trace's dispatch - owed: a
  resolve of its own, measured against the 0.1 ms it should cost. The tail's thin G-buffer (~0.35 ms) is shared with SCREEN.
- **Found on the way (the GI's, not the reflections'):** the sphere grid showed the GI's diffuse as a patch per surfel - the display
  filter's neighbour rule rejected a curved surface's neighbours (fixed and tested: test 6p); rough metals black on their shadowed half
  - the GI reflection layer reads the 3-lobe basis at R, not convolved with the lobe. Both are in
  `gi_surfel_reconstruction_proposal.md` (for review), with the surfels' move off the faces.
- **Next:** D (reconstruction) - the traced rough receivers' noise (the sphere grid's sparkle at roughness 0.2-0.4) is its input.

## 13. The final review (v3): what was adopted, and where we still differ

| Review point | Landed in |
|---|---|
| 1 Probe ownership: no decomposition of a combined probe; T1 explicit; secondary probe specular = labelled additional-bounce estimate; diagnostic mode; w(r) only on identifiable traced emissive endpoints; probes keep a labelled overlap, no global fade | sec. 3, 10 |
| 2 Support-guaranteed sampling: `q_mix` with `q_safe`, division by the actual mixture; importance at the hit; centre visibility guides, is not evidence; no undeclared hybrid; a reservoir's W is not a pdf; surfel reservoirs optional; novelty = the integration (ReGIR exists) | sec. 1, 6, 12 |
| 3 Reservoirs: scalar p^ vs RGB f, W, reconstruction, floors; Jacobian 1 limited to static / rigid area-preserving; four rejection cases; no blanket unbiasedness, a named scheme, labelled heuristics; finite / true sky / fallback separate, fallbacks outside; validity vs provenance; unresampled first; F optional | sec. 12.1 |
| 4 Visibility reuse: epoch + bounded log, old and new bounds, all reflection-relevant geometry, since last validation, retrace on expiry, two certificates; `PREFIX_INCOMPLETE` never attenuates radiance | sec. 4, 7 |
| 5 Planar: `HIT_PLANAR_SUPPORTED`; clipping / winding / feedback tests; smooth first; filtered, not "no reconstruction" | sec. 4, 8 |
| 6 Composite units R^, B, U, C_final; the two tests; full-res receiver state; Q real on metallic pixels | sec. 5 |
| 7 Desired / admitted / used LOD; screen hits measured, not "exact T0"; B's scope; the skinned benchmark's full chain on a declared GPU | sec. 9, 4, 12, 11 |
| 8 Metrics: error-change flicker with correspondence; fixed-camera light sequence; bias from repeated runs; the three invariants | sec. 11 |
| 9 The approve-now table | sec. 14 |

**Where we still differ (little):**
1. *"Use all geometry relevant to reflection visibility, not only shadow casters."* Agreed in substance; the note is that in this engine
   every drawn instance has bounds and a change entry in the instance table (the shadow pairs filter a subset of the same list), so the
   log is the full list at no new cost - the review's worry about coverage of the log is answered by construction, not by a new system.
2. *Planar blur for glossy planar receivers.* Agreed it is an approximation and goes after the world-ray comparison; we expect it to
   win on Police's floor at r 0.1-0.2 (a filtered ideal image misses only surfaces the ideal view lacks, which on a floor is the
   near-grazing band) - a hypothesis with the review's own gate, not a claim.
3. *Screen path "discrepancy measured".* Agreed; one addition: the discrepancy has a known direction (the screen hit uses the current
   material and this frame's shading; the world hit the capture and the cache), so for a *disagreement* between them the screen value
   is the fresher one - the measurement decides whether the world path should learn from it (a lighting-age update), which is why the
   screen path stays even where the world path could afford the ray.
Everything else in the review is right and is in the contract as written.

## 14. Decisions (final; the review's "approve now" folded in)

| Decision | Status |
|---|---|
| EnvLighting is the one owner of the receiver's environment / probe / reflection specular: mix(probe, U, conf) x B at full res (v4.1: no separate composite pass, no stored receiver state); units of sec. 5 | **Decided** |
| D fresh at the hit from B (v4.1); `E_direct,cached` per surfel from E as the exhaustion fallback, its own validity and age; the GI thread's conditions | **Decided** |
| The planar path for Police first (smooth receivers), `HIT_PLANAR_SUPPORTED`, its three tests; shippable after B | **Decided** |
| Screen Q export: one material variant, total cost and screen / world discrepancy measured before any migration | **Decided** |
| Fresh actual-hit lighting (E) with `q_mix` / `q_safe` and sec. 9's limits | **Decided** |
| Surfel light proposals, glossy path reservoirs, skinned BVH, rough planar, emitter MIS, decomposed probe capture, T2 | **Earn their place** (sec. 12), none a prerequisite |
| Changed-box visibility reuse only with validation epochs and the complete change log | **Decided** |
| The emitter blend w(r): temporary, identifiable traced endpoints only, bias reported | **Decided** |
| Competitor claims replaced by measured quality / time / memory on the declared GPU | **Decided** |
| The architecture is frozen; a deviation edits this document first | **Decided** |

## 15. Changes

**v4 -> v4.1** (milestone B's start, reviewed with Fable 2026-10-28):
| v4 | v4.1 | Why |
|---|---|---|
| A composite pass with full-res receiver state; U = R^/B with B floored | EnvLighting composes: mix(probe, U, conf) x B at full res; U = lobe-mean radiance from (wL, w), w = G2/G1 | the material has its exact receiver state; no division; the DFG table is E[F G2/G1], so this is the split sum on the traced lobe (its F-L bias reported) |
| `E_direct,cached` per surfel in B as the baseline | D fresh at the hit in B (sun ray, VALID pages, a capped ray, else omitted-labelled); the cached term in E as the fallback | the simpler complete path: no GI-side term and no late request pass before the first picture; exhaustion still never unshadowed |
| The planar view a separate path | it resolves into the same U (coverage -> conf) | one consumer, one units contract |

**v3 -> v4** (the final review):
| v3 | v4 | Why |
|---|---|---|
| T1 "replaces the probe term for the lights it covers"; w(r) on the probe fallback | No decomposition claimed; probe specular = labelled additional bounce + diagnostic off mode; w(r) on traced emissive endpoints only | a combined probe cannot be decomposed |
| Shared candidates from a surfel reservoir as E's mechanism | `q_mix` with a `q_safe` floor; surfel proposals optional | support conditions; a dark centre must not lose a light |
| Reservoir section with Jacobian 1 for movers, "rejected still counted", weakest-status merge, env + probe misses one domain | sec. 12.1: scalar target, W and reconstruction defined, static / rigid only, four rejection cases, validity vs provenance, fallbacks outside, named scheme, no blanket claim | the review's point 3 |
| This frame's changed boxes as reuse evidence | Visibility epoch + bounded log since last validation, old and new bounds, two certificates | a lamp off moves no box |
| `HIT_PLANAR_EXACT`, "no reconstruction", rough planar at once | `HIT_PLANAR_SUPPORTED`, filtered, smooth first, three tests | an ideal mirror image is still an approximation |
| Composite `final += F_env x resolved` | R^, B, U, C_final with the two tests; receiver state at full res; Q on metals | a double remodulation was possible |
| "Glossy hits never request fine pages"; screen hits "exact T0" | desired / admitted / used LOD; discrepancy measured | too strong |
| Flicker `mean|a_t - a_t-1| - mean|r_t - r_t-1|`; bias = a residual | error-change with correspondence; repeated runs; three invariants | cancellation; one residual is not bias |
| Sec. 13 "beyond the review" (four leaps) | Folded: the hit-as-receiver into sec. 6 (a fact of the cells, not a leap), surfel reservoirs and reservoirs into "earns its place", the boxes into sec. 7's log, the planar requests into sec. 8 | no speculative prerequisites; the edge is the buildable contract |
| 16 sections, 41 KB | 15 sections, the history folded | shorter |

Older: v1 -> v2 fixed the GI's content (indirect only), emission, declared models, the restart at the origin, two references; v2 -> v2.1
made pages at hits and reservoirs the leap, dropped the control variate; v2.1 -> v3 adopted the first review (D/S split, records, the
pass graph, hit / prefix classes, the emitter table, metrics, A-G). v2.1 is in git (97bb970); v3 was reviewed uncommitted and v4 is the first version committed after it.

## 16. The last questions - answered (Tomas, 2026-10-28: "go ahead and get started")

Approved as recommended. His principles, the frame for every milestone: better than the competition *and* something worth
contributing (clean code, smart ideas, simplicity); no wasted tokens or time; doing the right thing first - A may take as long as B
when justified; the order comes from the logical dependencies, not from a decree; Police may grow test content (a more formal level)
where the gates need it.

1. **A's time box.** The benchmarks and references of A are the gates' foundation; recommended: A is allowed to take as long as B, and
   the budget numbers it produces are the only ones B-E are held to.
2. **The planar view's second scene pass** on Police (bounded to the floor's extent) - accepted as the floor's cost even if the compute
   path later wins elsewhere? Recommended: yes; it is the one path that draws Lily exactly today.
3. **The composite's recompile scope** (v4.1: one binding, U + conf, in every lit pipeline - not a layout change): with the Q
   variant's prototype in the same scope, or apart? Recommended: the composite's change first (B needs it), Q's variant in C.
