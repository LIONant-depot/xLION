# Lighting strategy: direct light, shadows, many lights, GI (proposal, 2026-10-26)

Status: design only, for Tomas. Nothing is built until he says go. Sources: documentation/many_lights_and_shadows_research.md (the
competitors, options A/B/C, GigaLights), documentation/gpu_cluster_culling.md, and the GI notes in xLIONRender/documentation (surfel
GI master plan, chunks, working set). The GI belongs to its own thread: this document proposes interfaces, not a GI redesign. It
replaces documentation/many_lights_strategy.md (its first draft).

## 1. The vision

**One visibility service, shared by everything that needs to know "can this point see that one":**
- direct light, shadows and many lights;
- GI, AO, reflections and fog.

Light is evaluated **exactly where it matters and stable, stochastically only for the tail**, and visibility is **remembered where
the world does not change**. It runs without hardware ray tracing on every platform, and gets better with it.

| | Unreal 5 (Lumen + MegaLights + VSM) | GigaLights | How we beat both |
|---|---|---|---|
| Hardware RT | MegaLights' world traces need it (its software path is off by default) | Optional (own software BVH) | Not required; RT is the top tier of the same hierarchy |
| Visibility systems | Three: VSM pages, MegaLights traces, Lumen's tracing | One BVH, but every ray re-traced every frame | One hierarchy shared by direct light, GI, AO, reflections and fog, with remembered results |
| Strong lights (the sun, the 2-4 dominant lights of a tile) | VSM (stable), but MegaLights lights are stochastic and denoised | Stochastic and denoised, the sun included | Exact, noise-free, from cached shadow pages or remembered visibility |
| Many shadowed lights | Hundreds, at bounded cost (hardware RT) | Thousands, bounded by samples per pixel | Thousands, bounded cost, with fewer wasted rays: remembered visibility guides the sampling |
| Static lights, static world | VSM cached, MegaLights re-traced | Re-traced every frame | Lightmap-like: computed once, kept until something near changes |
| Many dynamic objects | VSM page invalidation; denoiser lag | Per-frame traces, denoiser lag | Invalidation by world bounds (as the sun clipmap does today); movers drawn over cached static depth |
| Camera cuts / disocclusion | History lost: noisy frames | Short history, recovery levels | Remembered visibility is in world space: it survives cuts |
| Down to mobile | VSM yes, MegaLights no | Software BVH, heavy on mobile | Deterministic tiers: pages + remembered visibility + screen traces need no ray tracing |
| Debuggability (editor, AI) | Visualisation modes | Debug views | Every layer readable by command (DescribeScene-style counters), freeze toggles, per-tile light lists and visibility queryable: the editor and the AI can ask "why is this dark" |

## 2. The architecture (per frame)

```
lights ─► light classes ─► light grid (froxels + world cells) ─► per-tile remembered lights (top K exact, tail candidates)
                                                                          │
        G-buffer / prepass depth (GPU cluster culling, two-pass Hi-Z) ────┤
                                                                          ▼
                                       sampling budget (variance-driven rays per tile)
                                                                          │
                     ┌──────────── visibility hierarchy (one service) ────┴──────────┐
                     │ 1 screen trace, blocked-only (contact span)                    │
                     │ 2 remembered visibility (lightmap-like caches, GI surfels)     │
                     │ 3 cached shadow pages (sun, key lights; static + movers)       │
                     │ 4 software BVH (the GI's BLAS/TLAS, cluster-level)             │
                     │ 5 hardware RT when present (replaces 4, extends range)         │
                     └────────────────────────────────────────────────────────────────┘
                                                                          ▼
                     exact lights (no denoise) + tail (short-history denoiser) ─► lit G-buffer ─► GI injection, fog
```

### 2.1 Light classes (Tomas's rules)

| Class | Examples | Shadows | Caching | GI |
|---|---|---|---|---|
| **Static** | Lamps, windows | Lightmap-like: visibility computed once per surface sample (a per-light shadow mask in pages, or per-cluster-surface texels), not surfels | Kept until a caster in the light's range changes (invalidation by world bounds) | Injected once, updated on change |
| **Slow** | Sun, moon | Cached sun clipmap pages, static and movers kept apart | Pages re-render only where casters change or the depth range moves | Converges with the GI (as today) |
| **Player-speed** | Torches, cars, flashlights | Stochastic tail + screen trace + BVH, or pages when the light is key | Remembered lists per tile follow them | Converges over frames |
| **Transient** | Bullets, muzzle flashes, sparks | None or contact-only (screen trace) | None | None |

