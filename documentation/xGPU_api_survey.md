# xGPU API survey: how other engines shape their GPU abstraction

Date: 2026-10-23. A read-only study for "make xGPU a clean, elegant API" (plan: *xGPU materials and textures: path to bindless*).
Sources: `E:\source_code` (NoGraphicsAPI, WickedEngine, Godot, O3DE, Unreal, Flax, Bevy) and xGPU at
`example.lionprj/Cache/dependencies/xGPU/source`. Every reference is `file:line` in those trees.

The fixed decisions this is measured against:
- Vulkan 1.3 is the minimum.
- Textures and samplers are bound bindless, by index. A non-bindless fallback is supported behind the same API.
- No GPU pointers: buffers stay handle + offset.
- Mesh shaders are not required.
- VRAM is sub-allocated with OffsetAllocator.
- Samplers live in one global, deduplicated table. A texture has a default sampler and a material slot can override it.
- Uploads have two lanes: a frame lane in the frame's command buffer, and a streaming lane on the transfer queue with a staging ring and timeline points.
- A render graph comes later.

---

## 1. Engine by engine

### NoGraphicsAPI (Sebastian Aaltonen's model, Vulkan 1.4 / Metal 4)
- **Handles:** opaque pointers to forward-declared structs (`Device*`, `Texture*`, `PSO*`; `NoGraphicsAPI.hpp:21-31`).
  - Free functions, no classes, no reference counting.
  - Heaps are value aggregates; copies alias the same allocation (`GpuHeap`, `:75-80`).
- **Creation:** one small `*Desc` struct per object with designated-initializer defaults (`TextureDesc :487`, `SamplerDesc :525`, `GraphicsPSODesc :615`).
  - The PSO has **no binding layout and no vertex layout**: only shaders, blend, attachment formats and raster state (`:615-623`).
- **Binding:**
  - Textures and samplers live in application-owned indexed heaps (`create_texture_descriptor_heap :747`, `write_texture_descriptor :749`, `write_sampler_descriptor :755`).
  - The heaps are bound once per command buffer (`set_texture_descriptor_heap :776`).
  - Each draw takes one `root` pointer to application-owned constant data (`draw(commands, root, ...) :822`). Shaders read indices from the root.
- **Commands:** pools per thread and per frame, one-shot buffers, explicit `submit` with timeline waits and a completion point (`SubmitDesc :95`, `submit :774`).
  - Threading is externally synchronized and written down in one block (`:687-696`).
- **Synchronization:** one global barrier names stages and accesses, with no resource lists (`barrier :791`; `Stage :391`, `Access :413`).
  - Images stay in GENERAL layout.
  - Cross-queue sync uses timeline points (`TimelinePoint :89`, `wait_timeline :709`).
- **Uploads:** the core has only `copy_memory` / `copy_memory_to_texture` (`:786-789`). Policy lives in a separate utility library:
  - `UploadQueue` (`utility/.../upload_queue.hpp:21`) has a fixed staging ring that never grows and returns a `TimelinePoint` from `flush()` (`:63`) for other queues to wait on.
  - `DeleteQueue` (`delete_queue.hpp:11`) frees resources at a timeline value.
  - `TextureAllocator` (`texture_allocator.hpp:14`) places textures in heaps.
- **Errors:** `Error` enum (`:33`). Creation returns nullptr or an empty aggregate, and the text goes to an optional thread-local callback (`set_error_callback :46`).
- **Elegant:**
  - The whole API is one 835-line header.
  - Destruction is immediate, with deferral as an opt-in utility.
  - The descriptor heap is the bindless table.
  - The PSO carries no layout.
  - The core never allocates on the application's behalf.
- **Painful / not for us:**
  - GPU pointers everywhere, which we rule out.
  - The application must manage every hazard by hand.
  - There is no fallback for devices without descriptor heaps.

### WickedEngine (`wiGraphicsDevice.h`, `wiGraphics.h`)
- **Handles:** value structs holding a reference-counted `internal_state` (`GPUResource`, `wiGraphics.h:862-864`). This is the same idea as xGPU's `m_Private`.
- **Creation:** `CreateX(const Desc*, ..., X* out) -> bool` (`wiGraphicsDevice.h:93-101`).
  - `CreateBuffer2` takes an **init callback** that writes straight into the destination (`:93`), the same trick as xGPU's `MemoryMap` lambda.
- **Binding:** bindless and slot binding sit side by side.
  - `GetDescriptorIndex(resource | sampler)` (`:109-110`) returns a bindless index that the application pushes with `PushConstants` (`:260`).
  - The DX11-style `BindResource` / `BindSampler` / `BindConstantBuffer` slots remain for older shaders (`:222-229`).
