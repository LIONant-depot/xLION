# Lighting strategy: direct light, shadows, many lights (v2, 2026-10-26)

Status: design only. Nothing is built until Tomas says go.

The GI belongs to its own thread: this document proposes interfaces the GI may adopt, never GI changes. Sources:
- documentation/many_lights_and_shadows_research.md;
- documentation/lighting_gi_material_synergies.md;
- documentation/gpu_cluster_culling.md;
- the GI notes in xLIONRender/documentation.

`R/` = `example.lionprj/Cache/dependencies/xLIONRender/src/`.

## Changelog from v1 (99bb74a)

| Change | Driven by |
|---|---|
| Visibility answers are typed (evidence / prediction / unknown). Unknown has a declared, counted fallback per source and is never silently "visible" (sec. 3) | External review 1 (sec. 1, 9); review 2 (cond. 1) |
| The fixed tier order became sources behind one typed query; surfel visibility is a prediction for selection only | Review 1 (sec. 1); Fable |
| An exists-vs-new table (sec. 2): the sun clipmap, local-map budget, light_cells SAMPLED, GI any-hit, roles and see-through already exist | Fable; my code checks |
| Two budgets: per-tile shading and global shadow preparation, with hysteresis | Review 1 (sec. 4) |
| Static caches hold static casters only; movers use restore-then-draw over the old and the new footprint; six transition tests | Review 1 (sec. 8); review 2 (cond. 4); Fable |
| Unbiasedness scoped to the estimator; three separate error measurements; guidance never removes support | Review 1 (sec. 5, 6); review 2 (cond. 2) |
| P0 gets two references (sampling, visibility) with coverage labels | Review 2 (cond. 3) |
| Unknown reasons are reported separately; "no blocker in a partial scene" is not "clear" | Review 2 (cond. 6) |
| Debug records come from the GPU path; freeze is generation-safe | Review 2 (cond. 7) |
| P1 split into P1a (correctness) and P1b (GPU caster culling); "flat CPU" defined | Review 2 (cond. 8) |
| One non-overlapping timing ledger with clock state and two operating conditions | Fable (P3 clocks); review 2 (cond. 9) |
| The competitor table became falsifiable hypotheses; MegaLights facts corrected; GigaLights claim cited | Review 1 (sec. 15); Fable; review 2 (cond. 10) |
| An out-of-scope table: blended, skinned, masked, fog, mobile, previews | Fable; review 2 (cond. 5) |
| Shared infrastructure placed into phases: light id + generation, material visibility class, one change list, shadow pages through the GPU cull, a shared light-eval include | Synergy review (Fable + me) |
| Removed: "three systems versus one", "survives camera cuts", "computed once", the unmeasured mobile 1.5 ms, fog as a consumer, hardware RT as an early reference | Fable; reviews 1 and 2 |

## 1. Goal and hypothesis

The goal: many lights, the strong ones stable and noise-free, the rest sampled at a bounded cost. Shadow work is shared with the
GI's visibility, and every decision can be inspected from the editor and by the AI.

**The hypothesis to prove or drop:**
> On scenes with substantial stable geometry and lighting, deterministic important lights, static-only shadow caches, and an
> unbiased sampled tail may reduce shadow work and temporal instability at a fixed total budget, without hardware RT.

How we stand against the competitors: hypotheses, each with the test that would refute it.

| Claim about us vs them | Facts we rely on | Test |
|---|---|---|
| Our sun and key lights are noise-free, like Unreal's | Unreal: the sun uses VSM, and MegaLights leaves directional lights out by default (`r.MegaLights.DirectionalLights=0`) | Temporal luminance deviation on a still scene, sun + key lights |
| The tail costs less per quality because static shadow work is cached | MegaLights guides its sampling by history (GuideByHistory, a visible-light hash per tile) and ships on hardware RT; a software path exists | Equal-time error against the reference on the stress city |
| We avoid re-tracing static visibility for key lights | GigaLights: every sample's shadow ray is traced each frame (`GigaLightsLightingKernels.hlsl`: the samples' shadow rays from `GL_ShadowRayStart`, e.g. lines 1005, 1228). It remembers *which* lights a tile saw (an 8-entry list with ages) and a radiance history (`GigaLightsRadianceHistory.compute`), not per-light visibility. Read 2026-10-26 in `E:\source_code\gigalights`, learning only | Shadow-pass ms with 0 / 50 movers |
| Runs without RT | xGPU has no acceleration structures; the GI's software BVH exists | All of P0–P4 run on the no-RT path |

