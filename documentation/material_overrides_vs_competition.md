# Material overrides: xLION against the competition

Step 3 of the plan "xGPU materials and textures: path to bindless" adds the Mesh's **Override Materials**. Each material slot of an
entity can swap its material instance and override any parameter the instance's material exposes. This review compares that design
with what other engines do, measures it, and lists what was changed because of it (2026-10-26).

Sources: the engines' source trees in `E:\source_code` (files named below) and the HypeHype / NoGraphicsAPI material in the same place.
Numbers for xLION come from `xlionrender_bench_overrides` (see "How to measure").

## How xLION does it

- **Saved:** only the parameters an entity overrides, by id and name (`mesh_slot::m_Params`). The inspector rows come from the
  material's manifest (real names, types, defaults).
- **At runtime** (`scene/xlionrender_material_overrides.h`):
  - Slots with the same instance and the same overrides share one renderer material, keyed by a hash of the overrides.
  - A change updates the slot's own material in place: one vec4 range through the upload ring, or one texture id.
  - When the material is shared, the changing slot gets a copy first (copy-on-write).
  - A slot that goes back to overrides another slot has shares that slot's material again.
  - Overrides never create a pipeline: every material of one shader and state shares one (`instance::m_SharedPipelines`).
- **Per draw (bindless):** override materials of one pipeline share its state. The material's block is found through the
  `MaterialBase` push constant the draw already sends, and its textures through ids in that block. So an override costs no binds.
- **Non-bindless fallback:** each override material has its own texture-table descriptor set. Since the review fixes below,
  this is the only per-draw bind left.

## The comparison

