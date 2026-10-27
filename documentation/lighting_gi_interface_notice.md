# Lighting -> GI: the interface notice (proposal, 2026-10-27)

**Built (2026-10-27, Tomas: "add the two accessors yourself"; the GI thread agreed to both, with conditions):** the two read-only
accessors below, written by lighting in the GI's files - no GI behaviour changed (the GI tests and the bitwise baselines pass):
- `gi::gpu_trace::getBvh()` (`R/features/gi/xlionrender_surfel_gi_gpu.h`): `bvh_view { m_pNodes, m_pTri4, m_pInstances, m_pTlas,
  m_TlasRoot, m_PrimOffset, m_bEmpty }`. The GI's conditions kept: never walked when `m_bEmpty` (the placeholder BVH loses the device;
  also empty before the first pack), read after the GI's update in the frame (`updateGI` runs before the scene pass, which runs the tail
  pass), coverage the opaque rigid meshes with GI.
- `gi::world::ForEachEmitter(Fn)` / `EmittersGen()` (`R/features/gi/xlionrender_surfel_gi.h`): `emitter_view { m_Pos, m_Normal, m_Area,
  m_Radiance, m_Instance }`, level-0 owned surfels of alive transporting instances, whether or not the GI's own emitter list exists. The
  generation bumps on every emitter-list change (`m_bEmittersDirty`), on an emission change without a list rebuild
  (`ResolveSurfEmission`) and on an emissive-scale change.
- **Built (2026-10-28, Tomas: "build it, keep emitters off"):** the GI leaves the emitters' direct term to lighting, behind the same
  switch as lighting's emitter lights (`instance::m_bEmitterLights`, or the Environment's **GIEmitterLights**; off by default: the GI and
  every baseline as before). Not by a stored term subtracted at the read: the GI treats the emitters as it treats the lights - a surfel's
  light holds no emitter's direct light (no emitter sample, no emission its rays meet: the transport's D, the ray solver's pass, the
  probes), and the hits are lit by them as by the lights (`EmitterIrradianceAt`, one sample with its shadow ray: the transport's F, the
  pass' and the probes' hits) - so the bounces stay, the read and the materials are untouched (no layout change, no recompile).
  `setup::m_bEmitterDirectExternal` (GD[11] bit 64); switching rebuilds the links (their keys) and lowers every surfel (`LowerAll`).
  Energy test (`xlionrender_test_screen_tail`, a 1 x 1 m panel over a GI floor): the floor under it 0.1039 with the GI alone, 0.1094
  with the emitter lights and the GI's bounces (5%: not counted twice); the GI's part alone with the switch on 0.0017 (its bounces).
  The CPU's ray solver (no compute) and the CPU links (`m_bEmitterLinks`) honour it too (2026-10-28; `xlionrender_test_surfel_gi` 6j3: under
  a sign, the hits / links / sampling 0.0000 / 0.0001 / 0.0001 against 0.608 with it off), and the GPU commit leaves the links' term out.

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

## Proposal: the BVH for lighting's traced visibility (P4, 2026-10-27)

Lighting's P4 traces the screen tail's shadow rays through the GI's any-hit (`Occluded` / `GICast` in
`R/shaders/xlionrender_gi_bvh.glsl`, which lighting would include unchanged, declaring the four buffers at its own bindings). What it
needs from the GI, read only, no change to the GI's behaviour:

1. **A read accessor on `gi::gpu_trace`** (`R/features/gi/xlionrender_surfel_gi_gpu.h`: the buffers are protected today), e.g.
   `struct bvh_view { const xgpu::buffer *pNodes, *pTri4, *pInstances, *pTlas; int TlasRoot, PrimOffset; bool bEmpty; }; bvh_view getBvh() const;`
   - valid for the frame it is asked in (the GI may repack them between frames: lighting asks every frame).
2. **The see-through rule:** lighting's shadow rays would block on see-through triangles as `Occluded` does (no alpha any-hit until the
   GI agrees one, strategy P4).
3. **Coverage:** the BVH holds the opaque rigid GI geometry only; lighting labels a ray through anything else (skinned, masked, meshes
   without GI) unknown, never clear (strategy sec. 3), and keeps its screen trace for them.
4. **World space:** the BVH's world is the absolute one; lighting adds its camera position to its camera-centred points.

Until then lighting's tail keeps its screen trace (P3) for lights without shadow pages.

## Proposal: emissive surfaces as lights (2026-10-27, reviewed with Fable)

Emissive materials (signs, screens, lava) should light their surroundings directly - contact detail and highlights - not only through the
GI's diffuse bounce. Lighting's many-lights path (the cells, the screen tail: 4096 lights in ~0.6 ms at 1080p) can take thousands of
small emitters. The GI already holds exactly what they are: its emitter surfels (`m_Emitters`, the captured emission over its threshold,
`EmitterRadiance`, `m_Em[k].m_A`, the surfels' position, normal and radius, `EmitGen`). Building a second emitter sampler in lighting
would duplicate the capture, the area weighting and the level policy, and the two would disagree on where the emission is. What lighting
needs, read only:

1. **An emitter view:** `struct emitter_view { fvec3 Pos, Normal; float Area; fvec3 Radiance; int Instance; }` - world space, level-0
   surfels only - and `std::span<const emitter_view> Emitters() const` (or a ForEachEmitter), with a global emitters generation so lighting
   rebuilds its emitter lights only when it changes.
2. **Double counting:** with emitter lights on, the GI's bounce already holds the emitters' first bounce onto other surfaces; a flag
   (e.g. `m_bEmitterDirectExternal`) that leaves the emission's direct term to lighting (the GI keeps the bounces after it).
3. **The same energy:** lighting shapes each emitter as a one-sided disc of the surfel's area (power = luminance x area; a hemisphere
   cone; the form factor A cos cos / (d^2 + A), the GI's own link weight), so the two agree; a shared test compares the GI's emitted flux
   with lighting's sum within 5%.

Lighting's side (once the view exists): the top N emitters by power (2048; the rest folded into their neighbours, the flux kept),
contact-shadowed by the screen trace, no shadow pages; never lighting their own surface.

## Not proposed

- No GI code changes from lighting; no shared mutable state; no lighting dependency on GI buffers in the main view's shading.
