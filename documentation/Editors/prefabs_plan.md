# Prefabs: storage, identity, runtime and the Prefab Editor - plan

Status: **phases 0, 1, 2, 3 and 4 done (2026-10-07), phases 5-7 not started.** Each phase ends in a state that is committed, tested and usable, so the work can stop
after any phase without leaving the engine half converted.

## 1. Goals

1. **Prefabs are the main building block of a game** - most objects will be one. Making an instance (in the editor and in the game) must be fast,
   and correct: physics and every other builder component built, references inside the prefab pointing at the new entities.
2. **A Prefab Editor** (Unreal style): a prefab opens in its own editor, which is a Level editor whose level is the prefab. It plays by itself.
   The person may bring other scenes in for context while testing; they are never part of the prefab.
3. **Editing in context** (Unity style), later: the level is drawn faded behind the prefab instance being edited, and only the prefab can be
   picked.
4. **One model all the way down**: nested prefabs and variants are the same mechanism, recursive, with no special cases.
5. **Changes reach every instance**: saving a prefab updates every instance in every open level, keeping each instance's own overrides (Unity
   behavior), without making those levels dirty.
6. **Nothing is lost on the way**: existing prefabs and levels are converted automatically, and the tests prove it.

Not a goal now: the scene compiler (an optimized form of a whole scene for the final game). The plan keeps the door open for it (section 9).

## 2. Where we are (verified in the code, 2026-10-07)