- **Commands:** `BeginCommandList(queue)` returns a small handle (`:122`), `SubmitCommandLists()` submits everything started this frame (`:125`), and `WaitCommandList(cmd, wait_for)` orders queues (`:215`).
  - Lists are recorded from many threads.
- **Synchronization:** explicit `GPUBarrier` with Memory / Image / Buffer / Aliasing kinds and before/after states (`wiGraphics.h:683`; `Barrier :256`).
- **Uploads:**
  - `AllocateGPU(size, cmd)` is a per-command-list linear ring for transient data (`:355`).
  - `CopyAllocator` runs on the copy queue with its own fences and semaphores (`wiGraphicsDevice_Vulkan.h:258-281`).
  - `CopyBufferAsync` can span frames (`:200`).
- **Errors:** `bool` returns plus logging.
- **Elegant:** the per-command-list transient allocator (`AllocateGPU`), and bindless indices served by the device from the same resource objects.
- **Painful:** every call takes a trailing `CommandList cmd` and goes through a virtual on one large device class. Two binding models are fully live, so every renderer path must pick one.

### Godot (`servers/rendering/rendering_device.h`)
- **Handles:** `RID` is an integer id resolved through typed owners (`RID_Owner<Texture> :415`). Resources are freed with `free_rid` (`:1917`), and the device defers the real destruction.
- **Creation:** `texture_create(format, view, data)` (`:469`) and `render_pipeline_create(shader, framebuffer_format, vertex_format, ...)` (`:1283`). The pipeline is tied to framebuffer and vertex formats.
- **Binding:** uniform sets are descriptor sets made against a shader's set (`uniform_set_create :1199`). Cached set formats are at `:910-931`.
  - Draws use `draw_list_bind_uniform_set` and `draw_list_set_push_constant` (`:1563`, `:1568`).
- **Commands:** draw and compute lists are ids (`draw_list_begin :1558`, `compute_list_begin :1687`).
  - Everything is recorded into an internal **RenderingDeviceGraph** (`draw_graph :1762`) that inserts barriers and can reorder commands (`draw_graph_reorder_commands :1765`).
- **Synchronization:** automatic. Manual `barrier()` / `full_barrier()` remain (`:993-994`).
- **Uploads:** `buffer_update` / `texture_update` go through staging blocks (`_staging_buffer_allocate :179`).
  - The header documents batching updates before draws (`:233-271`).
  - Readback is async through `buffer_get_data_async` / `texture_get_data_async` with a callback (`:274`, `:475`).
- **Errors:** `Error` codes plus `ERR_FAIL_*` macros.
- **Elegant:** the internal graph gives automatic barriers without the user writing a render graph. Async readback takes a callback.
- **Painful:** uniform sets per shader set mean a set per material per shader. This is exactly the per-material descriptor churn we are removing.

### O3DE Atom RHI (`Gems/Atom/RHI/Code/Include/Atom/RHI`)
- **Handles:** intrusive `Ptr<T>` reference counting on `DeviceObject`s, with pools (`BufferPool`, `ImagePool`, `StreamingImagePool`, `ShaderResourceGroupPool`). Results come back as `ResultCode` (`Device.h:59-90`).
- **Binding:**
  - ShaderResourceGroups (SRGs) are typed groups whose data is set by input index (`DeviceShaderResourceGroupData.h:74 SetImageView`).
  - They are compiled asynchronously in a batch (`DeviceShaderResourceGroup.h:26-35`, `Compile(..., CompileMode::Async)`).
  - Bindless lives next to them: a view exposes `GetBindlessReadIndex()` (`DeviceImageView.h:44`), and a fixed **bindless SRG** slot holds the unbounded arrays (`BindlessSrgDescriptor.h`).
  - This is the model Tomas pointed to: **bindless and classic binding behind one SRG concept.**
- **Commands:** the frame graph is made of `ScopeProducer`s, each with `SetupFrameGraphDependencies` → `CompileResources` → `BuildCommandList` (`ScopeProducer.h:19-21, 99-109`).
  - Barriers, transient aliasing and queue placement are derived from the declared attachments (`FrameGraph*.h`, `AliasedAttachmentAllocator.h`).
- **Streaming:** `StreamingImagePool` is a first-class resource pool:
  - `InitImage` uploads only the **tail mips** synchronously (`DeviceStreamingImagePool.h:40-61`).
  - `ExpandImage` adds mips asynchronously (`:63, :105`); `TrimImage` drops them (`:110`).
  - `AsyncWorkQueue.h` runs the copies.
