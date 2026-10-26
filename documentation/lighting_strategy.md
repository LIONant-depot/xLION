# Lighting strategy: direct light, shadows, many lights (v3.1, 2026-10-26)

Status: design only. Nothing is built until Tomas says go.

The GI belongs to its own thread: this document proposes interfaces the GI may adopt, never GI changes. Sources:
- documentation/many_lights_and_shadows_research.md;
- documentation/lighting_gi_material_synergies.md;
- documentation/gpu_cluster_culling.md;
- the GI notes in xLIONRender/documentation.

`R/` = `example.lionprj/Cache/dependencies/xLIONRender/src/`.

## Changelog

### v1 (99bb74a) → v2 (e8c8ed2)

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

### v2 → v3 (all driven by the final external review)

| Change | Review section |
|---|---|
| Shadow resource states: invalidation is immediate, rebuilding is budgeted, and head admission needs VALID (sec. 3, 4, 7) | 1, 7 |
| Light handle (lifetime) separate from revisions (visibility, radiometry), plus a dependency table (sec. 6.1) | 2 |
| Spatial completeness separate from instance capability flags; `m_Info.z/w` no longer committed (sec. 3, P4) | 3 |
| Temporal reconstruction distinguished from substituting predicted visibility (sec. 3) | 4 |
| Per-tile dynamic occupancy; the memory advantage is a hypothesis with an allocation sketch and accounting (sec. 7) | 5 |
| A shadow cull mode fed by shadow-eligible casters, not camera survivors; page Hi-Z optional (sec. 6.4, P1b) | 6 |
| LightEval split into entry points with stated quantities; reference outputs saved before extraction; `MaterialVisibility` compositional (sec. 6.2, 6.5) | 8, 9 |
| The ledger total includes records/grid and cache maintenance; fused ray cost not timestamped separately; the open questions became decisions (sec. 10, 13) | 10, 11 |

### v3 → v3.1 (the go-ahead review's clarifications)

| Change | Where |
|---|---|
| Caster changes include shadow-producing content without movement; static age = frames since the shadow-producing state changed | Sec. 6.3 |
| A working tile is VALID only with the required static version *and* dynamic composition | Sec. 3 |
| BLOCKED only from a hit that satisfies the requested semantics; masked hits without alpha prove nothing | Sec. 3 |
| P1 has no stale-map mode: VALID → sample, otherwise fallback + counter | Sec. 3, 13 |
| Head admission and sampling data come from one published snapshot | Sec. 4 |
| Freeze: membership frozen, parameters current, probabilities recomputed | Sec. 9 |
| P0 order, output tolerance, minimal P0 before P1a; static eligibility and occupancy rules; the P0/P1a report | Sec. 7, 11, 13 |

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
| Material classes | `render_settings`: Opaque / Masked / Translucent / Additive, cast shadows, alpha cutoff (`plugins/xmaterial.plugin/source/xmaterial_render_settings.h`) | One `MaterialVisibilityOf(material)` that every system reads |
| Light identity | None. Lights are rebuilt every frame; three consumers hash them | Light handle + revisions (sec. 6.1) |
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
2. **Prediction** (surfel visibility, remembered per-tile visibility, visibility history) may guide selection and work. It never
   substitutes for a fresh or validated visibility result in the raw light estimator. Three things are kept apart:
   - a historical *lighting* estimate: reused by temporal reconstruction under its own, separately measured contract (sec. 4);
   - historical *visibility* used for guiding: prediction;
   - cached visibility whose dependencies are validated: evidence.
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

A hit proves BLOCKED only if the hit itself satisfies the requested material and caster semantics. A supported opaque blocker proves
it even when unsupported geometry lies alongside; a hit on a masked triangle whose alpha was not evaluated does not (today the BVH
treats masked as solid). No blocker found in a partial scene is UNKNOWN, not CLEAR.

**The screen trace** covers only the span next to the surface and may conclude BLOCKED, never CLEAR. Its hits stay within the
declared contact-shadow approximation (APPROXIMATE), never stronger evidence than the depth buffer supports. It honours caster roles,
and its answers never enter a world-space cache.

