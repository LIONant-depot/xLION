# Lighting -> GI: the interface notice (proposal, 2026-10-27)

The lighting strategy (`documentation/lighting_strategy.md`, sec. 13 decision 5) owes the GI thread a notice of what lighting now
publishes and what it would like to use. **Proposals only:** no GI file was changed; the GI thread decides what to adopt and when.
`R/` = `example.lionprj/Cache/dependencies/xLIONRender/src/`.

## What lighting publishes now

| Item | Where | What it gives the GI |
|---|---|---|
| **Light identity** (6.1) | `R/scene/xlionrender_scene.h` `local_light::m_Handle`: the light's entity, filled by the scene renderer (`R/xlionrender_system.h`) | A key for the GI's light caches that survives list reordering and moves (today the GI rebuilds its lights every frame). Radiometry (colour, intensity) and visibility (position, shape, cone) are separable: lighting's shadow pages keep through a colour change, render again on a move (`R/features/shadows/xlionrender_shadow_local_pages.h` LightKey / ShapeKey) |
| **The frame's changes** (6.3) | `instance::m_FrameChanged` (`R/xlionrender_instance.h:704`): this frame's changed caster bounds, old and new boxes, built once in `renderShadows` | What `MarkLinksCrossing` could listen to instead of tracking moves itself (the GI marks old and new boxes today, `surfel_gi.h`) |
| **Shadow visibility, GLSL** | `R/shaders/xlionrender_shadow_vsm.glsl` `SunShadow(World, Ng)` and `R/shaders/xlionrender_local_lights.glsl` `LocalLightShadow(i, N)` / `LocalShadow(...)` | The same filtered visibility the main view's pixels get, for any world position - **with one constraint:** pages exist where the main view's depth asked for them; elsewhere the lookups fall back to the coarse pinned pages (the sun's net, each light face's coarsest page) - APPROXIMATE, and labelled so in sec. 3's terms. Surfels on screen would match the pixels; off-screen surfels would get coarse shadows |
| **Unshadowed light terms** | `LocalLightUnshadowed(i, ...)` (the BRDF x falloff x cone, the shadow apart) | A shared evaluation if the GI wants the direct term at a surfel with its own visibility |

## What lighting would like (later phases)

1. **P4 (traced tail visibility), R-B:** dispatch the GI's `Occluded` any-hit (`R/shaders/xlionrender_gi_pass_common.glsl:120`)
   read-only under lighting's own budget, within its opaque-rigid coverage; the BVH's maintenance stays the GI's (counted, never
   twice). Approved in principle by Tomas (sec. 13 decision 6.5); needs the GI thread's agreement on dispatch timing and buffers.
2. **Spatial coverage:** a query "is this region's geometry in the BVH" (instance flags are not enough: sections, LODs), so lighting
   never certifies CLEAR without complete coverage.
3. **Emission:** `material::m_Emissive` is in the renderer's constant material; a flag set by the material compiler (6.2,
   `MaterialVisibilityOf` + emissive) would let both systems agree on what emits.

## Not proposed

- No GI code changes from lighting; no shared mutable state; no lighting dependency on GI buffers in the main view's shading.
