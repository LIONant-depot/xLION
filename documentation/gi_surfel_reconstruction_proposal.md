# GI surfel reconstruction: proposal v2.1 (after external review)

2026-10-28. v1 was reviewed externally; the verdict was "do not implement as written". v2 adopts the review's points except where
sec. 8 argues otherwise, keeps Tomas's firm requirement (surfel density independent of faces), and moves simplified shapes to
addressing only. v2 was approved for implementation experiments with no architectural rewrite; v2.1 folds in its corrections
(marked "v2.1:" in place; the work order in sec. 9 replaces v2's stage order). Still a proposal; no code. Code referenced: `R/shaders/xlionrender_surfel_gi.glsl`,
`R/features/gi/xlionrender_surfel_gi.h` (Bake / Candidates, BuildReadGridAt, BuildNeighbors / SameLayer, UpdateShown / PassAt,
ReadPoint, CompileTransport), `R/shaders/xlionrender_gi_pass_common.glsl` (the hit read), `R/features/gi/xlionrender_surfel_gi_gpu.h`,
`R/shaders/xlionrender_environment.glsl`. Sec. 9 is the changelog from v1.

## 1. What the review found in today's system (checked against the code)

| Review rule | Today's code | Status |
|---|---|---|
| Connectivity must allow exactly zero across incompatible sides | The pixel read cuts at cos < 0.5 and the lists are per part (a wall across a cell splits the floor): zero is possible. But the three terms that decide it (normal cut, plane weight, moments) are proxies, and the filter uses a fourth (SameLayer) | Partly met, by accident of the cuts; the structure is not declared |
| Three-lobe coefficients from differently oriented frames must not be averaged component-wise | `UpdateShown`'s `PassAt` sums neighbours' `basis` arrays component-wise (`a0 += B[0].x * w ...`), each in its own `BasisDirs(N_s)` frame; the GPU filter (`xlionrender_gi_filter_comp.glsl`) mirrors it. Neighbours pass at cos >= 0.8 (frames up to 37 deg apart), and `BasisDirs` picks its tangent axis by `abs(N.x) < 0.9`: the frame *flips* across that threshold between two near-identical normals | **Violated.** The read itself is right: `GIBasisRead` evaluates each surfel in the query direction, then blends. The filter is the only place. v2.1: that it causes the faint patches left on the spheres after the SameLayer fix is a *hypothesis*, to be reproduced with synthetic directional data first (work order step 1) |
| Solver reads must not consume display-filtered state | CPU `ReadPoint` reads `I.m_E` (the solver's); the GPU hit read `GV(GD[R + 2u] + 3 sl)` is the instance's E set by `SetGPUState`, a scalar irradiance per surfel, never the lobes and never `m_Shown`. The filter writes only the renderer's ring | Met. Not protected by a test: add one (sec. 7, test 7) |
| Changing the reconstruction changes the transport operator | `CompileTransport` captures the read's normalized weights per hit (`m_pReadCapture`) into T; its comment says so ("once the reads' weights are fixed"). Validity already changes at run time without recompiling (known: "transport-valid with current source input") | Met in design, not enforced: no revision tag ties links to the reconstruction's definition |
| Area weights a_s against density bias | None. Harmless while every surfel of a mesh has one radius; wrong at seams between instances of different r (ghost surfels of another mesh) and at the level switch (a level-1 read weighs by the child's reach and lights by the parent) | Missing |
| "Unsupported" is several states | `GIQueryResult.bSupported` conflates: off the grid, empty part, all weights zero (out of reach / facing away / corners), all validity zero (buried or not yet initialized), not resident (a ghost missing) | Conflated; `SurfelGIWhyUnsupported` separates the first three for debug only |
| Density must not follow faces | `Candidates`: 4 per r^2 of area plus >= 1 per r/2 of edge plus a floor of 1 per triangle; Poisson in the candidate's own plane; `Density SPLIT_TRIANGLES` retessellates for the GI; `m_VertSurfels` keys the read by vertices | **Violated** (Tomas's requirement) |
| Hard/soft normal terms | `smoothstep(0.5, 0.75, c)` after the cut; `GIVisibility`'s plane weight; both continuous but neither declared as side separation | Heuristics, see v1's inventory (kept in sec. 9 for reference) |

**Interim SameLayer fix (mean normal + chord sag), is it consistent with v2?** `BuildNeighbors` first requires cos(n_A, n_B) >= 0.8,
so opposite sides (cos = -1) and creases (cos = 0) never reach SameLayer: no cross-side blending is introduced. The mean-normal plane
test is exact for spheres and cylinders (convex or concave: two points of a cylinder's interior are in their mean-normal plane too),
an approximation for saddles. The sag lift h + sag is 0 for coplanar surfels (unchanged behaviour) and at most ~0.41 r (two surfels
2r apart at 90 deg), so on a strongly curved surface the lifted chord can clear a small occluder up to that height that it would have
hit before - a bounded, rare over-connection, never across sides. Verdict: consistent as an interim; it is a geometric test standing
in for the declared side-id + chart adjacency of sec. 4, and retires with stage 4. Test 6p (37 of 103 sphere surfels without a
neighbour before, 0 after) is its gate; the faint patches that remain are not SameLayer's - the filter's frame handling is the
leading hypothesis (sec. 5), not a finding.

## 2. The three decisions, kept apart (review point 2)

1. **Sampling density**: world-space, area-proportional, independent of tessellation (the firm requirement; sec. 3).
2. **Surface attachment**: every sample has a physical anchor on the real surface, with a side (sec. 3).
3. **Addressing**: how a pixel or a hit finds its stencil in constant time (sec. 4). Simplified shapes live here and only here.

v1 fused 1 and 3 into convex proxies and let 2 go; the review is right that a proxy point can be inside the object, outside a
recess, across a hole or on the wrong side of a thin wall, that hull-vs-vertex tests certify nothing, and that transport lost to a
proxy (recess colour, light through a doorway, a small emitter, interreflection) is not something AO can give back. v2 simplifies
addressing aggressively and simplifies transport only under a separately measured contract (stage 6).

## 3. Placement: world density on real anchors

- **Candidates**: a jittered area sampling of every triangle at ~4 per r^2 of its area (a big triangle gets many, a tiny one a
  fractional chance proportional to its area: no floor of one, no edge rule). Thin features are not oversampled; coverage validation
  below catches what sampling misses.
- **Thinning**: Poisson-disc elimination at world spacing r *within compatible sheets*: a kept sample rejects a candidate only if
  within r, same side (sec. 4's side id, or until then: cos >= 0.8 and the mean-normal plane test) and in sight. Different sides
  never thin each other (today's rule (c)/(d) kept, re-stated on sides).
- **Coverage validation**: after thinning, every triangle's area is tested for a kept sample within r on its side (sample points at
  r/4); uncovered area inserts a sample at its own anchor. This replaces `PatchDefects` and `m_EmptyParts`. The review is right that
  Poisson spacing alone is not maximal coverage; the validation step makes coverage a checked property. v2.1: sampling at r/4 is
  evidence, not a bound, unless each validation point is required within r - delta of a sample with delta >= the sampling spacing
  (then every surface point between validation points is within r); the validation uses the same side, cut and sight rules as the
  thinning (a point across a wall's cut or a hole does not count as covered), respects narrow parts (a strip thinner than the
  spacing gets at least its medial points), and the triangle loop allocates per block of triangles, never per tiny triangle (the
  Bistro's 2.8M).
- **Anchor** per sample: position on the real surface, geometric normal, a tangent frame (sec. 5 fixes its continuity), side id,
  support scale h (= 2r of its level), material footprint (the triangle set within r on its side, for capture and emission), and a
  sampled ray-origin set (today's `BuildOrigins`: up to 7 mesh points within r/2 on the same side - kept, re-stated: origins are
  anchors, never proxy points; review point 5).
- **Material and emission over a footprint**: the surfel's albedo is the area mean of the per-triangle captures in its footprint;
  emission is *not* averaged. v2.1: one authoritative emission representation, keyed by a stable identity (the capture's triangle id
  within its cluster, surviving retessellation of neighbours and re-spacing of surfels); footprints *reference* emitters, they never
  own their power, so no emitter is counted twice or lost when footprints change. Test 9 varies tessellation, surfel spacing, texture
  resolution and the emitter's position relative to footprint boundaries.
- **Gate (stage 2)**: retessellating an unchanged surface (the dense vs sparse room of gi_render, Cornell at two tessellations) must
  not change the surfel count by more than the Poisson noise (~5 %) nor the lit result beyond the reference's noise; coverage
  validation reports zero uncovered area. `SPLIT_TRIANGLES` and the vertex-keyed read go when stage 3 lands.

## 4. Addressing: charts, stencils, barriers

**Charts.** A chart is a small connected region of one side of the surface with 2D coordinates and an explicit boundary: planes
(a wall face: a planar chart), cylinders and capsules (a column, a pipe) and generic triangle fans (a chart that is a cluster's
triangles with a local parametrization, which every cluster can be as a fallback). Built per cluster group at bake under a
*coordinate* error bound (the chart's coordinates must be a bijection onto its triangles, no folding), not a lighting bound. A box
wall's two faces are two charts; a doorway cuts a wall chart in two charts with no adjacency across the opening's edge. A hull or box
may be used to *find* the chart (a cluster -> chart table does it in constant time anyway), never as the lighting domain.

**Stencil per chart cell.** Each chart carries a small cell grid in its coordinates (the per-face 2D grid v1 wanted, now per chart);
each cell stores a bounded stencil: the surfels whose support intersects the cell on this chart and on its adjacent charts through
declared connectors, each with a quantized chi. Lookup: triangle -> chart (table) -> coordinates -> cell -> stencil. No patch scoring,
no plane search. The hash grid, patches, parts and corner fractions of `BuildReadGridAt` become this. v2.1, **continuity as a
construction invariant**: at a shared cell edge every sample with nonzero weight on the edge appears in both cells' stencils (the
stencil is "support intersects the cell", never "the nearest K"); shared boundary data (chi at the edge) is stored once and read by
both; a cell whose stencil overflows its bound is split, and the build records occupancy and overflow counts per chart. Connector
distance: d(x, s) = min over the connector boundary z of [d_A(x, z) + d_B(z, s)], evaluated the same way from both sides (an analytic
unfolding where the two charts are planar or developable, a precomputed boundary mapping otherwise), so a stencil read from either
chart gives the same weight.

**Reconstruction** at a point x (chart coordinates u, normal n):

    E_hat(x, n) = sum_s a_s phi(d_s / h_s) chi_s(x) E_s(n) / sum_s a_s phi(d_s / h_s) chi_s(x)
    phi(q) = (1 - q)^4 (4q + 1) for q < 1 (Wendland C2; phi(1/2) = 3/16), d_s = the chart-aware distance (in-chart: the chart's metric;
    across a connector: the sum of the two in-chart distances), a_s = the area the sample represents (its Voronoi area on its side,
    baked), chi_s in {0} U [chi_min, 1] with hard zero across unrelated or opposing sheets.

What this fixes and what it does not: phi'(0) = 0 removes the per-sample cusps (Shepard's peaks); normalization reproduces constants
(a flat field reads flat whatever the sample pattern) and does *not* reproduce gradients (the review is right: Shepard is zeroth
order; a gradient across a stencil is biased toward the denser side unless a_s corrects the density, which is why a_s is there;
v2.1: a_s removes the density preference but does not make Shepard first-order, so a synthetic linear-field test measures the
remaining gradient bias at density transitions). v2.1, area vs LOD: parent and child must not both own the same area - at the level
transition the fine and coarse representations take lambda_fine + lambda_coarse = 1 of the point's weight, each level normalized on
its own (repeated representations of one surface are a different problem from adjoining surfaces, and are not blended by a_s); the
cheap chart-cell area (the cell area divided among its samples) is benchmarked before any exact Voronoi area is built.
The pipeline is not C2: chart boundaries, stencil changes, LOD and quantized chi are all C0 at best; the claim is only that no term
*within* a stencil has a cusp, and the tests (sec. 7, 6 and 8) measure the remaining seams instead of asserting them away.
Variance reduction is measured, not computed (samples are correlated through the transport: Var = sum alpha_s alpha_t Cov_st).

**Barriers and connectors (review points 1 and 7).** chi is declared, not inferred:
- Within a chart: chi = 1 *unless a static scene cut crosses it*. v2.1: a non-folding map gives addressing, not visibility - a floor
  chart may run under the wall that separates two rooms. Chart identity establishes correspondence; the reconstruction barriers must
  also encode the scene's cuts, so today's "a wall across the cell splits the floor" information (the parts of `BuildReadGridAt`,
  built from lifted-chord occlusion between sample points) is kept as per-cell cut edges inside the chart, and chi = 0 across a cut.
- Across an adjacency (two charts sharing a boundary on the same side: a wall face and its return, a floor and the next floor tile,
  the sphere's two hemispherical charts): chi = 1 through the boundary, distances continue; this is what makes a curved object one
  surface (the sphere grid) and a modular corridor seamless (ghosts of the neighbour instance's chart).
- Across a crease (floor to wall): no adjacency. Each reads its own; the two exchange light through the solver, not through blending
  (the review's "two surfaces exchanging light does not mean their samples should be blended").
- Opposing sides (a thin wall's two faces), unrelated sheets (blinds and the frame behind): chi = 0, hard. No g(c) floor: v1's
  wrap-shading floor of 0.05 across sides is 4.5 % of an HDR room through a wall; it is gone.
- Overlapping charts of one side (a chart ends where another begins without a clean shared boundary, a cluster fan next to a plane):
  a *connector* record with the overlap's coordinate transform and chi = 1 inside the overlap, so the stencil continues.
- Baked visibility only where needed: two same-side charts separated by a gap (blind slats; a doorway's two jambs) carry a
  per-stencil-entry chi in [0, 1] from line-of-sight fractions (today's corner fractions, per entry, C1-interpolated), never a
  per-pair scalar: a doorway spreads light only where the stencil entries see through it.

**A soft normal term?** None across sides (barriers do that). Within one chart the geometric normal varies smoothly, and E_s(n) is
evaluated in the pixel's own direction (the lobes), so no extra normal weight is needed. The pixel's *face* normal keeps deciding
the side (as `GFace` does today).

**Simplified shapes (stage 6, optional).** A plane, cylinder or capsule chart *is* a simplified shape used for coordinates; that is
the extent of their role. Reducing geometry for transport (rays against a proxy instead of the mesh) is a separate contract with its
own lighting-error budget, measured on the doorway, recess and slat tests; not part of this proposal's gates.

## 5. Lobes, frames and the filter

Keep the three HL2 lobes for diffuse (normal-mapped) reads; the read evaluates each surfel's lobes in the query direction before
blending (today's `GIBasisRead` does). Two fixes:
- **Frame continuity**: `BasisDirs`' tangent axis flips at |N.x| = 0.9. v2.1: the frame is chart-derived (the chart's u axis
  projected to the tangent plane, coherent across a chart by construction) with explicit transitions at chart boundaries (the
  connector's coordinate transform rotates the frame); Duff et al. 2017's branchless ONB is the fallback where no chart exists and
  gives robustness (no flip), not continuity across neighbours. The moment texels use the same frame; they go with "moments off".
- **The display filter** (`PassAt`, GPU filter): a neighbour B's lobes are transferred into the receiver A's frame before averaging.
  v2.1, corrected: B'_i = sum_j M_ij B_j with **M_ij = b_j^B(d_i^A)** - B's reconstructed field (its lobe functions b_j^B) evaluated in
  A's lobe directions d_i^A - rows renormalized so a constant field is preserved. This transfers the 3-lobe *model* between frames; it
  is not an exact rotation of the field (the model class is not closed under rotation), so the transfer loses information. Unit tests:
  identity (same frame -> M = I), a constant field preserved exactly, and the A -> B -> A round-trip loss reported per angle (it bounds
  the filter's blur of directional content). A 3x3 per neighbour pair, computable from the two frames at filter time or baked with the
  neighbour weight. Test 6 (basis-frame seam) gates it.

One neighbourhood structure serves both the reconstruction stencils and the filter graph (the chart stencils' entries at the surfel
centers), with different weights: the filter's weight is the stencil's phi x chi x validity at the neighbour's center, and the filter
stays a display-only denoiser the solver never sees (today's rule, now with a test).

## 6. Transport and the solver

e = d + K R e: R is the read; the links of `CompileTransport` capture R's normalized weights at the hits. Rules:
- The reconstruction definition gets a **revision id** (kernel, chi rules, a_s, chart build) stored in the resource and in the
  links. v2.1: it is a *resource compatibility check* - links whose revision differs from the reconstruction's are invalid and are
  recompiled at load (the CPU prototype's compile is seconds; the GPU link build 39-192 ms), or the solver runs live reads until they
  are. This applies to **every** change of R, i.e. work-order steps 3-6 each rebuild the transport, not only a final "transport"
  stage. Test: with everything frozen (lights, instances, validity), live hit reconstruction and the compiled links give the same e
  within the links' truncation tolerance.
- Document which reconstruction the solver uses and which the display uses: today both use the same W on unfiltered E (sec. 1);
  v2 keeps that, with the display adding the filter on top. v2.1: and what compiled rows do when validity changes the run-time
  weights - today a row's weights were normalized at compile with the validities of that moment; a validity change afterwards is not
  in T (the row keeps reading a surfel that went invalid, or ignores one that became valid). The declared policy: rows store
  unnormalized weights and the validity factor is applied and renormalized at solve time (exact for validity, cheap), or the row is
  marked for recompile when any of its surfels' validity crosses a threshold; the first is preferred and measured.
- Ray origins are anchors and their origin sets (sec. 3); no sample's rays start off the real surface.
- Tests: positivity (a non-negative d gives non-negative e at every iteration), the constant field, energy and refinement
  convergence toward the path-traced reference as r shrinks (Cornell at r, r/2, r/4). v2.1, the energy tests made precise: with
  e = d + rho P e, P row-stochastic (P 1 = 1) and rho < 1, the constant source gives e* = d / (1 - rho) and, source off, e decays by
  rho per step; rho = 1 is a separate *conservation* test (the closed white box: no energy created or lost per step). Start on
  synthetic operators where rho and P are known, track the row sums of the compiled T (rho = max row sum must be < 1 for any
  albedo < 1), then the real scenes.

## 7. Tests (the review's list, with what exists)

1. Retessellation invariance (stage 2 gate): same surface at two tessellations, surfel count within Poisson noise, light within the
   reference's noise. New.
2. Thin-wall HDR: a 1e3:1 room pair, leak measured on both the camera read and the solver's hit read (`ReadPoint` capture) on the dark
   side within 2r of the wall. Extends today's leak checks.
3. Doorway localization: light through a doorway lands only in the doorway's stencils (a luminance profile along the dark wall).
4. Proxy origin (only if stage 6 is ever taken): no ray origin farther than epsilon from a real surface point on its side.
5. Directional impulse sweep: a small bright patch moved around a surfel's hemisphere; the read in direction R vs the impulse, for the
   diffuse read and the rough-specular prior (sec. 8).
6. Basis-frame seam: a curved object (the sphere grid, test 6p) and a plane straddling |N.x| = 0.9: the filtered light shows no
   per-surfel or per-frame structure (gradient-energy metric vs the unfiltered reference).
7. Transport: the three tests of sec. 6, plus "hit reads never read `m_Shown`" (a test that perturbs the shown light and checks the
   solver's result is unchanged).
8. Density / LOD transition: two instances of different r side by side and a level switch under the camera; no brightness step
   (a_s's gate).
9. Tiny emitter: a 2 cm emissive texel on a large dark triangle keeps its power at the receiver (footprint rule of sec. 3).
10. Coverage vs validity states: the debug view and the query result separate not-resident, not-initialized, invalidated, outside
    compatible support and defect; a test scene produces each and asserts the label.
Existing and kept: Cornell (6), 6j12 / 6j16 (filter convergence), 6p (sphere neighbours), gi_render's dense vertex-vs-pixel 2 %,
the Bistro bake time and peak.

## 8. Rough reflections and sky visibility (review points 8-9)

v1's motivating case (black halves on the rough metals) was an artefact - the sphere grid's triangles were wound inward and the
raster showed each sphere's far half from inside; fixed. v1's derivation was also wrong, and the review's corrections are adopted:
three cosine-weighted lobe integrals cannot recover L(R) ("exact for a mirror" withdrawn); measurement coefficients are not synthesis
coefficients (a solve against H_ij = integral a_i psi_j is needed, exact only inside the model class); clamped cos^2 lobes are not
band-limited to SH2 and 3 RGB coefficients are not 9 SH coefficients; and the GGX alpha -> 1 limit is not E / pi (the BRDF integral
of single-scattering GGX at alpha = 1, F = 1, normal view, unit radiance is 1 - ln 2 ~ 0.307 vs 1 for Lambert).

v2's position: the engine's split-sum needs a *prefiltered radiance* term L_R(alpha) = integral L D_R / integral D_R; the BRDF
integral itself is the DFG table's job (so the 1 - ln 2 is accounted there, not in the lobe read). The 3-lobe irradiance basis can
supply L_R only as a **calibrated low-frequency prior**, labelled approximate: w_i(R, alpha) fitted offline so that
sum_i w_i B_i best matches L_R over a training set of environments and surfel orientations (least squares on the directional impulse
sweep of test 5 plus real captured environments), constrained to be positive and to tend to a lobe-weighted mean as alpha -> 1.
Where traced reflections or probes cover (roughness <= 0.5 today), they stay the primary; the prior only replaces them for rough
lobes and normalizes nothing. Validate with test 5 and BRDF integration (the prefiltered term times DFG against a reference).
v2.1, the runtime convention the prior is fitted to: the material's *perceptual* roughness p maps to alpha = p^2; the prefilter
view is the split-sum's (the lobe around R = reflect(-V, N), N.V-dependent, as the DFG table assumes); the DFG table carries the BRDF
integral; B_i are lobe *irradiances* in the units of E (W/m^2 per channel), so L_R is B / pi-scaled and the fit absorbs the lobe
normalization. Constraint: for a white constant environment of unit radiance, sum_i w_i B_i^white = 1 exactly (enforced in the fit).
Validation on held-out environments and rotated impulses, never on the training set. The prior is **kept out of the diffuse
acceptance gate**: no diffuse stage waits on it.

Sky visibility: no scalar sky fraction multiplying the whole GI reflection. If a visibility term is kept, its estimator is declared:
per lobe, f_i = (cosine-weighted rays that missed, within the lobe) / (rays within the lobe), the same stratified rays as the light,
accumulated with the same estimator, with *unknown* coverage (rays not yet cast, not-resident neighbours) kept as a separate
confidence rather than folded into f_i; and a scalar still cannot tell a blocked bright window from a blocked dark corner, so it may
only scale the *sky* part of the environment term, never the bounced radiance (which the surfels carry directly). Today's
luminance-ratio occlusion stays until the directional impulse test shows the declared estimator beats it.

## 9. Stages, costs, changelog

**Work order** (v2.1: replaces v2's stage order; each step rebuilds the transport when it changes R, sec. 6):
| # | Step | Gate |
|---|---|---|
| 1 | Baseline (the tests of sec. 7 that run today, errors and costs recorded), and reproduce the frame-filter defect with synthetic directional data (a known directional field assigned to surfels of varying frames, filtered, compared) | reproducible numbers; the defect reproduced or the hypothesis dropped |
| 2 | Frame handling and transfer in isolation: chart-derived frame (ONB fallback), M_ij = b_j^B(d_i^A), the three unit tests | identity, constant preserved, round-trip loss reported; test 6 |
| 3 | Radial kernel (Wendland) in the five reads, transport rebuilt | quality and time; test 2 (no leak regression); live-vs-compiled test |
| 4 | Bounded chart/stencil addressing over the *existing* samples, with the continuity invariant, cut edges kept | read-time win at equal transport (Golem, Ducati, Police); Cornell unchanged; occupancy/overflow reported |
| 5 | Area-driven placement plus coverage validation (bounded, same rules), emitter identity | test 1 (retessellation invariance), coverage zero-defect, test 9 |
| 6 | Replace legacy connectivity (SameLayer, the normal cut, plane weight) only after the barrier and seam tests pass | tests 2, 3; a crease and a modular seam |
| later | LOD area (lambda_fine + lambda_coarse = 1, test 8); geometry reduction under its own budget (tests 3, 4); the rough prior and the sky-visibility estimator (test 5, held-out) | each its own gate; none on the diffuse acceptance path |
Moments off stays its own A/B (the `gi_no_moments_v` switch exists; a bitwise gate against today's path), runnable at any step.

**Cost accounting** (the review's list; honest, per surfel, before compression): anchor position 6-12 B, normal + frame 4-8 B,
side id + chart id + coords 6-8 B, support and LOD 2 B, a_s 2 B, material footprint reference 4 B; lobes 12-16 B, validity and
estimator state 32 B (CPU), history as today; stencils ~4 B per entry per cell (bounded, replacing today's lists which were quadratic
in local density); cross-chart connectors KB per mesh; links ~100 B (unchanged form). Quantization error of chi (4-8 bits) and of
the lobes (RGB9E5) is measured in tests 2 and 5. The v1 claim "4 B per surfel" is withdrawn: anchors are the whole point.

**Changelog v1 -> v2**
- Dropped: convex proxies as the lighting domain and as the surface samples live on; chi = 1 "inside a convex body"; the wrap-shading
  floor g(c) across sides; the per-pair visibility byte; the hull error bound by vertices and centroids; "AO restores lost detail";
  area-mean emission; the per-face 2D read grid on proxies; the 4 B surfel record; the SH-convolved lobe weights, "exact for a
  mirror", the E / pi limit, the sky-fraction multiply of the whole reflection; the black-metal motivating case (an artefact); the
  6x variance claim; "phi(1/2) >= 0.28" (it is 3/16) and "Poisson = coverage".
- Kept: Wendland phi; one neighbourhood structure for reconstruction and filter; the moments' removal as its own A/B; the three
  HL2 lobes for diffuse; the firm requirement (density by world area, no triangle floor, no edge rule, no GI retessellation);
  simplified shapes - as chart coordinates and optional transport reduction under contract only.
- Added: the three decisions kept apart; anchors with side ids and origin sets; coverage validation; charts, cells, bounded positive
  stencils with a_s; declared barriers, adjacency, connectors and per-entry baked chi; frame continuity and the filter's frame
  transfer (the component-wise averaging found in `PassAt`); the transport revision id and the solver-vs-display declaration; the
  review's ten tests and stage order; the check that hit reads use the solver's E, not the shown light; the SameLayer consistency
  analysis; the calibrated low-frequency reflection prior and the sky-visibility estimator contract.
**Changelog v2 -> v2.1** (local revision from the approving review; no architecture change)
- Frame transfer matrix corrected and reversed: M_ij = b_j^B(d_i^A), a model transfer, not a rotation; unit tests (identity,
  constant, round-trip loss). Chart-derived frames with explicit transitions; Duff's ONB as fallback for robustness only. The sphere
  patches are a hypothesis about the filter, to be reproduced synthetically first.
- Same chart is not safe interpolation: static scene cuts (the "wall splits floor" parts) kept as in-chart barriers.
- Stencil continuity made a construction invariant (support-intersects-cell, shared boundary data, split on overflow, occupancy
  recorded); symmetric connector distance.
- Area weights do not make Shepard first-order (linear-field test added); LOD transition lambda_fine + lambda_coarse = 1; cheap
  chart-cell area before Voronoi.
- Transport recompiled on every change of R (steps 3-6), revision id as a resource compatibility check, live-vs-compiled test,
  the validity-after-compile policy declared.
- Energy tests made precise (rho < 1 geometric decay and e* = d / (1 - rho); rho = 1 conservation separately; synthetic operators and
  row sums first).
- Coverage validation bounded (within r - delta), same side/cut/sight rules, narrow parts, no per-triangle allocation.
- One authoritative emission representation by stable identity; footprints reference it; the tiny-emitter test's variations.
- Rough prior: runtime convention stated (perceptual roughness -> alpha = p^2, split-sum view, DFG, B_i units), white-furnace
  constraint, held-out validation, out of the diffuse gate.
- The stage table replaced by the review's work order (baseline + synthetic frame defect, frames, kernel, addressing over existing
  samples, placement, connectivity; LOD / reduction / prior later).

- Disagreements argued (sec. 8 and here): none of substance. Two refinements of the review's wording: the GGX alpha = 1 point is
  right about the BRDF integral, which the engine's DFG term carries, so the lobe read's target is the prefiltered radiance, and the
  prior is calibrated to that; and the interim SameLayer fix is kept until stage 4 because `BuildNeighbors`' cos >= 0.8 gate already
  prevents the cross-side blending the review warns about (sec. 1).

**Results (2026-10-28)**
- Work order 1-2, the filter's frame transfer: built (M_ij = b_j^B(d_i^A) in the CPU and GPU filters), measured, not shipped. Its units
  hold (the identity on one frame, off-diagonal 6e-15; a constant kept, rows' sums 1 +- 6e-8); the 3-lobe transfer is lossy (a single
  lobe there and back keeps 0.78 / 0.23 / 0.05). On the 25 cm sphere under one directional light the filtered lobes miss the light's own
  by 0.503 transferred against 0.473 added component by component (mean relative error): both are the filter's spatial blur across a
  strongly curved surface (4 passes, neighbors ~30 degrees apart), not its frames - and per-neighbor transfers made the filter slower
  (the timing-bound 6j12). The sphere patches are not a frame problem. Target for steps 3-4: the filter's support scaled with the
  curvature, or the filter in chart space; the directional-field comparison (test 6q of xlionrender_test_surfel_gi) becomes their gate.
- The interim SameLayer fix (mean normal + chord sag) is committed with test 6p (a 25 cm sphere: 37 of 103 surfels without a filter
  neighbor before, 0 after).
- Work order 3 (xLIONRender cf4ce36, 7cebc4e): Wendland C2 in the five reads, transport rebuilt; Cornell mean 5.6 -> 5.3 %, max 16.2 ->
  14.5 %, leaks unchanged. Energy tests on a synthetic ring operator: steady state d / (1 - rho) to 1.4e-6, the source off a total falling
  by rho to 3e-7 an iteration, rho = 1 kept to 5e-7; the compiled Cornell links' largest row sum 0.75. No revision id yet: the links are
  compiled from the meshes at load, never stored.
- Work order 4, the filter on curved surfaces (87eaadf): a neighbor's weight f x exp(-(1 - c) / 0.03) (1 on a plane), so the filter's
  support follows the curvature. The 25 cm sphere: 6q's directional error 0.473 -> 0.181; noisy lobes against the clean ones (6r)
  0.303 -> 0.158 (unfiltered 0.255: the old filter was worse than none there).
- Work order 4, addressing - a negative result. Bistro's half-size GI read (Release, 3778 x 1600, Tomas's camera), split by ablation
  (pixel_nolookup / pixel_lookuponly): the pass without any lookup 0.92 ms, + the cell lookup 0.95 ms, + the list walk 0.8 ms (2.7-3.2 ms
  in all). Correction: the earlier "60 % of the read is the lookup" (from a 1-entry run, 1.58 of 2.68 ms) counted the pass's fixed cost;
  the lookup is about a third. Measured, with the same grid rebuilt at load both ways:
  - 4a, parts keyed by chart (per triangle a chart - welded edges, faces within 45 degrees; per cell a chart -> part map, binary search):
    the lookup 1.94 -> 1.87 ms, the read 3.20 -> 3.10 ms. 30 % of Bistro's map entries are ambiguous (a chart in several parts of a cell:
    scored anyway); the cost is the hash probe and the dependent loads, not the scoring.
  - 4b, direct per-triangle addressing (triangle -> up to 4 (cell slot, part) entries, no hash, no map; 90 % of Bistro's triangles
    covered, ~26 MB): the lookup 1.94 -> 1.69 ms (0.25 ms saved, under the 0.3 ms gate). Police unchanged (0.11 ms either way). On the
    curved test surface the triangle's own patch reads a smooth field 0.90 % off against the scoring's 0.82 %.
  Neither shipped: patches in xLIONRender documentation/experiments (gi_step4a_chart_lookup.patch, gi_step4b_direct_addressing.patch),
  tests 6s included. The read's remaining costs are the per-entry work (0.8 ms) and the pass itself; the larger GPU costs on Bistro are
  the GI update (6.8 ms: the trace batch ~3.0, the display filter's 4 passes ~3.5 over 505k surfels) - next in the order, then step 5.
