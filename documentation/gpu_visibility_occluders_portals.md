# GPU visibility: occluder meshes, portals and cells (design, not built)

Status: design for review. Nothing is built until Tomas says go.

Starting point: GPU cluster culling (documentation/gpu_cluster_culling.md). The main view's clusters are culled on the GPU against the
frustum and against a Hi-Z pyramid made from the depth prepass, in two passes, with an adaptive skip. What is missing:
- **Occluders for views without a depth prepass:** shadow views, the first frame after a camera cut, reflection and probe views.
- **Occluders that are cheap stand-ins:** for geometry that occludes badly (foliage, fences, very dense meshes).
- **A coarse, structural answer:** "the rooms you cannot see are not drawn", before anything is rasterized.

## What the others do

| Engine | Occluders | Portals / cells | Where it runs | Shadows | Dynamic (doors) | Authoring |
|---|---|---|---|---|---|---|
| CryEngine (Cry3DEngine/VisAreas.h, VisAreaMan.cpp) | Occluder areas/planes, plus a software coverage buffer (CCullBuffer) of the occluders and the vis areas' bounds | **VisAreas** (convex prisms: a polygon and a height) joined by **portals** (thin VisAreas). PreRender walks the connections, clipping a camera to each portal (UpdatePortalCameraPlanes), and decides whether the outdoors and the sky are visible through it | CPU | An area "affected by outside lights" or not; lights are culled by area | Portals turn on and off (m_bActive, e_Portals) | Designers draw the shapes in Sandbox; IgnoreGI/IgnoreOutdoorAO per area |
| id Tech 4 (Quake 4: renderer/renderworld_portals.cpp) | None (the portals are the system) | **Areas** made by the map compiler from the BSP, **portals** as windings between them. FloodViewThroughArea_r crops a screen rectangle portal by portal; entities and lights are referenced per area | CPU | Lights also flow through portals (FlowLightThroughPortals) - a light's view is culled the same way | **blockingBits** on a portal: a door closes view, air or sound (SetPortalState) | Areaportal brushes in the map; compiled |
| Unity / Umbra | Occluders and occludees baked from static geometry | Umbra bakes **cells and portals automatically** from voxelized static geometry ("smallest occluder", "smallest hole") | CPU at run time, offline bake | Umbra culls shadow casters against the camera's visibility | Occlusion areas, portals that open and close (OcclusionPortal) | Automatic; a few flags and volumes |
| Unreal | HZB occlusion of the previous frame, occlusion queries, software occlusion on mobile; Nanite: two passes on its HZB (as ours) | **Precomputed visibility**: cells along the play area or camera tracks (PrecomputedVisibilityVolume), baked visible sets; **HLOD**: far clusters of actors become one proxy mesh | GPU (HZB), CPU (precomputed tables) | Virtual shadow maps cull per page against their own HZB | Precomputed: none (static only) | Volumes; HLOD layers with a batching policy per component |
| Godot 4 (scene/3d/occluder_instance_3d.h, modules/raycast) | **OccluderInstance3D**: boxes, quads, spheres, polygons, or baked from the meshes (bake mask, simplification distance), rasterized on the CPU with Embree into a small HZB | None | CPU | Not culled by occluders | Occluders move | Bake button and gizmo in the editor |
| o3de (Atom: OcclusionCullingPlane, RPI Culling.cpp) | **Occlusion culling planes** (entities: a quad, transform), drawn into Intel's Masked Occlusion Culling buffer, the nearest first | None | CPU | Frustum only | Planes move or turn off | Component with a visualization |

What they agree on:
1. Occluders are low-poly and placed or baked conservatively, never the render meshes. Godot's bake simplifies the meshes, and
   o3de uses quads.
2. Portals and cells pay off indoors. All of them make cells either by hand (CryEngine, id) or automatically by voxelizing (Umbra).
3. Doors are portal state, not geometry.
4. Shadows are culled by the light's own view: through portals (id), by area (Cry), or against the camera's visibility (Umbra).

## Proposal

### 1. Occluder meshes (first: small, helps every view)

- **Component:** `Occluder`, a low-poly mesh (box, quad, or a compiled simplified mesh) with a transform. Like Godot's, it has a
  bake that builds it from the entity's meshes with a simplification distance, run in the xgeom_static compiler as an optional
  output ("occluder LOD"). The bake makes **interior** shapes (walls shrunk, never grown) so the occluder is conservative.
