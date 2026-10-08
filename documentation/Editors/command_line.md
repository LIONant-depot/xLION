# The command line

One line is one command: `Command -Option value -Option value ...`, or `Session\Command ...` to run it on an open editor (`Main Level\CreateEntity ...`, `list` shows the names).
The same text means the same thing typed in the editor's console, sent through the pipe by a script or an AI, or passed to `xeditorcli`.

## Rules (the Windows command line rules, implemented once in `xcmdline::parser::Tokenize`)

| Write | The command gets |
|---|---|
| words separated by spaces or tabs | one value each |
| `"two words"` | `two words` - inside quotes spaces, tabs and **line breaks** are kept as they are |
| `""` | an empty value |
| `"say \"hi\""` or `"say ""hi"""` | `say "hi"` |
| `C:\dir\file.txt` or `"C:\my dir\file.txt"` | the path as it is: a backslash is only special in front of a quote |
| `"C:\my dir\\"` | `C:\my dir\` (backslashes in front of the closing quote are doubled) |
| `"-5"`, `"-Name"` | a **value** (a quoted word is never an option) |

`Session\Command`: the session is only the first word of the line. A backslash later in the line (a path) is never a session. A session whose name has spaces (a Prefab Editor is named after the prefab: `Keeper Red`) is addressed by its whole name: `Keeper Red\SetProperty ...`.

A **Prefab Editor** (`OpenPrefab -Prefab hexguid`, or a double click on a Prefab in the Asset Browser) is a session like a Level's: the commands of the scene editor go to it (`<Prefab name>\CreateEntity -Scene <the prefab's guid> ...`; the document is the scene of the prefab's own guid), and so do `Play`, `Stop`, `Save`, `Undo`, `Close`. What is its own: `DescribePrefab`, `AddContextScene` / `RemoveContextScene` / `ListContextScenes` (the scenes it is tested against), `SetPrefabGame` / `GetPrefabGame` (the Game it plays with), `ReplacePrefabDocument` (how a save of the prefab from another editor reaches it), `DescribeRoles` (what each scene is in the session and what the last draw did). `<Level name>\EditInContext -Scene hexguid -Id hexid` opens the prefab of an instance in a Prefab Editor placed at the instance, with the Level around it as context. See [the Prefab Editor](prefab_editor.md).

Numbers, hex ids and names without spaces need no quotes. Text always can have them: `SetProperty -Path "Transform/Position/X" -Value "5.000000" ...`, `LogEmit -Text "first line
second line"`. A command is complete at the first line break that is not inside quotes.

An **entity id** (`-Id`, `-Parent`, `-AfterId`) is 64 bits: written with 8 hex digits when it fits in 32 bits (the ids the editor mints, `7E570001`), with 16 otherwise (`7123456789ABCDEF`); a command takes either, in any case, and fewer digits (`7e5712` is `007E5712`). The top bit is reserved: an id above `7FFFFFFFFFFFFFFF` is refused. `ListEntities`, `ListFolders` and the other listings print them the same way. A folder id (`-Folder`) stays 32 bits. A member of a prefab instance has an id derived from its instance's id and its place in the prefab (16 digits, the same after every reload); `ListPrefabOverrides -Scene -Id` lists an instance's members with their ids and addresses, and what the instance overrides (an override whose member the prefab no longer has is marked ORPHAN: `RemoveOrphanOverrides` takes them away). `InstantiatePrefab ... -Parent hexid` places an instance under an entity.

`Name\DescribePrefabOverrides -Scene hexguid -Id hexid` (a query; `-Id` is the instance's root or any of its members, a member of a nested instance answers for the instance placed in the scene) prints, in plain text and one line per item, exactly what the **Prefab Overrides** popup of the Inspector shows: `Instance <root id> "<name>"  Prefab <guid> "<name>"`, `Asked <id>`, `Changes: N  ComponentsAdded=a ComponentsRemoved=r PropertiesModified=m Hierarchy=h Orphans=o` (N is the sum: what the button's `Prefab Overrides (N)` says), then for each member that differs `Member <id> "<name>" <address or (root)>` followed by `  Added <Component>`, `  Removed <Component>` or `  Modified <Component> (n)` with one `    <Property path>: <prefab's value> -> <instance's value>` line per property, then `Hierarchy Removed <member id> "<name>" <address>` / `Hierarchy Added <entity id> "<name>" under <parent id> <address>` and `Orphan <address> <text>` (an override that names a member the prefab no longer has). The member asked about is listed first. It is built from the live instance against the prefab, so it needs no `RefreshPrefab...` first (the listing of `ListPrefabOverrides` is the recipe as stored). The commands the popup runs are the ones that exist: `RevertOverride` (a property row), `RemoveComponent` (an added component), `RevertHierarchyOverrides`, `RevertAllOverrides`, `ApplyOverrides`, `RemoveOrphanOverrides`, `Select`. **Revert All asks "Revert all overrides of X? N changes will be undone (you can undo this)" in the Inspector, and only there**: `RevertAllOverrides` itself never asks, so a script, a test or the AI runs it directly (and `Undo` brings the overrides back). `SetProperty`, `AddComponent` and `RemoveComponent` refuse the prefab instance component itself (the prefab of an instance is not changed from the command line either: `MakePrefab` / `InstantiatePrefab` make instances).

Programs that build commands use `xeditor::Quote(text)` (C++) or `harness.quote(text)` (the smoke tests): it writes any text as one value, whatever it holds.

## xeditorcli

`xeditorcli <command line>` sends the raw command line of the process (`GetCommandLineW`, minus the program name) to the editor: nothing is re-parsed, re-quoted or re-joined on the way,
so the editor sees exactly what was typed. `XEDITOR_PIPE` names another pipe than `\\.\pipe\xEditor_Console`.

## What is still base64

Only **binary** data: the packed `xmath` vectors of `Translate`, `Rotate` and `Scale` (`-Before`, `-After`; `xscene::commands::PackBlob`). Bytes are not text.

## For the editor's tests

`XLOG_USER_DIR` and `XLOG_LOGS_DIR` move the Logs' user state and the launches' folder; the smoke harness sets both (under `smoke/.logs/`) and starts every run from an empty folder, because
retention keeps crashed and interrupted launches over clean ones and the project's own history must not decide what a test finds.