**Coverage contract:** direct-light trace coverage follows the GI's published visibility residency and its supported caster
classes. Lighting never pins GI geometry. Evicting GI lighting state must never remove an occluder from the rays without the rays
reporting UNKNOWN (the GI chunks plan's "Streaming" rule already keeps geometry and light residency apart).

CLEAR = no blocker found **and** the required occluder coverage along the query is complete. That takes two kinds of metadata:

| Metadata | Answers |
|---|---|
| Instance capability flags | Does this *represented* instance support the needed geometry/material semantics? |
| Spatial coverage | Is potentially relevant geometry *missing* along this query (an empty region versus an unrepresented one)? |

Flags on resident TLAS instances cannot describe an instance that is not there. The GI thread chooses the spatial representation
(chunk coverage, non-resident bounds or proxies, a known-complete region).

**Shadow resources have a state:** ABSENT, VALID, DIRTY or BUILDING, plus a content/dependency version, an allocation generation,
the last update frame and an estimated update cost.
- **Invalidation is immediate; rebuilding is budgeted.** A resource loses evidence status the moment a dependency changes. The
  budget decides when it becomes VALID again, never whether the invalidation takes effect.
- A **working** tile is VALID only when it holds the required static-content version *and* the required dynamic composition for the
  published frame. A valid static source does not make a working tile valid while its movers' restore/draw is deferred. A small
  dependency record per tile is enough; no general dependency graph.
- While DIRTY or BUILDING, consumers use the declared fallback. **P1 rule: VALID → sample; otherwise → declared fallback + counter.**
  Reusing a stale map for a bounded age (classified APPROXIMATE, age counted) stays documented but unbuilt until fallback artifacts
  are a measured problem. Likewise a resource being rebuilt for an unrelated reason could keep its published version
  (double-buffered publication), only if measured stalls justify it.
- Three things are separate: a resource is VALID; it was selected for update; its light is admitted to the deterministic head. A
  light enters the head only with a VALID resource, never on the assumption that a requested map will exist.
- This reuses the local-map budgeting; there is no new allocator or scheduler, only a stronger readiness contract.

## 4. Light paths and budgets

- **Deterministic path:** the sun and K key lights, through cached shadow pages: stable filtering, full resolution, no denoiser.
  "Deterministic" means stable, not exact: maps have resolution and bias, and soft shadows from pages are a stable approximation.
- **Sampled path (the tail):** every other light in reach, via the grown `light_cells` SAMPLED estimator.
- **Two budgets, both logged:**
  1. per tile: head size K and tail samples;
  2. global shadow preparation: today's local-map update budget extended, not a new mechanism. It accounts for:
     - valid resources (free to retain);
     - dirty ones (repair);
     - missing ones (initial build);
     - the recurring restores and mover draws.
- **Two related decisions, two rankings:**
  - deterministic lights are *selected* by visual benefit and resource readiness. A slightly weaker light with a valid map may be
    cheaper to keep in the head than a stronger light that needs a new map every frame;
  - updates are *scheduled* by visual error and repair cost.
- Start with simple priority classes, not a numeric error/cost model, until there are measurements. Hysteresis never preserves
  invalid evidence.
- **Head:** the sun is outside K. Up to K = 4 admitted local key lights per tile. A light needs a useful contribution and a VALID
  visibility path; unused slots stay empty.
- **One published snapshot.** Light handles and revisions, resource bindings and validity, head membership and weights, and the
  sampling-distribution data are published together with the existing frame buffering. No shader sees a new admission list with old
  light parameters or resource metadata. No new synchronization framework.

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

1. **Light records: a lifetime handle plus revisions.**
   - `LightHandle { slot or entity; lifetimeGeneration }`. Deletion and slot reuse change the identity.
   - `LightRevisions { visibilityRevision; radiometryRevision }`. A moving light keeps its identity, so candidate lists keep its
     discovery history and only refresh its parameters.
   - The scene renderer already maps entities to ids. A persistent record buffer is uploaded on change, like `instance_slots`.
     Shadows, probes, cells and (optionally) the GI key on the handle plus the revision they depend on. Two hashes go away.

   | Property | Bumps | Shadow depth | Per-tile lists | Radiometric values |
   |---|---|---|---|---|
   | Position, orientation, light type, radius, cone, emitter size or shape, projection settings | Visibility revision | Invalid | Entry kept, its visibility re-checked | Recomputed |
   | Shadow-caster mask | Visibility revision | Invalid | Entry kept, visibility re-checked | — |
   | Colour, intensity | Radiometry revision | Kept | Kept (importance refreshed) | Recomputed |
   | Deletion, slot reuse | Lifetime generation | Freed | Entry dropped | Dropped |

   Not every row needs its own counter at first, but the table is the contract.
2. **`MaterialVisibilityOf(material_state)`:** one authoritative helper that returns separate properties, not one enum:
   `MaterialVisibility { opacityMode: OPAQUE | MASKED | BLENDED; castsShadow; alphaCutoff; alpha resources (when supported) }`.
   Emission is a separate property (`m_bEmissive`, set by the material compiler). A material that casts no shadow may still appear in
   reflections, receive light, emit, and keep its GI role. The GI's see-through, the caster loop and the later any-hit mask all call
   it. Today the GI sees through only blended materials, so masked materials are solid to its rays.
3. **One change list per frame:** `scene_changes { caster bounds (old and new), light handles + revisions, epoch }`, built once
   (today's `m_FrameChanged`). Consumers: the clipmap, local maps, probes, the static caches and the per-tile lists; the GI's
   `MarkLinksCrossing` may listen. The second diff path (`m_PrevCasters`) folds into `slot_caster`.
   - **A caster change includes any change to its shadow-producing geometry, opacity or participation, not only movement:** material
     assignment or opacity mode, alpha cutoff or alpha texture, `castsShadow` or caster-mask membership, mesh replacement or geometry
     revision, deformation or displacement state. Events keep the affected bounds even on deletion.
   - **Static age** = frames since the *shadow-producing* state changed. Shadow-affecting changes reset it; unrelated ones (an albedo
     colour) do not. `instance_slots`' change test is the starting point, narrowed to those fields.
4. **Shadow pages through the GPU cull, in a shadow mode.** Tile and face view-projections are the cull's matrix, but the input is
   the **eligible resident caster set**, not the camera's surviving draws. The shadow mode must not inherit:
   - camera visibility, camera size thresholds or camera LOD;
   - camera-facing normal-cone or backface assumptions;
   - static-only candidates;
   - the camera's depth convention.

   Candidates are built once per frame and reused across views; masked casters are runs bound by material base. Off-screen casters
   are a mandatory fixture. Page Hi-Z is not a prerequisite: first frustum and page culling, correct indirect submission and the
   existing masked and skinned handling, then measure whether a page Hi-Z pays for itself.
5. **One `LightEval` GLSL include: shared physics, not shared sampling decisions.** Separate entry points, each stating what it
   returns:
   - `EvaluateLightGeometry`: attenuation, cone, direction;
   - `EvaluateIncidentLighting`: incident radiance or irradiance;
   - `EvaluateReceiverBRDF`: outgoing radiance; needs the view direction and the material;
   - `EstimateSelectionImportance`: may differ between pixels and GI receivers.

   Used by forward shading, the cells' importance and, if the GI thread agrees, the GI's direct light; today the formula exists three
   times. A GI receiver wants diffuse irradiance or a source term, not camera radiance, so this is not a GI redesign. Later (P3), the
   cell walk becomes a shared function whose return quantity is stated per caller. **Before extracting it, P0 saves the current
   reference outputs.** Analytic tests (distance attenuation, cone boundaries, zero contribution, radiometry-only changes) guard
   against EXACT and SAMPLED sharing the same new bug.

## 7. Static/mover split: restore-then-draw

- The static depth of a tile or map is cached and holds static casters only. Each frame, every tile whose **previous or current**
  dynamic footprint touches it is restored from the static copy, then the movers are drawn into the working copy.
- The static copy and the working copy are both shadow resources with the states of sec. 3. A static change marks the static copy
  DIRTY at once; until it is rebuilt, the affected tiles use the declared fallback (or a counted, bounded-age APPROXIMATE).
- "Static after N frames" means cache-eligible, not proven static. Declared deformers (skinned) are always movers. When an object
  that is in the static cache moves, the static cache under its old and new bounds is invalidated and redrawn.
- **Eligibility versus admission.** N is the engine's existing threshold if one exists, otherwise a configurable value; promotions and
  demotions are logged. Eligibility is immediate; *admission* into the static cache is budgeted, so a wave of newly eligible objects
  does not cause a rebuild burst. Measured: static rebuilds caused by promotion, rebuilds caused by recently promoted objects moving
  again, dynamic drawing saved.
- **Occupancy is conservative:** from projected caster bounds, never a false negative. Tighter coverage only if excess restore work
  shows up in the ledger.
- **Per-tile dynamic occupancy.** A tile is not "dynamic forever" once a mover has touched it:

  | State | Work |
  |---|---|
  | Static-only, a mover enters | Restore static, draw movers |
  | Movers remain or move | Restore static, draw current movers |
  | The last mover leaves | Restore static once |
  | Static-only | No dynamic work |

  The recurring cost is then proportional to the tiles affected now, plus a one-time cleanup when a mover leaves.
- **Restore-then-draw versus a second layer is a hypothesis.** Both keep preserved static depth plus somewhere for the composited
  depth; which uses more memory depends on what already exists. Restore-then-draw stays the chosen experiment.

  ```
  today:          shadow atlas (sampled)  = static + movers, a moved caster re-renders whole tiles
  restore-then-draw:
                  static atlas (cache)    = static casters only, redrawn on static change
                  working atlas (sampled) = restored from static where occupancy says so, movers drawn on top
  second layer:   static atlas + dynamic atlas, both sampled and composited per lookup
  ```

  P1a measures persistent atlas bytes, working atlas bytes, restore bytes per frame, and the copy/restore synchronization cost.

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
  - light handle + revision, head or tail;
  - probability and weight;
  - visibility status, source and epoch, and the fallback reason;
  - whether the history was accepted, and the final contribution.
- No CPU re-evaluator.
- The inspector distinguishes three cases: not selected this frame, selected but zero, reconstruction dark.
- **Freeze-lists toggle**, shown as frozen. Candidate *membership* is frozen; the current valid light parameters are still read. A
  lifetime mismatch (deleted, slot reused) drops the entry. A visibility revision invalidates obsolete guidance; a radiometry revision
  refreshes the entry. The probabilities the active estimator needs are recomputed, never frozen while the weights they represent
  change. A fully frozen lighting snapshot, if wanted later, is a separately named debug mode.
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
| Visibility work | Tail BVH queries (P4), when they are a separate dispatch; fused into shading, they stay inside "direct shading" and are attributed approximately with paired variants (rays on/off), never as a fake exclusive timestamp |
| Cache maintenance | Static cache upkeep, list ageing |
| CPU (reported separately) | Caster enumeration and submission, change list |

**The sun's ≤ 0.8 ms (50 movers) is inside "shadow preparation", not inside the direct-shading budget.**
Lighting subsystem total = records/grid + shadow preparation + direct shading + reconstruction + visibility work + cache
maintenance. CPU is reported separately; costs shared with other systems (the GI's BVH, the camera cull) are named, never counted
twice.

**UNKNOWN fallback metrics:** the fraction of queries that fell back, and the estimated unoccluded contribution those queries
carried, sample-weighted for sampled lights. That second number is exposure to uncertainty, not measured "missing energy".

Statistics: median, p95, p99, cold start (first 60 frames after a level load or a teleport), unknown rate per reason, error against
the references.

## 11. Roadmap

Each phase has a gate, measured with the ledger.

| Phase | What | Gate |
|---|---|---|
| **P0** Reference and ledger (evidence, not the first big refactor) | In this order: 1. save today's outputs and timings; 2. make the reference fixtures reproducible: (a) **sampling reference**, EXACT with the same visibility source as SAMPLED; (b) **visibility reference**, the GI's light BVH with shadow rays, opaque rigid scenes only, every capture labelled (`opaque rigid: supported; skinned: unsupported; per-texel masked: unsupported`), skinned and masked scenes compared against the raster path; a many-ray tail reference; 3. the minimal ledger (sec. 10) and the diagnostic skeleton (sec. 9, record + counters, no finished inspector UI); 4. extract `LightEval` (sec. 6.5) with its analytic tests; 5. verify against the saved baseline. Break tests (below) are *defined* as fixtures; they are not all running before P1a | References reproduce. "Changes no saved output" = bitwise equal where practical, else within an explicit numerical tolerance; any difference outside it is explained, never accepted because EXACT and SAMPLED still agree |
| **P1a** Static/mover correctness, **sun first** | Light handle + revisions (6.1), `MaterialVisibilityOf` + emissive flag (6.2), one change list + static age (6.3); shadow resource states (sec. 3); restore-then-draw for the sun clipmap with old + new footprint and per-tile occupancy; skinned via the existing path. Local maps follow in the same phase only if the sun's assumptions hold | The six transition tests pass; no DIRTY resource or obsolete working composition is ever sampled as evidence; static redraw drops as expected; the allocation accounting of sec. 7 measured; forced preparation-budget exhaustion shows the declared fallback and its counters |
| **P1b** GPU caster culling | Shadow pages through the GPU cull's shadow mode (6.4), candidates built once per frame; page Hi-Z only if measured to pay | No per-light CPU caster enumeration or submission growth (that is "flat CPU"); sun ≤ 0.8 ms with 50 movers (warmed benchmark); no caster coverage regression, off-screen casters included |
| **P2** Per-tile head/tail | `light_cells` grows: per tile, GPU-built, stable ids, a visibility term from existing maps guiding selection with the floor kept | Sampling error against EXACT converges; no pops on a light ramp; the glossy floor test |
| **P3** The tail | `EvaluateDirectAtReceivers`; screen trace (blocked-only); short-history denoiser; the global preparation budget | Claim only: "key lights shadowed by pages, tail contact-shadowed"; reconstruction error measured separately |
| **P4** Traced visibility | Tail shadow rays through the GI's any-hit, with a declared ray budget. The GI publishes enough spatial coverage to tell an empty region from an unrepresented one; instance flags (possibly the free `m_Info` lanes) describe supported semantics, not completeness. Unknown reasons; alpha any-hit via bindless texture ids if the GI thread agrees | Visibility-model error on supported geometry; unknown rate per reason; no CLEAR without complete coverage |
| **P5** Caches | Demand-driven static visibility caches; surfel visibility as a *prediction* for selection (with the GI thread) | Net benefit including memory, invalidation and maintenance |
| **P6** Hardware RT | xGPU acceleration structures; RT as a visibility source | Equal-time comparison against the P4 software path |

**The P0/P1a report** (one compact report):

| Evidence | Required result |
|---|---|
| Reference preservation | Baseline comparison and analytic tests pass |
| Six transitions | Working depth agrees with a full redraw within the declared tolerance |
| Resource validity | No dirty or obsolete working composition sampled as evidence |
| Static reuse | Static redraw counts before/after |
| Cost | Restore, static redraw, mover draw, total shadow preparation |
| Memory | Static atlas, working atlas, metadata |
| Stress behaviour | 0 movers, 50 movers, and forced preparation-budget exhaustion |

Kept out of the critical path until measurements justify them: stale-map reuse, page Hi-Z, local-map expansion, every later-phase
feature.

**Break tests** (defined as fixtures in P0, enabled by the phase that needs them):
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
- Reuse the camera's Hi-Z or the camera's surviving draws for shadow pages or the GI.
- Add per-texel masked rays before P0's opaque reference exists.
- Route light class or budget through material blocks or `entity_params`.
- Treat hardware RT as an early reference: xGPU has no acceleration structures. The GI's `Occluded` and a many-ray reference serve
  instead.
- Prediction with stochastic correction (VisCache-style): research only, after P5.

## 13. Decisions (open questions, answered with the final external review)

1. **K:** the sun plus up to 4 admitted local key lights per tile; slots are not filled for their own sake. Today's SAMPLED mode stays
   as the baseline: a per-tile builder must show enough benefit to justify its preparation and memory cost.
2. **UNKNOWN fallback:** unshadowed and counted by default (sec. 10's two metrics); conservative dark as a diagnostic mode. No
   stale-map mode in P1.
3. **P1a scope:** the sun first, with its transition tests and timing, then local maps if its assumptions hold. Two cache
   implementations are not prerequisites for the first result.
4. **GI coordination:** send the GI thread a short interface notice now, and ask it to change nothing:
   - the light handle and revision fields;
   - the change-event schema;
   - the lighting quantities each entry point returns;
   - the spatial-coverage question (sec. 3).

   Code adoption is proposed only after P1a's measurements.
