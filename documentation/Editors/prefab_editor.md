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

**A prefab that names no Game still opens whole** (Edit Alone, a double click in the Asset Browser, `OpenPrefab`, `OpenResourceEditor`): its editor works, in memory only and until it closes, under (1) the
Game the prefab names; else (2) the Game of the Level (or prefab) the person is working in; else (3) the project's only Game; else none, with the message that says so. Nothing is written into the prefab:
the Inspector says `(no Game) - using <Game> from the Level. Set a Game to keep this.` in a neutral colour (red only when no Game could be found), `GetPrefabGame` still says `Source=none` and adds
`Using=` / `UsingFrom=`, and `DescribePrefab` says the Game in use and `GameFrom=`. `SetPrefabGame` keeps it.

**A click is not a change.** A selection is an undo step, but never makes a Level or a prefab "unsaved" (`xlevel::HasUnsavedDocumentChanges` skips `Select`, `SelectLevel`, `ToggleMultiSelect`,
`ClearSelection`): closing the editors of a Level and its prefab (the close button of the dock closes every tab at once) asks only about what was really edited, once per editor (the question's id carries the
document's guid).

## Play, and the scenes brought in to test with

Play works as in a Level: the prefab is saved, the world is rebuilt from what is saved with the builders on (a collider gets its body), and Stop puts the editor back. The prefab plays **by itself**; to test it in a
setting, bring scenes in: `AddContextScene -Scene <hexguid>` (or drop a Scene on the prefab row). A context scene is loaded, so it plays with the prefab, and that is all it is: it is **never picked, edited or saved**, and it is
no part of the prefab (a reference from the prefab to one of its entities is refused when the prefab is saved). Edit commands that name it are refused. They are not kept when the editor closes.

## One writer per prefab

While a prefab is open in a Prefab Editor, that editor is the only thing that writes its file. When another editor saves the prefab - Apply Overrides of an instance in a Level, or the undo of it - the
prefab is not written: the saved state goes to the Prefab Editor, which takes it as one undo step of its document (`ReplacePrefabDocument`): it shows the change, becomes dirty, and Ctrl+Z takes it back
before anything is saved. Save writes it. A Prefab Editor that is playing does not take a change: Apply writes the file as before.

## Live update

When a prefab's file changes (its Prefab Editor saves it, or an Apply Overrides writes it), every open editor that is not playing brings its instances of it up to date at once - the instances
of the prefab and those of every prefab that nests it, in Levels and in other Prefab Editors: each is spawned again from the prefab with its own overrides. Nothing is written and nothing turns dirty;
the members keep their ids, so a reference to one, the selection and the undo history still find it (a gizmo drag in progress is ended first, as one undo step). Apply Overrides updates the other
instances in its own Level the same way, and so does its undo. When a Prefab Editor turns down a change another editor handed it (Ctrl+Z of that step, or Close without saving), the other editors are
brought back to what the file holds. A Level that is playing keeps what it started with; Stop reopens it from the files, with the change. A prefab cannot hold an instance of a prefab that holds it
(A holds B holds A): `InstantiatePrefab` refuses it.

## Roles: what is the document and what is context

Every scene in an editing session has a role. The **document** (the Level's scenes, or the prefab) is picked, saved and in the undo; a **context** scene is loaded so that it is there to see and to play with, and that
is all it is. In the viewport (the scene view, when the editor is not playing) the render draws the context first, puts a full screen quad of the viewport's background over it (it fades only where something was drawn:
the background is left alone), then draws the document over that - full color, tested against the context's depth. Nothing of the context is picked: its entities are not offered to the pick, so a wall of the context in
front of the prefab does not hide the prefab from a click, and a click on the wall selects nothing. The texts of a context are not drawn. `xlionrender::roles` (`xlionrender_view.h`) is how the host tells the render which
entities are what (their runtime values, sorted: `DrawRoles`, `PickRoles`); the host knows the scenes, the render does not.

`DescribeRoles` says the roles of the editor it is addressed to: `Document=` and `Context=` (scene guids), `ContextEntities=`, `HiddenEntities=`, `InContext=`, and what the last draw did (`DrawnContext=`,
`DrawnDocument=` items, `Faded=`). `PickRay` answers with the same roles a click uses.

## Edit in Context

Right-click the root of an instance in a Level's tree and choose **Edit in Context** (or `<Level>\EditInContext -Scene S -Id I`): the instance's prefab opens in its own Prefab Editor as the document, **placed where the
instance is**, with the Level's scenes around it as context (as the Level is saved: save it first, or the reply says the instance is not in the saved scene yet and it is not hidden). The instance itself - its root, its
members and what was added under them - is not drawn and not picked in that editor: the prefab is there in its place. The camera looks at it.

* **Save** writes the prefab, and the live update brings every instance of it up to date: the one it was opened from (its own overrides stay), the others, in every open editor.
* **The placement is not the prefab's.** The root's Transform in context is the instance's place (a state of the editor, not an edit: the document is as clean as it was). A save, and every snapshot of the document, write
  the root as the prefab holds it; a change made to the root's own Transform while in context is not kept. Open the prefab on its own to change it.
* **Play is refused** in an editor opened in context (the prefab would play over the Level's own instance): play the Level.
* The editor works under the **Game of the Level** while it is open (so that the scenes around it load whole: the modules of its entities are there), whatever Game the prefab names; nothing is written into the prefab.
* Not from inside a prefab (no drill-down yet), and not when the prefab is already open in an editor.

## The prefab of an instance, in the Inspector

For an entity that is part of a prefab instance (the instance's root, or one of its members, nested ones too) the top of the Inspector shows, under Add Component:

* **The prefab row**: the prefab's picture, its name and, under the name, the *edit* and *find in the resource browser* buttons - the two lines of any resource reference of the Inspector, drawn by the same code
  (`xresource_editor::RenderResourceReferenceRow`) in its read-only form: no picker, no drag and drop, **no clear button**, no label; the reference is never changed from here (nor by command: `SetProperty`,
  `AddComponent` and `RemoveComponent` refuse the instance component). The edit button opens a menu under it with **Edit In Context** (the Level Tree's item: it queues `EditInContext` for the instance placed in the
  Level) and **Edit Alone** (opens the prefab in an editor of its own, as a double click in the Asset Browser does). An entry that cannot run is disabled and its hint says why (playing, an instance inside a prefab,
  the prefab already open in an editor).
* **`Prefab Overrides (N)`** (greyed with none; it still opens, to say so). The popup opens under the button and lists what the whole instance does differently, grouped by member (the entity selected first,
  expanded; a click selects that entity; a member of a nested instance shows its address, the ids of each prefab crossed): **Added** components (a revert icon removes it), **Removed** components (struck through;
  Revert All brings them back), **Modified (n)** components with `Name: prefab's value -> instance's value` per property (a revert icon each), then **Hierarchy** (children the instance removed, entities of the scene
  added under it), **Orphans** (overrides of a member the prefab no longer has, with *Remove orphan overrides*) and the footer **Revert All**, **Revert Hierarchy** (disabled with no hierarchy change) and **Apply**.
  *Revert All asks first*: "Revert all overrides of X? N changes will be undone (you can undo this)", Revert / Cancel; the command it runs, `RevertAllOverrides`, is undoable and asks nothing by itself.
* In the component list of the selected entity, the header of a component the instance **added** is grey-blue (one colour in every theme), and a component with **modified** properties has a thin blue mark at its left.
  A removed component has no header: it is only in the popup.

**Where a popup opens** is decided in one place, `xeditor::popup::PlaceUnder(anchorMin, anchorMax, assumedSize)` (`dependencies/xeditor/include/xeditor/hint.h`, next to `hint::PlaceAwayFromEdges`; the pure part
is `PlaceUnderAt`): call it before `ImGui::BeginPopup` with the rectangle of the item the popup belongs to. The popup goes under the item with its left edge on the item's; against the right border its right
edge goes on the item's right edge (then flush with the border); with no room below it goes above when there is more room there. It stays inside the window it is drawn in (a popup that crosses the window's
edge becomes a window of the OS of its own, cut at the screen). Used by the prefab row's edit menu, the Prefab Overrides popup and Add Component; the other popups that open under a button (the Systems popup, the
Game combo's list) could use it. `xeditor::ReadOnlyTextColor()` (same file) is the colour of the value of a read only property (the text colour faded as `ImGui::BeginDisabled` fades it): the prefab's name uses it.

The data of the popup is `DescribePrefabOverrides` (see command_line.md): the same text, one line per item.

## The Scene Editor

A **Scene** opens in an editor of its own, the way a prefab does: a double click on a Scene in the Asset Browser, `OpenResourceEditor` (the editor registered for the Scene type) or `OpenScene -Scene <hexguid>`
(queued like a Level's open, with the same reply: `Opened Scene <guid>`). It is the Level editor with the Scene as its document (`level_state::m_CurrentScene`, `session::isScene()`): the tree (`Scene Tree`) has the
scene as its top row, its entities and folders hang from it, there is no Level row and no Scene row of its own, and the commands reach it as `<Name>\Command` like a Level's. Undo, Save, Save All, Play, System
Registry and the Logs are the Level's; the tab and the toolbar use the Scene's icon.

* **It is not added to any Level.** A Level gets a Scene by dropping it on the Level or `AddScene`; a double click never does that (it used to add the Scene to whatever Level was open).
* **One writer per Scene.** A Scene that a Level, or another Scene Editor, has open is not opened a second time: that editor is brought to the front, nothing is selected, and the reply (`OpenScene: <guid> is
  already open in <Level or editor name>`) says where. A Level that wants a Scene another editor has open keeps today's behaviour (read-only there, `edited in <editor>`).
* **The Game.** A Scene names none, so its editor works, in memory only and until it closes, under the Game of the Level the person is working in (the one it was opened from), else the project's only Game
  (the same `BorrowAGame` a prefab that names none uses); nothing is written. The Inspector's Scene row says `Works under the Game ... from the Level`; with no Game found the same red hint as a prefab says why.
* **A click is not a change**, and a clean editor closes without asking; a changed one asks once (the question's id carries the scene's guid).

## What is not done

* The window layout of a Prefab Editor is the Level's (tree, editor, inspector, system registry); there is no preview-only mode yet.
* Opening a prefab from another prefab (drill-down) is not done: Edit in Context works from a Level.
* The context is the Level as it is *saved when the editor opens*: it is not kept in step with edits the Level has afterwards (open it again).
* The fade is a fixed 65% of the viewport's background; the context's texts are left out of the draw.
* A prefab (or a Scene, or a Level's scene) opened under a Game that lacks one of its modules: the components of that module are not registered, so its entities of that module are not loaded and the tree does not
  list them. Such a document **is never written**: Save, Close -Save 1, the save-before-close question, Save All and Play refuse it and say why (`... was not saved: N of its entities could not be loaded ...
  Give it a Game that lists that module, then open it again`), and its files stay byte for byte as they were (the entities that loaded lost their references to the others at load, and a prefab is written
  whole from what loaded: a write would be lossy). The Game hint of the Inspector says saving is blocked. A prefab document that has no unsaved change is not written either (Save and Play of a clean
  prefab leave its files alone).