### 2.2 The light grid and per-tile remembered lights
- **Grid:** the froxel light cells we have, plus a coarse world grid (off-screen work, fog, the GI).
- **Per 8x8 tile:**
  - **K exact lights** (2-4): the strongest by importance x remembered visibility. Evaluated exactly, with visibility from tiers 2-3.
  - **A remembered list of tail candidates:** lights found visible in earlier frames, with an age for shadowed ones (GigaLights'
    idea), plus a capped "discovery" share from the cell list with strided subsampling. That bounds the work whatever a cell holds.
- **Hand-off between exact and sampled:** by weight, blended over a few frames, so a light never pops between the two paths.

### 2.3 The sampling budget
- Rays per tile follow variance: settled tiles give their rays to tiles that just lost their history.
- The tail runs at half resolution by default; the exact lights at full resolution.

### 2.4 The visibility hierarchy
1. **Screen trace, blocked-only:** the short span next to the surface. It can say "blocked", never "visible", so approximate tiers
   behind it cannot self-shadow (GigaLights' trick).
2. **Remembered visibility:**
   - static lights: lightmap-like caches;
   - far and small lights: the GI's surfel visibility, through the interface of section 3.
   A lookup, no ray.
3. **Cached shadow pages:** the sun clipmap and key lights.
   - Rendered GPU-driven: casters through the cluster cull and indirect draws, the two-pass Hi-Z of each page's own depth.
   - Static depth cached, movers drawn on top.
4. **Software BVH:** the GI's BLAS/TLAS, already on the GPU with a traversal shader that casts sun and point-light shadow rays (GI
   phases G1/G2). Cluster-level culling inside it, a trace LOD beyond a detail distance.
5. **Hardware RT** where present: replaces tier 4 and extends the trace distance.

### 2.5 The denoiser
- Only the stochastic tail is denoised. The exact lights never are.
- Temporal accumulation with reprojection, then a variance-guided spatial filter.
- The history is short, with recovery levels by sample support after a disocclusion: extra spatial taps instead of claiming
  convergence.
- Upscaler-friendly output (FSR/DLSS keep their own history).

### 2.6 Static/dynamic split and caching
- Every cache (shadow pages, lightmap-like visibility, per-tile lists) is invalidated by the **world bounds of what changed**, the
  mechanism the sun clipmap already uses.
- An object becomes "static" after N frames without change (Unreal does this after 100). A mover is drawn over the cached static
  state, never re-rendering it.

## 3. The shared visibility structure and the GI interface