| Engine, mechanism | Per-draw cost | Memory per overridden entity | Value change | Texture change | Batching and pipelines | Limits | Editor UX |
|---|---|---|---|---|---|---|---|
| **xLION**: Mesh Override Materials (deduplicated override materials) | Bindless: none beyond a plain draw (shared state, push constant it already sends). Non-bindless: one set bind per distinct override material | Unique values: its block plus texture ids in MaterialParams (the test material: 32 B; a PBR block of about 5 vec4s: about 80 B) plus one CPU material record. Shared values: one slot record, no GPU memory | In place: **0.66 µs** (Release); copy-on-write when shared: **1.56 µs** | In place (bindless): **0.39 µs**; non-bindless: 4.3 µs (descriptor write) | Batched across override materials (one bind for 64 materials, tested). No new pipelines | MaterialParams 262144 vec4s (4 MiB); about 16k vec4s uploaded per frame, the rest waits a frame | Rows generated from the manifest, with the Material Instance editor's widgets; any parameter, any texture; per slot |
| **Unreal**: Custom Primitive Data (CPD) | None (per-primitive data in GPUScene) | 9 float4s reserved per primitive (`FCustomPrimitiveData::NumCustomPrimitiveDataFloat4s = 9`, SceneTypes.h:38) | Set on the component, then `Scene->UpdateCustomPrimitiveData` (PrimitiveComponent.cpp:2688): a GPUScene upload of the primitive | Not possible: textures need a MID | Batches perfectly; no new material | 36 floats; scalars and vectors only; the material author maps each parameter to an index | Index-based ("Custom Primitive Data" index on the parameter, per-component array in the details panel) |
| **Unreal**: Material Instance Dynamic (MID) | Its own uniform buffer, so a different material render proxy: draws do not merge with other materials | A whole UMaterialInstance plus its uniform buffer per MID | `SetScalarParameterValue` (MaterialInstanceDynamic.cpp:196) updates the parameter and its cached uniform expressions on the render thread | Supported (`SetTextureParameterValue`) | Breaks draw merging per MID; shares the parent's shaders | No dedup: N MIDs are N materials, even with equal values | Created from code or Blueprint; no per-slot editor UI without a component setup |
| **Godot 4**: `instance uniform` | None (read from the global uniform buffer by instance offset) | 16 slots reserved per instance (`MAX_INSTANCE_UNIFORM_INDICES = 16`, shader_language.h:358), each a vec4-sized value | Write into the global buffer; dirty regions uploaded | Not possible: "The 'instance' qualifier is not supported for sampler types" (shader_language.cpp:9860) | Batches; no new material | Global buffer has a project-set size ("Increase buffer size in Project Settings", material_storage.cpp) | Shown under "Instance Shader Parameters" in the inspector, from the shader |
| **o3de**: Material Component property overrides | Each overridden assignment is a unique material with its own Material SRG: one SRG bind per draw | A whole RPI::Material per overridden slot | `SetPropertyValue` then a material Compile (SRG compile) on the next tick (MaterialComponentController.cpp:676) | Supported (image property) | **No dedup:** any override means `Material::Create` instead of `FindOrCreate` (MaterialAssignment.cpp:109), so equal overrides do not share | Per-slot unique materials | Per-slot property inspector generated from the material type, with real widgets (the closest to ours) |
| **Bevy**: one material asset per variation, bindless slabs | Draws batch while their materials sit in the same slab | A material slot in a slab plus its data | Asset mutation: re-prepared, its slab data rewritten | Supported (bindless resource arrays, ref-counted per slab) | Batches within a slab; a new slab is a new bind group | Slab of 2048 resources (64 on Apple) (`AUTO_BINDLESS_SLAB_RESOURCE_LIMIT`, bindless.rs:25-32) | No dedup: each `materials.add` is a new asset; no editor |
| **Wicked**: ObjectComponent colors, else another material | Per-object `color` and `emissiveColor` cost nothing (in the instance data); another material: an index | 2 float4s per object; another MaterialComponent: 384 B (`sizeof(ShaderMaterial)`) | Every material is written into the GPU material array every frame (`WriteShaderMaterial`, wiScene.cpp:4352), so a change is free but the cost is per frame per material | Another material, bindless descriptor indices | Batches (bindless, material index) | Only color and emissive per object; anything else means cloning the material | Material per entity in the editor |
| **Flax**: per-slot material entries, virtual material instances | A virtual instance per entity is another material: instancing merges only draw calls that `CanBatch` (RenderList.cpp:919), so it draws on its own | A MaterialInstance plus its parameter buffer | Set the parameter on the virtual instance; its constants are rebound | Supported | Breaks instancing per instance | No dedup | Per-slot material in the model's Entries; values through code (`CreateVirtualInstance`, MaterialBase.h:77) |
| **Stride**: `ModelComponent.Materials` per slot | Another Material: its own parameter collection, so a resource-set bind | A Material with its ParameterCollection | Set on the material's parameters | Supported | Breaks batching per material | No dedup | Per-slot material override in the model component |
| **HypeHype / NoGraphicsAPI**: material data as GPU memory, draws carry pointers | Data pointer or offset per draw; no per-material descriptor sets (NoGraphicsAPI README: materials carry texture indices as data) | Only the data written | A memory write | An index write | Batching is not tied to the material at all | Whatever memory you allocate | Engine-level; no editor model |

### Where xLION stands

- **Per draw (bindless):** as cheap as Unreal CPD, Godot instance uniforms and the pointer/offset designs. An override material costs the
  `MaterialBase` push constant a plain draw already sends. Faster than MID, o3de, Flax and Stride, which bind per material.
- **Generality:** any parameter, including textures. CPD and Godot cannot override textures; Wicked only overrides two colors.
- **Dedup:** among these engines, only xLION shares equal overrides automatically. o3de, MIDs, Bevy, Flax and Stride make one
  material per override.
- **Memory:** a unique override costs about as much as a material (its block). That is 32-80 B, against Godot's 256 B always reserved
  per instance (16 vec4-sized slots), Unreal's 144 B (9 float4s) and Wicked's 384 B per material. Shared overrides cost no GPU memory.
- **Change cost:** sub-microsecond in place (Release). Unreal's CPD and Godot's buffer writes are in the same class. o3de recompiles an
  SRG per change.
- **Where competitors are still better:**
  - Creation costs more than CPD: 3.3 µs per unique slot (a material record, a block allocation, a texture table) against a plain data
    write.
  - In non-bindless mode each override material binds its own descriptor set.

