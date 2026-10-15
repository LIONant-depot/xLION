# Editable virtual resources + skin skeleton/animation import — execution plan

Decided with the user on 2026-10-16. Do one phase at a time, build what it touches, run only the tests named in it, and update this file at the
end of each phase (mark it DONE, note anything that differs). Commit only when the user asks (local commits per repo, never push unasked, stage
explicit paths). Write source and test files with the Write/Edit tools (shell heredocs eat backslashes).

## Why

A resource compiler can generate *virtual resources* (a geometry makes Material Instances and Textures, a font makes its atlas Texture, a skin
makes its Skeleton and Anim Package). Today they are rewritten in `Cache/Descriptors` on every compile, and `/Cache` is not in git, so a user
edit (a clip's Loop, a material's texture) is lost. Goal: the user edits a virtual resource like any other resource, the edit is in git and
survives recompiles.

## The rules (all agreed, do not redesign)

1. **Where they live**: virtual descriptors are ordinary descriptors in the project's `Descriptors/<Type>/xx/yy/<guid>.desc/Descriptor.txt`
   (folder named with `{:X}`, no leading zeros — that is how xresource_mgr loads). No copies, no `Cache/Descriptors` for descriptors any more.
   Their `Info.txt` links the owner as its parent (`m_RscLinks`): **the owner acts as their folder** (deleting the owner deletes them, after
   the user agrees, like any folder).