| Topic | Today | Where |
|---|---|---|
| Prefab storage | One file per prefab (`Entity.txt`), members keyed by `LocalId` (u32), minted GUID-like and kept stable across saves. The record format is the scene's (`SaveGroupMember` = `SaveEntity` with `PermanentId` renamed). No entity names, no folders. | `xecs_prefab_mgr_inline.h` (`Save`, `EnsureLoaded`, `SaveGroupMember`) |
| Template | Loaded prefab members are live entities with the exclusive `prefab::tag` (no system sees them) and `prefab::root` on the root. `m_PrefabList` holds the roots. | `xecs_prefab.h`, `xecs_prefab_mgr.h` |
| Instance in a level | **Every member is its own entity file in the level**, with a freshly minted permanent id. The root carries `prefab_instance` (prefab guid + overrides). Components the prefab owns are not written; load rebuilds them from the prefab (`DetectAndUnionPrefabInstance`, `ComputePrefabInstanceSaveOverlay`). | `xecs_reference_remap_inline.h`, `xecs_scene_inline.h` (`ReadEntity`) |
| Override addressing | `m_MemberPath`: a **child-index path** from the instance root. Hierarchy diffs too. `ApplyRemovedHierarchyDiffs` deletes "deepest paths first so sibling indices stay stable". | `xecs_editor.h` (`prefab_instance`, `prefab_component_override`, `prefab_hierarchy_diff`) |
| Scene ids | `permanent_id` = u32, GUID-like minting. Entity references are encoded as **int64** (positive: an id in the same scene; negative: an entry of the external table). | `xecs_scene.h`, `xecs_scene_inline.h` |
| Scene load | Read every entity into staging -> apply prefab overrides in staging -> create (builders run, see the overridden values) -> remap references. | `xecs_scene_inline.h`, `doc/xecs_builder_components.md` |
| Runtime spawn | `CreatePrefabInstance(Count, ...)`: batched only for a single-entity prefab. A multi-entity prefab is cloned entity by entity, recursively, with an `unordered_map` remap per instance and references patched by walking the properties ("a bit slow here"). Nested instances are re-derived at every spawn. **Builders are not run** - the builder doc lists "stage the runtime paths: prefab instancing" as still to do: a spawned prefab with colliders gets no physics body. | `xecs_prefab_mgr_inline.h`, `doc/xecs_builder_components.md` |
| Compilers | Neither Prefab nor Scene has a compiler: the editor reads the descriptors. | `Plugin.config/resource_pipeline.config.txt` |
| Editor | `xscene.plugin` edits scenes and knows nothing about levels or Play (`scene_context`). The Level editor (`xlevel::session`, a `resource_editor` keyed by a Level guid) owns the world, its engine copy, the Game module and Play. Commands: `MakePrefab`, `MakePrefabVariant`, `InstantiatePrefab`, `ApplyOverrides`, `RevertOverride`, `RevertAllOverrides`, `RevertHierarchyOverrides`. | `xscene_context.h`, `xlevel_session.h` |
| Data | The example project has 10 prefabs (9 single-entity, 1 two-entity, none nested) and 31 instance entity files in its scenes. | `example.lionprj/Descriptors/Prefab`, `.../Scene` |
| Tests | `smoke/test_prefabs.py` (14 tests: overrides, revert, apply, hierarchy removal); `xECSV2/smoke_test_scene.cpp`. | |
| Known oddity | The Level Tree shows a `Runtime (N)` folder, one entry per prefab made (wishlist #20) - probably templates leaking into a scene listing. | `WISHLIST_editor_and_engine.md` |

What follows from this:

* **Reordering, inserting or removing a child in a prefab silently moves every override in every level to the wrong member** (index paths).
* **A child added to a prefab probably never appears in instances already saved in levels**, because their members come from the level's own
  files. (Confirmed by a test in phase 0.)
* **Updating instances after a prefab changes would rewrite the levels and change member ids**, breaking references from the level into
  instance members, and making every level dirty.
* **Spawning in the game is neither fast enough nor correct yet** (no batching for groups, nested re-derivation per spawn, no builders).

## 3. The model we are building

### 3.1 One document type, three uses

A **scene** is a graph of entities with permanent ids. It is used three ways:

| Use | What | Resident as |
|---|---|---|
| **Placed** | a level's scenes | live entities |
| **Template** | a prefab, loaded to spawn from | inert entities (`prefab::tag`) plus a baked spawn plan (section 3.5) |
| **Edited** | a prefab open in an editor, or a level | live entities, in the editor's world |

A **prefab is a scene** with three extra rules: exactly one root (everything else descends from it), no folders, and references only to its own
members. It keeps its own resource type (`Prefab`), so the Asset Browser, the dependencies and the commands still tell them apart. Only the content
format and the code that reads and writes it are shared.

### 3.2 An instance is a recipe

A level stores an instance as **one record**: which prefab, the instance's own permanent id, its overrides, and its structural changes. It does not
store the members. Loading spawns the members from the template, then applies the recipe. So:

* a prefab change reaches every instance at the next load, or immediately with live update (section 3.6);
* the level files do not change when the prefab changes - nothing turns dirty;
* level files get smaller and merge better.

The recipe holds:

* **property overrides** - (member address, component, property path, value);
* **component diffs** - (member address, component added with its data | component removed);
* **hierarchy diffs** - (member address removed) and **added entities**: ordinary level entities whose parent is a member address;
* the instance root's own transform is just an override of the root.

### 3.3 Member addresses are id chains, not index paths

A member is addressed by **its permanent id inside the prefab**. A member that belongs to a nested instance is addressed by the chain of ids that
crosses each instance boundary: `[outer member id, inner member id, ...]`. An override in a variant of a variant of a prefab is just a longer chain.
Reordering children changes nothing; deleting a member leaves an orphan override that the editor reports (and can clean up) instead of silently
moving it.

### 3.4 Identity of instance members in a level

Other entities in the level reference instance members (a goal referencing the ball, a camera following a player's head), and undo, selection
and commands address entities by id. A member's id in the level must therefore be **the same every time the instance is spawned**.

**Proposal: derived 64-bit ids** (what Unity does with its 64-bit file ids):

* `permanent_id` becomes u64. Ids minted for ordinary entities stay GUID-like, with the top bit clear.
* A member's id in a level = `hash63(instance id, member address chain)`, top bit clear. It is computed at spawn and never stored.
* The int64 reference encoding already has room: positive = id in the same scene, negative = external table, unchanged.
* At load, a derived id that collides with an existing id is reported. At 63 bits, one million entities have about a 1 in 10^7 chance of any
  collision, but the check stays.
* Commands keep accepting the short 8-hex ids. Derived ids print as 16 hex.

The alternative is to keep u32 and store a per-instance table (member address -> minted id) in the recipe. It is less invasive, but the table must
be kept in sync with the prefab: a new member mints a new id, which makes the level dirty. 32-bit hashing is not an option, because the chance of a
collision is too high (about 70% at 100,000 entities).

### 3.5 Runtime spawn: the baked plan (prefab "compiler", in memory first)

Spawning has to be fast and must build what it spawns. When a template is loaded, it is **baked** once into a spawn plan:

* **Flattened**: nested instances are expanded and their overrides applied *at bake time*, never per spawn. A variant chain is resolved once.
* **Members in order**: parents before children, each with its archetype and an index. The remap of one spawn is an array indexed by member
  number, not an `unordered_map`.
* **Reference patch table**: for each (member, component, offset) that holds a reference to another member, the target member's index. It is
  computed once with the property walk, and each spawn then just writes values.
* **Batched**: `Spawn(Prefab, Count)` creates `Count` entities per member archetype in one call each, then patches.
* **Staged with builders**: instances go through the same staged create as scene load (`staged_components` + build plan), so builder systems
  (physics bodies) run. This closes the "stage the runtime paths" item of `xecs_builder_components.md`.
* **Invalidated** when the template changes (live update), and rebuilt lazily at the next spawn.

The plan is plain data. The **prefab compiler** is then this bake written to a file. We add it once phase 0's measurements show that loading and
baking a template is a cost worth removing from the game's startup. It is cheap to add because the in-memory bake already exists.

### 3.6 Live update

When a prefab is saved, every **editing** world that contains instances of it, directly or through other prefabs, respawns those instances:

1. find them through the prefab dependency graph (prefab -> prefabs that nest it -> levels and prefabs that use those);
2. for each instance, take the recipe (already in memory: it is the instance's data), destroy the members, spawn from the new template, and apply
   the recipe;
3. member ids are derived (section 3.4), so selection, references and undo entries that name a member still resolve.

Play worlds are not touched: a running game keeps what it started with.

### 3.7 Editing sessions: a stack of scenes with roles

An editor session edits **one document** (a Level, or a Prefab) and can hold **context scenes**:

| Role | Picked | Saved | Undo | Plays |
|---|---|---|---|---|
| Document | yes | yes | yes | yes |
| Context | no | no | no | yes (they are there to test with) |

* **Prefab Editor (Unreal style)**: the document is the prefab, with no context, or with scenes the person adds to test against.
* **Editing in context (Unity style)**, later: the level's scenes as context (drawn first, faded by a full screen quad, written without entity ids
  so nothing in them can be picked), and the instance's prefab as the document, placed at the instance.
* **Nested drill-down**, later: open an inner prefab from an outer one, with a breadcrumb back up.

**One writer per document**: when a prefab is open in a Prefab Editor, `ApplyOverrides` from a level goes into that session (an undo step there,
which makes it dirty) instead of writing the file behind its back. Save and Save All work as they do now.

## 4. Decisions

Agreed in the discussion:

* A1. A prefab is a scene (section 3.1).
* A2. Instances are recipes (section 3.2); overrides are addressed by id chains (section 3.3).
* A3. The Prefab Editor is the Level editor with the prefab as its level; it plays by itself; context scenes may be added for testing and are
  never part of the prefab.
* A4. Live update on save, Unity style (section 3.6).
* A5. Nesting and variants are recursive, with one mechanism.
* A6. In-context editing comes last.
* A7. The scene compiler waits; a prefab compiler may come early if it helps the runtime.

Decided 2026-10-07: every recommendation below was accepted (D1 derived 64-bit ids, D2 the prefab records its Game, D3 the compiler after phase
0's measurements, D4 convert on load plus `UpgradeProject`, and the phase 4 spawn targets).

* **D1. Member identity**: 64-bit derived ids (recommended, section 3.4) or u32 with a stored id table.
* **D2. The Game a prefab plays with**: a prefab's components can come from a Game's modules (the Soccer players, for example), and Play needs
  systems. Recommended: the prefab records, as an editor property, the Game it plays with. It defaults to the Game of the level it was made from,
  and can be changed in the Prefab Editor. Its modules are already known from `ComponentDeps.txt`, which a prefab gets for free as a scene.
* **D3. When to write the prefab compiler**: after phase 0 has measured template load and bake times (recommended), or right away.
* **D4. Converting old data**: converted automatically when loaded (an old reader kept for one release), plus an `UpgradeProject` command that
  converts and saves everything at once (recommended). The example project is converted and committed in the same change.
* **D5. The root of the instance in the level**: its transform is the only thing a placed instance always overrides. Recommended: the root keeps
  its own `Transform` as an ordinary override, with nothing special.

## 5. Phases

Every phase: tests first where behavior already exists (to pin it), the full prefab-related test set green at the end, the example project
converted if the format changed, and the docs (`xecs_prefab*.md`, `xecs_builder_components.md`, this file) updated. Commits only when asked.

### Phase 0 - Safety net and baseline

* Python tests that pin today's behavior, including the cases expected to be wrong, marked `xfail` with the reason (they turn into real tests in
  later phases):
  * a child added to a prefab after a level was saved does not appear in that level;
  * reordering a prefab's children moves an override to the wrong member;
  * a reference from a level entity to an instance member survives save and reload;
  * a two-level nested prefab: override inside the inner one, save and reload;
  * a variant: override of the base prefab, save and reload;
  * a prefab with a collider spawned during Play gets a physics body (expected to fail today).
* A C++ benchmark in `xECSV2/smoke_test_scene.cpp` (Release): spawn 1, 100 and 10,000 instances of prefabs with 1, 10 and 50 members, flat and
  nested two deep, with entity references inside. Measure time per instance and per entity, and heap allocations per spawn. Template load time
  from text. The numbers are recorded in this file.
* Explain the `Runtime (N)` folder (wishlist #20) - it is the same area.

Exit: the baseline numbers, and the pinned tests in the suite.

**Phase 0 - DONE 2026-10-07.** What was built, what it found, and what it measured.

*Files.* `source/Editors/LevelEditor/smoke/test_prefabs.py` (+8 tests, 14 -> 22), `source/Editors/LevelEditor/smoke/prefab_bench.py` (compiles and runs the benchmark),
`dependencies/xECSV2/smoke_test_prefab_bench.cpp` (the benchmark; a file of its own instead of a mode of `smoke_test_scene.cpp`: it has its own `main`, flags and allocation counter, and the scene test
deletes its data folder on every run), `documentation/Editors/WISHLIST_editor_and_engine.md` (#20 explained), the smoke `README.md`. Run the benchmark with `python prefab_bench.py` (about two seconds).

*Tests (22 in `test_prefabs.py`: 19 pass, 3 strict xfail).* Each saving test restores the Level's and its Scenes' folders when it ends (`level_files_restored`: the ids are the same `7E57xxxx` in every test). Two fixes to that fixture came out of the phase 0 review: it closes the Level only if the editor is still alive and restores the folders in a
`finally` (so a test that kills the editor does not leave its saved Level for the next one), and `_guid_folder` names the folder `f"{v:X}.desc"` because the folders have no leading zeros (`Level/F3/F3/166FAE5EB82F3F3.desc`).
There is no command that reorders children, so the plan's "reordering a prefab's children moves an override to the wrong member" is covered by its sibling, removing the first child (it shifts the index of every other
child the same way); a real reorder test needs a reorder command or a hand-edited prefab file, and can wait for phase 3 where the addressing changes.

| Test | Today | Becomes real in |
|---|---|---|
| a child added to a prefab after a Level was saved reaches that Level | **xfail**, as the plan expected: the saved instance still has one child, a new instance has two (confirmed by hand too) | 3 |
| removing a child of a prefab does not move an override to another member (stands in for the plan's "reordering children", for which there is no command) | **xfail**: three children 10/20/30, the instance overrides the middle one (99), the prefab loses its first child (Apply Overrides of another instance), the override is applied: the prefab ends with 20 and 99 (the override landed on the third child) instead of 99 and 30 | 3 |
| a prefab with a collider spawned during Play gets a physics body | **xfail**: the instance placed before Play has `Physics/BodyGeneration` != 0, the one spawned while Playing has 0 and still carries `PhysicsColliderBox` | 4 |
| a reference from a Level entity to an instance member (and to the instance root) survives save and reload | pass | stays |
| instance members keep their ids across save and reload | pass | stays (derived ids keep it, phase 3) |
| a new instance of a changed prefab has the change | pass | stays |
| a variant: override of the base, save and reload (instance of the variant overrides the base's property again) | pass | stays |
| a variant of a variant (base <- X=5 <- Y=7 <- instance Z=9), before and after save and reload | pass | stays |

*Things the plan has to know (found while pinning).*
1. **No command can make a nested member.** There is no reparent command and `InstantiatePrefab` takes no parent, so a prefab holding an instance as a non-root member cannot be built from the command line.
   The nested tests therefore use the nesting a variant is (an instance as the root of a prefab, chained two deep). The benchmark builds true nesting (instances as members) in C++. Phase 3 needs a command
   (or an `-Parent` on `InstantiatePrefab`) to test members that are instances.
2. **`MakePrefab` of a group with a reference between its members kills the Debug editor** (`xassert` at `xecs_prefab_mgr_inline.h:996`, "reference target is outside this prefab's own group"; in Release the
   reference is saved as null). `CloneEntityIntoPrefabGroup` copies the bytes, so the template's references still hold the handles of the entities it was copied from, and `Save` finds them outside the
   group. Reproduced: root + child with `EntityReference/Target` -> root, `MakePrefab` on the root. It is not a test (it would end the editor and fail the run on its assert); it is what goal 1
   ("references inside the prefab pointing at the new entities") needs fixed: the clone has to remap member references to the template's own members (phase 1, with the scene-format save).
3. **A nested prefab whose members hold references asserts in Debug at every spawn** (`xecs_prefab_mgr_inline.h:427`, "Issue a warning here"): the outer prefab's remap pass visits the nested root, whose
   references the inner spawn already resolved, finds them outside the outer group and asserts. Release skips it (values are right). The benchmark skips nested cells in Debug for this reason.
4. **Opening a Level right after `Close` can assert in the windowed editor** (`ImGui::AddSettingsHandler` `FindSettingsHandler(handler->TypeName) == 0`, from `xlevel::session`'s toolbar handler): the closed session
   still shows in `list` (an empty row) until it is destroyed, and `OpenLevel` in the next frame registers the same handler name. The tests' `_reload` waits for `list` to be empty. Not fixed (outside the phase).
5. `test_impact_map.py::test_every_test_file_is_named_in_the_impact_map` was already failing before this phase (`test_asset_reference.py`, `test_render_transform.py`, `test_system_constraints.py` are not in `golden/test_impact.json`).
6. Entities created by a spawn stay hidden from the systems until `UpdateStructuralChanges` (documented in `xecs_structural_changes.md`); the benchmark resolves them (untimed: it moves two counters and costs nothing next to the spawn) before it verifies.

*Runtime (N) folder (wishlist #20).* Not a leak: `xlevel_panel_level_tree.h` draws a read-only "Runtime" row listing every live entity of the editor's world that is in no open Scene: spawned entities, share-entities, and under
"Prefabs" the resident templates (every member of every loaded/made prefab carries the exclusive `prefab::tag`; the number is members). Phase 1 (templates in the prefab manager, not the scene world) removes that
sub-folder.

*Baseline (Release, `python prefab_bench.py`, one run on the development machine, 2026-10-07; variation between runs is about 10%).* `CreatePrefabInstance(Count, guid, {}, bRemoveRoot=false)`, entity references between
the members, every cell verified per instance (the number of instances and of entities in each; every link/parent/children reference of an entity lands in the same instance, never in the template and never in another
instance - the benchmark begins with a self-check that corrupts one link into another instance and requires the check to catch it). One fresh world per cell, one cold spawn timed apart, then the timed run.
"Nested" is two deep: A holds an instance of B holds an instance of C, split so one spawn makes the same number of entities as the flat prefab of that size.

| prefab | count | us / instance | ns / entity | heap allocs / instance | bytes / instance |
|---|---|---|---|---|---|
| flat 1 | 1 | 0.060 | 60 | 0 | 0 |
| flat 1 | 100 | 0.022 | 22 | 0 | 0 |
| flat 1 | 10,000 | 0.020 | 20 | 0 | 0 |
| flat 10 | 1 | 3.94 | 394 | 46 | 2,520 |
| flat 10 | 100 | 3.83 | 383 | 46 | 2,520 |
| flat 10 | 10,000 | 3.76 | 376 | 46 | 2,520 |
| flat 50 | 1 | 17.9 | 358 | 206 | 7,960 |
| flat 50 | 100 | 17.3 | 345 | 206 | 7,960 |
| flat 50 | 10,000 | 17.5 | 349 | 206 | 7,960 |
| nested 10 | 1 | 9.8 | 976 | 63 | 1,992 |
| nested 10 | 100 | 11.8 | 1,184 | 63 | 1,992 |
| nested 10 | 10,000 | 10.7 | 1,072 | 63 | 1,992 |
| nested 50 | 1 | 26.8 | 535 | 226 | 10,504 |
| nested 50 | 100 | 31.6 | 633 | 226 | 10,504 |
| nested 50 | 10,000 | 28.2 | 565 | 226 | 10,504 |

Cold first spawn: 3-8 us for the single entity, 16-38 us for flat 10/50, 40-60 us nested. Template load from text (`EnsureLoaded`, stdout of its debug trace sent to NUL, mean of 50; five runs, which vary up to
2x for the small ones - disk cache): flat 1 0.16-0.41 ms, flat 10 0.29-0.46 ms, flat 50 0.82-1.0 ms, nested 10 0.45-0.55 ms (three files), nested 50 0.97-1.04 ms. (The first version of this note said 0.91 and 1.69 ms for the nested ones; the
review measured about half and a re-measurement agrees with the review.) (The trace is a `printf` + `fflush` per line; with it going to a console the load is far slower.)

What it says: the single-entity prefab is already batched and allocation free (20-60 ns per entity, near the 100 ns target). Every multi-entity spawn costs 350-400 ns per entity flat and 500-1,200 ns nested, with
about 4 heap allocations per entity (the `unordered_map` remap, the children snapshots, the property walk of every reference), and the cost does not improve with the count, so it is per instance, not per call. Nested is
1.5-3x flat for the same entity count (re-derived at every spawn), as the plan said. Against the phase 4 targets (< 100 ns per entity batched, 0 allocations per spawn, nested = flat) the gaps are about 4x on the time, 206 allocations
instead of 0 for 50 members, and 1.5-3x between nested and flat. Template load is about 1 ms for 50 members, and a nested chain loads in about the time of a flat prefab of the same size: a bake at load is worth doing only if a game loads hundreds of templates at startup (D3 stays open for phase 4).

*Not measured / not covered.* Heap use outside `operator new` (the pools take system pages); builder work (no builder is registered in the benchmark); Debug numbers (the benchmark prints a warning in Debug); a
reference *into* a nested instance's members from the outer prefab (no command or API makes one today); the editor's `InstantiatePrefab` command path (uses the same `CreatePrefabInstance` but also registers every member in the
scene, mints ids and marks the level dirty, which this benchmark does not include).

### Phase 1 - Prefab storage is the scene format

* Generalize the scene I/O (`xecs_scene_inline.h`: descriptor, `entity_db`, `ComponentDeps.txt`, names) to take its resource folder, so that
  `Descriptors/Prefab/<b0>/<b1>/<guid>.desc/` holds a scene: `Descriptor.txt` (active entities, names, root id), `entity_db/`, `ComponentDeps.txt`.
* `prefab::mgr::EnsureLoaded` and `Save` read and write that format; `group_bookkeeping` becomes the scene's own `m_LocalToRuntime`/
  `m_RuntimeToLocal` (same ids: `LocalId` values are kept as permanent ids).
* Template residency is separate from editing: templates live in the prefab manager, never in the scene manager's list, so trees never see them.
* Converter: old `Entity.txt` -> scene format, on load; the old reader is kept.
* Rules checked on save: one root, everything descends from it, references only inside.

Tests: every existing prefab test; round trip of every example prefab (old -> new, same components and values); a prefab gains entity names.
Exit: prefabs are scenes on disk; nothing else changed in behavior.

**Phase 1 - DONE 2026-10-07.** Decided after phase 0 and done here too: finding 2 (MakePrefab of a group with references between its members) is fixed and tested.

*What was built.*
* **The scene I/O takes its folder** (`xecs_scene_inline.h`): `EntityFileInFolder(Folder, Id)`, `ReadEntityFile(GameMgr, Path, Out, ExtraInfos)`, `WriteEntityFile(GameMgr, Path, Id, Entity, Resolve)`, `CreateStagedEntity(GameMgr, Scene, ...)`,
  `CollectComponentDependencies` / `WriteComponentDependencies`. The Scene's `ReadEntity`, `SaveEntity`, `SaveSceneComponentDependencies` are now thin wrappers over them (same files, byte for byte).
* **A prefab folder holds a scene**: `Descriptor.txt` (`xecs::prefab::descriptor`: `Root`, `ActiveEntities`, `EntityNames`; the old `ComponentTypeGuids` is gone, `ComponentDeps.txt` replaces it), `entity_db/<b0>/<b1>/<id>.entity`
  (the scene's entity format, `PermanentId`), `ComponentDeps.txt` (with each component's module: what D2 will use). `prefab::tag` and `prefab::root` are never written; load adds them (`ExtraInfos`), and `prefab::tag` keeps the builders off
  a template (`getBuildPlan`).
* **`group_bookkeeping` is `xecs::scene::instance`** (`local_id` = `permanent_id`): ids, live members and names, held in `prefab::mgr::m_PrefabGroups`, never in the scene manager's list.
* **`Save`**: checks the rules first (one root, every member its descendant by construction, and what is written references only members: a live entity outside refuses the save and nothing is written; a dead handle - a member
  Apply removed - is written as null), writes every member, then the descriptor (temp + rename: it is what marks the new format), then `ComponentDeps.txt`, then removes the old `Entity.txt` and the files of members that
  are gone. **`EnsureLoaded`**: a descriptor with a `Root` is the new format (every member staged, none created unless all read); otherwise the old reader (`details::EnsureLoadedOldFormat`, `LoadGroupMember` kept, the
  `LocalId`s kept as permanent ids). A prefab that fails to load leaves nothing behind (`ForgetGroup`; before, half a group stayed resident).
* **Finding 2 fixed** (`CloneEntityIntoPrefabGroup`): the top call clones the subtree, then moves every reference of the clones to the clone of its target (`KeepReferenceInsidePrefab`); a reference to anything outside the
  group becomes null with a warning (what Unity does). The same call gives each clone the name its source has in its scene: **a prefab keeps its entities' names**. Apply Overrides drops (null) a reference an override would
  copy into the template from the level (see *deferred*). `RemapEntityReferences` (the reference walk) is shared by load, clone, the Save check and Apply; `RemapWrittenReferences` limits it to what a member writes (a nested
  instance's member does not write what its prefab owns).
* **`UpgradeProject`** (`Name\UpgradeProject`, in `xscene_commands_make_prefab.h`, decision D4): every prefab still in the old format is read with that Level's world and saved in the new one; one that cannot be read is listed and
  left alone. Phase 3 extends it to levels.
* **The Level Tree's `Runtime/Prefabs` sub-folder is gone** (wishlist #20): templates are not counted or listed; `Runtime` holds what the game spawned and the share-entities.
* **Follow-up (the coordinator's decision on the two unconverted example prefabs):** the Parent reader (`parent::Serialize`, `xecs_component_others_inline.h`) accepts a record written before `Follow` was a field: the
  column is read apart from the error and, when missing, `m_Follow` keeps `FOLLOW_DEFAULT` (x, y, z and rotation: the value the field was introduced with, commit 7e0abb9). Writing is unchanged. While testing it, the
  clone was found to reset a child's `Follow` to the default (it skipped the whole `parent` component); it now copies it and clears only the link (the caller sets the new parent).

*Files.* xECSV2: `src/details/xecs_scene_inline.h`, `src/details/xecs_prefab_mgr_inline.h`, `src/details/xecs_reference_remap_inline.h`, `src/xecs_prefab.h`, `src/xecs_prefab_mgr.h`, `src/xecs_prefab_descriptor.h`,
`doc/xecs_prefab.md` (new section "On disk: a prefab is a scene"), `smoke_test_prefab_bench.cpp` (its hand patch of the template references removed: the clone does it now), new `smoke_test_prefab_storage.cpp`,
`src/details/xecs_component_others_inline.h` (the Parent reader). xscene.plugin: `xscene_commands_make_prefab.h` (UpgradeProject). xlevel.plugin: `xlevel_panel_level_tree.h`. Root: `source/Editors/LevelEditor/commands/LevelEditor_CommandSet.h`; smoke: `test_prefabs.py`, new `test_prefab_storage.py`,
`prefab_bench.py` (`build` takes the source), `harness.py` (`UpgradeProject` writes to disk), `project_guard.py` (puts `Descriptors/Prefab` back too), `golden/test_impact.json`, new `golden/prefab_v1/` (the example's ten
prefabs as they were before this phase), `README.md`; `documentation/Editors/WISHLIST_editor_and_engine.md` (#20). example.lionprj: 9 prefabs converted (`Descriptor.txt` rewritten, `Entity.txt` removed, `entity_db/` and
`ComponentDeps.txt` added).

*Tests (test_prefabs.py 22 -> 27, plus test_prefab_storage.py).* All of `test_prefabs.py`: 24 pass, the 3 strict `xfail`s still fail as expected. New:
| Test | What it protects |
|---|---|
| `test_every_example_prefab_reads_the_same_from_the_old_format` | each of `golden/prefab_v1` copied under a new guid (old reader, converted on load) gives an instance whose `DescribeEntity` - the root's and every member's, runtime handles left out - equals the converted example prefab's (9 load; Shadow fails in both); written and passing **before** the change, to pin it |
| `test_a_prefab_is_stored_as_a_scene` | Root, two ActiveEntities, two entity files, ComponentDeps.txt, no Entity.txt |
| `test_a_prefab_keeps_the_names_of_its_entities` | the names reach the descriptor, and survive an Apply Overrides (a re-save) |
| `test_make_prefab_of_a_group_whose_members_reference_each_other` | finding 2: root <-> child references; no crash, and the references point inside the instance MakePrefab leaves, a new instance, and one made after a reload |
| `test_upgrade_project_converts_a_prefab_of_the_old_format` | the copy is converted; Shadow (`66879B27D9D067FB`) is listed with why ("no longer registered") and its `Entity.txt` kept; the converted instance equals the original; a second run converts nothing |
| `test_prefab_storage.py` (C++ in Debug, no editor, ~15 s) | the clone's references and names; the files; a fresh world loads the same; a member that left loses its file; a reference outside refuses the save and nothing changes; an old Entity.txt read and converted; a broken prefab leaves nothing resident; a child's `Follow` survives MakePrefab, save and load; **a Parent record without `Follow` loads, with `FOLLOW_DEFAULT`** |

After the follow-up: `test_prefabs.py` 24 pass + 3 xfail, `test_prefab_storage.py` passes; with `test_hierarchy.py`, `test_entities.py`, `test_physics_events.py`, `test_scenes_and_levels.py` (the Parent component and
the clone): all pass. Before the follow-up, wider run (19 files picked by `impact.py`): 143 passed, 6 xfailed, 3 failed - all three failed before this phase and touch nothing it changed: `test_impact_map` (the three test files phase 0 already noted), `test_ecs_gate` scan
(`xlevel_world_check.h`, `m_pPool` 0 -> 1, from the 2026-10-06 commit 8c52eb1 of xlevel.plugin), `test_module_dependencies::test_saving_a_scene_does_not_forget_...` (its precondition looks for a column spacing the committed Physics
scene descriptor does not have; fails alone too).

*The example project, converted.* `Soccer\UpgradeProject` converted 8 of the 10 prefabs. Shown to load the same: the instance of each, described before and after the conversion in fresh editors, is identical (8 equal, the 2 that did
not load fail in both); all 72 entities of the Soccer level are described identically with the prefabs in the old format and in the new one. After the follow-up (the tolerant Parent reader) a second `UpgradeProject` converted
`7E5700000000B001` (its child's Parent record had no `Follow`): its instance describes identically read from the old file and from the converted one in a fresh editor, and its child is written with `Follow` `#F` (the default).
**Known leftover for the user: `66879B27D9D067FB` "Shadow"** stays in the old format, untouched: it uses component `EC0212D079E9A6A9`, which no module registers any more, so it cannot be read (it could not before this phase
either). `UpgradeProject` lists it every time ("Prefab group member file references a component type that is no longer registered"). It is the user's data: nothing deletes it; re-registering that component (or re-making the
prefab) is the user's call.

*Measurements (Release, `python prefab_bench.py`).* Spawn is unchanged for flat prefabs (flat 10: 358-383 ns/entity, flat 50: 337-341, 46 and 206 allocations). Nested got about twice as fast (nested 10: 480 ns/entity, was 976-1,184;
nested 50: 382-387, was 535-633), because `EnsureLoaded`'s "already resident" early-out no longer prints a trace line with a flush, and every nested spawn calls it. **Template load is slower**, one file per member: flat 1
0.31 ms (was 0.16-0.41), flat 10 0.67-0.77 ms (was 0.29-0.46), flat 50 2.6-2.75 ms (was 0.82-1.0), nested 10 0.89-1.0 ms, nested 50 2.8-3.9 ms (was ~1.0) - about 40-50 us per member file. This weighs on D3 in phase 4: the
baked/compiled template removes it.

*Deferred, and why.*
* An override that is a reference to an instance member, carried by Apply Overrides into the prefab, becomes null instead of the prefab's own member that instance member stands for (no exact mapping exists with index paths;
  phase 3's id chains give it). Before, Debug asserted on the save.
* A reference from a member to an entity outside the group becomes null when the prefab is made (no override keeps it on the instance either): Unity keeps it as an instance override; that needs entity-valued overrides
  that survive save, phase 3.
* `66879B27D9D067FB` "Shadow" (above): left as it is, by decision; the user's to repair or remove.
* `[SaveEntity]` debug trace lines still print for every entity written (as before, now also for prefab members).

### Phase 2 - 64-bit permanent ids (if D1 = derived ids)

* `permanent_id` -> u64 (37 files and 294 uses today). File field widened; reading an old 32-bit id still works.
* Command arguments and replies: 8-hex ids keep working; 16-hex accepted and printed when needed.
* `external_entity_address`, `m_ExternalRefTable`, `m_EntityNames`, folders, selection, undo snapshots: widened.

Tests: the full suite (this touches everything that names an entity). Exit: no behavior change; ids are 64-bit.

**Phase 2 - DONE 2026-10-07.** `xecs::scene::permanent_id` (and the prefab's `local_id`) is `std::uint64_t`. Everything below was decided inside the plan's frame (no question was needed); the choices that were not spelled out are marked *decision*.

*What was built.*
* **The type and its text** (`xecs_scene.h`): `permanent_id = std::uint64_t`, `max_permanent_id_v` (`0x7FFF...F`), and `FormatPermanentId` / `FormatPermanentIdW` / `ParsePermanentId`: **8 hex digits when the id fits in 32 bits, 16 otherwise**; parsing takes either, any case, shorter text. Entity file names, the commands (`xscene::commands::ParseEntityId` / `FormatEntityId` are these), the listings (`ListEntities`, `ListFolders`) and the logs use it, so every id of before reads exactly as it did.
* *Decision - the top bit is reserved.* An entity reference is an int64 whose negative values index the external table, so an id with the top bit set could never be referenced. `CreateEntity` and `InstantiatePrefab` refuse it ("the id does not fit in 63 bits"). Phase 3's derived ids are `hash63`, as the plan says.
* *Decision - minted ids stay 32-bit values* (`NextFreeEntityId`, `NextFreeLocalId` unchanged): the plan says ordinary ids "stay GUID-like", and it means no existing project file changes just because the editor ran. The 64 bits are for what phase 3 derives; until then only a command line (or a test) can make a larger id.
* **Entity files** (`WriteEntityFile` / `ReadEntityFile`, `xecs_scene_inline.h`; scene entities and prefab members): an id that fits in 32 bits is written in the `EntityInfo` record's `PermanentId:g` column **exactly as before, so such a file is byte for byte what it was** (and an old editor still reads it); an id that does not fit gets the record `[ EntityId64 ] { Id:G }` right after `EntityInfo` (`PermanentId` then holds the low 32 bits, ignored by the reader). *Why not a `PermanentId:G` column:* xtextfile's `ReadColumn` copies the column's own size into the variable it is given and does not convert, so a `g` column read into a `u64` yields the neighbouring bytes, and a reader cannot ask a column's type; a second column name would print "Unable to find the field" at every read of an old file. The file names under `entity_db/` have 8 digits for an id that fits and 16 for one that does not (`DiscoverEntityIds` reads both).
* **Descriptors** (`Scene/ActiveEntities`, `EntityNames/Id`, a folder's `Entities`, `ExternalRefs/ParentEntity`, the prefab's `Root`, `ActiveEntities`, `EntityNames`): now `;u64` rows, written when the scene or prefab is next saved. **Reading `;u32` rows needed a change in xproperty**, outside xECSV2: `xproperty::sprop::WidenToMember` (`dependencies/xproperty/source/sprop/property_sprop_getset.h`, the two places `setProperty` hands a value to an atomic member): an unsigned integer read from a file into a wider unsigned member is widened instead of handed over as the wrong type (which asserted in Debug and read garbage in Release). Nothing else converts. It is a general growth of xproperty (any field widened later benefits), 33 lines in a repository of its own (uncommitted there, like the rest).
* **The old prefab format** (`Entity.txt`: `LocalId`, `RootLocalId`) is read as the 32-bit columns it is and widened.
* **The editor**: every undo record that held an id as `std::uint32_t` now holds a `permanent_id` (writers and readers together; the compiler does not warn about those narrowings, so they were found by reading: apply/revert overrides, component edit, entity lifecycle including the delete snapshot and its shadow ids, entity name, entity reference, make prefab, property edit, folder snapshot of a delete (its entity ids), instantiate, move to folder, transform gizmo, selection, the scene dependency's cleared references); `printf` formats of ids (`%u`, `%08X`) fixed (the compiler does warn about those: C4477); the Level Tree keys its rows with the whole id (`ImGui::PushID` of a pointer-sized value; `static_cast<int>` dropped the high half) and its "seen" set holds 64 bits. Folder ids (`folder_id`) stay 32 bits. The options' help says "8 or 16 hex digits".
* *Not changed, on purpose:* `prefab_instance::m_MemberPath` (child indices, phase 3 replaces it), the int64 reference encoding, `xecs::component::entity`.

*Files.* xECSV2: `src/xecs_scene.h`, `src/details/xecs_scene_inline.h`, `src/details/xecs_prefab_mgr_inline.h`, `doc/xecs_scene_entity_ids.md` (new, the id's rules and what is on disk), `doc/xecs_prefab.md`, `smoke_test_scene_ids.cpp` (new). xproperty: `source/sprop/property_sprop_getset.h`. xscene.plugin (`source/Editor/`): `xscene_command_context.h`, `xscene_scene_ops.h` (comment), and `xscene_commands_` `apply_overrides`, `component_edit`, `entity_lifecycle`, `entity_name`, `entity_reference`, `make_prefab`, `property_edit`, `scene_organization`, `selection`, `transform_gizmo`, plus `xscene_panel_entity_properties.h`, `xscene_prefab_authoring.h` (log formats). xlevel.plugin (`source/Editor/`): `xlevel_commands_level.h`, `xlevel_commands_scene_dependency.h`, `xlevel_commands_hierarchy.h`, `xlevel_commands_text.h`, `xlevel_commands_workspace.h`, `xlevel_panel_level_tree.h`, `xlevel_scene_sanity_scan.h`. Smoke: `test_entity_ids.py` (new), `harness.py` (the id regex of `entities()`), `test_prefabs.py` and `test_module_dependencies.py` (two assertions that looked for `;u32`, see below), `golden/test_impact.json`, `README.md`. `documentation/Editors/command_line.md`. **The example project's data was not touched**: it reads as it is, and its descriptors become `;u64` when a scene is next saved (its entity files do not change at all).

*Tests.* New `test_entity_ids.py` (11 tests):
| Test | What it protects |
|---|---|
| `test_ids_in_the_engine_text_files_references_and_old_data` | compiles and runs `smoke_test_scene_ids.cpp` in Debug (about 80 checks): the text form of ids of every width; two scenes (parent and child) with ids small, `0xFFFFFFFF`, `0x100000000`, a 63-bit one, `0x7FFF...F`, three that share their low 32 bits; the files (names, `EntityInfo` as before, `EntityId64` only past 32 bits, the descriptor's `;u64`, the external table holding a 64-bit id); a fresh world loading them (every id, same-scene and cross-scene references, names, folder members); saving again changes no byte; `DiscoverEntityIds`; **a scene whose descriptors are rewritten with `;u32` rows loads**; a prefab with big member ids saved, loaded and spawned; a prefab descriptor with `;u32` rows loads. Checked to catch a regression: with `WidenToMember` disabled the Debug run asserts at step 4 |
| `test_an_entity_with_a_64_bit_id_is_listed_and_described_with_that_id` | 16 digits for a big id, 8 for one that fits (`FFFFFFFF`, and `0000000100000000` is the first 16-digit one); lower case accepted |
| `test_a_short_id_is_the_same_id` | `7e5712` is `007E5712` |
| `test_the_top_bit_of_an_id_is_reserved` | `CreateEntity` and `InstantiatePrefab` refuse it, nothing is made; `7FFFFFFFFFFFFFFF` is fine |
| `test_create_and_delete_of_a_64_bit_id_undo_and_redo` | undo/redo of create and of a delete of a parent with its child, same ids, hierarchy intact |
| `test_property_edit_name_and_component_of_a_64_bit_id_undo` | SetProperty, RenameEntity, AddComponent undo/redo on a big id |
| `test_an_entity_reference_to_a_64_bit_id_and_the_move_of_it_into_a_folder` | SetEntityReference undo restores the big target; folder listing, DeleteFolder and MoveToFolder undo with a big member |
| `test_an_instance_of_a_prefab_can_have_a_64_bit_id` | InstantiatePrefab with a big id, undo, redo |
| `test_entities_with_64_bit_ids_survive_save_and_reload` | the Level saved with big ids (parent, child, name, folder, a reference from a small-id holder) and reopened: same entities, folders, names, reference resolved; the files (`EF/CD/7123456789ABCDEF.entity` with `EntityId64`, a small id's file without it, the descriptor's `;u64` row) |
| `test_a_scene_saved_with_u32_id_rows_loads` | the Level's scene descriptors rewritten with `;u32` rows (what every project had) reopen as they were |
| `test_removing_a_scene_dependency_that_clears_a_reference_to_a_64_bit_id_undoes` | `RemoveSceneDependency -ClearRefs 1` and its undo with a big target in the parent scene (needs a second Scene: the Level is saved with it added and reopened). Checked: narrowing the undo record makes it fail |

Two existing assertions changed in place, same intent: `test_prefabs.py::test_a_prefab_is_stored_as_a_scene` looked for `Prefab/Root ;u32` (now `;u64`); `test_module_dependencies.py::test_saving_a_scene_does_not_forget_the_entities_that_could_not_be_loaded` looked for `;u32 #101` in the scene descriptor with an exact column spacing (this is the test phase 1 recorded as failing before it changed anything; with the row type and spacing taken from a regex it passes).

*Results.* Full smoke suite (`python -m pytest -q`, Debug editor, 19 minutes): **489 passed, 6 xfailed (the phase 0 ones and the old ones), 4 xpassed, 4 failed - none caused by this phase**: `test_ecs_gate` (the registry baseline, `m_pPool` 0 -> 1, from commit 8c52eb1 as phase 1 recorded), `test_impact_map` (`test_asset_reference.py`, `test_render_transform.py`, `test_system_constraints.py` are not in `golden/test_impact.json`; `test_entity_ids.py` is), `test_script_module_editor::test_a_module_exports_as_a_cmake_file...` (expects 7 headers, the Soccer module has 8: project data, nothing to do with ids) and `test_module_dependencies::test_saving_a_scene_does_not_forget...` (fixed afterwards, passes alone and in the run of the files listed next). A second run of `test_entity_ids`, `test_prefabs` (24 pass + the 3 strict xfails), `test_prefab_storage`, `test_module_dependencies`, `test_entities`, `test_folders`, `test_undo_redo`, `test_scenes_and_levels`, `test_hierarchy`, `test_impact_map` after the last build: 91 passed, 3 xfailed, 1 failed (`test_impact_map`, above).

*Measurements.* `python prefab_bench.py` (Release) is unchanged from phase 1: flat 10 363-380 ns/entity, flat 50 342-350, nested 10 476-485, nested 50 377-385, the same 46 / 206 / 63 / 226 allocations per instance; template load from text 0.67 ms (flat 10), 2.65 ms (flat 50), 1.02 ms (nested 10), 2.95 ms (nested 50). The ids doubling in size costs nothing measurable here.

*Not verified.* The windowed editor was not looked at: the Level Tree's `ImGui::PushID` change (a pointer-sized value of the id instead of an `int`) is covered only by the commands and the headless runs. The `UpgradeProject` command is unchanged (it converts prefabs; scenes keep reading their `;u32` rows and become `;u64` when saved) - the plan's phase 3 extends it to levels and can write the new rows then. The xGPU `E29_LevelSceneEditor` example (not part of this solution) uses the alias and was not built. One editor start in the first run died with an access violation in `xresource_editor::compilation::instance::queue::pop` (`xresource_editor_asset_mgr.h:594`, a compile-queue job on a worker thread, during the first `OpenLevel` of the run); it did not happen again in three more runs and nothing in this phase is near it - worth a look by whoever owns the asset pipeline.

*Left for later.* A reference encoded in a file stays an int64 (ids to 63 bits); the `Entity #{}` display name of an entity without a name is still its id in decimal (`EntityDisplayName`) - a derived id will make that long, phase 3 can print it with `FormatPermanentId`.

### Phase 3 - Recipes and id-chain addresses

* `prefab_instance` becomes the recipe: overrides, component diffs and hierarchy diffs keyed by member address chains; added entities are
  ordinary scene entities whose parent is a member.
* Scene save: an instance writes its root record only. Scene load: spawn from the template **in staging** (so builders still see overridden
  values), apply the recipe, give members their derived ids, create, remap references.
* The editor's prefab features are re-pointed: override markers, Revert, Revert All, Revert Hierarchy, Apply Overrides, Make Prefab, Make Prefab
  Variant, Instantiate. Orphan overrides (their member is gone) are listed on the instance, with "Remove orphan overrides".
* A variant is a prefab whose root is an instance of the base prefab; `prefab::root::m_ParentPrefabGuid` is retired.
* Converter: old levels (member files + index paths) -> recipes, resolving each path against the current prefab; the old member files are
  removed when the converted level is saved.
* A `-Parent` option on `InstantiatePrefab` (or a reparent command), so that a prefab holding an instance as a non-root member can be built
  from the command line and tested (decided after phase 0, finding 1: no command can make a nested member today).

Tests: the phase 0 `xfail`s about added children, reordering, references and nesting now pass; all of `test_prefabs.py`; a level converted and
reloaded draws the same entities with the same values (compare `DescribeEntity` before and after); nested members built with `-Parent`.
Exit: a prefab can be changed freely without damaging any instance.

**Phase 3 - DONE 2026-10-07.** A scene stores a prefab instance as one entity file, its recipe; the members are spawned from the prefab at load with ids
derived from the instance's id and their address. Choices the plan did not spell out are marked *decision*.

*What was built (engine, xECSV2).*
* **The recipe** (`xecs_editor.h`): `xecs::editor::member_address` (`std::vector<u64>`: the member's permanent id in its prefab, one element per nested instance
  crossed). `prefab_component_override::m_Member`, `prefab_component_diff::m_Member` (component diffs per member), `prefab_hierarchy_diff::m_Member`,
  `prefab_instance::m_Format` (0 = written before recipes: an old file has no `Format` row; 1 = recipe). The old `m_MemberPath` (child indices) is still
  read (`member_flags<DONT_SHOW, DONT_SAVE>`: never written) so old files convert. *Decision:* the root of a variant (a prefab whose root is an instance)
  adds no address element, so a variant's instance addresses its members as its base's, and MakePrefabVariant keeps every member's id.
* **Derived ids** (`xecs_scene.h`): `DeriveMemberId(instance id, address)` = FNV-1a + splitmix64 finalizer, masked to 63 bits, forced above 32 bits
  (*decision*: a derived id never takes a minted 32-bit id, and prints with 16 digits); the root keeps the instance's id. `scene::instance::m_InstanceMembers`
  (id -> instance, address, the name it was spawned with): members are in `m_LocalToRuntime` like any entity, have no file, are not in `ActiveEntities`,
  and their name is written only when it was renamed in the scene. A collision is reported and the member left out.
* **`xecs_prefab_recipe_inline.h`** (new): `MakePlan` (every entity a spawn of a prefab makes, parents first, nested instances expanded with their
  recipes' removals and component diffs, one *level* per nested prefab), `StageMembers` (members staged from their templates with derived ids, parent,
  children and references written as those ids), `ApplyStagedOverrides` (nested recipes first, the instance's last; an entity value is `#<n>`, the
  reference as the file encodes it), `StageSceneInstances` / `RegisterMembers` / `LinkChildren` (scene load), `RefreshRecipe` (from the live members: their
  component diffs - a component added to a member keeps its data as overrides of every property -, removed members, members with scene entities under them,
  entity texts), `SpawnMissingMembers`, `InstantiateInScene`, `ConvertOldInstances`, `ApplyToPrefab`, `ConvertNestedRecipe`, `ApplyNestedRecipeLive`.
* **Scene load** (`EnsureLoaded`): read every file -> stage the recipes' members and apply every recipe's overrides in staging (builders see them) ->
  create -> register members -> remap references -> join the scene's entities under a member to its children list -> convert the old instances.
  `DetectAndUnionPrefabInstance` gives a recipe's root a children component when its prefab can have members, and the root no longer copies the
  prefab root's children (it used to be overwritten by the file's).
* **Scene save**: a pending change to a member writes its instance instead; `SaveEntity` refreshes the recipe before writing; a recipe's file holds no
  `children` record. `WriteEntityFile` retries its open for up to half a second (the pipeline's watcher had a Soccer file open for a moment and the save
  failed half-way, see *found*). `mgr::SaveEntity` asserts `Id <= max_permanent_id_v` (carry-over).
* **Prefab manager**: `CloneSubtreeIntoPrefab` (the clone's top call, with a map of live entities to template members - Apply's - the source -> clone map,
  and the references that left the group); `CreatePrefabFromEntity(Source, Guid, pOutside, pMemberIds)`; `CreateNestedPrefabInstance` applies the nested
  recipe by address (`ApplyNestedRecipeLive`, with an early-out when it touches only its root - without it nested spawn was 2x slower); a nested recipe
  written before phase 3 is converted when its prefab loads. `prefab::root::m_ParentPrefabGuid` is retired (variants are prefabs whose root is an instance).
* **Apply** (`recipe::ApplyToPrefab`): overrides written into the template members; a reference to a member of the instance (or its root) becomes the
  prefab's member it stands for, anything else null (carry-over 1); component diffs carried (with data); removed members leave the prefab; the scene's
  entities under the instance join it (`CloneSubtreeIntoPrefab`) and become members of the instance with their derived ids (Unity: they are connected);
  what concerns a nested instance's member goes into that nested recipe; orphans stay on the instance. A final pass maps the references of every
  template member (a carried component can hold one).
* **Old levels**: an instance with `m_Format` 0 is converted once live: its members are paired with the plan by position (as the old spawn made them,
  the old removals in template index space), take their derived ids (what referenced them is marked to be written again; other scenes' external tables
  follow), their values that differ from a fresh spawn become overrides, old path overrides that named an entity of the scene under the instance (the
  Soccer players' added children) are dropped (that entity's file holds its values), members the prefab gained are spawned. The old member files go at
  the next save.
* `SerializeGameState` (Play's reload bridge) reading a binary snapshot accepts the end of the file where an empty table would be (a component whose only
  properties are DONT_SAVE, like RenderTransform, has none in a binary file): the converted Soccer scene put the ball's pool last and the reload failed
  (`test_game_module_reload`).

*What was built (editor).* `xECSEditor` grew (`kVersion` 10 -> 11, carry-over): `ResolvePrefabMember` (replaces `ResolveMemberPath`),
`PrefabMemberAddresses`, `InstantiatePrefabInScene`, `RefreshPrefabRecipe`, `SpawnMissingPrefabMembers`, `LinkSceneChildren`, `ApplyPrefabRecipeToMembers`,
`ApplyInstanceOverridesToPrefab(Scene, Root)`, `CreatePrefabFromEntity(..., pOutside, pMemberIds)`. `FindContainingPrefabInstance` answers from
`m_InstanceMembers` (an entity added under a member is an ordinary entity of the scene now, not part of the instance). The incremental hierarchy bookkeeping
(`RecordAdded/RemovedChildOverride`, index shifting) is gone: removals are computed from the live instance when the recipe is refreshed; deleting a member
marks its instance dirty. `InstantiatePrefab -Parent hexid` (carry-over). MakePrefab: refreshes the recipes of the instances in the group, keeps a member's
reference to an entity outside the group as an override of the instance (carry-over 2), moves every reference to an entity of the group to the member it
became, puts the instance back at its index among its siblings, refuses a member of another instance. MakePrefabVariant: refreshes first, clears the
hierarchy diffs too. RevertAllOverrides: places the instance again under the same id (same member ids), and no longer leaves the root marked deleted
(the old code removed the root's file at the next save). RevertHierarchyOverrides: deletes the scene's entities under the instance, spawns the removed
members back; undo reverses both. New `ListPrefabOverrides` (the recipe by member address, ORPHAN marks, the members and their ids) and
`RemoveOrphanOverrides` (undoable). Undo snapshots carry member addresses (u64) and, per entity, whether it is a member (restored into
`m_InstanceMembers`, children relinked, the recipe re-applied to restored members). `UpgradeProject` also converts every scene with an instance written
before recipes (loads it into this Level's world when it is not open, saves, releases). `EntityDisplayName` prints `FormatPermanentId` (carry-over). Dead
UI copies removed: `RegisterInstantiatedSubtree`, `InstantiatePrefabIntoScene`, `CreatePrefabFromGroupRoot`, `CreatePrefabVariantFromInstance`,
`AttachPrefabInstanceComponent`, `ClonePrefabEntityIntoScene` (the commands were the only path).

*Files.* xECSV2: `src/xecs_editor.h`, `src/xecs_scene.h`, `src/xecs_prefab.h`, `src/xecs_prefab_mgr.h`, `src/xecs.h`, `src/details/xecs_prefab_recipe_inline.h`
(new), `src/details/xecs_scene_inline.h`, `src/details/xecs_prefab_mgr_inline.h`, `src/details/xecs_reference_remap_inline.h`, `src/details/xecs_prefab_inline.h`,
`src/details/xecs_game_mgr_inline.h`, `src/details/xecs_game_mgr.cpp`, `doc/xecs_prefab.md` ("An instance in a scene is a recipe"), `doc/xecs_scene_entity_ids.md`,
`smoke_test_prefab_recipe.cpp` (new). xLIONCore: `src/game/xlioncore_editor.h/.cpp`. xscene.plugin: `xscene_prefab_overrides.h`, `xscene_prefab_authoring.h`,
`xscene_commands_apply_overrides.h`, `xscene_commands_make_prefab.h`, `xscene_commands_scene_organization.h`, `xscene_commands_entity_lifecycle.h`,
`xscene_commands_component_edit.h`, `xscene_commands_property_edit.h`, `xscene_entity_inspector_bridge.h`, `xscene_scene_ops.h`. Root: `LevelEditor_CommandSet.h`,
`documentation/Editors/command_line.md`; smoke: `test_prefab_recipe.py`, `test_prefab_recipes.py` (new), `test_prefabs.py`, `test_module_dependencies.py`,
`test_script_module_editor.py`, `golden/scenes_v1/` (new: the example's two scenes with instances as they were before phase 3, and their `DescribeEntity`
captured with the phase 2 build), `golden/test_impact.json`, `README.md`. example.lionprj: the Physics and Pitch scenes converted (`UpgradeProject`).

*Tests.* `test_prefab_recipe.py` (C++ in Debug, no editor, 8 steps: derived ids - 20,000 distinct, all above 32 bits; an instance saved as one file - no
children record, no member file, a member override, a component added to a member, a scene entity referencing a member, one under a member - loaded back
with the same ids/values/references and a second save changing no byte; the prefab gains a member and has its children reordered; the prefab loses a member
- orphan kept, the reference to it null; nested: a prefab holding an instance, the nested recipe's value and the level's override, after a reload;
Apply - an override and the scene's entities under the instance join the prefab, which take derived ids and lose their files; a one-entity prefab's
instance gets its children component back at load). `test_prefab_recipes.py` (8): the Physics scene of before phase 3 converts on load and reads the same
(every `DescribeEntity` equal to the golden one, the member with a derived id), and again once saved and reopened, its old member file gone; the same for
the Soccer level (72 entities, 27 instances); reordering a prefab's children (its root file edited) keeps every override on its member and every id;
a prefab holding an instance as a member (`-Parent`, MakePrefab): two-element addresses, an override inside survives a reload, a fresh instance has the
prefab's value; `-Parent` and Undo; orphans listed, removed, undone; MakePrefab keeps an outside reference as an override (and across a reload, the prefab
itself null); Apply maps a reference to an instance member to the prefab's member. `test_prefabs.py`: the two phase-3 strict xfails are normal tests now
(the added-child one counts the change reaching the instance MakePrefab left too, and checks the placed instance's two members through ListPrefabOverrides);
the physics one stays xfail (phase 4). Two assertions changed in place to the converted data: `test_module_dependencies` (the Physics scene lists 14 entity
files, not 15: the member has no file; compared before/after now), and `test_script_module_editor`'s header count 7 -> 8 (carry-over; the Soccer module has 8).

*Results.* Prefab-related set after the last build (`test_prefab_recipe`, `test_prefab_storage`, `test_prefabs`, `test_prefab_recipes`, `test_entity_ids`,
`test_hierarchy`, `test_undo_redo`, `test_scenes_and_levels`, `test_impact_map`): **81 passed, 1 xfailed** (the phase 4 physics one). Earlier, wider runs on
this phase's code: 147 passed + 3 failed (`test_ecs_gate` - the pre-existing `m_pPool` 0 -> 1 in `xlevel_world_check.h`, nothing of this phase's; the added-child
count and the 15-files assertion, both fixed above) over `test_prefabs, test_prefab_recipes, test_prefab_recipe, test_prefab_storage, test_entity_ids,
test_hierarchy, test_entities, test_undo_redo, test_scenes_and_levels, test_folders, test_module_dependencies, test_physics_events, test_components,
test_disable_tags, test_command_helpers, test_read_only_queries, test_robustness, test_session_command_surface, test_ecs_gate, test_impact_map`; and 80 passed
+ 1 failed (`test_game_module_reload`: the snapshot EOF, fixed above) over `test_play, test_soccer_goals, test_soccer_referee, test_physics_contact_events,
test_save_all, test_level_games, test_engine_copies, test_render_transform, test_game_module_reload, test_sessions_and_entities` and the ones above;
`test_game_module_reload`, `test_prefabs` and the module-dependency test pass after the fixes. `test_impact_map` passes (the three files phase 0 found missing
are in the map now). The ECS source gate is unchanged by this phase (still the pre-existing `m_pPool` line).

*The example project, converted.* `Soccer\UpgradeProject` converted the Physics scene (instance 203 of the two-entity prefab: its member `C2C318DC` became
`496A8FA0E0264D7F`, its file removed) and the Pitch scene (27 instances, no prefab members: the old path overrides on the players' added children dropped,
the added-children hierarchy diffs recomputed). Shown to load the same: every entity of the three Levels described in a fresh editor before (phase 2 build,
old data) and after (this build, converted data): identical, but for the member's id (`compare_describes`: Physics 15/15, Pitch 72/72, names equal).
"Shadow" (`66879B27D9D067FB`) is still listed as left (phase 1).

*Measurements* (`python prefab_bench.py`, Release): flat unchanged (flat 10: 363-381 ns/entity, flat 50: 343-354, 46 / 206 allocations); nested 10 470-477 ns,
nested 50 374-384 ns, 63 / 226 allocations - phase 2's numbers. Without the early-out in `ApplyNestedRecipeLive` nested was 760-860 ns and 152/673
allocations (a plan built per nested spawn): the early-out is what keeps it. Template load: 0.67 ms (flat 10), 2.64 ms (flat 50), 0.87 ms (nested 10),
2.99 ms (nested 50).

*Found.* (1) The resource pipeline's watcher opens a project file the moment it changes, so a save of many files in a row can fail one with "Permission
denied" (seen once, converting Pitch; the half-written scene was put back from git and converted again) - the write now retries. (2) The phase 0 fixture
`level_files_restored` used `rmtree(ignore_errors=True)`: a locked file once left a member file of the example missing; it retries now. (3) The binary
snapshot's empty-table-at-the-end bug (above). (4) `SerializeRoundtrip` (a level command no test uses) reads a snapshot into the live world and asserts in
`CreateNewPoolFamily` (a family that already exists) - it is not the Play reload path (that reads into a fresh world); not chased. (5) A reference to a
deleted entity still asserts in Debug on Save (`WriteEntityFile`, "reference target not resolvable") - pre-existing; MakePrefab no longer creates such
references (it moves them to the new members). (6) The access violation of phase 2's first run (`compilation::instance::queue::pop`) did not recur.

*Deferred / not verified.* Placing an instance in the editor still uses `CreatePrefabInstance` (the game's call) and pairs the result with the plan; scene
load and respawn use the staged spawn - phase 4 makes them one path (which is also why the physics xfail stays). The inspector's "revert to the prefab's
value" for a member inside a nested instance reads the inner prefab's template value, without the outer prefab's nested recipe layered on it. An entity
override inside a nested recipe of a prefab made from a scene instance keeps the scene's encoding (`#<scene id>`) when its member is not live in the
template (rare: a reference override on a member of a nested instance). ApplyOverrides' Undo restores the prefab's property values and the instance's
bookkeeping, not its structural changes (removed members, joined entities, carried components) - as before. Undo of RemoveOrphanOverrides and of the
hierarchy revert is covered by tests; undo of MakePrefab with members' derived ids by the existing MakePrefab tests only. The windowed editor (Level Tree,
inspector override markers) was not looked at; the commands and headless runs cover the bookkeeping they read. Old-format instances whose prefab changed its
children since the level was saved are paired by position (as the old code addressed them), so such an instance converts with whatever the old code
would have shown.

### Phase 4 - Fast, built spawning

* The baked plan (section 3.5), built when a template is loaded and invalidated when it changes.
* `Spawn(PrefabGuid, Count, Callback)` for the game: batched, staged with builders, references patched from the table, no heap allocation per
  instance in steady state.
* Scene load and live update use the same spawn (one path to keep correct).
* Benchmark against phase 0; decide D3 (the prefab compiler) with the numbers.

Tests: the phase 0 physics spawn `xfail` passes; the benchmark has targets (below) and a test that fails when spawning slows down by more than a
margin. Exit: spawning is fast and correct in the game.

Proposed targets (Release, to be confirmed by the baseline): **the ECS part of spawning (without the builders' own work, such as creating a Box3D
body) under 100 ns per entity when batched, zero heap allocations per spawn, and nested prefabs costing the same as flat ones of the same size.**

**Phase 4 - DONE 2026-10-07.** (An earlier attempt was cut off before it changed any file; this one started clean.) Choices the plan did not spell out are marked *decision*.

*What was built (xECSV2).*
* **The baked plan** (`xecs::prefab::baked`, `mgr::getBaked`, end of `xecs_prefab_recipe_inline.h`): the plan of phase 3 (nested prefabs expanded), each member staged
  from its template with the nested recipes applied (`recipe::ApplyNestedOverrides`, split out of `ApplyStagedOverrides`), then the table of its references
  (component, byte offset, target member; found by giving each reference a sentinel and finding it in the component's bytes) - a reference inside a container
  the component holds is kept by its order (`m_Indirect`) and patched through the property walk. Each member's data is kept as an **inert entity**
  (`prefab::tag`: no system sees it, no builder runs on it, the Level Tree counts it with the templates) with every reference null. *Decision:* baked at the
  first need (not at template load: a template that is never spawned costs nothing), cached in `mgr::m_Baked`.
* **`mgr::Spawn(Guid, Count, Callback)`**: each member made `Count` times in one `CreateEntities` from its baked entity, then parents, children lists and
  references written from the table (the pool columns found once per member), then `Callback` on each root. Returns every entity made, member-major. When the
  world runs builders and a member has builder components, that member is staged and built one at a time (`staged_components::Create` with the build plan) -
  what closes the builder doc's "stage the runtime paths: prefab instancing". `CreatePrefabInstance(Count, Guid, Callback, bRemoveRoot=false)` goes through it
  for a prefab of the scene format; the old clone stays for prefabs made in code (`CreatePrefab<T...>`), variants being made, added/removed components and the
  root left out.
* **One path**: the editor's InstantiatePrefab (`recipe::InstantiateInScene`) spawns with `Spawn` (no pairing with `PairLive` any more), and a scene load,
  `SpawnMissingMembers` and the old-level converter stage members from the same baked data (`StageMembers` takes the bake) and apply only the instance's own
  recipe. Live update (phase 6) will use the same.
* **Invalidation**: `mgr::Save` and `CreatePrefabFromEntity` drop every baked plan (`InvalidateBaked`, deleting their inert entities) - every template change of
  the editor (Apply, MakePrefab, the Undo of an Apply, UpgradeProject) ends in a Save. *Decision:* all plans, not the saved prefab's alone: an outer prefab's
  plan holds what it nests. Not in `ForgetGroup` (a failed load inside a bake would free the plan a scene load is using).
* *Decision - builders inside a physics step* (risk table): no queue. xLION reads Box3D's contact and sensor events after `b3World_Step` returns and registers
  no step callbacks, so no game code (event handlers included) runs while the Box3D world is locked.
* **Found and fixed (phase 3 bug)**: `MakePlan`'s `ExpandNested` took the nested node's address by reference into the node list, which reallocates as members are
  visited: the second member of a nested prefab got a garbage address (spawned as a member of the outer prefab, its nested-recipe override lost). Phase 3's
  nested test had one member left; the new test has two.
* **Found: the editor loads a stale Game.dll after an engine layout change.** `prefab::mgr` grew (`m_Baked`), which moves every member of
  `game_mgr::instance` after it; the editor rebuilds Game.dll only when a script module's source is newer than the DLL
  (`BuildGamePluginIfStale`), not when an engine header changed, so the first test run loaded the DLL of 12:06 and hung in its `RegisterSystems`
  (a level opened after a Play; 100% CPU in Game.dll). Touching a module source (`soccer_game.cpp`, mtime only) makes it stale, but the editor
  still loads the old DLL first and rebuilds in the background, so the first level that loads it hangs; the rebuilt DLL (once the background
  build ends) works. Not fixed here (the game plugin build, outside the phase): **after this change, a person's Game.dll must be rebuilt once**
  (touch a module source and let an editor rebuild it, or move `Cache/Resources/Platforms/WINDOWS/GameDll/<game>/Debug/Game.dll` aside: an editor
  with no usable DLL builds before it loads). The same holds for `xLION_Headless` (`live.py` without `--window`), which the `xLION` target does not
  build: it crashed at startup against the new LIONCore.dll; it was rebuilt (`/t:xLION_Headless`).
* Build: `xlioncore_editor.cpp` passed MSVC's section limit (C1128): `/bigobj` for xLIONCore (`dependencies/xLIONCore/Build/dependency/CMakeLists.txt`; CMake
  re-run on `Build/xLION.vs2022`).

*Files.* xECSV2: `src/xecs_prefab_mgr.h`, `src/details/xecs_prefab_mgr_inline.h`, `src/details/xecs_prefab_recipe_inline.h`, `doc/xecs_prefab.md` ("Spawning:
the baked plan"), `doc/xecs_builder_components.md` (status), `smoke_test_prefab_bench.cpp` (`--check`, the Debug skip of the nested cells removed),
`smoke_test_prefab_spawn.cpp` (new). xLIONCore: `Build/dependency/CMakeLists.txt`. Smoke: `test_prefab_spawn.py` (new), `prefab_bench.py` (`--check`),
`test_prefabs.py` (the physics xfail is a normal test), `golden/test_impact.json`.

*Tests.* `test_prefab_spawn.py` (no editor): `test_prefab_spawn_engine_checks` (C++ in Debug: three instances in one call - values, parent, children and
references in their own instance, never the template or another instance, what the systems see; `CreatePrefabInstance` through the plan with its callback;
references in a container patched; nested - the nested recipe's value in every spawn, both nested members addressed through the nested instance (the bug
above), references across the nesting; builders on - the builder component consumed, the handle written from the prefab's data, the template never built, and
`InstantiateInScene` builds too; builders off - an ordinary component; a saved prefab bakes again and the old plan's entities are gone) and
`test_prefab_spawn_meets_its_targets` (the Release benchmark with `--check`: batched under 100 ns/entity, allocations per instance no more than the children
lists, nested within 1.5x flat; seen to fail on an allocation miscount while it was written). `test_prefabs.py::test_a_prefab_with_a_collider_spawned_during_play_gets_a_physics_body`
is a normal test now.

*Measurements* (Release, `python prefab_bench.py`, before = phase 0 / phase 3):

| prefab | count | ns/entity before | ns/entity now | allocs/instance before | now |
|---|---|---|---|---|---|
| flat 1 | 100 / 10,000 | 22 / 20 | 25 / 23 | 0 | 0 |
| flat 10 | 100 / 10,000 | 383 / 376 | 49-50 / 40 | 46 | 1 |
| flat 50 | 100 / 10,000 | 345 / 349 | 50-51 / 39-41 | 206 | 1 |
| nested 10 | 100 / 10,000 | 1,184 / 1,072 (phase 3: ~470) | 61-62 / 50-53 | 63 | 3 |
| nested 50 | 100 / 10,000 | 633 / 565 (phase 3: ~380) | 52-53 / 42 | 226 | 3 |

One instance per call: 69 ns/entity (flat 1) to 90-114 (the rest). Nested / flat: 1.24 (10 members: three children lists against one), 1.06 (50). The first
spawn, which bakes: 40-50 us (flat 10), 120-150 us (flat 50), 70-80 us (nested 10), 150-160 us (nested 50). Template load from text unchanged (0.68-0.72 ms
flat 10, 2.7 ms flat 50, 0.86-0.99 ms nested 10, 2.85-2.9 ms nested 50). Against the targets: under 100 ns per entity batched - met (40-62); nested = flat - met
within 1.24x; **zero heap allocations per spawn - not met: one per member that has children**, the `children::m_List` `std::vector` each instance needs (a
prefab of 50 members under one root still needs its list of 49). Getting to zero means another container for `children` (inline storage, or the children
in a pool), which touches every user of `m_List` in the engine and the editor: left for a later change.

*D3 (the prefab compiler) - decided: not now.* Spawning no longer depends on how the template was loaded, and the bake costs 40-160 us per prefab once. What a
compiled form would remove is the text load: about 50 us per member file (0.7 ms for 10 members, 2.7 ms for 50), paid once per prefab when a game first needs
it. That matters only for a game that loads hundreds of prefabs at startup; the scene compiler (section 9) needs the same binary writer, so the two belong
together. The bake is plain data already (a plan, inert entities, a reference table), so writing it to a file stays cheap to add.

*Results.* Engine tests: `test_prefab_spawn` (2), `test_prefab_recipe`, `test_prefab_storage`, `test_entity_ids::test_ids_in_the_engine...`: all pass.
Editor (Debug, after Game.dll was rebuilt, see *found*): `test_prefabs`, `test_prefab_recipes`, `test_entity_ids`, `test_hierarchy`, `test_undo_redo`,
`test_scenes_and_levels`, `test_impact_map`: **80 passed** (phase 3's set had 81 passed + 1 xfail with the two engine files counted; the xfail now passes);
`test_play`, `test_game_module_reload`, `test_soccer_goals`, `test_physics_events`: 11 passed. The Soccer level (27 instances, loaded through the bake) opens
with its 72 entities and `test_prefab_recipes` still finds every example entity described as before phase 3. The full suite was not run.

*Deferred / not verified.* Zero allocations (above). A reference held by a SHARE component of a member is not patched by a spawn (a share belongs to its family;
the old clone did not either). A spawn's Callback runs after the members are built, so it cannot change what a builder sees (a staged callback needs the
callback's arguments from the staging: not needed yet). Phase 3's open item - the inspector's "revert to the prefab's value" inside a nested instance reads
the inner prefab's template without the outer prefab's nested recipe - is not fixed: the baked member has that value, but the inspector reaches it through
`xECSEditor::ResolvePrefabMember`, which Apply's undo also uses to write into the template, so it needs a separate call in the editor interface (a `kVersion`
change, two repositories, a UI path no test drives); left open. The windowed editor was not looked at.

### Phase 5 - The Prefab Editor

* The Level editor session is generalized: its document is a Level **or** a Prefab (`xlevel::session` keyed by either guid; the Prefab's tree
  shows the root as the top row, as the Level row is today).
* Opening a prefab from the Asset Browser (double click, `Open Resource`) opens it in its own Prefab Editor tab, with tree, inspector, viewport,
  gizmos, undo, Save, Save All, System Registry, Logs.
* Play: the prefab plays by itself, with the Game of D2. Context scenes: "Add Context Scene" brings a scene in to test with; it plays, it is never
  picked or saved, and it is not part of the prefab.
* One writer per document: `ApplyOverrides` into a prefab open in a Prefab Editor goes through that session.
* The command line reaches a Prefab Editor session like a Level session (`<Name>\Command ...`), so the AI and the tests drive it the same way.

Tests: open, edit, undo, save and reopen a prefab; Play a prefab with a collider; a context scene plays and is not saved; Apply Overrides into an
open Prefab Editor is an undo step there.

### Phase 6 - Live update

* On prefab save: respawn every instance in every editing world through the dependency graph (recursive), keeping recipes, ids, selection and
  undo; invalidate baked plans.
* Play worlds untouched.

Tests: two levels open with instances of a prefab; edit the prefab in its editor and save; both levels show the change, keep their overrides, are
not dirty, and a reference into an instance member still resolves. Nested: a change to an inner prefab reaches instances of an outer prefab.

### Phase 7 - Editing in context

* Session roles in the viewport: context scenes drawn first, a full screen fade quad, no entity ids written for context (nothing to pick), then the
  document.
* "Edit in Context" on an instance: opens its prefab as the document, placed at the instance, with the level as context; Save -> live update.

Tests: what can be picked; save from context updates the instance it was opened from and the others.

## 6. Migration

* Converted on load, old readers kept for one release, `UpgradeProject` to convert everything at once (D4).
* The example project is converted and committed in the same change as each format step (phase 1: prefabs; phase 3: levels).
* Before converting, the converter writes nothing until the whole level converted cleanly; a level that cannot be converted is left as it is and
  reported (the person keeps the old data).

## 7. Risks

| Risk | Mitigation |
|---|---|
| The save/load/override code is intricate (its comments record many past bugs: pool reallocation, nested place != load, builder ordering). | Phase 0 pins the behavior first; each phase changes one thing; the full prefab test set runs at every phase. |
| Widening ids touches every command and panel. | Its own phase (2), with no behavior change, gated by the full suite. |
| Converting real projects loses data. | Convert in memory, compare, write only when complete; keep the old reader; keep the old files until the converted level is saved. |
| Live update while a person is mid-edit in a level (selection, an open gizmo drag, undo history). | Ids are derived, so they survive; a drag in progress is ended first; tested in phase 6. |
| Runtime spawn from a template whose builders run inside a physics step. | The builder doc's open question on handoff queueing; the spawn API refuses to run inside a step, or queues, decided in phase 4. |
| Hot reload of Game.dll with templates resident. | Templates are reloaded with the world, like scenes; tested with `test_game_module_reload*`. |

## 8. Open questions

* D1-D5 above.
* Should a prefab instance be allowed to *remove* its root's children (hierarchy removal), or only hide them? Unity allows removal only in
  recent versions; we already support it (keep, with id addresses).
* Should a prefab be allowed to hold **more than one root**? The plan says no (a single pivot). A scene instanced inside a level (section 9)
  covers the many-roots case.

## 9. Beyond this plan

* **Scene compiler**: the same bake as the prefab's, for a whole scene, for the final game (archetype-batched blocks, references resolved, no
  text). Phase 4 builds the pieces.
* **A scene instanced in a level** (Unreal's Level Instances): once a prefab is a scene and an instance is a recipe, instancing a whole scene is
  the same thing without the single-root rule.
* **Streaming**: scenes already have residency; with compiled scenes, streaming cells are scenes loaded and unloaded by distance.
* **Spawn pools**: with a baked plan, a game can keep pre-spawned inactive instances and activate them (the disable tag already exists), for
  bullets, particles and crowds.
