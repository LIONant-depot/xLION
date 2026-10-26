# Lighting strategy: direct light, shadows, many lights (v3.3, 2026-10-26)

Status: v3.1 adopted; v3.2 (virtual shadow maps as P1) agreed 2026-10-26; v3.3 = the final version after external reviews A and B
(VSM hardening; visibility as what the renderer schedules). P0 built 2026-10-26 (xLIONRender e2b7318: 109 + 12 saved images bitwise,
visibility reference 6.3% disagreement at the edges, ledger, counters, LightEval; the fixtures:
`xLIONRender/documentation/lighting_fixtures.md`). **Nothing after P0 is built until Tomas says go.**

The GI belongs to its own thread: this document proposes interfaces the GI may adopt, never GI changes. Sources:
documentation/many_lights_and_shadows_research.md, lighting_gi_material_synergies.md, gpu_cluster_culling.md, the GI notes in
xLIONRender/documentation. `R/` = `example.lionprj/Cache/dependencies/xLIONRender/src/`.

## Changelog

### v1 → v3.2 (summary; the full tables are in git history, 99bb74a … 19cc3c6)

| Version | What it settled | Driven by |
|---|---|---|
| v2 | Typed visibility (evidence / prediction / unknown, counted fallbacks); sources behind one query; two budgets; static caches hold static casters only, movers by restore-then-draw; three error measurements; P0 references; one ledger; falsifiable competitor table; out-of-scope table; shared infrastructure (light handle, material visibility, change list, cull shadow mode, LightEval) | Reviews 1-2, Fable, the synergy review |
| v3 | Shadow resource states (invalidate at once, rebuild by budget, head admission needs VALID); handle vs revisions with a dependency table; spatial coverage vs instance flags; per-tile dynamic occupancy; the shadow cull mode fed by eligible casters; LightEval entry points; ledger totals; open questions became decisions | The final external review |
| v3.1 | Caster change = any shadow-producing change; working tile VALID needs static version *and* dynamic composition; BLOCKED only from a semantically valid hit; no stale-map mode in P1; one published snapshot; freeze semantics; P0 order and tolerance | The go-ahead review |
| v3.2 | The sun's shadows become virtual shadow maps on the clipmap's levels (pages by screen demand, not cascades, not warping); P1 = VSM steps; a virtual-memory core shared with textures; references' facts cited | Tomas: the sun's texels are too large on screen |

### v3.2 → v3.3 (reviews A and B, Tomas's additions)