2. **The cache** holds only binary data a generator needs (e.g. the font atlas pixels), never descriptors.
3. **Ownership list**: the owner's compiler writes, in its own descriptor folder, a file listing the guids it generated (e.g.
   `<owner>.desc/Virtual.txt`, xproperty text: full_guid list). On each compile it reads that list and the existing descriptors, and:
   - a virtual resource that does not exist yet is created (as today's emitters do);
   - one that exists is **loaded and only the generator-owned fields are updated**, everything else is the user's:
     - Material Instance: the base material ref; a texture slot only while it still points at a texture on the owned list (anything else is
       the user's choice); never the tunable values.
     - Texture (generated): its source file/mix inputs.
     - Anim Package: its `SkeletonRef` and its import source path; clips stay (the package already matches clips by `OriginalName`).
     - Skeleton: its `ImportAsset` only (bones/masks/PreTransform are the user's; it matches bones by name).
   - one no longer needed (material removed from the model, import turned off) stays on disk with its edits, is not compiled, is not listed as
     a dependency, and is dimmed or hidden in the asset browser; re-needed later it is reused with its edits. A command "Remove unused imported
     resources" on the owner deletes them.
   Write files only when their text changed (reuse `WriteIfChanged` from
   `plugins/xmaterial_instance.plugin/source/Compiler/xmaterial_instance_import_compiler.h`): a write in `Descriptors/` wakes the file watcher.
4. **Compile order**: run groups (Plugin.config `RunAfter`) order the **real** resources, as today. A virtual resource never starts a chain:
   when an owner finishes, the pipeline queues its virtual resources right after it, in their own dependency order (Skeleton before the Anim
   Package that reads its bone manifest), **inside the owner's group**. A group is finished only when its resources and their chains are
   finished; only then the next group starts. A virtual resource owned by a virtual one goes up the owners to the real one.
5. **A changed virtual resource** (saved by an editor, or changed by a `git pull` — same case): look at its owner (its parent link). Owner clean
   and not queued/compiling → compile it alone, now. Owner changed, queued or compiling → it waits in the owner's chain (queued when the owner
   finishes, even if the owner did not rewrite it; if the owner dropped it, it is not compiled).
6. **Who may use a virtual resource**: only resources with the same owner (the owner itself, or another of its virtual resources: Anim Package
   → Skeleton, Material Instance → Texture). Enforce:
   - resource pickers **never list virtual resources** (any picker, anywhere): only their owner's editor/compiler assigns them;
   - the pipeline fails a compile whose dependencies include a virtual resource of another owner, with a message naming both.
   (The user confirmed today's usage already follows this; no audit needed.)
7. To reuse one elsewhere: "Duplicate as override" makes a real copy (exists for materials today).

## Current state (before phase 1)

Uncommitted, built, `smoke/test_imported_skeleton.py` passes (in `source/Editors/LevelEditor/smoke`):
- `plugins/xskeleton.plugin/source/compiler/xskeleton_merge.h` (new): the Skeleton compiler's bone merge/hash/manifest code, shared;
  `xskeleton_compiler.cpp` uses it.
- `plugins/xgeom_skin.plugin`: descriptor `import_animation { m_bSkeleton, m_bAnimations }` (`ImportAnimation`), `ImportedSkeleton(Owner)` /
  `ImportedAnimations(Owner)` guids, `isImportedSkeleton`, `SyncSkeletonSlot`, `OwnerFromPath`; the compiler builds the manifest itself
  (`BuildManifest`) and emits a virtual Skeleton + AnimPackage (`EmitVirtual` lambda in `onCompile`); the editor has a SkeletonRef override
  arrow (`RegisterSkeletonRowLabel`) and `PreviewAnim()` fallback; `documentation/editor.md` section "Imported skeleton and animations".
- `example.lionprj`: the two existing skins got `ImportAnimation/bSkeleton 0` and `bAnimations 0`.
Phase 4 replaces the two bools and the arrow; keep the rest.

Key code: virtual cascade and orphan cleanup in `dependencies/xresource_pipeline_v2/source/editor/xresource_editor_asset_mgr.h`
(`VirtualCascadeList` ~line 4340, `UpdateVirtualRefs`, `RemoveVirtualResource`, `getQueueIndexFromType`/run groups, `m_VirtualRefs`);
emitters: `xmaterial_instance_import_compiler.h`, the font compiler (`plugins/xfont.plugin`), the skin compiler; the material import editor
`plugins/xmaterial_instance.plugin/source/Editor/xmaterial_instance_import_editor.h` (`duplicate_cmd` copies from `Cache\Descriptors` —
update it); hover card `xresource_editor_resource_hint.h`.

## Phase 1 — pipeline: virtual descriptors in Descriptors/, owner chains — DONE (2026-10-16, uncommitted)

What was built (all in `dependencies/xresource_pipeline_v2/source/editor/xresource_editor_asset_mgr.h` unless said):
- Virtual descriptors live in `Descriptors/`; the library has no `m_SysDescriptorPath` any more, the scan and the watchers read only `Descriptors/`.
  Emitters write there (`project_paths::m_Descriptors`: the material emitter's member is `m_Descriptors` now; the font compiler writes the atlas
  Texture descriptor there). Migration at library load (`library_mgr::MigrateVirtualDescriptors`): moves `Info.txt` + `Descriptor.txt` of every
  `Cache/Descriptors/**/*.desc` folder; other files in the folder (the font atlas PNG) are generated data and stay; a folder with an empty/missing
  `Info.txt` is a leftover and is not moved.
- "Is virtual" = its Info links a parent that is not a folder (`library_db::IsVirtual`), the owner.
- Chain bookkeeping is `virtual_chain` (new `xresource_editor_virtual_chain.h`, standalone): who each virtual resource's real owner is (`m_Refs`, filled
  by the scan and each compile like the old refcount), which resources are queued/compiling (`m_Busy`), the force of a Recompile All kept for a
  resource that had to wait. `library_db::IsBlockedVirtual` (called by `AddToCompilationQueueIfNeeded`): unused (nobody lists it) -> never compiled;
  owner busy -> waits; an earlier virtual resource (run group of its type) of the same owner busy -> waits. `QueueForCompilation` puts a virtual resource
  in the queue level of its owner's type. The worker frees the busy mark when the node gets its final state, then queues the owner's virtual
  resources (cascade, sorted by run group) or, for a virtual one that ended, the rest of its owner's chain (`VirtualChainList`). Group completion
  waits for chains for free: everything is queued before the worker's `m_WorkersWorking` drops.
- Changed virtual resource (watcher or `git pull`): the same gate. Owner clean -> compiled alone, now; owner busy -> queued when it ends.
- Rule 6: after a compile, `library_mgr::CheckVirtualDependencies` reads the dependencies the compile wrote; a listed virtual resource of another
  owner makes that compile fail, naming both. (Only virtual resources the editor knows are listed; picker filtering is Phase 2.)
- Unused ones are kept: `RemoveVirtualResource` stays (adapted to `IsVirtual`) but nothing calls it; Phase 3's command will.
- `xmaterial_instance_import_editor.h` `duplicate_cmd` reads from `Descriptors\` (it was Phase 2's item, but the move broke it).
- Docs: `xresource_pipeline_v2/documentation/FolderOrganization.md`, `Terminology.md`.

Differs from / not in the plan:
- Unused virtual resources are NOT dimmed or hidden in the asset browser yet (they stay the owner's children): UI part of rule 3, still open.
- A virtual resource whose compile FAILED does not release the later ones of its chain: they wait until the owner compiles again (the cascade).
- The font atlas PNG still lives in `Cache/Descriptors/Texture/..../<guid>.desc/` (pixel data only); Phase 2 may rename the folder.
- The example project's virtual descriptors moved into `example.lionprj/Descriptors/` (its own git repo: untracked files there until committed).
  `project_guard` removes files a run created, so run the suite only after the editor has migrated the project once (a first run inside pytest ate the
  atlas descriptors; they were regenerated by recompiling the two fonts).

Tests: new `smoke/test_virtual_chain.py` (+ `dependencies/xresource_pipeline_v2/smoke_test_virtual_chain.cpp`, no editor); `test_virtual_resource_cleanup.py`
rewritten (import off keeps the resources and does not compile them, startup keeps an unlisted one, legacy `Cache/Descriptors` migration);
`test_imported_materials.py`, `test_imported_skeleton.py`, `test_font_mips.py` paths moved; `golden/test_impact.json` maps the chain files.
Ran (all pass): test_virtual_chain, test_virtual_resource_cleanup, test_font_mips, test_imported_materials, test_imported_skeleton. Compilers rebuilt
(Debug and Release: xfont, xgeom_skin, xgeom_static), editor Debug.

Original list:


- Cascade/LoadInfo of virtual resources: descriptor path under the library's `Descriptors/` (not `m_SysDescriptorPath`); Info parent = owner.
- Scheduling (rules 4, 5): owner's group, chain after the owner, group completion waits for chains; changed virtual resource → owner check.
- Rule 6 pipeline check (fail the compile, clear message).
- Orphans: replace "delete a virtual resource nobody lists" with "unused: not compiled, kept" (rule 3); keep the refcounts (`m_VirtualRefs`)
  where dependencies update.
- One-time migration at project load: move `Cache/Descriptors/<Type>/.../<guid>.desc` of every virtual resource to `Descriptors/` (keep Info).
- Tests: extend `smoke/test_virtual_resource_cleanup.py` (unused kept, not deleted) and add a no-editor test of the order (owner → chain →
  next group) if the scheduler can run without an editor; else a C++ unit test of the ordering function. Also `golden/test_impact.json` if a
  new test needs an impact mapping.

## Phase 2 — generators update instead of rewrite — DONE (2026-10-16, uncommitted)

What was built:
- Shared helper `dependencies/xresource_pipeline_v2/source/xresource_pipeline_virtual.h` (namespace `xresource_pipeline::virtual_rsc`): `WriteIfChanged`
  (moved from the material emitter, which still forwards to it), `owned_list` (`Virtual.txt` in the owner's descriptor folder: Load/Save/Contains,
  sorted so the same resources are the same text), `EmitDescriptor(Folder, Fresh, CopyOwned)` (create from Fresh; otherwise load and let `CopyOwned`
  copy only the generator's fields; write only when the text changed), `EmitInfo` (guid and the link to the owner are the generator's, the name and
  the rest are the user's once the Info exists).
- Material emitter (`xmaterial_instance_import_compiler.h`; new member `m_OwnerFolder`, callers in the static and skin compilers pass it): Texture: only
  `m_InputVariant`; Material Instance: the base material and the slots that still hold a texture the geometry made (`IsGenerated`: on the earlier
  `Virtual.txt`; with no list yet, a texture whose Info links an instance that links the geometry) - a slot the user pointed elsewhere stays. The
  instance has no tunable values today, so none is touched. `Emit()` writes the list.
- Font compiler: the atlas Texture (bitmap and MTSDF/SDF) updates only the input (+ `GenerateMips`/`MipCustomMinSize` for MTSDF/SDF: they follow the
  atlas size and the font's MipLevels); Info/name the user's; `SaveOwnedList()` writes the font's `Virtual.txt`. Pixel data stays in `Cache/Descriptors/..`.
- Skin compiler (pulled forward from Phase 4's "package edit survives a recompile"): the virtual Skeleton updates only `ImportAsset`, the Anim Package only
  `SkeletonRef` and the path of its first import source (clips stay); the skin writes one `Virtual.txt` with materials + skeleton + animations (the
  material emitter wrote its part first, the skin's list replaces it). Phase 4 keeps this when it replaces the two bools.
- Pickers never list a virtual resource: the tree tab does not splice virtual children in when it is a picker (`m_Browser.isPopup()`), the Search tab skips
  `library_db::IsVirtual` nodes in a picker, a virtual tile is not draggable, and `ResourceBrowserPopup` refuses a dropped or selected virtual resource
  (`library_mgr::IsVirtualResource`). The xgpu examples (E19-E24) keep their own copies of the picker code: untouched.
- `DescribeAsset` prints `Virtual: yes|no` (what the tests read).

Tests (all pass): `test_imported_materials.py` + 4 (texture edit and the name survive a recompile and are not rewritten; a slot that holds what the model
made follows the model, the old texture stays unused; a slot the user pointed elsewhere is kept; the list is written, and without it the slots still
follow), `test_imported_skeleton.py` + 1 (skeleton pre-transform survives, the package's skeleton is restored), `test_virtual_resource_cleanup.py` + 1
(`Virtual: yes` for generated resources, `no` for the owner). Not tested: the picker lists themselves (ImGui only, no command reads them).
Compilers rebuilt Debug + Release (xfont, xgeom_skin, xgeom_static), editor Debug.

Original list:


- Shared helper (e.g. in `xresource_pipeline_v2`, or next to `WriteIfChanged`): read/write the owned list (`Virtual.txt`), load an existing
  virtual descriptor, let the generator update its owned fields, write if changed.
- Material import emitter: rule 3's Material Instance and Texture fields; `duplicate_cmd` reads from `Descriptors/`.
- Font compiler: its atlas Texture descriptor in `Descriptors/`, its pixel data stays in the cache.
- Pickers never list virtual resources (rule 6): find the picker filter in `xresource_editor_inspector_pickers.h` / the asset browser.
- Tests: `smoke/test_imported_materials.py` — paths move to `Descriptors/`; add: edit a generated instance's value, recompile, edit kept;
  change the model's texture of an untouched slot, recompile, slot follows; a slot with the user's texture is kept.

## Phase 3 — "Remove unused imported resources" — DONE (2026-10-16, uncommitted)

- `library_mgr::UnusedVirtualsOf(library, owner)`: walks the owner's children (the Info parent links) and returns the ones nothing lists
  (`virtual_chain::IsListed`), parents first. `library_mgr::LoadVirtualDescriptor` loads a descriptor folder into the library (what an undo needs).
- `RemoveUnusedImportedResources` (new `source/Tools/Editor/xeditor_virtual_resources.h`, `remove_unused_cmd`): Redo removes them with the existing
  `RemoveVirtualResource` (descriptor folder, compiled data, log), deepest first; "nothing is unused" is an error (no history entry). The undo backup is every
  file of each folder (guid, folder, names and bytes), Undo writes them back and loads them. Registered in `session_part` (static geom and skin through
  `xmaterial_instance_import_editor.h`) and in the font session.
- UI: `unused_button` above the Description inspector of the three editors (count refreshed every second, modal confirmation: they may hold edits).
  The asset browser draws an unused virtual resource dimmed (`m_bUnused` in the tree tab's right panel) - the UI part of rule 3 left open in Phase 1.
- Docs: `editor.md` of xgeom_static, xgeom_skin, xfont. Impact map: the new header maps to `test_virtual_resource_cleanup.py`.
- Tests (pass): `test_virtual_resource_cleanup.py` + 2: remove then undo gives the same files and children (instances and their textures), "nothing is
  unused" while in use; the font editor has the command, keeps its own atlas and leaves nothing else.
- Not covered: the button and the dimming (ImGui only); the skin editor's registration (shared `session_part`, compiled, not opened by a test).

Original list:


A command on the owner's editors (static geom, skin, font if it has one), undoable, listed in each plugin's `documentation/editor.md`.

## Phase 4 — skin: one flag, read-only references, AnimationRef in the resource

User decisions (do not offer choices):
- Replace `ImportAnimation{bSkeleton,bAnimations}` with **one bool `ImportSkeletonAndAnimation`**, placed **right after `ImportAsset`** in the
  descriptor's property list; on for new skins; the two existing skins in example.lionprj get it `0` (replace the two lines the current state
  added).
- On: `SkeletonRef` is **read-only** (always the generated skeleton), a new **`AnimationRef`** (xrsc::anim_package) row is **read-only** (the
  generated package; empty when the model has no clips — then warn, do not fail). Use xproperty dynamic flags (`member_dynamic_flags`, see
  `AllMeshesDetails` in `xgeom_skin_descriptor.h`). Off: `SkeletonRef` editable as before, `AnimationRef` hidden.
- Remove the SkeletonRef override arrow (`RegisterSkeletonRowLabel`, `m_SkeletonRowLabel` in `Editor/xgeom_skin_editor.h`): no overrides.
- The preview's `PreviewAnimRef` (`Editor/xgeom_skin_editor_preview.h` `render_settings`) is **read-only and set to the skin's AnimationRef**
  while the flag is on (replace `PreviewAnim()`'s fallback accordingly).
- The compiled GeomSkin stores `AnimationRef` next to `m_SkeletonRef` (`xgeom_skin.h` geom struct + its serializer, `xgeom_skin_xgpu_rsc_loader`,
  the compiler sets it at the `result.m_SkeletonRef` line). Format change: every skin recompiles; bump whatever version the serializer has.
- Clip settings (Loop, …) are edited on the generated Anim Package itself (works after phases 1–2). Animation events do not exist yet: out of
  scope.
- Update `plugins/xgeom_skin.plugin/documentation/editor.md` and `smoke/test_imported_skeleton.py` (single flag; the compiled skin carries the
  package guid; package edit survives a recompile).

## Building and testing (project rules)

- Compilers: MSBuild the plugin's `build/<plugin>_compiler.vs2022/<plugin>_compiler.sln`, Debug **and** Release (tests use Release).
- Editor: MSBuild `Build/xLION.vs2022/xLION.vcxproj` Debug. Never build `Cache/Script/.../Game.vcxproj` by hand.
- Run only the tests named above (`python -m pytest <file> -q` in `source/Editors/LevelEditor/smoke`); never the full suite; no other smoke
  tests unless asked. C++ unit tests of the change are fine.
- Live editor checks: `live.py` + `xcmd.py` (one editor, only one you started: check `live.py start` printed "live editor up"); screenshots with
  CaptureWindow + virtual input, never the real mouse.