What is shared (owned by the GI thread, used by lighting):
- **The BVH:** per-mesh BLAS (the rays' BVH), the TLAS of instances, their GPU packing.
- **The traversal shader:** the GI's G1 traversal. Lighting needs an any-hit "shadow" entry point and a ray budget per call.
- **Transport roles per instance:** occluder / receiver / bounce / emitter. A shadow ray only sees occluders.
- **Surfel visibility of lights** (new, proposed): per surfel, the visibility of the few lights that matter to it.

The contract, proposed:
1. **Lighting asks:** `Occluded(origin, dir, tMax, mask)` for a batch of rays (any hit), on the GPU, inside a budget it declares per
   frame.
2. **Lighting reads:** `SurfelLightVisibility(position, normal, light)`, an approximate visibility for far lights, from published
   GI state only (the GI's rule 7: published versus working state).
3. **Lighting provides the GI with:**
   - the light grid (the same light list, classes and importance);
   - the direct light it computed (the GI's light injection can reuse exact lights instead of re-tracing them);
   - the invalidation events it sees (light moved, class changed).
4. **Neither waits for the other.** Visibility answers come from published state. The GI's maintenance allowance (2 ms on the main
   thread) is unchanged; lighting's GPU budget is separate.
5. **Roles and budgets are explicit,** as the GI master plan already demands.

## 4. Quality tiers

Expected costs are targets to validate, on Tomas's RTX 4070 Ti SUPER at 1080p unless noted.

| Tier | Exact lights | Tail | Visibility tiers | Denoiser | Expected direct-light GPU cost |
|---|---|---|---|---|---|
| Mobile / low | Sun + 1 key light | 1 sample at quarter res (up to 64 lights) | 1, 2, 3 (no tracing) | Short, spatial-heavy | ~1.5 ms at 720p on a mid phone (to measure) |
| Desktop, no RT | K = 2-4 per tile | 1-2 samples at half res, thousands of lights | 1-4 (software BVH) | Full | ≤ 2.0 ms at 1080p, ≤ 4.5 ms at 4K, 1000 shadowed lights |
| Desktop, RT | K = 4 | 2-4 samples at half res | 1-3 + 5 | Full | ≤ 2.0 ms at 1080p with longer trace range; better contact and far shadows |

## 5. Metrics and targets

- **Counts:** 1000+ lights on screen, all shadowed (the stress city has 1024 today with 16 shadowed); 50 movers crossing sun tiles.
- **Budgets (1080p, RTX 4070 Ti SUPER, Release):**
  - sun pages ≤ 0.3 ms static and ≤ 0.8 ms with 50 movers;
  - direct light total (exact + tail + denoise) ≤ 2.0 ms;
  - shadow CPU cost flat with moving lights (today 0.95 ms for 16 moving maps).
- **Stability:**
  - still camera, still scene: per-pixel temporal luminance deviation below 1% for exact lights and below 3% for the tail;
  - a moving light: frames to 90% of the converged image ≤ 4;
  - camera cut: frames to 90% ≤ 3 (remembered visibility helps here).
- **Fair comparisons:**
  - the same stress-city layout (1024 lights) rebuilt in Unreal 5 (MegaLights on, VSM, Lumen) and in Unity with GigaLights, same
    resolution, same GPU;
  - GPU times from each engine's own profiler, plus captures (RenderDoc on ours) for the stability metrics;
  - the same camera paths, still and moving.

## 6. Roadmap (each phase ships value and is measured: Release median-of-21, compile-idle checked)

| Phase | What | Ships | Proves |
|---|---|---|---|
| 1 | Shadow pages GPU-driven: casters through the cluster cull and indirect draws, static depth cached + movers over it, Hi-Z per page | Flat shadow CPU cost; cheaper moving casters | Tier 3 at scale, the static/dynamic split |
| 2 | Light classes + light grid v2 + K exact lights per tile (the 16 shadowed lights become "key") | Stable strong lights, bounded per-pixel work | Exact/tail split without pops |
| 3 | Stochastic tail: remembered per-tile lists, screen trace blocked-only, pages for key lights, short-history denoiser | Every light shadowed (contact + key) | Thousands of lights at a bounded cost |
| 4 | Software BVH visibility through the GI's traversal (the interface of section 3); variable-rate rays | Off-screen occluders for every light, no RT needed | One shared structure; no RT requirement |
| 5 | Lightmap-like static light caches; surfel light visibility (with the GI thread) | Static lights nearly free; far lights cheap; GI agrees with direct light | The "remembered visibility" leap |
| 6 | Hardware RT tier; fog and AO on the same hierarchy; the comparison scenes | RT quality on high-end | Leaps both, measured side by side |

## 7. Risks and open questions (with recommendations)

1. **Is hardware RT a first-class tier?** Recommended: no. It is the top of the hierarchy, never a requirement (mobile/Apple). Build
   tiers 1-4 first.
2. **Soft shadows: marching through the pages, or stochastic area sampling?** Recommended:
   - pages with a short march (SMRT-like) for the exact lights: deterministic, no noise;
   - area sampling for the tail, where noise is denoised anyway.
3. **Light counts?** Recommended target:
   - 1000+ shadowed lights on screen at desktop no-RT;
   - 64 on mobile;
   - unlimited transients (unshadowed or contact-only).
4. **Coordination with the GI thread?** Recommended:
   - agree on section 3's interface before phase 4;
   - the GI keeps owning the BVH and the surfels;
   - surfel light visibility is designed jointly in phase 5.
5. **Risk, exact/tail pops:** a light crossing the top-K threshold changes method. Mitigation: blend by weight over a few frames;
   test with a light ramp.
6. **Risk, remembered visibility memory:** lights per surfel and per static cache. Mitigation: a sizing experiment on the Bistro
   before phase 5, with budgets as in the GI working-set note.
7. **Risk, the denoiser:** the tail still needs one. Mitigation: keep it small (the exact lights take the bulk of the light), short
   history, recovery levels; measure the stability metrics every phase.
8. **Risk, the software BVH's cost** at city scale (the Bistro BVH alone is 200 MB). Mitigation: trace LOD beyond a detail
   distance, cluster-level culling, the GI chunks' working set; hardware RT takes over where present.
