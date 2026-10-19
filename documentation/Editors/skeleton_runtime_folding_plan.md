# Skeleton: runtime joints, source nodes kept for the editor

Status: first version built 2026-10-19 (agreed: whole chains kept, synthetic root over a group, bake at the clip rate, blending validation later). Not yet: user keep/fold overrides in the descriptor, the "Show source nodes" toggle.

## The problem

An FBX hierarchy carries more than the rig's joints: assimp's pivot helpers (`$AssimpFbx$`), group nodes
(`RootNode`, `ArtPartsDataResource_2684_16` with ~290 children), mesh nodes. Today every node becomes a runtime
bone: each costs an evaluation per frame and an animation channel, and the view draws fans out of group nodes.

## The decision: two layers

| Layer | What it holds | Who sees it |
|---|---|---|
| Runtime skeleton (compiled resource) | Only the joints, Unreal style | the game, the animation evaluator |
| Source record (`Details.txt`, editor only) | Every source node, its parent, its local transform, where it went | the skeleton editor, later the animation tools |

Nothing the user sees is invented: a runtime bone is real at runtime, a source node is shown as source only.

## Where the work happens

The manipulation of the hierarchy (folding, baking) lives in **xraw3d**, on its skeleton and animation data,
as a reusable operation. The importer (`xraw3d_assimp_import_v3.h`) stays a plain translation of what assimp
gives. The skeleton compiler calls the xraw3d operation and writes the source record.

## Which nodes are kept (the keep set)

Keep by purpose, not by weight or position alone:

1. Every node a mesh is bound to.
2. Every authored joint of an accepted skeleton branch, weighted or not: the CC forearm, physics, cloth and hair
   chains (the whole chain, not only its ends), end joints.
3. Every node something at runtime refers to: socket parent, IK target, physics reference, root-motion source,
   a user "keep" override in the descriptor.
4. The ancestors needed to connect the above.

Folded: assimp's `$AssimpFbx$` helpers, group nodes above the skeleton, and nodes a user marks "fold".
Where the source cannot tell an authored joint from a generic transform, the descriptor's keep/fold override
decides.

**Root**: the lowest common ancestor of the kept joints. Kept when it is a meaningful node (a joint, the
root-motion source); otherwise a synthetic runtime root takes its place and its transform is folded.

## Folding

For `Parent -> Folded -> Child` (column vectors): `L'_Child(t) = L_Folded(t) * L_Child(t)`; several folded
ancestors compose in hierarchy order. Inverse binds and joint indices are remapped, never recomputed.

A fold is a **compiler check**, not an assumption: it must reproduce every kept joint's global transform (and so
the skinning) within tolerance. When the composed transform does not fit translation / rotation / scale
(non-uniform scale with rotation makes shear), the node is kept instead and the log says why.

## Animation

Bake the evaluated result, not the keys: evaluate the source hierarchy at the bake samples, derive each kept
joint's local track relative to its new runtime parent (`L'_j(t) = G_p'(t)^-1 * G_j(t)`), encode and reduce it,
and compare against the source, between keys too. An unanimated child of an animated folded node gets a track.

Log: info "animated source node folded; motion baked into N runtime tracks"; warning on approximation, unusual
scale, bigger tracks, root-motion policy; error (or keep the node) past tolerance.

## The source record (Details.txt, editor only)

Per source node: stable id/path, original parent, original local transform, the runtime bone it maps to (or
"folded into ..."), the keep/fold reason, and references to its source animation and bake diagnostics. Enough
to rebuild the source hierarchy - including the animated one - for later tools.

## The editor

- Viewport default: runtime joints and runtime links only.
- "Show source nodes" (off by default): folded nodes as faint dashed markers and links, never as bones.
- Hierarchy: runtime bones as today; folded nodes greyed, labelled "Source only - folded at compile".
  Selecting one selects its source record, not a pretend bone.
- The tree scrolls to and opens down to a bone hovered or selected in the 3D view (done, 2026-10-19).

## Tests

- xraw3d unit tests of the fold: globals of kept joints preserved; shear case keeps the node; animated fold
  baked and compared between keys.
- Compiler: Walking.fbx (no helpers: nothing folded, byte-identical), the "Full Body with Shorts" rig
  (`ArtPartsDataResource` folded, the hair/cloth/face chains kept), lady.fbx.
- Editor: the source record loads; folded nodes greyed; the toggle draws them.

## Open points (to confirm before building)

1. The keep set above, including whole physics/cloth/hair chains. Agreed?
2. The root policy: synthetic runtime root when the common ancestor is only a group node?
3. Bake sampling rate: the clip's frame rate, or a fixed one (30 Hz)?
4. Blending/additive validation: in scope now, or after the first version?

## Intents (built 2026-10-19)

What a bone is FOR, beyond moving the skin: `xskeleton::intent` - Motion (root / trajectory), Facing, Look-at, IK target. Compiled into
3 bits of the bone's flags byte (no format change), so tools and the runtime find "the facing bone" without hard-coding names.

- Authored per bone in the skeleton descriptor (`bone::m_Intent`): **Auto** (default) follows `xskeleton::SuggestIntent` (common rig
  names: `*_Root`, `Trajectory`, `MTP_Global_*`, `MTP_Head_*`, `IK_*`, `MTP_*_Foot/Hand_*`); None or a specific intent is the user's.
- Skeleton editor: right click a bone > Intent > Auto (suggested: X) / None / Motion / Facing / Look-at / IK target (`SetBone -Intent`,
  undoable). The tree shows the intent's icon at the end of the row (dimmed while only suggested), spelled out on hover.
- A bone with an intent is always a runtime joint (`merge::KeepIntentBones`, used by every compiler that folds).
- Drawing is shared (`xskeleton_editor_view.h`: `BuildIntentGlyphs`, `DrawIntentIcon`, `IntentsFromFlags`) so the skin, animation and
  level editors draw the same glyphs: Motion a ground ring with an arrow, Facing an arrow on the bone's Y axis, Look-at an eye with a
  dashed ray, IK target a box. The 2D icon and the 3D glyph are the same shape.
- Next: a trail of the Motion bone's path while an animation plays; the Look-at ray from the head it drives; Socket as an intent.