## 2. What exists and what is new

| Piece | Exists (where) | New in this plan |
|---|---|---|
| Sun shadows | Clipmap of world-anchored cached tiles; invalidation by caster bounds projected along the light (`R/features/shadows/xlionrender_shadow_clipmap.h`) | Static/mover split. Today a mover re-renders its whole tiles (line 18), and skinned casters invalidate theirs every frame |
| Local shadows | Cached octahedral/frustum maps in a buddy atlas, an update budget (maps without a map first, then by urgent age), a cache key ignoring colour and intensity (`xlionrender_shadow_local.h:253-261`) | The same split; the budget grows into the global preparation budget |
| Many lights | `light_cells`: a world-cell clipmap; mode SAMPLED = exact head + one tail light with a floored probability, tested unbiased against EXACT (`R/features/lights/xlionrender_light_cells.h`, `tests/xlionrender_test_light_lab.cpp`). Rebuilt on the CPU every frame | Per tile; a visibility term from existing maps; stable light ids; a GPU builder |
| Rays | The GI's software BVH (BLAS/TLAS), any-hit `Occluded`, see-through per triangle, transport roles (`R/shaders/xlionrender_gi_bvh.glsl`) | Lighting's ray budget and coverage classification (sec. 3) |
| An exact local-light reference | The GI's direct light: a light BVH with a shadow ray per light (`R/features/gi/xlionrender_surfel_gi.h:3265-3290`) | Used as P0's visibility reference, opaque rigid geometry only |
| Footprint invalidation | The GI marks the old and the new box on a move (`surfel_gi.h:2357-2381`); the shadows' `m_FrameChanged` lists changed caster bounds (`R/plans/forward/xlionrender_plan_forward.cpp:1076-1116`) | One per-frame change list (sec. 6) |
| Caster culling | GPU cluster culling for the camera, with a matrix-parametrized cull shader (`R/shaders/xlionrender_cull_comp.glsl`) | Shadow pages through it (P1b) |
| Material classes | `render_settings`: Opaque / Masked / Translucent / Additive, cast shadows, alpha cutoff (`plugins/xmaterial.plugin/source/xmaterial_render_settings.h`) | One `VisibilityOf(material)` that every system reads |
| Light identity | None. Lights are rebuilt every frame; three consumers hash them | Light id + generation |
| Denoiser, screen trace, per-tile memory | None | P2–P3 |

## 3. The visibility contract

Every visibility query returns a typed answer:

```
VisibilityResult { status: BLOCKED | CLEAR | APPROXIMATE | UNKNOWN;
                   value;                       // 0..1 when APPROXIMATE
                   source;                      // screen | shadow page | cache | BVH
                   epoch;                       // the published state it read
                   reason; }                    // when UNKNOWN
```

The rules:
1. **Evidence** (a current shadow-map sample within its model, a current BVH query, an unchanged cached sample whose dependencies are
   valid) may shade.
2. **Prediction** (surfel visibility, remembered per-tile visibility, history) may only guide selection and work, never darken the
   final light.
3. **Unknown stays unknown.** The consumer applies the source's *declared* fallback and counts the unresolved contribution (light
   energy shaded by a fallback, per reason). A fallback is neither a visibility fact nor unbiased.

| Situation | Declared behaviour |
|---|---|
| A valid shadow map covers the query | Use the map (evidence) |
| A valid, unchanged cached answer exists | Reuse it (evidence) |
| Only contact shadowing applies (a tail light with no map, before P4) | The contact-shadowed approximation, labelled APPROXIMATE |
| No supported source | The tier's declared fallback (default: unshadowed, counted); a "conservative dark" mode for debugging |
| A reference needs unsupported geometry | That measurement is marked unsupported, never treated as ground truth |