- **Elegant:** streaming as a pool with init / expand / trim, and SRG compiles batched per frame.
- **Painful:** a very large surface area (more than 100 headers just for the RHI). Multi-device templates sit in front of everything (`Device*` vs non-`Device` pairs).

### Unreal RHI (`Runtime/RHI/Public`)
- **Handles:** reference-counted `FRHIResource` (`RHIResources.h:53`) held through `TRefCountPtr`.
  - Bindless: every resource and view can return an `FRHIDescriptorHandle { type, index }` (`RHIDefinitions.h:1397`; `GetBindlessHandle :638`).
- **Creation:** builder descriptors such as `FRHIBufferCreateDesc::CreateStructured(name, ...)` with chained setters (`.SetInitialState`, `.SetDebugName`) (`RHIResources.h:1466-1592`; the texture variant is at `:2091-2105`). A debug name is required up front.
- **Binding:** shader parameter structs are filled by reflection; under bindless the same parameters become handle indices.
  - The rollout is gradual through `ERHIBindlessConfiguration { Disabled, RayTracing, Minimal, All }` (`RHIDefinitions.h:1433`).
  - **The same shader code works with bindless on or off.**
- **Commands:** `FRHICommandList` records into an RHI thread and parallel translate. The immediate list is special (`RHICommandList.h:2493`, `FRHIComputeCommandList`).
- **Synchronization:** explicit transitions `FRHITransitionInfo(resource, before, after)` with split begin/end transitions (`RHITransition.h:118`; `BeginTransitions RHICommandList.h:2739`).
  - RDG (the render graph) usually generates them.
- **Uploads:** `LockBuffer` / `UpdateTexture`, plus `FRHIResourceUpdateBatcher` for streaming. Texture streaming is a separate engine system built on these.
- **Elegant:**
  - The bindless handle as a small typed value.
  - The bindless configuration flag with a fallback.
  - Builder descriptors with mandatory debug names.
- **Painful:** decades of layers (immediate list, RHI thread, deferred deletes, transitions). Hard to reason about without RDG.

### Flax (`Source/Engine/Graphics`)
- **Handles:** `GPUResource` objects that are also scripting objects (`GPUResource.h:46`).
- **Binding:** a DX11-style immediate `GPUContext` with slots: `BindSR`, `BindUA`, `BindCB`, `BindSampler` (`GPUContext.h:410-452`), `SetState(pso)` (`:651`), and `FlushState` (`:676`).
- **Synchronization:** automatic resource-state tracking, with `SetResourceState` / `MemoryBarrier` / `OverlapUA` escapes (`:686-709`).
- **Uploads:** `UpdateBuffer` / `UpdateTexture` on the context (`:259`, `:280`).
  - Async work is `GPUTask`s on a `GPUTasksManager` with `GPUSyncPoint`s (`Graphics/Async/GPUTask.h:14-73`; `GPUDevice.h:340`).
  - Streaming is per resource (`Streaming/StreamableResource.h`) with handlers that decide the target quality.
- **Elegant:** the separation between `StreamableResource` (what quality is wanted) and `GPUTask` (how the upload runs).
- **Painful:** the immediate context hides costs and is single-threaded.

### Bevy (wgpu)
- **Pipelines:** `PipelineCache` queues pipelines and compiles them on tasks (`CachedPipelineState { Queued, Creating(Task), Ok, Err }`, `render_resource/pipeline_cache.rs:48-76`).
- **Bindless with a fallback:** `MaterialBindGroupAllocator { Bindless(...), NonBindless(...) }` (`bevy_render/src/material_bind_groups.rs:85-89`).
  - Bindless materials share **slabs** (`MaterialBindlessSlab :121`) whose resources sit in binding arrays (`render_resource/bindless.rs`).
  - Non-bindless materials get one bind group each (`:224`).
  - **The material code above the allocator does not change.**
- **Elegant:** this is the cleanest small example of "bindless with a fallback behind one API" in the set.

### xGPU today (for comparison)
- **Handles:** value structs around `std::shared_ptr<details::*_handle> m_Private` (`xgpu_buffer.h:65`, `xgpu_pipeline.h:210`).
  - There is no move: `Destroy(std::move(x))` queues a copy. Destruction is deferred through the device's death list.
  - The destructor of the last reference destroys the object (`Details/xgpu_pipeline_inline.h:132-138`).