## Numbers

`xlionrender_bench_overrides`: 10000 entities of one cluster mesh (a sphere), all on one texture-table material. "Distinct" is how
many different override values there are (0% dedup: every entity its own). Frame CPU is `instance::Render`; GPU is the scene pass's
timestamps. The machine: RTX 4070 Ti SUPER, Vulkan 1.4, 120 frames a row.

### Before the review fixes (Release, bindless, 60 frames)

| Dedup | Distinct | Materials made | Failed | Frame CPU ms (none: 30.2) | GPU scene ms (none: 2.9) |
|---|---|---|---|---|---|
| 0% | 10000 | 8191 | **1809** | **60.3** | 4.6 |
| 50% | 5000 | 5000 | 0 | **52.3** | 4.7 |
| 99% | 100 | 100 | 0 | 36.0 | 6.2 |

Two problems:
- MaterialParams held 16384 vec4s, so 10k unique overrides did not fit.
- Every distinct material re-bound the full state, even though they share one pipeline. That doubled the frame's CPU time.

### After the fixes: Release, bindless

| Dedup | Distinct | Materials | Failed | MaterialParams vec4s | Create µs/slot | Steady µs/slot | Change in place µs | Copy-on-write µs | Texture µs | Frame CPU ms (none 30.3) | GPU scene ms (none 3.8 → 6.2) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 0% | 10000 | 10000 | 0 | 20000 | 3.29 | 0.056 | 0.66 | - | 0.39 | 31.1 | 4.3 |
| 50% | 5000 | 5000 | 0 | 10000 | 1.09 | 0.056 | 0.54 | 1.56 | 0.41 | 31.7 | 5.7 |
| 99% | 100 | 100 | 0 | 200 | 0.07 | 0.058 | 0.32 | 0.38 | 0.38 | 32.9 | 5.7 |
| 100% | 1 | 1 | 0 | 2 | 0.06 | 0.056 | 0.48 | 0.70 | 0.71 | 30.8 | 6.4 |

- **GPU:** the scene pass drifts upward over a run. The no-overrides baseline measured 3.8 ms first and 6.2 ms again at the end, and
  every override row falls in that band. The GPU cost of overrides is within noise. That is expected: the same draws, the same
  pipeline, and one more vec4 read through `MaterialBase`.
- **Frame CPU:** within 1-3 ms (3-9%) of no overrides; it was double before the fixes.
- **Steady:** the per-frame `Acquire` of an unchanged slot. In the editor, the scene renderer also skips the source resolve for an
  unchanged slot (see fix 3), so a steady slot costs about what a plain slot costs: one map lookup plus a hash of its overrides.

### After the fixes: Release, non-bindless (`XGPU_NO_BINDLESS=1`)

| Dedup | Distinct | Create µs/slot | Change in place µs | Copy-on-write µs | Texture µs | Frame CPU ms (none 30.4) | GPU scene ms (none 3.6 → 6.2) |
|---|---|---|---|---|---|---|---|
| 0% | 10000 | 7.75 | 0.63 | - | 4.27 | **46.8** | 6.3 |
| 50% | 5000 | 3.29 | 0.51 | 3.35 | 4.06 | 39.4 | 5.5 |
| 99% | 100 | 0.13 | 0.32 | 2.08 | 3.76 | 32.3 | 6.7 |
| 100% | 1 | 0.06 | 0.26 | 2.02 | 3.81 | 31.9 | 6.6 |

The fallback pays one descriptor-set bind per distinct override material (+16 ms for 10000 unique ones). That is the cost already
accepted for non-bindless devices.

### After the fixes: Debug, bindless (30 frames)

| Dedup | Create µs/slot | Steady µs/slot | Change in place µs | Copy-on-write µs | Texture µs | Frame CPU ms (none 39.6) |
|---|---|---|---|---|---|---|
| 0% | 29.5 | 0.29 | 4.6 | - | 5.4 | 42.6 |
| 50% | 9.5 | 0.26 | 4.5 | 15.0 | 5.5 | 42.7 |
| 99% | 0.82 | 0.20 | 4.1 | 5.5 | 5.1 | 42.9 |