**Unknown reasons, reported separately:**
- outside the resident coverage;
- unsupported caster or material semantics;
- traversal or work limit reached;
- published state unavailable or invalid.

A blocker found proves BLOCKED under the query's semantics. No blocker found in a partial scene is UNKNOWN, not CLEAR.

**The screen trace** covers only the span next to the surface and may conclude BLOCKED, never CLEAR. It honours caster roles, and its
answers never enter a world-space cache.

**Coverage contract:** direct-light trace coverage follows the GI's published visibility residency and its supported caster
classes. Lighting never pins GI geometry. Evicting GI lighting state must never remove an occluder from the rays without the rays
reporting UNKNOWN (the GI chunks plan's "Streaming" rule already keeps geometry and light residency apart).

## 4. Light paths and budgets

- **Deterministic path:** the sun and K key lights, through cached shadow pages: stable filtering, full resolution, no denoiser.
  "Deterministic" means stable, not exact: maps have resolution and bias, and soft shadows from pages are a stable approximation.
- **Sampled path (the tail):** every other light in reach, via the grown `light_cells` SAMPLED estimator.
- **Two budgets, both logged:**
  1. per tile: head size K and tail samples;
  2. global shadow preparation: which lights or pages get updated this frame, ranked by estimated error reduction / update cost,
     admitted with hysteresis. This is today's local-map update budget extended, not a new mechanism.

**The estimator.** With head weights a_l(x), L = Σ a_l C_l + Σ (1 − a_l) C_l. The tail estimates the second sum as
(1 − a_J) C_J / q_J. Its correctness rests on:
- q matching the implemented selection;
- every contributing tail light keeping q > 0 (the floor);
- complementary head and tail weights;
- light ids carrying a generation.

The probability calculation is documented next to the code, not only tested. Selection is q = (1 − ε) q_guided + ε q_discovery.
Discovery reaches every light in reach, and lights that are new or changed get priority discovery in the cells they touch.
Visibility guidance never removes a contributing light's support.

**Three error measurements, never merged:**
1. **Sampling error:** SAMPLED against EXACT with *identical* visibility.
2. **Visibility-model error:** the visibility source against the visibility reference, on the geometry it supports.
3. **Reconstruction error:** after half resolution, temporal accumulation, filtering and clamping.

## 5. Light classes

| Class | Examples | Path | Caching |
|---|---|---|---|
| Static | Lamps, windows | Key, or tail (by importance) | Pages kept until their dependency epoch changes |
| Slow | Sun, moon | Deterministic (clipmap) | Tiles re-render only where the change list says so |
| Player-speed | Torches, car lights | Tail; key when it ranks | Per-tile lists follow by light id |
| Transient | Muzzle flashes, sparks | Tail, contact-only | None |

## 6. Shared infrastructure (from the synergy review)

1. **Light records with id + generation.** The id comes from the entity, which the scene renderer already maps. The *visibility
   generation* changes with position, radius or cone; the *radiometry generation* with colour or intensity. A persistent record
   buffer is uploaded on change, like `instance_slots`. Shadows, probes, cells and (optionally) the GI key on (id, gen). Two hashes
   go away.
2. **`VisibilityOf(material_state)`:** OPAQUE / MASKED / SEE_THROUGH / NO_SHADOW, plus `m_bEmissive`, set by the material compiler.
   The GI's see-through, the caster loop and the later any-hit mask all call it. Today the GI sees through only blended materials,
   so masked materials are solid to its rays.
3. **One change list per frame:** `scene_changes { caster bounds (old and new), light ids + generations, epoch }`, built once
   (today's `m_FrameChanged`). Consumers: the clipmap, local maps, probes, the static caches and the per-tile lists; the GI's
   `MarkLinksCrossing` may listen. The second diff path (`m_PrevCasters`) folds into `slot_caster`. **Static age** is frames since
   `instance_slots` last saw a change.
4. **Shadow pages through the GPU cull:** tile and face view-projections as the cull's matrix, candidates built once per frame and
   reused across views, masked casters as runs bound by material base.
5. **One `LightEval` GLSL include** (falloff, cone, attenuation), used by forward shading, the cells' importance and, if the GI thread
   agrees, the GI's direct light. Today the formula exists three times. Later (P3), `EvaluateDirectAtReceivers(P, N, cells, lights,
   rng, visibility)` is the cell walk as one function, called by pixels (shadow maps) and optionally by GI hits (`Occluded`).

## 7. Static/mover split: restore-then-draw

- The static depth of a tile or map is cached and holds static casters only. Each frame, every tile whose **previous or current**
  dynamic footprint touches it is restored from the static copy, then the movers are drawn into the working copy.
- "Static after N frames" means cache-eligible, not proven static. Declared deformers (skinned) are always movers. When an object
  that is in the static cache moves, the static cache under its old and new bounds is invalidated and redrawn.
- Why restore-then-draw rather than a second layer: the clipmap is 4 levels × 4×4 tiles in an 8×8 atlas. A permanent dynamic layer
  doubles that memory, while with about 20 tiles touched by 50 movers the copy is cheaper. This gets confirmed by measurement in
  P1a.

**Transition tests (P1a), each checked against a full re-render for stale depth:**
1. A mover enters a tile.
2. It crosses into another tile.
3. It leaves the visible region.
4. It is deleted.
5. It becomes cache-eligible.
6. That newly cached object moves again; the static cache must invalidate.

## 8. Out of scope for the first phases, and the rule meanwhile

| Case | Rule |
|---|---|
| Blended receivers | Keep today's full-cell shading; they never consume opaque half-resolution lighting or history. The many-light cost bound applies to the opaque path only |
| Skinned / deforming casters | Always movers through the raster shadow path; not in the BVH, so no off-screen tail occlusion is claimed for them |
| Alpha-tested casters | Raster visibility where a map covers the light. A masked caster shadows a tail light only if that light has raster coverage. Rays do not certify per-texel visibility until P4's alpha any-hit |
| Fog | A future consumer; no dependency |
| Mobile / Apple | Unmeasured targets, not performance claims; MoltenVK subgroup behaviour unverified |
| Material previews, thumbnails | One host-granted budget per application (as the GI's allowance); no main-view allocation |

## 9. Debuggability

- **Per-pixel record from the real GPU path**, read back asynchronously like the cull stats. It holds:
  - view and frame, surface id, cell or tile;
  - light id + generation, head or tail;
  - probability and weight;
  - visibility status, source and epoch, and the fallback reason;
  - whether the history was accepted, and the final contribution.
- No CPU re-evaluator.
- The inspector distinguishes three cases: not selected this frame, selected but zero, reconstruction dark.
- **Freeze-lists toggle:** shown as frozen. A referenced light that changed or was deleted is detected by its generation and dropped,
  never read stale.
- Counters through `DescribeScene`: unknown rate per reason, fallback energy, pages updated, restore and copy ms.

## 10. Measurement: one ledger

Every row is exclusive (no overlaps). Each capture records:
- GPU clock state (the editor can sit at P3, 200-450 MHz);
- resolution, active views, build configuration, workload;
- compile idle before and after.

Two operating conditions, both reported:
1. **Editor-normal:** what Tomas sees.
2. **Warmed benchmark:** maximized, Release, frame budget off, reproducible. The comparison basis.

| Ledger row | Contents |
|---|---|
| Light records + grid | Record upload, cell or tile build |
| Shadow preparation | Restore/copy, static redraw, mover draw, page culling (separate sub-rows) |
| Direct shading | Head + tail evaluation |
| Reconstruction | Denoiser, upsampling |
| Rays | Tail BVH queries (P4) |
| CPU | Caster enumeration and submission, change list |

**The sun's ≤ 0.8 ms (50 movers) is inside "shadow preparation", not inside the direct-shading budget.** The direct-light total =
shadow preparation + shading + reconstruction + rays.

Statistics: median, p95, p99, cold start (first 60 frames after a level load or a teleport), unknown rate per reason, error against
the references.

## 11. Roadmap

Each phase has a gate, measured with the ledger.

| Phase | What | Gate |
|---|---|---|
| **P0** Reference and ledger | (a) **Sampling reference:** EXACT with the same visibility source as SAMPLED. (b) **Visibility reference:** the GI's light BVH with shadow rays, opaque rigid scenes only, every capture labelled (`opaque rigid: supported; skinned: unsupported; per-texel masked: unsupported`); skinned and masked scenes compared against the raster path. Many-ray tail reference. The ledger (sec. 10). The `LightEval` include (sec. 6.5). The per-pixel record skeleton and counters (sec. 9). The break tests listed below as fixtures | References reproduce; the ledger runs on the stress city and Police |
| **P1a** Static/mover correctness | Light id + generation (6.1), `VisibilityOf` + emissive flag (6.2), one change list + static age (6.3); restore-then-draw for the sun clipmap and the local maps, old + new footprint; skinned via the existing path | The six transition tests pass; static redraw drops as expected; memory and restore bandwidth measured |
| **P1b** GPU caster culling | Shadow pages through the GPU cull (6.4), candidates built once per frame | No per-light CPU caster enumeration or submission growth (that is "flat CPU"); sun ≤ 0.8 ms with 50 movers (warmed benchmark); no caster coverage regression |
| **P2** Per-tile head/tail | `light_cells` grows: per tile, GPU-built, stable ids, a visibility term from existing maps guiding selection with the floor kept | Sampling error against EXACT converges; no pops on a light ramp; the glossy floor test |
| **P3** The tail | `EvaluateDirectAtReceivers`; screen trace (blocked-only); short-history denoiser; the global preparation budget | Claim only: "key lights shadowed by pages, tail contact-shadowed"; reconstruction error measured separately |
| **P4** Traced visibility | Tail shadow rays through the GI's any-hit, with a declared ray budget; coverage bits in the TLAS instance record's free lanes (`m_Info.z/w`, published by the GI); unknown reasons; alpha any-hit via bindless texture ids if the GI thread agrees | Visibility-model error on supported geometry; unknown rate per reason reported |
| **P5** Caches | Demand-driven static visibility caches; surfel visibility as a *prediction* for selection (with the GI thread) | Net benefit including memory, invalidation and maintenance |
| **P6** Hardware RT | xGPU acceleration structures; RT as a visibility source | Equal-time comparison against the P4 software path |

**Break tests** (fixtures from P0, enabled by the phase that needs them):
- a door opening (rediscovery);
- a small blocker with a long shadow (non-local invalidation);
- a mover stopping, becoming cache-eligible, then moving again;
- a light colour change (radiometry only: no page redraw);
- a moving sun (churn);
- a glossy surface across tile boundaries;
- a camera teleport into a cold region;
- alpha-tested foliage (backend agreement);
- GI state eviction with direct shadows visible (ownership);
- many overlapping lights in one cell;
- forced queue or cache overflow (classified degradation).

## 12. Not to do

- Merge the allocators (shadow buddy, material OffsetAllocator, GI rings, probe slots): their lifetimes differ, and GI residency is
  the GI thread's.
- Make the GI read the camera-centred tile or cell lists as its light source. Share the *function* (6.5), not the data; GI hits are
  off-screen.
- Fold material opacity into the GI's transport role: role is per instance, opacity per material; they compose.
- Unify compile-time identities (`UpdateCount`, `m_LayoutHash`, `m_GIStamp`) with frame change events.
- Reuse the camera's Hi-Z for shadow pages or the GI: per-page Hi-Z only.
- Add per-texel masked rays before P0's opaque reference exists.
- Route light class or budget through material blocks or `entity_params`.
- Treat hardware RT as an early reference: xGPU has no acceleration structures. The GI's `Occluded` and a many-ray reference serve
  instead.
- Prediction with stochastic correction (VisCache-style): research only, after P5.

## 13. Open questions for Tomas

1. **K, the head size per tile:** 2-4? Recommended: start with 4 and measure the sampling error.
2. **The declared fallback for UNKNOWN:** unshadowed (counted) by default, conservative dark in a debug mode? Recommended: yes.
3. **P1a's local maps:** same phase as the sun, or right after it? Recommended: the sun first (it has the measured 50-mover problem),
   then local maps in the same phase if restore-then-draw holds.
4. **The GI thread adopting `LightEval` and the change list:** propose it now, or after P1a lands? Recommended: after P1a, with
   numbers.