- **Draw:** the occluders' depth goes into the view's depth **before pass 1**, with a depth-only pipeline, no material and no
  prepass record. For the main view this seeds the Hi-Z on a camera cut. The first frame after a cut then hides correctly instead
  of drawing everything in pass 2.
- **Shadow views:** today they cull by frustum only. Per shadow tile, the occluders are drawn into a small depth target (tiles are
  cheap: a few thousand triangles), a Hi-Z is made of it (the same single-pass downsampler), and the casters' clusters are
  culled against it with the same cull shader (a light's L2C instead of the camera's). Casters that cannot reach a visible
  receiver are a later step (Umbra's idea): the camera's visible boxes extruded along the light direction.
- **Cost:** components, a compiler option, one more depth draw and pyramid per view that uses it. Nothing changes in the cull
  shader.

### 2. Portals and cells (when indoor levels need it)

- **Data:**
  - **Cell:** a convex volume, like CryEngine's prism or a box set.
  - **Portal:** a convex polygon joining two cells, with a state: open, closed, or closed to view only.
  - Every entity (later every cluster, by its box) is assigned to the cells it overlaps when the level is compiled. Dynamic
    entities are assigned by their box each frame.
- **Per view (CPU, small):**
  1. Find the camera's cell.
  2. Walk the portals (id's FloodViewThroughArea_r), cropping a screen rectangle per portal and stopping at closed portals.
  3. The output is the set of reached cells with each one's screen rectangle: a few hundred bytes a frame, uploaded with the
     candidates.
- **GPU:** each candidate carries its cell. The cull shader drops a cluster whose cell was not reached, or whose screen box is
  outside its cell's rectangle, before the Hi-Z test. Outdoors (no cell) everything passes.
- **Doors:** a portal's state is a property of a Door component, as id's blockingBits. A closed door blocks the walk.
- **Lights:** a light reaches the cells its own walk reaches (id's FlowLightThroughPortals). Point and spot shadows then skip
  cells the light cannot reach.

### 3. Cells as more than visibility

Cells are a partition of the level, which other systems need too:
- **GI sections:** the GI already splits over-cap geometry into sections (one GI instance and BVH each: the 2026-10-24 sections decision). A cell is a natural section.
  - Surfels and probes are per cell.
  - Light does not leak through walls between cells unless their portal is open.
  - A closed door can stop GI transport (CryEngine's IgnoreGI per area, made dynamic).
- **Streaming units:** a cell, with its portals' neighbours, is what has to be resident around the camera. The streaming lane
  (xGPU uploads) can load by cell.
- **Audio occlusion and AI:** id uses the same portals for sound (PS_BLOCK_AIR). Our portal state can carry bits for other
  systems later.

### 4. Editor authoring

- **Cell:**
  - drawn as a box or extruded polygon (CryEngine's style) with a gizmo;
  - "Fit to selection" makes a cell from the selected entities' bounds;
  - an automatic pass (Umbra's style) can come later, from a voxelization of the static geometry.
- **Portal:** a quad placed between two cells, which snaps to the shared face. The inspector shows the cells it joins and its
  state.
- **Occluder:** a component with a shape (box, quad, mesh) and a Bake button (from the entity's meshes, simplification distance).
  Debug view: the occluders over the scene.
- **Debug views** (the toolbar's culling menu):
  - the camera's cell;
  - the portals walked, with their screen rectangles;
  - cells not reached, greyed out;
  - occluders drawn in a color;
  - freeze (already there) to fly around and inspect.

## Order of work (proposed)

1. Occluder component + depth draw before pass 1 (main view). Test: a camera cut behind a wall hides on its first frame.
2. Occluders for shadow tiles (Hi-Z per tile, the casters culled). Measure: shadow pass time on the Bistro with the sun low.
3. Occluder bake in the xgeom_static compiler (an optional output; it marks every GeomStatic stale once).
4. Cells and portals: components, the per-view walk, the cell test in the cull shader, doors. Test level: the Police station with
   rooms.
5. Cells as GI sections and streaming units: separate designs once 4 is in.

## Open questions for Tomas

- Should cells be authored (CryEngine and id style, exact) or computed (Umbra style, less work for the designer but heavy to
  build)? I suggest authored first, with automatic cells later.
- Occluder bake: in the geometry compiler (an extra output, compiled with the asset), or a separate resource type an Occluder
  component references?
- Should a portal's state be part of the save data (a door's state in the level)? Then doors also need an undo-able state.
