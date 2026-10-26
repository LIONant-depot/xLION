# Lighting x GI x materials: synergies (analysis, 2026-10-26)

What the lighting strategy (`lighting_strategy.md`, plus the two external reviews and the Fable review), the surfel GI and the material
system can share, delete or level up. Analysis only: nothing here is approved for building. The GI belongs to its own thread, so the
GI items are **interfaces the GI may adopt**, never GI rewrites.

`R/` = `example.lionprj/Cache/dependencies/xLIONRender/src/`, `M/` = `plugins/xmaterial.plugin/source/`. Phases follow the
revised roadmap:
- P0: reference and ledger.
- P1a: static/mover correctness. P1b: GPU caster culling.
- P2: per-tile head/tail.
- P3: the tail and its estimator.
- P4: traced visibility with coverage.
- P5: caches. P6: hardware RT.

Two passes went into this doc:
- **Fable** read the three systems end to end.
- **I** checked the key claims in the code and added the findings marked *(me)*.

## The short version

Most of the infrastructure the strategy asks for already exists, but each system grew its own copy of it:

- **Light identity:** each light consumer finds its own changes. Local shadows hash the light (`LightKey`), the probes hash it again,
  the GI keeps its own `m_PrevPoints` keys and light BVH, and the cells rebuild from scratch. Lights have no id and no generation.
- **Caster changes:** the forward plan diffs casters twice (`slot_caster`, plus the `m_PrevCasters` map) and produces
  `m_FrameChanged`, which shadows and probes read. The GI computes its own old and new boxes in `SetTransform`.
- **Opacity:** every system derives it on its own. The GI sees through only *blended* materials; masked ones are solid walls to its
  rays. Shadows use the masked cutout; the `m_bCastShadows` flag sits on the material.
- **Light falloff:** the formula is written three times (forward, GI shader, cells), in three GPU light layouts.

So the cheapest big win is to give these a single owner, not to build new systems.

## Already-built precedents the reviews asked for

| Review condition | Already in the code |
|---|---|
| Rebuild the old and the new footprint (review 2, sec. 4) | The GI does exactly this: `SetTransform` marks `AffectNear` / `MarkLinksCrossing` over the old *and* the new box (`R/features/gi/xlionrender_surfel_gi.h:2357-2381`). *(me)* |
| Keep radiometry apart from visibility (review 1, sec. 7) | `LightKey` hashes type, position, radius and cone, not colour or intensity, so a colour change keeps the shadow map (`R/features/shadows/xlionrender_shadow_local.h:253-261`). *(me)* |
| An exact visibility reference for local lights (P0) | The GI's direct light walks a light BVH with a shadow ray per light (`Occluded`; `surfel_gi.h:3265-3290`, `:4605-4615`), on the CPU and the GPU: the P0 visibility reference for the opaque rigid geometry the BVH covers. *(me)* |
| A generation-safe slot store | `instance_slots` already hands out (slot, generation) (`R/xlionrender_instance.cpp:126-139`). |
| An async GPU-to-CPU readback for diagnostics | The cull-stats readback ring (`R/features/cull/xlionrender_gpu_cull.h:85-118`). |

## Ideas, ranked by value / cost

Cost: S = days, M = a week or two, L = more.