- **Creation:** `device::Create(T&, const T::setup&) -> error*` overloads (`xgpu_device.h:34-68`). This is a good, uniform shape.
- **Binding:**
  - The pipeline owns the sampler layout; a `pipeline_instance` owns one descriptor set of textures (`xgpu_pipeline_instance.h`).
  - Buffers bind as `StaticBuffers` spans on `setPipelineInstance` (`xgpu_cmd_buffer.h:8`) plus `setDynamicUBO` / `setPushConstants`.
  - `vkCmdBindPipeline` runs on every `setPipelineInstance`, even when the pipeline did not change (`Details/Vulkan/xgpu_vulkan_window.cpp:1414-1507`).
- **Commands:** the command buffer comes from the window (`xgpu_window.h:29-32`: `BeginRendering`, `getCmdBuffer`, `StartRenderPass`, `PageFlip`). One graphics queue, no explicit submit, no timelines.
- **Synchronization:** implicit, by render pass layouts and internal barriers. There is no public barrier.
- **Uploads:** `MemoryMap` with a lambda, `allocEntry` for transient UBO rings, and synchronous `ReadTexture`. No transfer queue or staging ring.
- **Errors:** `error*` (a static string through `VGPU_ERROR`), `[[nodiscard]]`. Cheap and readable.

---

## 2. The patterns side by side

| | Handle | Binding | Commands | Sync | Streaming |
|---|---|---|---|---|---|
| NoGraphicsAPI | raw opaque ptr | indexed heaps + root ptr | pools, explicit submit, timelines | global barriers | utility UploadQueue |
| Wicked | refcounted value | bindless index + legacy slots | lists per frame, multi-thread | explicit typed barriers | copy queue allocator |
| Godot | RID integer | uniform sets per shader | draw lists into internal graph | automatic (graph) | staging + async readback |
| O3DE | intrusive Ptr + pools | SRGs + bindless SRG | frame graph scopes | from graph | StreamingImagePool |
| Unreal | refcounted + typed index | params → handles, configurable | RHI thread, parallel | explicit transitions / RDG | update batcher |
| Flax | object | immediate slots | immediate context | automatic | GPUTasks + StreamableResource |
| Bevy | wgpu objects | bind groups, bindless slabs | wgpu | wgpu | — |
| xGPU | shared_ptr value | pipeline_instance sets | window-owned buffer | implicit | MemoryMap only |

---

## 3. The 10 best ideas for xGPU (within the fixed decisions)

1. **A bindless index as a small typed value** (Unreal `FRHIDescriptorHandle`, `RHIDefinitions.h:1397`; Wicked `GetDescriptorIndex`, `wiGraphicsDevice.h:109`).
   - `texture::getIndex()` / `sampler_id` return `xgpu::texture_index { std::uint32_t }`. Shaders receive them through push data or the material parameter block.
   - Keep it typed (texture vs sampler vs storage image) so a mix-up does not compile.

2. **One binding API, two allocators behind it** (Bevy `MaterialBindGroupAllocator`, `material_bind_groups.rs:85-89`; O3DE bindless SRG + SRGs; Unreal `ERHIBindlessConfiguration`).
   - The material asks for "a texture table of N slots". Under bindless that is a range of indices in the global heap.
   - Under the fallback it is a classic descriptor set built from the same list.
   - The renderer and the materials never branch. `device::isBindless()` exists only for shader variant selection.