| Change | Where | Driven by |
|---|---|---|
| VSM is a visibility **backend** behind the typed query; the request describes receiver, light, footprint and semantics, never a page address; "every shadow is virtual" → **every shadow query has a supported resolution path** | Sec. 3, 7 | Review B (5, rec.) |
| `BLOCKED_CONSERVATIVE` joins the answers: proven blocked from a coverage-aware coarse representation; never CLEAR from coarse data | Sec. 3 | Review B (2) |
| Layered residency: `VirtualResidencyService` (policy + telemetry) / `ShadowVirtualSpace` / later `TextureVirtualSpace`; format- and consumer-compatible pools, not one pool; shadows built directly, generalized after data | Sec. 7b | Review A (1), wording |
| Filter-safe residency: request dilation by the filter footprint + a pinned coarse fallback (today's local maps already fold a 2-texel border, `shadow_local.h:42`) | Sec. 7 | Review A (2) |
| Protected admission classes (pinned / frame-protected / in-flight / evictable); slot generations; rejected admissions counted apart from misses; recency policy only among evictable pages | Sec. 7 | Review A (3) |
| A guaranteed coarse safety net: pinned coarse pages cover the active view; overflow = designed resolution loss | Sec. 7 | Review A (4) |
| The moving sun: sec. 5's contradiction fixed with **directional epochs**; a day/night cycle gets its own phase (P1e) with a recommendation and a gate | Sec. 5, 7, 11 | Review A (5), Tomas |
| Memory explicit: the pool starts at today's 32 MiB (4096² x 16-bit = 1024 pages of 128²), configurable; a decision before P1b on static/working storage | Sec. 7 | Review A (7), Tomas |
| Work = page/caster pairs in batched indirect submissions; GPU amplification is a gate beside "flat CPU" | Sec. 6.4, 11 | Review A (8) |
| Point lights: 6 virtual cube faces first (today's maps already render as faces + a remap); the octahedral virtual map is an option, not the plan | Sec. 7, 11 | Review A (9), Tomas |
| Texel density is a debug view; the gate is reference error + temporal stability; the extra P1 metrics | Sec. 10, 11 | Review A (6) |
| The five invariants as gates of P1a | Sec. 7, 11 | Review A |
| Phases: P1a-0/1/2, P1b, P1c, P1d, P1e (moving sun), VM generalization; the research track R-A/R-B/R-C with go/no-go criteria and adverse scenes, sequenced off the critical path | Sec. 7c, 11 | Review A, review B (7), Tomas |
| Synergies: conservative rejection reuses the GPU cull's Hi-Z test and pyramid in light space; the direct-test backend *is* the GI's `Occluded` (P0's reference); R-C absorbs the "second layer" question; one request format for the diagnostic record and the residency telemetry | Sec. 7c, 9 | Me |
| Deleted: the octahedral virtual map as the plan, "one request pass writes shadow and texture requests", "LRU eviction" as the policy, "VSM ties texels to pixels", "slow sun re-renders only where the change list says" | Sec. 5, 7, 7b, 12 | Reviews A and B |

Everything of v3.1 and v3.2 not named above stays in force.

## 1. Goal and hypothesis

The goal: many lights, the strong ones stable and noise-free, the rest sampled at a bounded cost. Shadow work is shared with the
GI's visibility, and every decision can be inspected from the editor and by the AI.

**The hypothesis to prove or drop:**
> On scenes with substantial stable geometry and lighting, deterministic important lights, static-only shadow caches, and an
> unbiased sampled tail may reduce shadow work and temporal instability at a fixed total budget, without hardware RT.

**The research hypothesis behind it (review B, ours to measure, sec. 7c):**
> Expensive shadow work should follow *unresolved, visually important visibility*, not screen coverage, light count or cache age.
> At matched quality, avoiding resolved work must save more than classifying and scheduling it costs; otherwise a conventional VSM is
> the right answer and the machinery is deleted.

How we stand against the competitors: hypotheses, each with the test that would refute it. None of the parts is new (adaptive shadow
maps, conservative shadow prepass, hybrid map + ray shadows, Unreal's VSM caching); what we are testing is the integration around the
typed contract.

| Claim about us vs them | Facts we rely on | Test |
|---|---|---|
| Our sun and key lights are noise-free, like Unreal's | Unreal: the sun uses VSM, and MegaLights leaves directional lights out by default (`r.MegaLights.DirectionalLights=0`) | Temporal luminance deviation on a still scene, sun + key lights |
| The tail costs less per quality because static shadow work is cached | MegaLights guides its sampling by history (GuideByHistory, a visible-light hash per tile) and ships on hardware RT; a software path exists | Equal-time error against the reference on the stress city |
| We avoid re-tracing static visibility for key lights | GigaLights: every sample's shadow ray is traced each frame (`GigaLightsLightingKernels.hlsl`: shadow rays from `GL_ShadowRayStart`, e.g. lines 1005, 1228); it remembers *which* lights a tile saw, not per-light visibility. Read 2026-10-26 in `E:\source_code\gigalights`, learning only | Shadow-pass ms with 0 / 50 movers |
| Unresolved work picks its backend per region (page vs direct test), not per light forever | Unreal resolves every receiver through pages (+ SMRT over the depth); MegaLights traces every sample. Neither chooses per region | R-B (sec. 7c): page refinement vs direct BVH tests vs the hybrid rule, same reference |
| Runs without RT | xGPU has no acceleration structures; the GI's software BVH exists | All of P0–P4 run on the no-RT path |

## 2. What exists and what is new

| Piece | Exists (where) | New in this plan |
|---|---|---|
| Sun shadows | Clipmap of world-anchored cached tiles; invalidation by caster bounds projected along the light; **a direction change (`Z.Dot(m_Z) < 0.99999f`) or a level-0 size change invalidates every slot** (`R/features/shadows/xlionrender_shadow_clipmap.h:82-91`). 4 levels x 4x4 tiles of 512 texels (the 8x8 atlas is full: 4096² x 16-bit = 32 MiB), 3x3 PCF of exact texels clamped inside the tile; a pixel reads the finest level that holds it (`R/shaders/xlionrender_shadow_clipmap.glsl:8-41`), so on screen the texels are too large (Tomas checked) | Virtual shadow pages (sec. 7): pages by receiver demand, finer levels, a page pool with protected admission; the static/mover split per page. Today a mover re-renders its whole tiles (`clipmap.h:18`), and skinned casters invalidate theirs every frame |
| Local shadows | Cached octahedral/frustum maps in a buddy atlas, an update budget (maps without a map first, then by urgent age), a cache key ignoring colour and intensity (`xlionrender_shadow_local.h:253-261`); **a 2-texel border, folded over the octahedral edges, for PCF** (`shadow_local.h:8,42`); point maps render as 6 cube faces into a scratch, then a remap (`shadow_local.h:9`, `xlionrender_shadow_remap_frag.glsl`) | The same pool after the sun (P1d); the budget grows into the global preparation budget |
| Many lights | `light_cells`: a world-cell clipmap; mode SAMPLED = exact head + one tail light with a floored probability, tested unbiased against EXACT (`R/features/lights/xlionrender_light_cells.h`, `tests/xlionrender_test_light_lab.cpp`). Rebuilt on the CPU every frame | Per tile; a visibility term from existing maps; stable light ids; a GPU builder |
| Rays | The GI's software BVH (BLAS/TLAS), any-hit `Occluded` (`R/shaders/xlionrender_gi_bvh.glsl:13`, `gi_pass_common.glsl:120-124`; CPU `surfel_gi.h:3233`), see-through per triangle, transport roles | Lighting's ray budget and coverage classification (sec. 3); the **direct-test backend** of sec. 7c |
| An exact local-light reference | The GI's direct light: a light BVH with a shadow ray per light (`surfel_gi.h:3265-3290`) | P0's visibility reference (built), opaque rigid only |
| Hi-Z occlusion | The camera cull builds a max-depth pyramid (`xlionrender_hiz_comp.glsl`) and tests a box's nearest depth against the farthest depth it covers (`xlionrender_cull_comp.glsl:44-71`) | The same pyramid and test, in light space, as R-A's conservative blocker test (sec. 7c) |
| Footprint invalidation | The GI marks the old and the new box on a move (`surfel_gi.h:2357-2381`); the shadows' `m_FrameChanged` lists changed caster bounds (`R/plans/forward/xlionrender_plan_forward.cpp:1076-1116`) | One per-frame change list (sec. 6) |
| Caster culling | GPU cluster culling for the camera, matrix-parametrized, a frustum-only mode 2 (`cull_comp.glsl:30,107`) | Page/caster pairs through it in a shadow mode (P1c) |
| Material classes | `render_settings`: Opaque / Masked / Translucent / Additive, cast shadows, alpha cutoff (`plugins/xmaterial.plugin/source/xmaterial_render_settings.h`) | One `MaterialVisibilityOf(material)` that every system reads |
| Light identity | None. Lights are rebuilt every frame; three consumers hash them | Light handle + revisions (sec. 6.1) |
| Denoiser, screen trace, per-tile memory | None | P2–P3 |

## 3. The visibility contract

Every visibility query returns a typed answer:

```
VisibilityQuery  { receiver (P, N, screen footprint); light handle + revision; filter footprint (source angle, kernel);
                   required semantics (caster classes, opacity modes) }           // never a page address
VisibilityResult { status: BLOCKED | BLOCKED_CONSERVATIVE | CLEAR | APPROXIMATE | UNKNOWN;
                   value;                       // 0..1 when APPROXIMATE
                   source;                      // screen | shadow page | coarse blocker | cache | BVH
                   epoch;                       // the published state it read (incl. the directional epoch, sec. 5)
                   reason; }                    // when UNKNOWN
```

**Backends, not an abstraction.** Virtual shadow pages, the screen trace, the GI's any-hit, a coarse blocker representation and
caches are *resolution paths* behind this query. The renderer schedules visibility; a page is one way to hold evidence. The rule
replacing v3.2's "every shadow is virtual": **every shadow query has a supported resolution path**, and the cheapest supported path is
chosen per region (sec. 7c decides the rules by measurement; until then: a valid page, else the declared fallback).

The rules:
1. **Evidence** (a current shadow-page sample within its model, a current BVH query, a conservative-blocked verdict from a
   coverage-aware representation, an unchanged cached sample whose dependencies are valid) may shade.
2. **Prediction** (surfel visibility, remembered per-tile visibility, visibility history) may guide selection and work. It never
   substitutes for a fresh or validated visibility result in the raw light estimator. Three things are kept apart:
   - a historical *lighting* estimate: reused by temporal reconstruction under its own, separately measured contract (sec. 4);
   - historical *visibility* used for guiding: prediction;
   - cached visibility whose dependencies are validated: evidence.
3. **Unknown stays unknown.** The consumer applies the source's *declared* fallback and counts the unresolved contribution (light
   energy shaded by a fallback, per reason). A fallback is neither a visibility fact nor unbiased.
4. **Conservative answers.** `BLOCKED_CONSERVATIVE` is evidence only when the representation is coverage-aware: a texel proves
   blocking only if a supported opaque caster *fully* covers it (Tokuyoshi & Mizokuchi's conservative shadow prepass; inner-coverage
   conservative rasterization where the device has it). A low-resolution depth sample or a min/max pyramid never proves thin
   geometry absent, and a few shadowed samples never prove coverage: coarse data can say BLOCKED, never CLEAR. Criterion: every
   receiver rejected as blocked is blocked in the reference; otherwise the test is a prioritization heuristic (prediction), not
   evidence.

| Situation | Declared behaviour |
|---|---|
| A valid shadow page covers the query (filter footprint included) | Use the page (evidence) |
| A coverage-aware coarse representation proves the receiver blocked | BLOCKED_CONSERVATIVE (evidence); no finer work |
| A valid, unchanged cached answer exists | Reuse it (evidence) |
| The fine page is not VALID, a pinned coarser page covers the point | The coarser page, labelled APPROXIMATE with its level delta, counted (designed resolution loss) |
| Only contact shadowing applies (a tail light with no map, before P4) | The contact-shadowed approximation, labelled APPROXIMATE |
| No supported source | The tier's declared fallback (default: unshadowed, counted); a "conservative dark" mode for debugging |
| A reference needs unsupported geometry | That measurement is marked unsupported, never treated as ground truth |

**Unknown reasons, reported separately:** outside the resident coverage; unsupported caster or material semantics; traversal or
work limit reached; published state unavailable or invalid; **admission rejected** (a requested page the pool could not take, apart
from a miss).

A hit proves BLOCKED only if the hit itself satisfies the requested material and caster semantics. A supported opaque blocker proves
it even when unsupported geometry lies alongside; a hit on a masked triangle whose alpha was not evaluated does not (today the BVH
treats masked as solid). No blocker found in a partial scene is UNKNOWN, not CLEAR.

**The screen trace** covers only the span next to the surface and may conclude BLOCKED, never CLEAR. Its hits stay within the
declared contact-shadow approximation (APPROXIMATE). It honours caster roles, and its answers never enter a world-space cache.

**Coverage contract:** direct-light trace coverage follows the GI's published visibility residency and its supported caster
classes. Lighting never pins GI geometry. Evicting GI lighting state must never remove an occluder from the rays without the rays
reporting UNKNOWN. CLEAR = no blocker found **and** the required occluder coverage along the query is complete, which takes instance
capability flags (does this represented instance support the semantics?) and spatial coverage (is relevant geometry *missing*?). The
GI thread chooses the spatial representation.

**Shadow resources have a state:** ABSENT, VALID, DIRTY or BUILDING, plus a content/dependency version, an allocation generation,
the last update frame and an estimated update cost.
- **Invalidation is immediate; rebuilding is budgeted.** A resource loses evidence status the moment a dependency changes.
- A **working** page is VALID only when it holds the required static-content version *and* the required dynamic composition for the
  published frame. A small dependency record per page; no general dependency graph.
- While DIRTY or BUILDING, consumers use the declared fallback. **P1 rule: VALID → sample; otherwise → declared fallback + counter.**
  Stale-page reuse for a bounded age stays documented, unbuilt.
- Three things are separate: a resource is VALID; it was selected for update; its light is admitted to the deterministic head. A
  light enters the head only with a VALID resource.
- **Generation safety:** a physical slot is not republished for a new page until every access using its old generation has completed
  (invariant 1, sec. 7). Sampling data and page-table entries come from one published snapshot (sec. 4).

## 4. Light paths and budgets

- **Deterministic path:** the sun and K key lights, through cached shadow pages: stable filtering, full resolution, no denoiser.
  "Deterministic" means stable, not exact: pages have resolution and bias, and soft shadows from pages are a stable approximation.
- **Sampled path (the tail):** every other light in reach, via the grown `light_cells` SAMPLED estimator.
- **Two budgets, both logged:** per tile (head size K and tail samples); global shadow preparation (today's local-map update budget
  extended: valid resources free to retain, dirty ones repaired, missing ones built, the recurring restores and mover draws, and
  from P1a the page requests admitted per frame).
- **Two rankings:** deterministic lights are *selected* by visual benefit and resource readiness; updates are *scheduled* by visual
  error and repair cost. Simple priority classes first; hysteresis never preserves invalid evidence.
- **Head:** the sun is outside K. Up to K = 4 admitted local key lights per tile; unused slots stay empty.
- **One published snapshot.** Light handles and revisions, resource bindings and validity, page tables and slot generations, head
  membership and weights, and the sampling-distribution data are published together with the existing frame buffering. No new
  synchronization framework.

**The estimator.** With head weights a_l(x), L = Σ a_l C_l + Σ (1 − a_l) C_l. The tail estimates the second sum as
(1 − a_J) C_J / q_J. Its correctness rests on: q matching the implemented selection; every contributing tail light keeping q > 0
(the floor); complementary head and tail weights; light ids carrying a generation. Selection is q = (1 − ε) q_guided + ε q_discovery;
discovery reaches every light in reach, new or changed lights get priority discovery in the cells they touch; visibility guidance
never removes a contributing light's support. The probability calculation is documented next to the code.

**Three error measurements, never merged:** sampling error (SAMPLED vs EXACT, identical visibility); visibility-model error (the
source vs the reference, on supported geometry); reconstruction error (after half resolution, accumulation, filtering, clamping).

## 5. Light classes

| Class | Examples | Path | Caching |
|---|---|---|---|
| Static | Lamps, windows | Key, or tail (by importance) | Pages kept until their dependency epoch changes |
| Slow | Sun, moon | Deterministic (virtual clipmap) | Caster changes invalidate the intersecting pages. **A directional projection change opens a new directional epoch, which invalidates every page of that light** (what the clipmap does today, sec. 2); the rebuild is budgeted, coarse pinned pages first. A continuously moving sun (day/night) is P1e, sec. 7 |
| Player-speed | Torches, car lights | Tail; key when it ranks | Per-tile lists follow by light id |
| Transient | Muzzle flashes, sparks | Tail, contact-only | None |

## 6. Shared infrastructure

1. **Light records: a lifetime handle plus revisions.** `LightHandle { slot or entity; lifetimeGeneration }`,
   `LightRevisions { visibilityRevision; radiometryRevision }`. A persistent record buffer uploaded on change, like `instance_slots`.
   Shadows, probes, cells and (optionally) the GI key on the handle plus the revision they depend on. Two hashes go away.

   | Property | Bumps | Shadow depth | Per-tile lists | Radiometric values |
   |---|---|---|---|---|
   | Position, orientation, type, radius, cone, emitter size/shape, projection settings | Visibility revision | Invalid (a new directional epoch for the sun) | Entry kept, its visibility re-checked | Recomputed |
   | Shadow-caster mask | Visibility revision | Invalid | Entry kept, visibility re-checked | — |
   | Colour, intensity | Radiometry revision | Kept | Kept (importance refreshed) | Recomputed |
   | Deletion, slot reuse | Lifetime generation | Freed | Entry dropped | Dropped |

2. **`MaterialVisibilityOf(material_state)`:** one helper returning separate properties:
   `MaterialVisibility { opacityMode: OPAQUE | MASKED | BLENDED; castsShadow; alphaCutoff; alpha resources (when supported) }`.
   Emission is a separate property (`m_bEmissive`, set by the material compiler). The GI's see-through, the caster loop, the coarse
   blocker render (R-A: opaque only) and the later any-hit mask all call it.
3. **One change list per frame:** `scene_changes { caster bounds (old and new), light handles + revisions, epoch }`, built once
   (today's `m_FrameChanged`). Consumers: the page invalidation, local maps, probes, the static caches, the per-tile lists; the GI's
   `MarkLinksCrossing` may listen. `m_PrevCasters` folds into `slot_caster`. A caster change includes any change to its
   shadow-producing geometry, opacity or participation (material or opacity mode, cutoff or alpha texture, `castsShadow` or mask,
   mesh or geometry revision, deformation state), not only movement. **Static age** = frames since the shadow-producing state changed.
4. **Page/caster pairs through the GPU cull, in a shadow mode.** The unit of work is a (dirty page, eligible caster) pair, generated on
   the GPU and batched into indirect multi-page submissions; not one draw per page. The input is the **eligible resident caster
   set**, not the camera's surviving draws, built once per frame and reused across pages and faces. The shadow mode must not inherit
   camera visibility, size thresholds, LOD, normal-cone or backface assumptions, static-only candidates, or the camera's depth
   convention. Masked casters are runs bound by material base. Off-screen casters are a mandatory fixture. Page Hi-Z only if measured
   to pay. Gates: flat CPU **and** bounded GPU amplification (pairs, generated draws, rasterized triangles vs a full redraw).
5. **One `LightEval` GLSL include (built in P0):** `EvaluateLightGeometry`, `EvaluateIncidentLighting`, `EvaluateReceiverBRDF`,
   `EstimateSelectionImportance`, each stating what it returns. Later (P3) the cell walk becomes `EvaluateDirectAtReceivers`, whose
   visibility callback is the typed query: pixels resolve it through pages, GI hits through `Occluded`.

## 7. Sun shadows: virtual pages, hardened

**Why not cascades or warping:** a cascade's resolution is fixed per frustum slice and re-renders on camera moves; warping (PSM,
LiSPSM, TSM) and SDSM fitting move the projection with the camera, which breaks world-anchored page caching and shimmers. VSM
allocates pages by receiver demand; projected footprint and filtering still determine the density a page must have. The last
centimetres at contact come from the P3 screen trace, as Unreal pairs its VSM with contact shadows.

**The design (the clipmap's levels, virtual):**
1. **Levels:** each clipmap level is a virtual texture (start: 16k x 16k texels in 128 x 128 pages) world-anchored as today; more
   levels (start: 10-12) so centimetre texels near the camera and kilometre range share one mechanism.
2. **Requests:** a pass over the depth buffer records, per pixel, the projected footprint along both screen derivatives, selects
   the level whose texel fits it, and marks that page needed; requests are **dilated by the filter footprint** (PCF kernel, source
   angle) so every tap lands on a requested page; deduplicated; then admitted (below). "~1 texel per pixel" is the debug view's
   target, not a gate: the gates are reference error and temporal stability (sec. 11).
3. **Pool and page table:** a physical pool and a per-level page table read through one indirection per lookup. **Start at today's
   sun budget: 4096² x 16-bit = 32 MiB = 1024 pages of 128², configurable.** Separate pools per format and consumer (sec. 7b).
4. **Protected admission, not pure LRU.** Slots carry a class: *pinned* (the coarse safety net), *frame-protected* (referenced by the
   published snapshot), *in flight* (requested, clearing, rendering, restoring, awaiting completion), *evictable*. A recency policy
   runs only among evictable slots. A slot is republished for a new page only after every access of its old generation has completed.
   Rejected admissions are counted apart from misses.
5. **The coarse safety net.** Enough coarse pages to cover the active view are pinned (start: 25% of the pool, configurable; today's
   4 levels x 4x4 tiles at 256² per tile = 256 pages = 8 MiB); fine pages degrade to the pinned level under pressure. Overflow is a
   designed resolution loss (APPROXIMATE with a level delta, counted), never a hole; only unsupported semantics reach unshadowed.
   The request pass pins the coarse set first, then admits fine pages by demand.
6. **Filter-safe residency:** request dilation + the pinned coarse fallback (rule chosen; replicated gutters and per-tap translation
   stay as alternatives if dilation overhead shows in the ledger). Today's local maps already fold a 2-texel border for the same
   problem. Fixtures: page boundaries, level boundaries, screen edges, thin blockers, large source angles. Unreal mitigates unmapped
   pages under filtering with dilated mappings and still leaks occasionally (review A); we count the boundary-tap fallback rate.
7. **States per page:** sec. 3's ABSENT / VALID / DIRTY / BUILDING; a requested page not yet VALID uses the pinned coarser page
   (APPROXIMATE), never a stale page.
8. **Rendering:** page/caster pairs through the cull's shadow mode (6.4), indirect, batched.
9. **Filtering:** bilinear compare PCF from the start; slope-scaled bias; soft shadows later as an *extension of the query* (sec. 7c).
10. **Directional epochs.** A sun direction change opens a new epoch: every page of the old epoch is invalid at once; the new epoch's
    pinned coarse set is rebuilt first, then fine pages by demand within budget (sec. 5). The first build treats the sun as fixed per
    epoch and a direction change as a stress result (B5). P1e makes a continuous cycle usable (below).
11. **Local lights (P1d):** spots as 1 virtual map; **points as 6 virtual cube faces** (today's maps already render as faces + a remap;
    Unreal: a spot is 1 map, a point 6, `VirtualShadowMapArray.cpp:4134`). A virtual octahedral map is an option only if an isolated
    prototype proves it simpler and faster. The buddy atlas retires when P1d lands, not before.

**Memory, decided before P1b:** static and working copies at full capacity would double the pool (Unreal's separate static caching
can double its pool). Options, one chosen on P1a data: separate fixed pools; shared slots with typed ownership; working copies only
for pages with dynamic occupancy (the expected choice: movers touch few pages); a temporary restore destination. Gate: peak and
committed bytes, fragmentation, working/static ratio, copy bandwidth, memory under forced overflow.

**The five invariants (gates of P1a, tested as fixtures):**
1. no shader samples an invalid or generation-mismatched physical slot as evidence;
2. every filtering tap has valid fine data or an explicit coarser fallback;
3. pool exhaustion degrades resolution while keeping the pinned coverage;
4. a directional projection change is an explicit whole-epoch invalidation;
5. every demand, admission, eviction, rendering, fallback and memory cost appears in the ledger.

**The moving sun (P1e, a day/night cycle).** Candidates weighed:
- *Fixed transform per epoch, rebuild within budget:* correct and simplest; a slow cycle (say 24 minutes per day = 0.25°/s ≈
  0.004°/frame) would open a new epoch every frame and rebuild the on-screen set continuously. Unreal pays this (light movement
  invalidates its cache; `VirtualShadowMapCacheManager.cpp` keys the cache per light on a rendered-frame number, line 270/322).
- *Scrolling/reprojection of depth:* a reprojected light-space depth is not evidence (depth changes nonlinearly with the projection
  and reveals holes); it could only ever be APPROXIMATE. Rejected as a correctness path.
- *Quantized direction epochs with a cross-fade:* the shadow projection steps by θ while the shading direction (N·L) stays
  continuous; the next epoch is built ahead within budget (pinned coarse first, then the on-screen pages nearest the camera by
  demand); when it is VALID where it is needed, the shadow term blends from the old epoch to the new over a few frames (two evidence
  samples, both VALID, blended; labelled). Two epochs resident at the transition: the on-screen set at most, not the pool.
- *Budgeted refresh by age:* pages refreshed oldest-first under a fixed budget; stale pages sampled as evidence contradict sec. 3.

**Recommendation: quantized epochs with a cross-fade, rebuilt nearest-pages-first within budget.** θ is configurable; the start
value makes the shadow displacement at the mid level under one texel, and never smaller than cycle speed x the measured time to
rebuild the on-screen set. Gate: on B5 at cycle speed (B5b) no visible pop (temporal deviation under the still-scene threshold),
page renders per frame bounded, pool peak < 1.5x the single-epoch peak, the old epoch released within a bounded number of frames.
Tomas decides the cycle length and whether θ is user-visible.

**The static/mover split, per page (restore-then-draw; P1b):** the static depth of a page holds static casters only. Each frame,
every page whose previous or current dynamic footprint touches it is restored from the static copy, then the movers are drawn.
Both copies are shadow resources with sec. 3's states. "Static after N frames" means cache-eligible; declared deformers are always
movers; a cached object that moves invalidates the static cache under its old and new bounds. Eligibility is immediate, admission
into the static cache budgeted (no rebuild burst). Occupancy is conservative (projected caster bounds). Per-page dynamic
occupancy: a page is not dynamic forever once a mover touched it (restore + draw while movers remain; one restore when the last
leaves; no dynamic work when static-only). **Restore-then-draw versus composing V_static x V_dynamic per query is R-C (sec. 7c);**
both stay behind the query interface. Transition tests, per page, each against a full re-render: a mover enters a page; crosses into
another; leaves the visible region; is deleted; becomes cache-eligible; moves again after being cached.

**Costs and risks:** the request pass (ledger); one page-table indirection per lookup; page thrash on teleports (fallback counted,
the recovery curve measured); many page/caster pairs (6.4's amplification gate); the moving sun (above); deformers and
world-position-offset materials are always dynamic.

## 7b. Residency: one framework, several spaces

Shadow pages and texture streaming share *policy and telemetry*, not a pool or a page table (Unreal's VT keeps separate physical
pools per format and tile size, each with its own recency policy; Vulkan sparse residency needs capability queries):

| Layer | Owns | Shadow (P1a) | Textures (later) |
|---|---|---|---|
| `VirtualResidencyService` | consumer registration, `VirtualPageKey` + generation, request queues in one request format, admission/eviction hooks and classes, budgets, counters, the ledger rows | built directly inside the shadow code in P1a | extracted after shadow measurements (the "VM generalization" phase) |
| `ShadowVirtualSpace` | depth-derived demand with dilation, the shadow pools, the rendered-page producer, the pinned coarse fallback, compare filtering | P1a | — |
| `TextureVirtualSpace` | material/feedback demand, per-format pools, IO + decompression producer, mip fallback, trilinear/anisotropic filtering | — | its own design when the texture work starts |

Consumer-specific request producers write a common request format where practical; what differs is the miss (a shadow page renders
this frame; a texture page arrives from disk later, the material shows a coarser mip meanwhile, counted) and filtering.

**Texture policy (unchanged in substance):** mip streaming driven by feedback for every texture (Vulkan sparse where supported, plain
streaming elsewhere); virtual texturing opt-in per texture (terrain, decals, baked data); the GI capture, previews and thumbnails write
requests within their host-granted budgets. Nothing of it is in P1's critical path.

## 7c. Research track: visibility as the scheduled thing (review B)

Prior art, cited so we do not claim it: adaptive shadow maps (resolution at shadow boundaries); Tokuyoshi & Mizokuchi's conservative
shadow prepass (fully-covered texels block; exclude conclusively shadowed receivers before the expensive stage); Chalmers' clustered
many-light shadows (rays for sparse lights, maps where many samples share work; dispatch overhead can erase the benefit); AMD Hybrid
Shadows (maps + rays, lit/shadowed rejection, ray-interval reduction). Ours is the integration: typed answers, shared receiver demand,
interchangeable backends, bounded work with designed degradation, and a record of why each expensive operation happened. The
central failure case to measure: foliage, thin geometry, wide penumbrae, moving lights and conservative bounds can leave most of the
image unresolved, so the saving vanishes while the classification cost stays.

Three experiments, each a branch off the minimal VSM path (never on it), each with a go/no-go and adverse scenes (dense foliage, thin
fences, a moving sun, many tiny lights, cold teleports; never only big opaque walls):

| | What | How, with what we have | Go / no-go |
|---|---|---|---|
| **R-A** Conservative rejection | Fixed sun, opaque rigid: a coarse coverage-aware blocker representation classifies visible receivers proven-blocked vs unresolved; the unresolved are compacted and resolved by the reference-capable path; compare with resolving everyone | The pinned coarse pages, rendered with **inner-coverage conservative rasterization** (`VK_EXT_conservative_rasterization` underestimate mode; else a full-coverage flag per texel), then **the cull's max-depth pyramid and `Occluded` test in light space** (`hiz_comp.glsl`, `cull_comp.glsl:44-71`, with the comparison turned to "the receiver's nearest depth is beyond the farthest blocker"); `MaterialVisibilityOf` keeps masked out | Every rejected receiver blocked in the reference (else it is a heuristic, kept only as prediction); total cost (generation, classification, compaction, sync, resolution) below resolving everyone at matched error on at least the Police and stress city, and reported on the adverse scenes |
| **R-B** Page vs direct test for unresolved work | Fine page refinement vs direct software-BVH queries vs a simple hybrid rule (many unresolved receivers share a page → raster; few + complete BVH coverage → direct tests; else the declared coarse approximation) | The GI's `Occluded` any-hit (P0's reference, already on the GPU: `gi_pass_common.glsl:120`) within its opaque-rigid coverage; the BVH's maintenance cost counted even though the GI shares it; the same visibility model and reference for all three | At matched error, the hybrid beats both pure paths on total cost including scheduling; otherwise pages only (and P4 keeps direct tests for the tail only) |
| **R-C** Dynamic composition | Restore-then-draw vs V_total = V_static x V_dynamic (query static; if conclusively blocked stop; else query a small dynamic layer or a direct dynamic-geometry test; combine per sampled light direction, never per independently filtered factor) for a small mover in a mostly static scene | P1b's restore path vs a second small raster layer; extra lookups, dynamic upkeep and divergence counted | Net timing and memory against P1b's measured restore cost on 1 / 10 / 50 movers; the loser is deleted, not kept behind a flag |

**Soft shadows** extend the query, not its meaning: an area light classifies emitter-direction regions (fully blocked / fully visible /
mixed → subdivide); research after R-A. Unreal's SMRT samples a depth representation (plausible, not geometry-tested); we keep that
distinction in the labelling (APPROXIMATE).

Sequence: R-A first (the smallest experiment that could change the architecture), after P1a-1 exists to host it; R-B after P1a-2 (it
needs fine pages to compare against); R-C beside P1b. If all three say no, the result is a conventional, well-measured VSM and sec. 3's
`BLOCKED_CONSERVATIVE` is removed. If R-A and R-B say yes, they become the basis of P4/P5 and the per-region rule enters sec. 3's table.

## 8. Out of scope for the first phases, and the rule meanwhile

| Case | Rule |
|---|---|
| Blended receivers | Keep today's full-cell shading; they never consume opaque half-resolution lighting or history |
| Skinned / deforming casters | Always movers through the raster shadow path; not in the BVH, so no direct-test path is claimed for them |
| Alpha-tested casters | Raster visibility where a page covers the light; never in the coarse blocker representation; rays do not certify per-texel visibility until P4's alpha any-hit |
| Fog | A future consumer; no dependency |
| Mobile / Apple | Unmeasured targets, not performance claims; MoltenVK subgroup behaviour unverified |
| Material previews, thumbnails | One host-granted budget per application; no main-view allocation |
| Reflections | The GI thread's; lighting shares only the P3 screen trace with SSR |

## 9. Debuggability

- **Per-pixel record from the real GPU path**, read back asynchronously like the cull stats: view and frame, surface id, cell or
  tile; light handle + revision, head or tail; probability and weight; visibility status, source, epoch (directional epoch
  included), fallback reason and level delta; whether the history was accepted; the final contribution. No CPU re-evaluator.
- **Why each expensive operation happened:** every page render, restore, admission rejection and eviction carries its cause
  (request, dilation, epoch change, caster change, pressure) in the residency telemetry; the same record format as the request
  queue, so the inspector and the ledger read one stream.
- Debug views: selected level and projected footprint per pixel; page boundaries and fallback taps; the coarse net; epoch age.
- The inspector distinguishes: not selected this frame, selected but zero, reconstruction dark, degraded to coarse.
- **Freeze-lists toggle:** membership frozen, parameters current, lifetime mismatches dropped, probabilities recomputed.
- Counters through `DescribeScene`: unknown rate per reason, fallback energy, pages requested/admitted/rejected/rendered/reused/
  evicted, restore and copy ms.

## 10. Measurement: one ledger

Every row is exclusive. Each capture records GPU clock state, resolution, views, build configuration, workload, compile idle before
and after. Two operating conditions: **editor-normal** and the **warmed benchmark** (maximized, Release, frame budget off).

| Ledger row | Contents |
|---|---|
| Light records + grid | Record upload, cell or tile build |
| Shadow preparation | Page requests (the pass from depth, dilation, dedup), admission and page-table update, then page rendering: static redraw, restore/copy, mover draw, pair generation and culling (separate sub-rows); coarse-net upkeep; epoch rebuilds |
| Direct shading | Head + tail evaluation |
| Reconstruction | Denoiser, upsampling |
| Visibility work | Classification and compaction (R-A), direct tests (R-B, P4) when separate dispatches; fused work attributed by paired variants, never a fake exclusive timestamp |
| Cache maintenance | Static cache upkeep, list ageing |
| CPU (reported separately) | Caster enumeration and submission, change list |

Lighting total = records/grid + shadow preparation + direct shading + reconstruction + visibility work + cache maintenance. Costs
shared with other systems (the GI's BVH, the camera cull's pyramid) are named, never counted twice.

**Metrics beyond time:** the UNKNOWN fraction and its sample-weighted unoccluded contribution (exposure, not "missing energy");
page requests before/after dedup and dilation overhead; requested / admitted / rejected / rendered / reused / evicted; protected and
in-flight slots; fine-to-coarse fallback rate and the pixel energy it affects; page-table lookups per filtered lookup; page/caster
pairs and raster amplification vs a full redraw; slot-reuse generation failures caught by tests; pinned bytes and guaranteed-coverage
bytes; footprint under/over-resolution percentiles; boundary-tap and coarse-fallback sample rates; epoch full-invalidation rate; the
teleport recovery curve per frame; shadow-edge error against a high-resolution reference. Statistics: median, p95, p99, cold start
(60 frames after a load or teleport), error against the references.

## 11. Roadmap

Each phase has a gate measured with the ledger. The critical path is P1a-0 → P1a-1 → P1a-2 → P1b → P1c; everything else branches.

| Phase | What | Gate |
|---|---|---|
| **P0** (done) | Saved outputs, the sampling and visibility references with coverage labels, the ledger, the diagnostic skeleton, LightEval with analytic tests, break tests defined | Delivered 2026-10-26 (sec. status) |
| **P1a-0** Virtual addressing | Shadow-only virtual address encoding, page table, a small physical pool (32 MiB), protected slot classes and generations, the debug views; no caching optimization; light handle + revisions (6.1), `MaterialVisibilityOf` + emissive (6.2), one change list + static age (6.3) | Synthetic page, boundary and slot-reuse tests; invariant 1; saved outputs unchanged (the old clipmap still renders) |
| **P1a-1** Fixed-sun pages | Depth-derived request pass with dilation and dedup, admission, page rendering with today's casters, sampling with bilinear compare PCF, the pinned coarse net, APPROXIMATE fallback with level delta | Matches a full redraw within tolerance; invariants 1-3, 5; controlled overflow (B11) shows resolution loss, no hole; B7 recovery curve recorded |
| **P1a-2** Clipmap levels | World-anchored levels (10-12), screen-derived level selection, directional epochs with whole-epoch invalidation (B5 as a stress result) | Visibility-reference disagreement no worse than today's 6.3% and lower at the edges; footprint distribution and edge error improve over today's clipmap; temporal stability on a still scene; invariant 4; the P1 report |
| **P1b** Static/working split | Restore-then-draw per page, per-page occupancy, the memory decision of sec. 7; skinned via the existing path | The six transition tests; no DIRTY page or obsolete composition sampled; net timing and memory benefit vs P1a-2 |
| **P1c** GPU pairs | Page/caster pair generation on the GPU through the cull's shadow mode, indirect batching; page Hi-Z only if measured | Flat CPU; bounded pair and triangle amplification; sun ≤ 0.8 ms with 50 movers (warmed benchmark); off-screen casters included |
| **P1d** Local lights | Spots as 1 virtual map, points as 6 cube faces; the buddy atlas retired | The local-shadow tests and saved outputs within tolerance; the same invariants and counters |
| **P1e** Moving sun | Quantized epochs with a cross-fade, nearest-pages-first rebuild (sec. 7) | B5b at cycle speed: no visible pop, bounded page renders, pool peak < 1.5x, old epoch released in bounded frames |
| **VM generalization** | Extract `VirtualResidencyService` from the shadow code on P1 data | The texture consumer reuses policy and telemetry without shadow assumptions |
| **R-A / R-B / R-C** | Sec. 7c, branches off P1a-1 / P1a-2 / P1b | Their go/no-go; a "no" deletes the branch |
| **P2** Per-tile head/tail | `light_cells` per tile, GPU-built, stable ids, a visibility term from existing pages guiding selection with the floor kept | Sampling error converges; no pops on a light ramp; the glossy floor test |
| **P3** The tail | `EvaluateDirectAtReceivers`; screen trace (blocked-only); short-history denoiser; the global preparation budget | "Key lights shadowed by pages, tail contact-shadowed"; reconstruction error separate |
| **P4** Traced visibility | Tail shadow rays through the GI's any-hit with a declared budget and coverage classification; alpha any-hit if the GI thread agrees; R-B's per-region rule if it passed | Visibility-model error on supported geometry; unknown rate per reason; no CLEAR without complete coverage |
| **P5** Caches | Demand-driven static visibility caches; surfel visibility as prediction (with the GI thread); R-A's representation as a cache if it passed | Net benefit including memory and maintenance |
| **P6** Hardware RT | xGPU acceleration structures; RT as one more backend behind the query | Equal-time comparison against P4 |

**The P1 report** (one per step):

| Evidence | Required result |
|---|---|
| Reference preservation | Saved outputs and analytic tests pass; changed images explained (the sun's shadows change on purpose) |
| Footprint and density | Footprint percentiles, selected level and requested pages, boundary and fallback rates (debug view + numbers) |
| Resource validity | No ABSENT, DIRTY, obsolete or generation-mismatched page sampled as evidence (invariants 1-2) |
| Degradation | Forced overflow: resolution loss with pinned coverage, no hole (invariant 3); epoch invalidation explicit (4) |
| Static reuse | Page redraw counts before/after; six transitions (P1b) |
| Cost and memory | Every sec. 10 metric (invariant 5): request, admission, rendering, pairs, pool peak/committed, pinned bytes |
| Stress | 0 / 50 movers, a fast camera move, a teleport (B7), a moving sun (B5), forced budget exhaustion (B11) |

Kept out of the critical path until measured: stale-page reuse, page Hi-Z, local lights, the moving sun, texture streaming, the
research track, every later phase.

**Break tests** (fixtures, `lighting_fixtures.md`): B1 door; B2 small blocker, long shadow; B3 mover stops, cached, moves; B4 colour
change (done); B5 moving sun 0.1°/frame, **B5b at cycle speed**; B6 glossy across tiles; B7 teleport; B8 foliage; B9 GI eviction; B10
overlapping lights; B11 forced overflow; **B12 filter boundaries** (page, level, screen edge, thin blocker, large source angle);
**B13 slot reuse under generation mismatch**.

## 12. Not to do

- Merge the allocators or the physical pools (shadow, textures, material OffsetAllocator, GI rings, probe slots): lifetimes and
  formats differ; share the residency policy and telemetry only.
- Make the GI read the camera-centred tile or cell lists; share the function (6.5), not the data.
- Fold material opacity into the GI's transport role.
- Cascades, warping or SDSM for the sun; depth reprojection as a correctness path for a moving sun.
- Pure LRU over the whole pool; a slot republished before its old generation's accesses complete.
- "Every shadow is virtual" as a rule: a light reaching five receivers may be cheaper to test directly once R-B says so; until then
  pages are the only supported path for raster-only semantics (masked, skinned).
- CLEAR from coarse or incomplete data; BLOCKED from a texel a caster does not fully cover.
- Make every texture virtual; unify compile-time identities with frame change events; reuse the camera's Hi-Z *contents* for shadow
  pages (the pyramid *code* is reused in light space, R-A).
- Per-texel masked rays before the opaque reference (exists now) is matched by the page path.
- Route light class or budget through material blocks or `entity_params`.
- Treat hardware RT as an early reference; prediction with stochastic correction before P5.
- Claim novelty or performance for sec. 7c before its experiments report.

## 13. Decisions

1. **K:** the sun plus up to 4 admitted local key lights per tile. Today's SAMPLED mode stays the baseline.
2. **UNKNOWN fallback:** unshadowed and counted; conservative dark as a diagnostic; no stale-page mode in P1; under pool pressure the
   pinned coarse page, labelled, is the fallback before unshadowed.
3. **P1 scope (v3.3):** the first build is P1a-0/1/2, a shadow-only, fixed-sun-per-epoch correctness experiment with the pool at 32 MiB;
   then P1b, P1c; P1d, P1e and the VM generalization after; R-A/R-B/R-C as branches with their own go/no-go. Not in the first build:
   the texture backend, octahedral points, full-capacity static/working duplication, a pure-LRU pool, the moving sun.
4. **Point lights:** 6 cube faces. **Sun motion:** quantized epochs with a cross-fade (P1e), θ configurable.
5. **GI coordination:** the interface notice (handle and revisions, change-event schema, the entry points' quantities, spatial
   coverage) plus one new item: whether `Occluded` may be dispatched for R-B's direct tests under lighting's budget, read-only.
   Code adoption proposed only after P1b's measurements.
6. **Open for Tomas:** the day/night cycle length and whether θ is exposed; the pinned-net share (25% proposed); the memory option
   before P1b (working copies only for occupied pages proposed); whether R-A runs before or after P1b when both are ready.