| # | Idea | Evidence | Value | Cost | Phase | Owner |
|---|---|---|---|---|---|---|
| 1 | **Light records: id + generation.** `local_light` gets `m_Id` from the entity (the scene renderer already maps entities to ids, `R/xlionrender_scene_renderer.h:290`) and a `m_Generation` bumped when its *visibility* fields change. Colour and intensity bump a separate radiometry generation. One persistent record buffer, uploaded on change like `instance_slots`. Shadows, probes, cells and the GI key on (id, gen). | 3 hashes + 1 rebuild today (above) | Unblocks per-tile remembered lists (P2), generation-safe freeze and the diagnostic record (review 2, sec. 7); a moved light keeps its map slot | S | P1a groundwork | lighting; GI reads it |
| 2 | **`VisibilityOf(material_state)`**: one function returning OPAQUE / MASKED / SEE_THROUGH / NO_SHADOW, plus a new `m_bEmissive` the material compiler sets when Emissive is connected or non-zero. The GI see-through, the caster loop and the future any-hit mask all call it. | `R/scene/xlionrender_scene.h:47-65`, `M/xmaterial_render_settings.h`, GI see-through `R/plans/forward/xlionrender_plan_forward.cpp:243` | One answer to "does this block / shadow / emit"; makes masked a *declared* class (review 2, sec. 5); `m_bEmissive` lets the GI skip the emission capture for non-emissive instances | S | P1a | material + lighting; GI calls it |
| 3 | **One change list per frame.** Publish `scene_changes { caster boxes (old and new), light ids, epoch }` built once in the shadow update (it is `m_FrameChanged` today). Consumers: clipmap, local maps, probes, the P1a static cache, P2 lists, and optionally the GI's `MarkLinksCrossing`. Fold `m_PrevCasters` into `slot_caster` (require ids). Static age = frames since `instance_slots` last saw a change. | `plan_forward.cpp:1076-1116`, `:961` | The P1a "old + new footprint" and "cache-eligible after N frames" rules come from one source; deletes one diff path | S | P1a | lighting |
| 4 | **Shadow pages through `gpu_cull`.** The cull shader is already matrix-parametrized (`L2C` and clip planes, frustum-only mode 2). Feed it the tile and face view-projections; build the candidates once per frame and reuse them across the views; masked casters are runs bound by their material base (bindless). | `R/shaders/xlionrender_cull_comp.glsl:71-111`, CPU caster tests `plan_forward.cpp:1233-1242` | This is P1b, with no per-light CPU caster enumeration | M | P1b | lighting |
| 5 | **Coverage bits on the TLAS instance.** `GIBvhInstances.m_Info` is an ivec4 using `.x` and `.y` only. The GI publishes `.z` = coverage (resident / complete / caster class / proxy) and `.w` = epoch. The lighting's any-hit classifies "unknown: outside coverage / unsupported" from it. | `R/shaders/xlionrender_gi_bvh.glsl:7` | Review 2 condition 6 (separate unknown reasons) with no second residency system | S | P4 | GI publishes; lighting reads |
| 6 | **One `LightEval` GLSL include** (falloff, cone, attenuation) used by `xlionrender_local_lights.glsl`, the GI's `Direct`, and the cells' importance. | `local_lights.glsl:98-104`, `gi_pass_common.glsl:140-149`, `light_cells.h:113-114` | Forward, GI and the reference can't drift apart; the needed condition for "SAMPLED vs EXACT on identical visibility" | S | P0 | lighting; GI includes it |
| 7 | **`EvaluateDirectAtReceivers` = the cell walk as one GLSL function** (P, N, cells, lights, rng, visibility callback), returning {head, tail, p, ids}. Pixels call it with shadow maps; GI hits call it with `Occluded`. One probability, one estimator. | cell walk `local_lights.glsl:117-158`; GI `Direct` loops every light | The tail's estimator is tested once and serves both; the GI gets many-light scaling for free | M | P3; GI adopts after P3 measures | lighting; GI opts in |
| 8 | **Async per-pixel diagnostic record** from the real shading path, on the cull-stats ring pattern (no CPU re-evaluator, per review 2). | `gpu_cull.h:85-118` | The "why is this pixel dark" inspector | S | P0 | lighting |
| 9 | **Per-texel masked any-hit via bindless.** It needs a per-triangle (material base, UVs) side table, because `GITri4` has no UVs. The texture id comes from the material block (`R/xlionrender_instance.cpp:936-941`), the cutoff from `alpha_cutoff_param_id_v`. Covers "texture alpha x cutoff" only; procedural alpha stays unsupported. | `gi_bvh.glsl:7,18-21,52` | Foliage stops being a solid wall for GI and tail rays | M | P4 (after the opaque reference) | GI thread decides |
| 10 | **Untextured emission without a capture**: the emissive value is in the material block at its manifest offset; textured emission keeps the capture. | `M/xmaterial_data_file.h:21-33`, GI capture `plan_forward.cpp:248-253` | Cheaper GI loads and recaptures | M | GI thread | GI + material |
| 11 | **Per-light overrides by keyed id** (class, budget) through the existing keyed-list paths, once lights have ids. | `documentation/material_overrides_vs_competition.md:73-77` | Prefab-safe light tuning | S | after P2 | editor |

## Deletions (once the owning idea lands)

- The `m_PrevCasters` hash path, `plan_forward.cpp:1089-1104` (idea 3).
- The probes' light hash, `plan_forward.cpp:962-973` (idea 1).
- The GI's own falloff copy and its 12-word light pack (ideas 1 and 6; the GI thread's call).
- The per-draw constant-material UBO rewrite. The contract already regrets it (`material_contract.md` sec. 0); the constant material
  becomes a real instance with a block. Material thread, S.
- The stale `ponytail: spots as points` comment, `plan_forward.cpp:329`: spots are handled right below it.

## Do NOT do

- **Merge the allocators** (shadow buddy, OffsetAllocator, GI rings, probe slots). Their lifetimes differ, and GI residency is the GI
  thread's.
- **Make the GI read the froxel / tile light grid as its light source.** Share the *function* (idea 7), not the camera-centred data:
  GI hits are off-screen.
- **Merge the material opacity class with the GI transport role.** Role is per instance (Mesh component), opacity is per material;
  they compose.
- **Unify compile-time identities** (`UpdateCount`, `m_LayoutHash`, `m_GIStamp`) with frame change events: they answer different
  questions, and the layout hash is what keeps `E_LAYOUT_STALE` safe.
- **Reuse the camera's Hi-Z for shadow pages or the GI.** Per-page Hi-Z only.
- **Add per-texel masked rays before P0's opaque reference exists** (review 2, conditions 3 and 5).
- **Route light class or budget through material blocks or `entity_params`.**

## Top 5

1. **Light records with id + generation** (S, P1a groundwork). Everything remembered per light (P2 lists, freeze, diagnostics) needs it,
   and it deletes two hashes.
2. **`VisibilityOf(material_state)` + `m_bEmissive`** (S, P1a). One source for "blocks / shadows / emits"; masked becomes a declared
   class.
3. **One per-frame `scene_changes` list + static age from `instance_slots`** (S, P1a). The restore-then-draw old + new footprint and
   cache eligibility come from one place; the GI's links can listen to it.
4. **Shadow pages through `gpu_cull`**, with the candidates built once per frame (M, P1b).
5. **One `LightEval` include, then `EvaluateDirectAtReceivers`** (S then M, P0 then P3). Forward, GI and the reference share the formula,
   then the estimator. Plus the TLAS coverage bits (S, P4) for typed unknowns.
