# Skin geometry: bone palettes for the clusters that need them

Status: proposal, 2026-10-19, revised after review. Nothing built yet.

## The problem

A skinned vertex stores each of its (up to 4) bones as a 7 bit offset from its cluster's base bone (`xgeom_skin::geom::vertex`, `m_Packed`).
The cluster's base bone is `cluster_data::m_PosScaleAndBaseBoneIndex.m_W`. So every triangle's bones must lie within 128 consecutive slots
of the skeleton's bone order.

Big rigs break that. `Assets/LadyNJ/lady.fbx` (952 bones) has a shoulder vertex weighted to `chestLower` (#231), `chestUpper` (#247),
`rCollar` (#404) and `rShldrBend` (#410): 179 slots apart. The compiler now stops with that error instead of crashing (commits `07a96f2`
xraw3d, `b012abf` xgeom_skin).

Reordering the skeleton cannot fix it. Bones must stay parents-first, so one arm's whole subtree (about 150 bones in this rig, with twist and
finger bones) always lands between the chest and the other arm. Two hierarchy orders were tried (depth first with the smaller subtrees first;
each bone's children grouped right after it): 178 and 179 apart. Both were reverted. The skeleton keeps its order: animation, masks and the
manifest depend on it.

## The decision

Two addressing modes, chosen per cluster at compile time. Both are normal representations; the palette is not an error path.

| Mode | When | Vertex bone | Extra data |
|---|---|---|---|
| Base offset (today) | the cluster's bones span at most 128 slots: `Max - Min <= 127` | `Base + Index` | none |
| Palette | anything wider, with at most 128 distinct bones | `BoneMap[PaletteStart + Index]` | the cluster's palette in the geometry's `BoneMap` |

The test for the base offset is the index **span**, not the number of distinct bones: bones 4, 5, 6 and 400 are four bones but span 396 slots
and need a palette.

What this costs: clusters using the base offset need no palette storage, and a geometry whose clusters all fit has an empty `BoneMap`
(Walking.fbx today). Every skin still carries the decode logic and one mode test per vertex.

This is the same local remapping Unreal uses (a bone map per section), except that contiguous clusters keep a storage-free encoding and only
the others pay for a map. The trade is a fixed ceiling of 4 influences and 128 bones per cluster, which keeps the vertex at 12 bytes.

What the change guarantees: no valid mesh is rejected because its triangles' bones span more than 128 positions in skeleton order. With four
influences, a triangle has at most 12 distinct bones, so it always fits a 128 entry palette. Meshes can still be rejected for other reasons
(bones missing from the skeleton, more than 65,536 bones, bad weights).

## Compiler (plugins/xgeom_skin.plugin/source/Compiler/xgeom_skin_compiler.cpp)

1. The modes are explicit inside the compiler; packing happens only when writing the cluster data:
   ```cpp
   enum class bone_addressing : std::uint8_t { BASE_OFFSET, PALETTE };
   struct cluster_bones
   {
       bone_addressing             m_Mode;
       std::int32_t                m_BaseBone;     // BASE_OFFSET
       std::vector<std::uint16_t>  m_Palette;      // PALETTE: skeleton bone indices, ascending
   };
   ```
2. Cluster policy in `RecurseClusterSplit`, simplest first:
   1. the cluster fits the base offset: base offset;
   2. otherwise, its distinct bones fit a palette (at most 128): palette, **without splitting**;
   3. otherwise: split, then apply the same policy to each half.

   Splitting only to stay on the base offset is not done. A split costs cluster data, duplicated seam vertices, culling and draw work, and
   smaller clusters; a palette costs at most four 2 byte reads per vertex and a few hundred bytes. A cost model that splits when it pays can
   come later, from measurements (see Performance).
3. Palettes are deterministic: each palette is in ascending skeleton bone order, and palettes are written to `BoneMap` in cluster order.
   A palette identical to one already written reuses its start (exact match only, in order: no hash-map iteration order reaches the output).
   The same input gives the same binary.
4. Vertex ownership: packed skin vertices belong to exactly one cluster. This is already true: `RecurseClusterSplit` remaps every cluster's
   vertices into its own range of the output (`old_to_new`), so a source vertex shared by two clusters is written twice. A vertex packs its
   bones for its own cluster's mode (offset from the base, or index into the palette). A test pins this invariant (see Tests).
5. Remove the two span hard errors: the per-vertex check in `ConvertToCompilerMesh` and the per-triangle throw in `RecurseClusterSplit`.
   Keep the bone-naming diagnostic for the one case left, a cluster needing more than 128 distinct bones, which splitting always resolves.
6. Checks, with checked arithmetic:
   - the skeleton has at most 65,536 bones (palette entries are `uint16`), checked before any narrowing;
   - every influence: `Base + Index < nBones` (base offset) or `Index < Palette.size()` and `Palette[Index] < nBones` (palette);
   - `PaletteStart + PaletteSize <= nBoneMap`, and `PaletteStart` fits the packed field's payload.
7. Cases already defined:
   - unweighted vertices: the importer gives them their mesh's node bone (`07a96f2`);
   - zero-weight influences: dropped by CleanWeights before addressing; they never enter a palette;
   - duplicate influences (the same bone twice on a vertex): merged by summing their weights before CleanWeights (to add if not already so);
   - a bone missing from the skeleton: already an error ("A skin vertex references bone which is not found").

## Format (plugins/xgeom_skin.plugin/source/xgeom_skin.h)

- `cluster_data` stays 48 bytes. Its second `vec4` (`m_PosTrasnlationAndWPADDING`, W unused today) becomes a struct whose fourth member is
  a real integer, so nothing ever handles it as a float:
  ```cpp
  struct pos_translation_and_bones
  {
      float           m_X, m_Y, m_Z;          // the cluster's position translation
      std::uint32_t   m_BoneAddressing;       // bits 31..30: mode (0 BASE_OFFSET, 1 PALETTE); bits 29..0: payload
  };
  ```
  - BASE_OFFSET: payload 0; the base bone stays in `m_PosScaleAndBaseBoneIndex.m_W` as today.
  - PALETTE: payload = the palette's start in `BoneMap`.
  - Modes 2 and 3 are reserved and rejected by the loader. They leave room for later formats (a shared palette, wider indices).

  `GetBoneAddressing()` and `SetBoneAddressing()` are the only access. A comment on the struct documents the layout. The serializer writes the
  integer as an integer.
- New geometry-wide array: `std::uint16_t* m_pBoneMap; std::uint32_t m_nBoneMap;` (the palettes). `m_nBoneMap == 0` means no cluster may
  use the palette mode.
- `xserializer_version_v` 3 -> 4. Every compiled skin recompiles anyway (the compiler is newer than the resources).
- Loader (`xgeom_skin_xgpu_rsc_loader.cpp`):
  - one more storage buffer for the bone map. A skin without palettes binds one shared, immutable dummy buffer (created once, not one per
    skin), so the descriptor set layout never changes. The dummy entry is never addressed.
  - validation before the upload (always on in Debug): mode tag known, palette mode only with `m_nBoneMap > 0`, every palette range inside
    `BoneMap`, every `BoneMap` entry inside the skeleton.

## Bone matrices: the whole chain

```
vertex 7 bit index
  -> Base + index (base offset)  or  BoneMap[PaletteStart + index] (palette)
  -> full skeleton bone index
  -> the bone matrix array, indexed by full skeleton index
```

To verify and fix during the work:
- **The matrix array must hold every bone of the skeleton.** The skin editor's preview uploads at most `g_MaxBonesSupported = 256`
  matrices (`xgeom_skin_editor_preview.h`): bone #404 of the lady rig would read past what was uploaded. Size the buffer from the skeleton.
  Check xLIONRender's skinned path and the thumbnails the same way.
- **Skeleton LODs:** if a LOD uploads a compact matrix array instead of a full-index one, add the remap (full index -> LOD index, a removed bone
  -> its surviving ancestor) where the matrices are prepared, not in the palette. Document whichever is true.

## Shaders

The decode is in `dependencies/xLIONRender/src/shaders/xgeom_skin_mb_skinning.vert` (`ComputeSkinMatrix(lo32, hi16, baseBoneIndex, ...)`).
The copies in `plugins/xgeom_skin.plugin/source/runtime/` (`xgeom_skin_mb_skinning.vert`, `xgeom_skin_mb_clusters.vert`) must match it,
and the editor's wireframe and debug-normal shaders include the runtime's input files.

- Each vertex invocation reads its cluster's addressing once and branches once, outside the influence loop. All four bone indices are decoded
  by the chosen path:
  ```glsl
  if (Mode == PALETTE) DecodePaletteBones(...);     // BoneMap[Start + index_i]
  else                 DecodeBaseOffsetBones(...);  // Base + index_i
  ```
  Never a test per influence. The condition is the same for every vertex of a cluster.
- Whether a GPU wave can hold vertices of several clusters depends on how xLIONRender draws (vertex order, indexed reuse, draws vs dispatches).
  No sorting of clusters by mode unless profiling shows divergence: sorting could cost locality, culling or material order.
- `BoneMap` is read as `uint16` (or the nearest the shader language allows). Packed 32-bit pairs or aligned palettes only after looking at the
  generated code and measuring.

## Editor

The skin editor's facts inspector (Skinning group) shows: base-offset clusters, palette clusters, `BoneMap` entries, unique palettes, the largest
palette, and the `BoneMap` bytes. A later debug view could color clusters by mode.

## Tests

Headless, in `source/Editors/LevelEditor/smoke/test_imported_skeleton.py` (compile and inspect the output), plus C++ unit tests for the packing:
- **Models:** lady.fbx compiles and logs its palette clusters and `BoneMap` size; Walking.fbx compiles with no palette clusters.
- **Determinism:** the same input compiled twice gives byte-identical output.
- **Boundaries:** span 126 and 127 -> base offset; span 128 -> palette; 127 and 128 distinct bones -> one palette; 129 -> split.
- **Mixed geometry:** one geometry with base-offset clusters and palette clusters of different sizes; the palettes do not all start at 0
  (for example at 0, 4 and 17), so a shader ignoring the start is caught.
- **Ownership:** a source vertex on a seam between a base-offset cluster and a palette cluster decodes to the same bones in both.
- **Packed field round trip,** through the whole serialization: payloads 0, 1, 2, 127, 128, 65,535 and the largest valid start.
- **Corrupt resources** (loader validation): palette start outside `BoneMap`, index outside its palette, entry outside the skeleton, a reserved
  mode, a palette mode with an empty `BoneMap`.
- **CPU reference:** for sampled vertices, the decoded bone (`Base + index` or `BoneMap[Start + index]`) equals the original skeleton bone the
  importer gave it.
- **Skeleton LOD:** a palette that references a bone a LOD removes reaches the right surviving ancestor (once the LOD contract is known).
- **Live:** lady.fbx renders correctly in the skin editor, in the bind pose and while an animation plays.
- The existing skin tests keep passing (`test_imported_skeleton.py`, `test_imported_materials.py`, `test_skin_import.py`).

## Performance (after it works)

Measure, on the lady model and a small rig: all base offset, mixed, all palette (forced), split aggressively to stay on the base offset, palettes
unsplit. Compare GPU skinning time, cluster and draw counts, vertex count after duplication, resource size. That decides whether the policy
ever needs a splitting cost model.

## Settled points

1. Palette size: 128 entries. The vertex keeps its 7 bit indices; no 8 or 16 bit vertex format until an asset needs one.
2. Policy: base offset if it fits, otherwise palette if it fits, otherwise split. A cost model only if measurements ask for one.
3. Facts inspector: yes, the counts above.
