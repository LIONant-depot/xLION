# Skin bone palettes: hand-over (2026-10-19)

Read first: `documentation/Editors/skin_bone_palette_plan.md` (the decisions, plus "Implementation notes" at the end).

## Done and pushed (main)

| Repo | Commit | What |
|---|---|---|
| xGPU | fa6fe14 | static descriptor writes up to 16 buffers |
| xLIONRender | 340f8ac | BoneMap = set 1 binding 8 in the skin shaders and every skin pipeline |
| xgeom_skin.plugin | 0930f56 | format v4, compiler palettes, loader, preview bone buffer sizing, facts counts, `-SELFTEST` |
| xLION | b466d40 | plan notes, tests in `smoke/test_imported_skeleton.py` |

Verified: `xgeom_skin_compiler.exe -SELFTEST` passes; Walking.fbx compiles with an empty BoneMap, byte-identical twice; the Debug editor builds;
test_skin_import.py / test_imported_materials.py: 18 passed. One failure there, an ImGui assert in `ximgui::toolbar::RenderToolbarHost`
(skin editor camera toolbar, array subscript), is in code this work did not touch: check whether it fails without it too.

## Left to do

1. **Make lady.fbx compile** (`example.lionprj/Assets/LadyNJ/lady.fbx`). Its clusters are fine (12 base-offset, 14 palette clusters, 335 BoneMap
   entries), then the skin compiler dies writing `Details.txt` (`onCompile`, `xproperty::sprop::serializer::Stream(File, m_Details, C)`):
   xproperty's collector builds each property path in `std::array<char, 256>` (`dependencies/xproperty/source/sprop/property_sprop_collector.h`)
   and the model's assimp node tree (`details::m_RootNode`, `xgeom_skin_details.h`) is far deeper (4096 also failed).

   **The user's design (do not grow xproperty):** the compiler sets a flag in Details when the node tree is too large for xproperty, and saves
   the tree in its own compact format at the end of Details.txt instead of through xproperty; the skin descriptor editor reads the flag and that
   section, so it neither crashes nor loses the tree. Confirm the format with the user before building (sync-before-big-tasks).
   Test: `test_a_952_bone_rig_compiles_with_palettes_deterministically` in `test_imported_skeleton.py` (currently failing) must pass.
2. **Live check:** lady.fbx renders correctly in the skin editor, bind pose and an animation playing (the palette path on the GPU has not run
   on a real model yet). Use live.py / CaptureWindow (see the memory notes).
3. Plan items not done: skeleton-LOD test (LODs are bone counts, matrices stay full-index: no remap needed, document if it changes);
   performance measurements (plan's Performance section).

## Gotchas

- Build the Release compiler: MSBuild `plugins/xgeom_skin.plugin/build/xgeom_skin_compiler.vs2022/xgeom_skin_compiler.vcxproj`.
- Symbols for a Release crash: set env `_CL_=/Zi` and `_LINK_=/DEBUG`, rebuild, run under cdb; rebuild without them afterwards.
- The xskeleton compiler exe was stale (older than its source): rebuild it if the PreTransform test fails on `Joints N Size`.
