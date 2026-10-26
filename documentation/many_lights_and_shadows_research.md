# Many lights and shadows: research (2026-10-26)

Tomas: "we must be able to handle many lights and shadow similar to what lumen does... in fact we should really be trying to aim
higher". Research only: nothing is built until Tomas says go.

## Where xLION stands (measured)

What exists:
- **Sun:** a world-anchored clipmap of cached shadow tiles. A tile re-renders only when a caster that touches it changes, or when
  the camera leaves the level's depth range.
- **Point and spot lights:** cached maps (octahedral for points, a frustum for spots) in an atlas, re-rendered within a per-frame
  budget. Lights beyond the shadowed set are unshadowed.
- **Many lights:** clustered (light cells), 1024 street lights in the stress city.
- **Shadow casters:** drawn by the CPU, one draw each, frustum-culled per tile. The GPU cluster culling and its Hi-Z are the main
  view's only.

Measured: Release, nothing compiling.

`xlionrender_stress` city, 1280x720: 8001 draws, 1024 lights (the first 16 shadowed), the sun, 600 frames each.

| Scenario | GPU shadows | CPU shadows | Tiles/maps re-rendered per frame | GPU scene pass (1024 lights) |
|---|---|---|---|---|
| Flyover | 0.16 ms | 0.25 ms | 1.1 mean, 19 max | 4.3 ms |
| Street | 0.14 ms | 0.21 ms | 0.3 mean, 16 max | 1.4 ms |
| Moving lights (16 shadowed lights move) | 0.16 ms | 0.95 ms | 16 | 1.4 ms |

The Police level in the editor, maximized 3778x1600: sun shadows 0.41 ms GPU, about the same with the Building moved every 100 ms
(0.40 ms); CPU shadows 0.01 ms.

So, today:
- **Shadows are cheap** because the caches work, and the cost of re-rendering grows on the CPU, not the GPU (16 maps: 0.95 ms CPU).
- **The limit is how many lights can be shadowed, not shadow cost:** only 16 of the 1024 street lights cast shadows. The scene
  pass with 1024 lights costs 1.4-4.3 ms because every pixel walks its cell's lights.

## What the others do

| Technique | How | Cost behaviour | Quality | Hardware | Cache | Dynamic objects |
|---|---|---|---|---|---|---|
| **Unreal 5 Virtual Shadow Maps** (Renderer/Private/VirtualShadowMaps) | A 16k virtual map per light (a clipmap for the sun, 6 faces for points) in 128x128 pages from a physical pool (2048 pages); pages allocated where pixels sample; casters culled per page with an HZB of the page (two passes); SMRT: soft shadows by marching a few rays through the map (7 for directional) | Cost follows the pages that change, not the lights | Sharp near the camera, soft by SMRT; resolution follows screen density | Compute; Nanite helps | Pages kept between frames; static and dynamic kept apart; an object becomes static after 100 frames without a change (r.Shadow.Virtual.Cache.FramesStaticThreshold) | Invalidates the pages under it (GPU, by bounds); deformables invalidate |
| **Unreal 5 MegaLights** (Renderer/Private/MegaLights, Shaders/Private/MegaLights) | Per pixel, at half resolution by default: 4 light samples chosen by importance (the light grid, history-guided); each sample's visibility traced by a screen trace, then a world trace (hardware ray tracing, or VSM marking/tracing for lights with VSMs); spatial and temporal denoiser | About constant per pixel: hundreds of shadowed lights | Soft area shadows; noise under motion until the denoiser settles | Hardware RT for world traces (software RT optional) | Temporal history | Traced each frame: nothing to invalidate |
| **Lumen** | Indirect light (surface cache, screen probes); direct light comes from VSM/MegaLights; it reuses their shadows for the surface cache | - | - | Software or hardware RT | Surface cache | - |
| **id Tech 7 (Doom Eternal)** | Clustered forward; every light can cast; one big shadow atlas; static shadows cached, re-rendered only on change, at an update rate per light | Atlas space and the lights that change | Good, stable | Raster | Static per light | Dynamic drawn over the static |
| **Frostbite / SEED** | Stochastic area lights and shadows ("hybrid" RT shadows in PICA PICA), shadow denoisers | Per pixel | Soft | RT | - | Traced |
| **Cyberpunk 2077 RT Overdrive (NVIDIA RTXDI), Kajiya** | ReSTIR DI (Bitterli 2020): per pixel, candidate lights by importance, reservoirs reused over time and space, one shadow ray per pixel | Constant per pixel, millions of lights | Very good with a denoiser | RT | Reservoirs (temporal) | Traced |
| **Capsaicin (AMD)** (components/light_sampler_grid_*) | A world grid of cells, each with a CDF or reservoir stream of the lights that matter there (64 per cell); per-pixel sampling, ReSTIR-style | Constant per pixel | Research quality | RT | - | Traced |
| **Wicked** | Shadow atlas, plus RT shadows with a tile-classified denoiser (rtshadow*) | Per light / per pixel | - | RT optional | - | - |
| **Godot 4** | Shadow atlas in quadrants; a positional light's shadow re-renders when its light or casters change | Per changed light | Plain PCF | Raster | Per light | Re-renders the light |
| **Bevy** | Cascades and cube maps, re-rendered every frame; clustered lights | Every frame | Basic | Raster | None | - |
| **o3de (Atom)** | Cascades plus a projected-shadow atlas, ESM/PCF | Every frame | Basic | Raster | None | - |
| **CryEngine** | Cascades, a cached far cascade, point-light shadow budget | - | - | Raster | Far cascade | - |