3. **The descriptor heap as an application-visible indexed table** (NoGraphicsAPI `create_texture_descriptor_heap` / `write_texture_descriptor`, `NoGraphicsAPI.hpp:747-757`).
   - xGPU owns one global texture heap and one sampler heap; indices are handed out by a free list.
   - A slot is reused only after its timeline point has passed (that is the fallback's job too).
   - Writes happen at creation and on stream-in (a mip change rewrites the same index: zero material changes).

4. **A deduplicated global sampler table** (NoGraphicsAPI `SamplerDesc` → `write_sampler_descriptor`, `:525`, `:755`; Wicked `GetDescriptorIndex(const Sampler*)`).
   - `device::getSampler(const sampler_desc&) -> sampler_id` hashes the descriptor and returns the existing entry.
   - The texture stores its default `sampler_id`; a material slot stores an optional override.
   - This makes "both texture and slot" cheap and keeps most draws on the default (the fast path Tomas asked for).

5. **Pipelines without per-material binding layouts** (NoGraphicsAPI `GraphicsPSODesc`, `:615-623`; the step-1 change already made one pipeline per shader+state).
   - With bindless, every material pipeline shares **one pipeline layout**: global heap sets + push data + the frame's buffer set.
   - The pipeline keeps only shaders, state and attachment formats, and the pipeline cache key becomes (shaders, state, formats).
   - Pair it with skipping redundant `vkCmdBindPipeline` (today it rebinds every time, `xgpu_vulkan_window.cpp:1507`).

6. **Explicit submit with timeline points instead of window-owned command buffers** (NoGraphicsAPI `SubmitDesc` / `TimelinePoint`, `:89-100`; Wicked `WaitCommandList`, `:215`).
   - `device::Submit({ cmd buffers, waits, signal })` returns an `xgpu::timeline_point`.
   - The window only acquires and presents.
   - This is the base both upload lanes and, later, the render graph need, and it removes the window's role as a hidden command owner.

7. **Two upload lanes as a small utility, not in the core** (NoGraphicsAPI `UploadQueue`, `upload_queue.hpp:21-63`; Wicked `AllocateGPU` + `CopyAllocator`, `wiGraphicsDevice.h:355`, `wiGraphicsDevice_Vulkan.h:258`).
   - **Frame lane:** `cmd.allocTransient<T>()`, a per-frame linear ring (generalizing today's `allocEntry`).
   - **Streaming lane:** `upload_queue` on the transfer queue with a fixed staging ring that never grows. `upload_texture(tex, mip, bytes)` and `flush() -> timeline_point`; the frame waits on that point.
   - Async by construction, which is what streaming needs.

8. **Streaming textures as init / expand / trim on a resident index** (O3DE `StreamingImagePool::InitImage/ExpandImage/TrimImage`, `DeviceStreamingImagePool.h:40-110`; Flax `StreamableResource` + `GPUTask`).
   - A texture is created with only its tail mips, so it is usable at once at low resolution.
   - Expand adds mips through the streaming lane; trim drops them.
   - Because the shader reads a bindless index, an expanded texture just rewrites its descriptor (or swaps the image behind the same index), and materials never notice.

9. **Deferred destruction keyed by timeline values, explicit in the API** (NoGraphicsAPI `DeleteQueue`, `delete_queue.hpp:11`; Godot `free_rid`, `:1917`).
   - Keep xGPU's death list but key it by the submission's timeline value, not a frame index.
   - Add move constructors so `Destroy(std::move(x))` really empties `x`. Today the moved-from handle keeps a reference, a trap the renderer works around (`ReleaseBuffer`, and the `.reset()` after `Destroy` in step 1).
   - OffsetAllocator blocks are freed through the same queue.

10. **Uniform descriptors, debug names and one error path** (Unreal `FRHIBufferCreateDesc::Create*(...).SetDebugName`, `RHIResources.h:1466-1592`; NoGraphicsAPI thread-local error callback, `:46`; xGPU's existing `Create(T&, setup) -> error*`).
    - Keep `device::Create(obj, setup) -> error*` as the single creation shape. It is already the best part of xGPU.
    - Every `setup` gets an `m_pName` used for validation-layer object names.
    - Add one optional error callback for the details, so the `error*` stays a short static code.
    - Write the threading contract in one header block the way NoGraphicsAPI does (`:687-696`): what is externally synchronized, and what is per thread.

### Also worth keeping in view (not top 10)
- **Godot's internal command graph** (`draw_graph :1762`): automatic barriers inside the device. This is a cheap stepping stone before a real render graph if explicit barriers prove noisy. O3DE's `ScopeProducer` triple (`ScopeProducer.h:99-109`) is the cleanest render graph pass interface for later.
- **Bevy's async pipeline cache** (`pipeline_cache.rs:48`): build pipelines on worker threads (xscheduler) and draw with a fallback until ready. This removes first-use hitches now that pipelines are shared.
- **Async readback with a callback** (Godot `texture_get_data_async`, `:475`) to replace the synchronous `ReadTexture` in the editor's thumbnail and probe paths.
- **Barrier model:** NoGraphicsAPI's global stage/access barrier (`:791`) is the simplest public form and fits Vulkan 1.3 synchronization2. Keep image layouts internal (GENERAL / attachment-optimal) the way it does.

### Not to copy
- GPU pointers and raw roots (NoGraphicsAPI): ruled out by decision; buffers stay handle + offset.
- Per-shader uniform sets (Godot) and per-material descriptor sets (xGPU today): the churn bindless removes.
- Two binding models exposed to every caller (Wicked's slots + indices): the fallback must stay behind the API.
- O3DE's size and multi-device templates; Unreal's immediate-list and RHI-thread layers.
