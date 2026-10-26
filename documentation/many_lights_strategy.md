# Many lights and shadows: the strategy (2026-10-26, proposal, nothing built)

The research is in documentation/many_lights_and_shadows_research.md.

The competitors:
- **Unreal 5:** Virtual Shadow Maps plus MegaLights.
- **GigaLights:** every light ray traced, with a software BVH fallback.

Both are good. Both pay the same cost every frame for things that did not change, and both decide visibility from the screen and
from history alone.

The leap: **visibility becomes cached, shared world data**, computed once where it is stable and only re-traced where something
changed. The renderer, the GI, the fog and the AO all ask the same service.

## Where they spend and what they lose

| | Unreal 5 (VSM + MegaLights) | GigaLights | Where we can do better |
|---|---|---|---|
| Static light, static geometry | VSM pages cached, but MegaLights re-traces every frame | Re-traces every frame | Computed once, cached in world space, re-done only on change |
| Which light a pixel samples | Screen-space history (visible light hash) | Per-tile list of visible lights (screen history) | World-space knowledge: the surfels know which lights reach them, so it survives camera cuts and disocclusions |
| Noise | Everything stochastic goes through the denoiser | Same | Strong lights evaluated exactly (no noise); only the long tail is sampled, so there is less to denoise |
| Off-screen / far occluders | HW RT (or no shadow) | Software BVH, step and memory budgets, LOD | Tiers: screen trace (blocked only), cluster BVH, surfel visibility far away, HW RT on high-end |
| GI agreement | Lumen uses its own tracing | GI add-on traces the same BVH | GI surfels share the same light grid and visibility: direct and indirect light agree by construction |
| Platforms without HW RT | MegaLights limited | Software BVH everywhere | Cached tiers need no tracing at all; tracing only refreshes them |

## The architecture

### 1. A light grid that also knows visibility

- **The grid:** the light cells we already have (froxels), plus a coarse world grid for off-screen work and the GI.
- **Per light, a class by how stable it is:**
  - **Static:** it does not move.
  - **Dynamic:** it moves (cars, characters' torches).
  - **Transient:** short-lived (muzzle flashes, bullets).
- **Per surfel, the visibility of the lights that matter to it,** a compact list (light id + visibility, a few bytes each). For
  static lights it is refreshed only when a caster near the light path changes: the same invalidation by world bounds the sun
  clipmap already uses. This is the "aim higher" part. It turns most shadow rays into a lookup.

### 2. Sampling: exact for the strong lights, stochastic for the tail

- **Per tile (8x8), the K strongest lights** (by importance at the tile, times cached visibility): evaluated **exactly**, with
  their shadow from the visibility tiers below. No noise, no denoiser, stable in motion. K is 2-4, the sun is usually one of them.
- **The rest:** stochastic, ReSTIR-style with temporal and spatial reuse.
  - Candidates come from the tile's known-visible list (GigaLights' idea) and the surfels' cached visibility (lights a surfel knows
    are blocked get almost no weight), plus a capped "discovery" share from the cell's full list with strided subsampling.
  - Only this tail goes through the denoiser.
- **Variable-rate rays:** pixels whose result has settled give their rays to pixels that just lost their history.

### 3. Visibility tiers (every query: shadow rays, GI rays, fog, AO)

1. **Screen trace, blocked-only:** covers the span next to the surface (contact shadows, GigaLights' trick). It can only say
   "blocked", so the coarser tiers behind it never cause self-shadowing.
2. **Cached shadow pages** for the sun and static key lights. The clipmap we have today becomes GPU-driven:
   - casters through the GPU cluster cull with indirect draws, the two-pass Hi-Z per page (the page's own depth);
   - static depth cached, movers drawn on top.
   Sharp, stable, nearly free when nothing moves.
3. **Cluster BVH (software ray tracing):** our clusters as the bottom level (they already have boxes), instances on top, the same
   structure the GI sections build. A trace LOD beyond a detail distance, a memory budget. On hardware with ray tracing, HW RT
   replaces this tier.
4. **Surfel visibility far away:** beyond the trace distance, a shadow ray reads the cached visibility of the nearest surfels
   (smooth, cheap, correct enough for far lights).

### 4. One system for direct light, GI, fog and AO

- **GI:** the surfel GI injects light from the same grid, with the same cached visibility, so direct and indirect light agree.
  - Slow lights (sun, moon) converge as the GI notes already say. Fast lights: the GI gets them through the stochastic path, or
    not at all for transients (bullets: direct light with contact shadows only).
- **Fog:** froxels lit by the same light grid and visibility tiers, with the fog's shadows refreshed every N frames.
- **AO:** short rays through tiers 1 and 3.

### 5. Scaling across platforms

| Tier | Mobile / no ray tracing | Mid PC | High-end PC |
|---|---|---|---|
| Exact strong lights | Shadow pages | Shadow pages | Shadow pages |
| Tail visibility | Screen trace + surfel cache | + Cluster BVH | + HW RT |
| Tail samples per pixel | 1 at quarter res | 1-2 at half res | 2-4 at half res |

## Phases (each measured: the stress city, the Bistro, Release median-of-21, compile-idle checked)

1. **GPU-driven shadow pages:** shadow casters through the cluster cull and indirect draws; the static/dynamic split.
   Target: shadow CPU cost flat with moving lights (today 0.95 ms for 16 maps).
2. **Light grid v2 and the exact-K evaluation per tile:** the existing lights, the 16 shadowed ones exact.
   Target: the stress city's 1024 lights at or below today's scene pass time (1.4-4.3 ms).
3. **The stochastic tail with screen traces plus pages,** and a short-history denoiser. Every light shadowed, contact shadows.
4. **The cluster BVH** (software ray tracing) shared with the GI sections; variable-rate rays.
5. **Surfel light visibility cache:** static lights become lookups; it feeds the GI's light injection.
6. **HW RT** as the high-end world tier; fog and AO on the same tiers.

Proof points to beat:
- **Stability:** strong lights noise-free while MegaLights and GigaLights denoise them.
- **Static cost:** near zero for static lights on static geometry (both competitors re-trace).
- **No hardware ray tracing needed:** everything works without it (MegaLights does not).
- **GI agreement:** direct and indirect light agree.

## Risks and open questions

- **Surfel visibility memory:** lights per surfel and bytes each; how it is invalidated when many objects move. It needs a sizing
  experiment on the Bistro.
- **Exact-K per tile:** tiles at the edge of a light's influence can switch between exact and sampled. That needs a smooth hand-off
  (blend by weight), or it pops.
- **The denoiser is still needed for the tail.** How short a history can be while staying stable is tuned per platform.
- **For Tomas:**
  - whether hardware ray tracing is first-class;
  - the look of soft shadows (marching pages versus area sampling);
  - the light count target;
  - whether the surfel visibility cache is designed with the GI thread.