## Candidate architectures

### A. Virtual shadow pages, GPU-driven (Unreal's VSM, done our way)

- **Pages:** the sun clipmap and every shadowed local light get virtual maps in fixed-size pages, allocated where receivers sample.
- **Rendering:** casters go through our GPU cluster culling, per page, with the two-pass Hi-Z of each page's own depth (Tomas's
  idea: the shadow map is depth).
- **Static/dynamic split:** each page keeps a cached static depth plus the movers drawn on top. An object turns static after N
  frames without changes.
- Pros: deterministic and stable, no ray tracing needed (mobile/Apple), cost follows change.
- Cons: page memory; many dynamic lights still re-render pages; soft shadows need SMRT-like marching.

### B. Stochastic many-light sampling (MegaLights / ReSTIR DI)

- **Light sampling:** per pixel, at half resolution, a few lights sampled by importance from a light grid (Capsaicin-style cells,
  built from our light cells), with reservoirs reused over time and space (ReSTIR).
- **Shadow rays:** each sample's visibility comes from a screen trace (the Hi-Z exists), then a shadow-map lookup when the light has
  pages (A), then hardware ray tracing when available.
- **Denoiser:** temporal and spatial.
- Pros: constant cost per pixel, every light shadowed, soft area shadows.
- Cons: noise and lag in motion; a denoiser to build and tune; the best quality needs hardware ray tracing.

### C. Aim higher: one visibility for direct and indirect light (A + B + our surfels)

Unreal keeps three separate visibility systems: VSM, MegaLights traces, and Lumen's surface cache. We already have surfels that
trace visibility for the GI. The proposal:
- **The sun and a few hero lights:** A's pages (sharp, stable, cached).
- **The long tail of lights:** B's sampling, with visibility answered in tiers. Screen trace first. Then the light's pages if it
  has any. Then, for far and small lights, the **surfels' visibility**: each surfel caches the visibility of the lights that matter
  around it, refreshed at the GI's rate (slow lights converge; bullets and fast lights get the screen trace only, as in the GI notes).
  Hardware ray tracing replaces the far tiers where present.
- **One light grid** feeds both the direct sampling and the GI's light injection.

Result: every light shadowed. The near field is sharp from pages and screen traces; the far field is cached and almost free from
surfels. GI and direct light agree because they share visibility. It works without ray tracing, which becomes a quality upgrade.

Trade-offs:
- the most work of the three;
- the surfel visibility cache is new research (its memory per surfel, and its update budget);
- B's denoiser is needed for the tail either way.

## Recommended path (phases)

1. **Shadow casting through the GPU pipeline.** Casters per tile and map go through the cluster cull with indirect draws (CPU cost
   drops; today 16 maps cost 0.95 ms of CPU), plus the static/dynamic split per tile and map with cached static depth.
2. **Page HZB culling** (A): the two passes per page.
3. **Virtual pages for local lights** (A): shadowed light count limited by page memory, not by a fixed 16.
4. **Many-light sampling** (B) on the light grid, with screen traces plus page lookups and a denoiser. All 1024 street lights
   shadowed.
5. **Surfel light visibility** (C) for far and small lights; hardware RT as the high-end far tier.

Each phase is measured with the stress city (moving lights, a flyover with moving casters) and the Bistro, in the Release
benchmark.

## Open questions for Tomas

- Should hardware ray tracing be a first-class tier (best quality on PC) or only an option? It decides how much B and C lean on
  software traces.
- Soft shadows: SMRT-style marching through the maps (deterministic), or stochastic area-light sampling with a denoiser? It decides
  the look.
- What is the light count target: shadowed lights on screen (hundreds? thousands?) and dynamic lights (muzzle flashes, bullets)?
- C's surfel visibility cache touches the GI: should it be designed together with the GI work in the other thread?