### Memory

- **MaterialParams (device-local):** 4 MiB fixed, 262144 vec4s.
  - Room for 10000 unique overrides of a block up to 26 vec4s.
  - It was 256 KiB (16384 vec4s).
- **Upload ring (host-visible):** 3 regions of 16384 vec4s, 768 KiB.
  - It was 3 regions the size of the whole buffer, so with the new buffer size it would have been 12 MiB.
- **Growth with the number of entities:** one block per distinct override (0% dedup: 20000 vec4s = 312 KiB for the bench's 10000
  entities; 99%: 3 KiB). Shared overrides add none.
- **Not measured:** the CPU side per override material (a material record, a texture-table handle, a map entry).

## What was changed because of this review

1. **Draws on materials of one pipeline bind once** (`plans/forward/xlionrender_plan_forward.cpp`).
   - The scene and shadow passes compared each material's own pipeline-instance handle. Texture-table materials of one pipeline hold
     copies of one shared instance, so every distinct material re-bound the whole state.
   - They now compare the shared instance. When it is the same, only the texture table is set again (bindless: the same set, so
     nothing happens).
   - Frame CPU at 0% dedup dropped from 60.3 to 31.1 ms.
   - Test: 64 override materials, 1 scene bind (`xlionrender_test_overrides`).
2. **MaterialParams grows to 4 MiB with a fixed-size upload ring** (`xlionrender_instance.h/.cpp`, `updateInstances`).
   - Pending blocks are packed into the frame's ring region, after what the frame's earlier renders wrote. What does not fit waits for
     the next frame, in order.
   - 10000 unique overrides now fit (1809 had failed).
   - Test: 9000 override materials (more than one ring region); the last one draws its value.
3. **The scene renderer skips an unchanged slot** (`xlionrender_scene_renderer.h`, `OverrideOf`).
   - Each slot keeps a check value: its instance's own material id (a compile replaces it), the loaded texture of each texture
     override, and the overrides as written.
   - A frame that changed none of them returns the slot's material without rebuilding the source, the overrides or the key.
   - A texture that is still loading is never cached.
   - A slot whose overrides all went away now releases its override material.
   - Checked in the editor: the Puppy turned red, then magenta when B changed on a later frame.

## What was not changed, and why

- **CPD-style routing through `entity_params`.**
  - Materials can mark up to 3 parameters as entity fields (TINT, PARAM0, PARAM1, `xmaterial::entity_field`). Routing those overrides
    into the draw's `m_EntityParams` would make no material at all, like Unreal's CPD.
  - Not done: `entity_params` is per draw, not per slot (`m_SlotMask` is reserved). The bindless override path already draws at the
    cost of a plain draw. And Tomas asked that parameters come from the material instance, not from fixed fields.
  - It would only save the 3.3 µs creation and the 80 B block of unique overrides.
  - Worth revisiting if a game sets unique values on many thousands of entities every frame.
- **Non-bindless set per material.**
  - Override materials that change only values could share their instance's texture table, which would remove the extra set binds in
    that mode.
  - Not done: the table would then need its own copy-on-write for texture overrides, and non-bindless devices are expected to be rare
    (accepted earlier).
- **The renderer's 3 µs per draw on the CPU.** The baseline (30 ms for 10000 draws, Release) is the renderer as a whole, not overrides.
  It is outside this step.

## How to measure

```
cd example.lionprj/Cache/dependencies/xLIONRender/Build/test/vs2022
cmake --build . --config Release --target xlionrender_bench_overrides
Release/xlionrender_bench_overrides.exe --frames 120            (bindless)
XGPU_NO_BINDLESS=1 Release/xlionrender_bench_overrides.exe      (the fallback)
```

`--entities N` changes the count. Compare frame times against the two "no overrides" rows, the first and the last of the run, not
against one of them: the GPU drifts over a run.
