# The Prefab Editor

A prefab opens in its own editor (Unreal style): double click it in the Asset Browser, or `OpenPrefab -Prefab <hexguid>`. It is the Level editor with the prefab as its document - the same tree, inspector,
viewport, gizmos, undo, Save and Save All, System Registry, Logs and Play - next to the Levels that are open (any number of editors can be open, each with a world of its own). Part of
[the prefab plan](prefabs_plan.md), phase 5.

## What the document is

A prefab is stored as a scene (`Descriptors/Prefab/<b0>/<b1>/<guid>.desc/`: `Descriptor.txt`, `entity_db/`, `ComponentDeps.txt`), so the editor opens it as **a scene of the prefab's own guid**
(`xecs::scene::instance::m_bPrefabDocument`): the scene manager reads and writes the prefab's folder, as a prefab. Its entities are ordinary live entities (no `prefab::tag`: systems see them, a click picks
them) and every command of the scene editor edits them: `Name\CreateEntity -Scene <the prefab's guid> ...`, `SetProperty`, `AddComponent`, `Undo` ... The ids are the ones the prefab has on disk, so
they are the same after every save and open. A prefab that holds an instance of another prefab (nesting, a variant) shows the instance's members with their derived ids; an edit inside it is
saved as the recipe of the nested instance, as in a Level.

The tree's top row is the prefab (its Game, the scenes it is tested against); the entities of the prefab hang from it, with no Scene row of their own. Select the prefab row and the Inspector shows its Game
and its context scenes (`DescribePrefab` says the same on the command line).

**The rules of a prefab are checked when it is saved**: exactly one root (the one entity with no parent) and references only to its own entities. A document that breaks one is not written - nothing is - and
stays unsaved (`Save` says so; Play is refused too, because Play plays what is saved). A prefab in the old format (one `Entity.txt`) does not open until `UpgradeProject` has converted it.

Not in a prefab: folders (`CreateFolder` is refused), and an instance of itself (`InstantiatePrefab` of the prefab into its own editor is refused; a cycle through other prefabs is not detected yet).

## The Game a prefab plays with

A prefab's components may come from a Game's script modules (the Soccer players), and Play needs those systems. The prefab names its Game (the `Game` of its `Descriptor.txt`, kept by every save): a
prefab made from a Level starts with that Level's Game. `SetPrefabGame -Prefab <hexguid> [-Game <assetguid>]` (undoable, written at once; the combo of the Inspector, or the prefab row's menu in the tree)
changes it, and refuses a Game that lacks a module the prefab needs; without `-Game` the prefab names none: no scripts, components or systems of any module, as a Level that names none. It takes effect when the
editor is opened again. The prefabs of the example project name none until they are given one.

## Play, and the scenes brought in to test with

Play works as in a Level: the prefab is saved, the world is rebuilt from what is saved with the builders on (a collider gets its body), and Stop puts the editor back. The prefab plays **by itself**; to test it in a
setting, bring scenes in: `AddContextScene -Scene <hexguid>` (or drop a Scene on the prefab row). A context scene is loaded, so it plays with the prefab, and that is all it is: it is **never picked, edited or saved**, and it is
no part of the prefab (a reference from the prefab to one of its entities is refused when the prefab is saved). Edit commands that name it are refused. They are not kept when the editor closes.

## One writer per prefab

While a prefab is open in a Prefab Editor, that editor is the only thing that writes its file. When another editor saves the prefab - Apply Overrides of an instance in a Level, or the undo of it - the
prefab is not written: the saved state goes to the Prefab Editor, which takes it as one undo step of its document (`ReplacePrefabDocument`): it shows the change, becomes dirty, and Ctrl+Z takes it back
before anything is saved. Save writes it. When the Prefab Editor saves, the other editors forget the template they hold of the prefab, so the next instance they place has the change; the instances they
already placed are updated by the live update of phase 6. A Prefab Editor that is playing does not take a change: Apply writes the file as before.

## What is not done

* The window layout of a Prefab Editor is the Level's (tree, editor, inspector, system registry); there is no preview-only mode yet.
* Opening a prefab from another prefab (drill-down) and editing in context come with phase 7.
* A prefab that is in no Game: its components of a module are not registered, so its entities of that module are not loaded; they are kept (a save writes them back), and the tree does not list them.
