# xLION Logs - design (V3.1)

> Status: **P0 built and tested** (2026-10-02): the `xlog` library, the build adapter, the pipe commands, the Game.dll tab as a view over the store; everything after P0
> is still design. The rest of this document is the design as agreed. Built on *Signal Console V2* (the pasted V2 spec) and, behind it, the V1 research
> (`Designing an AI-Ready Signal Console for a Multi-Editor Game Engine.md`). V3.1 folds in the owner's feedback (two tabs, the layout width
> concern, a wider scope, doubts about Operations) and a second reviewer's correctness pass (verification, ingestion, undo, identity, durability).
> The aim is wishlist **#5** (a script cannot see why a game build failed): #5 is one question the Logs answer, not a feature of its own.
>
> The central rule, from the review: **Logs records what happened, reports what evidence is available, and only claims verification within an explicitly completed check.**

The editor-facing name stays **Logs**. "Signal Console" is only the architecture's name.

---

## 1. What xLION has today (the survey)

Nine places where "something happened" is written, none aware of the others:

| # | Sink | Where | What is wrong with it |
|---|---|---|---|
| 1 | **stdout** (`printf` everywhere) | process stdout; the smoke harness keeps it in `smoke/.logs/editor_N.log` | Unstructured; a GUI user cannot see it; the physics prints a line per tick; `[Prefab::EnsureLoaded]`, `[System] Tick Logger A` ... all equal |
| 2 | **"Log" drawer tab** (`LogGamePlugin`, `LevelEditor_GamePluginLog.h`) | a *global* `static std::vector<std::string>` + a global mutex | Text only, no severity, unbounded, "Clear" destroys the evidence; build errors are plain lines the reader must find |
| 3 | **Commands drawer tab** (`xeditor::console_log`) | `host.m_ConsoleLog`, entries `{text, System/User/Pipe}` | A command audit trail; a failing command's reason lives only in the reply string |
| 4 | **Compilation tab** (per-asset compile logs) | `Cache/Resources/Logs/<type>/.../log.txt` + the tab | `msg_type` INFO/WARNING/ERROR exists here and nowhere else; per-asset only |
| 5 | **Error popup** (`xeditor::notifier`, `NotifyError`) | a modal, one message at a time | Every error interrupts; the last one overwrites the previous; xGPU's `m_pLogErrorFunc` is wired to it |
| 6 | **xGPU callbacks** (Vulkan validation) | `m_pErrorCallback` / `m_pWarningCallback` -> stdout | 42 identical warnings per run until we filtered the hint; found only by regexes in `conftest.py` |
| 7 | **Crash diagnostics** (`xeditor::diagnostics`) | trace file (truncated per launch) + `LevelEditor.problems.log` (appended) | Separate from everything; invisible in the UI |
| 8 | **Idle work** (`xeditor::idle_work`) | its own panel | Progress and outcome, not connected to problems |
| 9 | **The smoke harness' report** | `conftest.py` regexes over stdout (`ERROR VK\d`, `CRT report`) | Parsing text to find out what the program already knew as structure |

Consequences we already paid for: the Vulkan error that sat in the log "for a while" was invisible to the suite until we taught the harness a regex; a
script that wants to know why a build failed must open an stdout file; an error raised while another editor was in front used to be drawn by nobody.

Things xLION already has that the design reuses (nothing below is a new framework):

- the **Host Drawer** (`xeditor/drawer.h`): one overlay per OS window, edge-attached, only its depth changes, an internal tab bar, Space toggles, bodies filled by `host.m_OnDrawerTab`;
- the **actions / keymap / hint system** (`actions_and_keybindings.md`): every key is a rebindable action, `F1` explains, the palette lists what is live;
- **xundo commands** (query/edit split) and the **console pipe** (`\\.\pipe\xEditor_Console`, one request per connection, 64 KB buffers), also served by the headless host;
- **xproperty** (typed reflection, inspectors), **xtextfile** (typed text tables), **xdelegate** (multicast delegates);
- `xeditor::notifier`, `xeditor::BeginModal`, `xeditor::diagnostics`, `xresource_pipeline` `msg_type`.

---

## 2. V2, decision by decision

**Keep:** the four concepts (event, problem, operation, session); events are the append-only truth, problems are derived; severity / channel / kind as independent
classifications (six levels, no Notice); problem grouping, event folding, mute and capture reduction as four different mechanisms; lifecycle as separate dimensions
("not observed" is not "resolved"); follow-context off by default plus pin; retention honesty; typed source references; a deterministic core with AI as a reader;
log text is untrusted data.

**Change** (V2 adjusted for xLION and for the feedback):

| V2 | xLION V3.1 |
|---|---|
| Three views: Problems, Events, Timeline | **Two sub-tabs: Problems and Events.** Problems is the *state* (what needs attention now); Events is the *evidence* (what happened, with the **ruler**). *Operations are not a tab*: they are the spans drawn on the Events ruler (section 6.4). They stay in the data model and the pipe |
| One scope (project / document / selection / operation) | **Two independent lenses**: *Source* (who produced it: any editor instance, system or script, or all) and *About* (what it concerns: an asset, the selection, an operation). Section 6.5 |
| Sessions: editor, play, build, import | **Session = one editor launch, plus one per Play run.** Builds, imports, compiles, loads are *operations* inside them |
| Three capture profiles | **One policy plus an override table**: each channel has a minimum level (Project Settings, an xproperty page); **Focus** raises chosen channels to Debug/Trace for N minutes. "Full capture" is cut |
| Modal only for fatal failures | **`NotifyError` records and badges; a toast is requested explicitly; a modal only when the user must decide or acknowledge something** (section 6.2) |
| "Resolved after a clean run" / "Success verifies" | **Verification is only claimed within a check's declared coverage** (section 5.2). A successful build is a fact; "these problems are gone" is a separate claim with its own evidence |
| Producer sequence + cross-process clocks | Sequence per producer; clocks matter only for remote runtimes (later) |

**Cut for now:** attachments, Full capture, semantic search, inferred causal clusters, team-shared views, replay, an Operations tab. The record leaves room for
`attachments` and `cause` so none of them forces a migration.

**Added beyond V2** (things V2 does not say because it is not xLION):

1. **The build is the first producer to get right.** MSBuild/cl/link/cmake/shaderc output is parsed into structured diagnostics (`file(line,col): error C2065: ...`), and the whole build is an operation with an outcome and a declared check coverage. This is what #5 needs, and it proves the model on a hostile, high-volume text source.
2. **The smoke harness becomes a client** with a strict result contract (section 7.5): it asks the Logs instead of regexing stdout, and each test is an operation so problems are attributed by correlation, not by time window.
3. **A crash is recovered by the next launch**, without rewriting where it happened (section 4).
4. **The per-frame spam policy.** Channel levels decide what is collected: the physics tick line, prefab-load lines and the system tick loggers default to Trace (never recorded). Disabled calls are rejected before any formatting or allocation.
5. **Headless parity.** The Logs service lives in `xeditor::host` and is pumped by the host thread, not the UI: the headless host has the same store and the same pipe commands.
6. **Annotations are xundo commands where undo means something** (section 7.3).
7. **Actions, not hard-coded keys.** Next/previous problem, focus search, mute, acknowledge, open source are ordinary actions (`Host/Logs/...`).

---

## 3. The model in xLION terms

### 3.1 Vocabulary

| Concept | Meaning in xLION | Examples |
|---|---|---|
| **Event** | An immutable occurrence | "Unresolved external symbol", "Compile of Face.exr finished in 220 ms", "Play started" |
| **Problem** | A persistent diagnostic identity with occurrences | `C2065` for `Kick` in `soccer_player_system.h` |
| **Operation** | A unit of work with parent, origin, subject and outcome (Succeeded, Failed, Cancelled, Abandoned) | Build Game.dll, Compile asset, Load Level, Reload module, Play, a test |
| **Session** | An execution boundary | This editor launch; one Play run |

Not every event is a problem. Command traffic, progress and successful transitions stay in Events.

### 3.2 The record (C++ sketch; the real header is written with the implementation)

```cpp
namespace xeditor::logs
{
    enum class severity : std::uint8_t { Trace, Debug, Info, Warning, Error, Fatal };
    enum class kind     : std::uint8_t { Log, Diagnostic, Command, Progress, State };
    enum class outcome  : std::uint8_t { Running, Succeeded, Failed, Cancelled, Abandoned };

    // Owned values only. A closed set, so an event can always be kept, written and read back after a plugin unloads:
    // no borrowed pointers, no plugin formatter callbacks, no arbitrary xproperty::any.
    using value = std::variant<bool, std::int64_t, std::uint64_t, double, std::string, duration, ref, std::vector<value>>;

    struct ref                       // a typed target, never a string to parse
    {
        enum class type : std::uint8_t { Asset, Entity, File, Graph, Operation, Object } m_Type;
        xresource::full_guid m_Guid;            // Asset / Graph
        std::uint64_t        m_Id;              // Entity (scene permanent id) / Operation / Object
        std::string          m_Path;            // File
        std::int32_t         m_Line, m_Column;  // File
        std::uint64_t        m_Revision;        // what it pointed at when recorded (hash or save counter); 0 = unknown
    };

    struct origin                    // WHO produced it (a different question from what it is about)
    {
        enum class type : std::uint8_t { Editor, System, Script, Tool } m_Type;
        std::string          m_Name;            // stable: "level", "material", "physics", "game.module:Soccer", "msbuild"
        std::uint64_t        m_Instance;        // an open editor instance / document, 0 for singletons
    };

    struct event_key { std::uint64_t m_Session; std::uint64_t m_Sequence; };    // external, persistent identity

    struct event
    {
        event_key      m_Key;                   // session id + sequence: unique across launches, copies and imports
        std::uint64_t  m_ObservedAt;            // collector clock (ns since the session started)
        std::string_view/atom m_Producer;       // STABLE namespace: "msvc.compiler", "vulkan.validation", "xlion.ecs"
        origin         m_Origin;
        severity       m_Severity;  kind m_Kind;
        atom           m_Channel;               // hierarchical: "asset.compile.material"
        std::string    m_Title;                 // the FIRST line: what a list row shows, what a problem is named by
        std::string    m_Body;                  // the rest, raw, any number of lines (see 3.4); empty for a one-line event
        std::uint32_t  m_BodyLines;             // how many lines the body has (the row shows "+N lines" without touching the text)
        // optional
        std::string    m_Code;                  // "C2065", "VUID-vkCmdDrawIndexed-None-08600", "TEX.UNSUPPORTED_FORMAT"
        atom           m_Template;
        std::vector<std::pair<atom, value>> m_Attributes;
        ref            m_Source;                // where it was raised from
        std::vector<ref> m_Subjects;            // what it is about
        std::uint64_t  m_Operation;             // operation sequence in the same session, 0 = none
        event_key      m_Cause;                 // explicit "caused by", zero = none
        std::string    m_Discriminator;         // what makes this occurrence a different problem (see 5.1), empty = unknown
    };

    struct operation
    {
        std::uint64_t  m_Id, m_Parent;          // sequence in the session
        atom           m_Kind;                  // "game.build", "asset.compile", "play.run", "test"
        origin         m_Origin;  ref m_Subject;
        std::uint64_t  m_Started, m_Ended;  outcome m_Outcome;
        // what a success may claim (section 5.2)
        std::string    m_VerificationTarget;    // "Game.dll|Debug|x64|msvc-17.14"; empty = nothing can be verified through it
        coverage       m_Coverage;              // Complete | Subjects | Unknown, + the checked units for Subjects
        bool           m_bEvidenceReady;        // every output reader finished and every record is in the query store
    };
}
```

Required envelope: `key, observed_at, producer, origin, severity, kind, channel, title`. The rest is optional.
Attribute values keep their type, so the Events view can sort `duration > 100ms` and the AI never parses a rendered string. The value set maps onto
xproperty type guids for display, so the inspector can show them without a second type system.

**Identity is persistent.** An event is `session id + sequence`; an operation is `session id + sequence`. Session ids are random 64-bit values written
in the session's header, never a launch ordinal. Interned names (producer, channel, template, attribute keys) are **persisted with the capture** as a dictionary;
a problem's fingerprint uses the *stable name strings*, never a session-local integer. Compact integers are an in-memory detail.

### 3.4 One event, many lines

Information about one occurrence often spans several lines: an MSVC error is followed by `note:` lines and a source excerpt, a Vulkan validation message is a paragraph
with object handles and the spec text, a stack trace is twenty lines, a CMake error quotes its call stack. They are **one event**, not twenty rows.

- `m_Title` is the **first line** (trimmed): the summary the list shows, the text problems are named by, and what the folding and the template are computed from.
  `m_Body` holds the **remaining lines raw** (line breaks kept, indentation kept, never re-wrapped), with `m_BodyLines` counting them.
- **Adapters group continuation lines**: the build adapter attaches `note:`/`see declaration of`/indented source-excerpt lines and the `^~~~` caret lines to the diagnostic they belong to,
  until the next diagnostic or the end of the file's block. An adapter that cannot tell where a block ends emits the lines it is sure of and marks the event *heuristic*.
- **The list shows one line per event** (the title, with a `+12 lines` badge). Expanding a row, or selecting it, shows the **whole body** below it in a monospace block, wrapped to the
  width, with line numbers and Copy; row heights are measured only for expanded rows, so a million collapsed rows cost one line each.
- **Search and queries match the title and the body** (a `body:` prefix restricts to the body); the match highlight shows in the expanded block.
- **Copy** copies title and body together; `Copy as context pack` includes the body up to the pack's budget.
- **A size cap protects the store**: a body is kept up to a limit per event (default 64 KB); beyond it the tail is replaced by `... 1,204 more lines not kept` and the event is marked `Summarized`.
  Very long single lines are kept whole up to the cap and wrapped by the view.
- **On the pipe** a row carries only the title and `Lines=N`; `LogEvent -Id e` returns the body as continuation lines prefixed with `| ` (so they can never be mistaken for a reply row), within the reply budget and with `Truncated=true` and a cursor when it does not fit.

### 3.3 Channels, codes, operation kinds (the vocabulary xLION starts with)

```text
Channels   editor.command   editor.ui   editor.crash
           asset.compile.<type>   asset.import   asset.library   source.control
           game.build   game.module   game.runtime
           level.load   level.save   scene.edit
           gpu.vulkan   gpu.device     physics   ecs.system
Operation kinds
           game.build   game.reload   asset.compile   asset.import   level.load   level.save   play.run   idle.job   command   test
Origins    Editor: level, material, texture, geomstatic, ... (one per open instance)   System: physics, renderer, asset.pipeline, source.control, idle.work, gpu
           Script: game.module:<name>   Tool: msbuild, cmake, shaderc
```

Codes are owned by the producer. Compiler codes pass through (`C2065`, `LNK2019`; shaderc gets `SHADERC.<n>`), Vulkan uses the VUID, engine diagnostics use `AREA.WHAT`.

---

## 4. Architecture

```text
 producers ──► typed API / adapters ──► bounded ingest ──► HOST thread drains ──► query store ──► indexes ──► Logs window
 (any thread)                           ring (no blocking)   (also headless)      │                         └► pipe commands
                                                                                   └► bounded writer queue ──► append files (writer thread)
```

- **Owner.** `xeditor::host::m_Logs` (a member, like `m_Notifier`), reachable from any producer through `host::current()`. No global vectors, no global mutex; `LogGamePlugin`'s global store goes away.
- **Emit API, in order of preference**
  1. *Typed*: `Logs.Diagnostic({...})` and `auto Op = Logs.Begin("game.build", {...}); ... Op.Succeed()/Fail()`. An operation destroyed without an outcome is recorded **Abandoned**, never Succeeded. Macros check the channel's level **before** formatting or allocating; a disabled call is one load and one compare.
  2. *Adapters* for what we do not own, each parsing into the same record and marking derived fields as heuristic: the MSBuild/cmake/shaderc output parser, `xresource_pipeline` `msg_type` messages, the xGPU callbacks, `NotifyError`, the command audit trail, idle-work progress.
  3. *Raw `printf`*: left alone in the first phases (still on stdout, still read by the harness). A later phase may tap stdout; a tap only produces legacy-grade events.
- **The host thread drains; the UI is only a client.** Any thread emits onto the bounded ring. **The host thread** (one per frame in the UI host, once per loop iteration in the headless host) drains it, assigns keys, interns names and updates counts. Background threads never touch ImGui or the store.
- **Ingestion barrier (the answer to "I asked before it arrived").**
  - Every query **drains the ring first**, on the host thread that serves the pipe, so anything pushed before the query is in the answer.
  - An operation's terminal record is published **only after its output readers have finished and been parsed** (the build's stdout/stderr readers, the compile job's message queue). Until then it reports `EvidenceReady=false`.
  - Replies carry `CommittedThrough=<n>` (a monotonic commit counter) and each operation `EvidenceReady`. A client that needs the final answer **polls** (the harness already has `wait_for`); the host thread never blocks waiting for a worker (it is the thread that would drain the ring). A timeout means *not ready*, never *no problems*.
  - Waiting for ingestion is not waiting for the disk, and a barrier never turns dropped records into complete evidence.
- **Bounded, and honest about it.** The ring is bounded; overflow never blocks a producer. Capacity is reserved for diagnostics and operation boundaries (lower levels are dropped first). Every drop, summarization and expiry is counted and reported by `LogStatus`.
- **Completeness is judged against the declared policy.** Three separate things: a **presentation mute** (never affects coverage), a **capture exclusion** (a channel below its minimum level: intentional, shown in the status, not "loss"), and **collector loss** (ring overflow, writer failure: affects coverage). Excluded Trace traffic does not make a session look Partial; otherwise every default session would be "incomplete" and the badge would mean nothing.
- **Durability and recovery** (the append contract matters more than the file format):
  - The authoritative stream is **one append-only sequence of records**: events *and* operation start / update / end. `operations.txt` and the problem/facet indexes are **rebuildable projections**; two authoritative files can never disagree after a crash.
  - Every file has a schema version; the dictionaries of interned names are persisted in the stream; every record is framed (length + checksum) so the last complete record is identifiable, and a **torn final write is truncated** on open.
  - Serialization and disk I/O run on a **writer thread** fed by a bounded queue, never on the frame-critical drain. The status shows `PendingWrite=n` and `PersistenceFailed` (with the reason); a failure never blocks emitters and is itself a Fatal-class collector-health problem that cannot be muted.
  - Format: **xtextfile tables** for the first versions (typed columns, readable, consistent with the project), one chunk per N records. *Open decision 1.*
  - Location: `<project>/Cache/Logs/<session id>/...`.
- **Retention.** *Prefer* retaining crashed sessions and failed builds; *explicitly pinned* captures are protected; under the hard size budget, unpinned evidence is evicted by priority and recorded as **Expired**; if protected evidence alone exceeds the budget, the status reports storage pressure and the limitation it causes. Small problem summaries may outlive their bulk payloads (their detailed evidence then reads *Expired*).
- **User state** (acknowledgements, mutes, saved views, Logs layout): one xproperty-reflected object per user, `Project.config/Logs/<user>.logs.txt`, beside the keymap.
- **Crash recovery.** `xeditor::diagnostics` is untouched and stays dependency-free. At the next launch the Logs import the previous session's tail **without rewriting its origin**:
  - recovered records keep `Original session = <previous>` and are marked `Observed during = <this launch>`;
  - a persistent **import checkpoint** stops the same tail from being imported twice;
  - the termination is classified, not assumed: **Confirmed crash** (a crash record exists), **Interrupted shutdown** (no clean-exit marker, no crash record), **Unknown**. A missing marker alone never says "access violation";
  - operations that were running in that session are marked Abandoned, in that session.

### 4.0 Packaging: xlog is a library of its own

The Logs are not part of any editor: they are a dependency the editors, their plugins, the compilers' adapters and the tools all use, so it lives in its own depot
repository, `dependencies/xlog` (header-only, declared to CMake like `xdelegate`; `FetchAndPopulate` in the root `CMakeLists.txt`, and xeditor's `updateDependencies.bat`).

```text
xlog                       knows nothing of any editor
  source/xlog.h            umbrella: the core
  source/xlog_hub.h        record types, the hub (ring, store, problems, operations), the query grammar          standard library only
  source/xlog_build.h      the MSBuild / cl / link / CMake output adapter                                        <regex>
  source/xlog_commands.h   the pipe commands, registered into ANY xundo::system                                  xundo, xcmdline
  editor/xlog_tab.h        the Logs window, to embed in any editor                                               ImGui, xeditor widgets (EDITOR PART)
  editor/xlog_diagnostics.h the diagnostics view (the editors' Feedback)                                        ImGui, xeditor widgets (EDITOR PART)
xeditor                     depends on xlog: xeditor::host OWNS the hub, makes it current, drains it in pump_services()
plugins (xlevel, ...)       depend on xlog: reach the hub with xlog::hub::current(); the Game.dll tab is xlog::RenderTab with channel "game."
```

- **Finding the hub.** `xlog::hub::current()` (the owner calls `make_current()`, the way `xeditor::host::current()` works). A producer with no hub simply does not record; no producer ever blocks on the log.
- **Opt-in headers.** A tool that only emits includes `xlog_hub.h`; the build adapter, the commands and the tab are separate so nothing pays for what it does not use.
- **The commands are not xeditor's**: they register into whichever `xundo::system` the host gives them (the workspace one today), so a headless host, a compiler process with a pipe, or a test harness gets the same queries.
- **Namespaces**: everything is `xlog::`; xeditor keeps only the two small producers that belong to the host (`NotifyError` and the command audit trail), which emit through the hub.

### 4.1 Scale: jobs, snapshots and levels of detail

A busy editor session produces hundreds of thousands of events (a Play run with the physics and the systems talking, an import batch, a long build), and the owner's rule is
that the editor stays responsive however many there are. The design therefore fixes **who is allowed to do what**:

**The host thread does O(1)-per-event work, under a budget, and nothing else.**
- It drains the ring with a **per-frame budget** (about 0.5 ms and a cap on events); what does not fit waits for the next frame, and the status shows the backlog (`Draining 18,200 behind`). A backlog is visible, never silent, and never stalls the frame.
- Per event it only: assigns the key, interns names, appends to the current segment, updates the counters, and updates the problem it belongs to. No sorting, no searching, no string scans, no allocation beyond the segment arena.

**Everything heavier is a job on `xscheduler`** (the scheduler the editor already starts, the one idle work uses at low priority):

| Work | Runs as | Notes |
|---|---|---|
| Query / filter / search over many segments | a **job per segment batch**, results merged | cancelled by a *query generation*: typing in the search box supersedes the running query at once |
| Text search over titles and bodies | jobs over the sealed segments; the live segment is scanned on the host thread (it is small) | segments carry a code/channel dictionary and a small bloom filter, so most are skipped without a scan |
| The ruler's density strip | **precomputed while ingesting** into a pyramid of buckets (1 s, 10 s, 1 min, 10 min) per severity and per origin | drawing is O(width of the strip), independent of the event count |
| Problem aggregation | incremental, on the host thread (O(1) per occurrence) | the retained occurrences per problem are bounded (first N, last N, an exemplar per distinct variant); the rest are counters, reported as `Summarized` |
| Folding repeated events | incremental at ingest: a run `(template, origin, window)` is one record with a count | the Events list shows the run; expanding shows the retained members |
| Writing to disk | a **writer job** (see Durability) | never on the drain |
| Retention, compaction, index rebuild | **low-priority jobs**, exactly like idle work, listed in the Idle Work panel with progress | cancellable; a rebuild never blocks a query, which uses the previous snapshot |

**The UI reads immutable snapshots.** Segments are **append-only and immutable once sealed** (a few MB each); the live segment is the only mutable one. A *snapshot* is
`(list of sealed segments, a watermark in the live one)`, which is what a query (and every pipe reply: `Snapshot=...`) is evaluated against. Taking one is O(1); a job
holds it without a lock; eviction waits for the last reader. The UI never walks the store: it holds a **result set** (a vector of event indices, or runs) produced by a job and
draws **only the visible rows** with a clipper, so the cost of a frame is the number of rows on screen, not the number of events.

**Levels of detail keep the picture readable as the count grows.**
- **Events list.** Up to a comfortable count it is a flat list. As the result set grows or the ruler range widens it **folds by run**, then **groups by problem or template** ("1.2 M events in 40 s: 9 problems, 14 busy templates; zoom or select a range to see events"). The count of hidden rows is always shown; the user never scrolls a million rows.
- **Ruler.** Zoomed out it shows the pyramid's coarse buckets coloured by worst severity; zooming in swaps to finer buckets and finally to individual event ticks; operation spans below a pixel width merge into a labelled "n operations" block. The strip is a **heat map per origin** when the Source lens has more than one entry, so "who is loud" is visible at a glance.
- **Top talkers.** A small panel (and `LogStatus`) lists the busiest channels/templates by rate with one click to **exclude (capture level)**, **mute (presentation)** or **Focus**, so noise is dealt with where it is noticed.
- **Storm mode.** When a channel exceeds a rate for a few seconds, the collector switches **that channel** to aggregate mode (counts, first/last, exemplars, a rate histogram) and writes a `telemetry.compacted` record with what it did and why. Errors and fatals are never put in storm mode; their repeats are occurrences of one problem.
- **Problems** stay small by construction (one row per identity), whatever the occurrence count.

**Budgets are part of the contract** (and tests, section 9): the host thread spends no more than the drain budget per frame; a UI frame touches only visible rows; a query over one million events returns its first page in well under a second *while the frame rate does not move*; ingest sustains at least a hundred thousand events per second per producer thread; memory is bounded by the segment cap and the eviction policy, never by the session length.

---

## 5. Problems, identity and lifecycle

### 5.1 Identity

```text
problem = hash( producer namespace, code, site, subject, discriminator )          family = ( producer namespace, code )
```

- **Typed producers** give code, site, subject and, when they are confident, a **discriminator** (for a compiler error: the offending identifier; for a missing component: the component guid). Without one the problem is labelled **Heuristic grouping** and its key is inspectable.
- Compiler errors start with `site = file:line` (not the column). That is a heuristic: a line shift changes the identity, and two `C2065` on one line can concern different identifiers, which is exactly what the discriminator is for.
- Vulkan: `code = VUID`, `site = object type`, `subject = debug name`; a debug name is a label, not a unique id, so `unnamed` never silently merges distinct objects into a confident identity (heuristic badge).
- **Never in the identity**: timestamps, addresses, handles, session ids, the rendered text.
- **A family is a view**, not an identity: problems with the same producer and code share a collapsible heading even when site or subject differ. Narrower grouping is an option.
- **AI never merges identities.** It may suggest "related"; only an explicit command links.
- The grouping algorithm is versioned. Acknowledgements and mutes are stored against the *identity key and version*; after a version change a stored annotation is re-attached **only when the correspondence is unambiguous**; otherwise it becomes an **unmatched annotation** shown in the footer, never broadly re-applied.

### 5.2 Lifecycle (four independent dimensions) and what verification means

| Dimension | Values |
|---|---|
| Triage | Unreviewed, Acknowledged |
| Verification | Unverified, Reproduced, **Verified resolved** |
| Suppression | None, Temporary mute, Policy mute |
| Run presence | Observed, Not observed, Unknown |

**A success is a fact; "these problems are gone" is a separate claim.** A successful build can still emit warnings, an incremental build skips targets, and the
*subject* of a diagnostic (`soccer_player_system.h`) is not the *verification target* (the `Game.dll` build). So:

> A successful operation may verify earlier problems **only within the diagnostic coverage its producer declared**. Matching operation kind and verification target is necessary, not sufficient.

```text
Verification target   Game.dll | Debug | x64 | msvc-17.14                (operation field)
Coverage              Complete target check | Selected units checked | Unknown
Check unit            what produced a problem: the translation unit or job that ran (soccer_game.cpp)
```

- Successful **full** build with complete diagnostic capture: a covered problem that did not recur may be verified.
- Successful **incremental** build: only the units the build actually compiled count as checked (the adapter records them from the compiler's own file lines); problems whose check unit was not recompiled stay *Not observed*.
- A problem that **occurs again** in a successful operation is *Reproduced*, whatever the exit code.
- Unknown coverage, or a collector loss touching the relevant channel, **does not verify**.
- A *presentation mute* does not change coverage: a muted problem that was really rechecked, with complete evidence, can be verified.
- If a verified problem occurs again it is a **Regression**; an acknowledged one that returns is **Recurring**.

**For P0 the Logs expose "Build succeeded" and the problems of that build; automatic verification arrives in P2**, with coverage. Two facts, two phases.

### 5.3 Four noise mechanisms (never presented as equivalent)

| Mechanism | Evidence behaviour |
|---|---|
| Problem grouping | occurrences stay individually addressable while retained |
| Event folding (Events tab) | presentation only; "Physics contact rejected x420 - 3 objects - 2.1 s", expandable |
| Mute | collection continues; the hidden count stays visible; never rewrites severity; Fatal and collector-health problems cannot be fully hidden |
| Capture policy (channel levels, Focus) | may skip whole levels; reported as intentional exclusion in the status |

Progress events update one row and keep only boundaries and milestones.

---

## 6. UX / UI

### 6.1 Where it lives

- A tab of the **Host Drawer** named **Logs** (it replaces the current "Log" tab, index 4), with **two sub-tabs: Problems | Events**. The drawer already follows the user across editors, remembers its edge and depth, and opens with Space.
- **Commands** stays its own drawer tab: it is an *input* surface. What it runs is also recorded as `kind=Command` events (origin System / User / Pipe, as today).
- **Compilation** and **Idle Work** stay as job views (progress and per-job controls); their messages and outcomes are *also* events/operations, so the Logs can answer questions about them.
- Opening Logs from any editor keeps: selected problem/event, search, filters, source and about lenses, session, scroll, pinned lens. State belongs to the drawer, not to an editor.

### 6.2 Closed drawer: the badge, the toast, the modal

- The **status line** (the bottom strip that already lists the mouse gestures) gets a quiet right-aligned item: `Logs  2 errors  1 new`. It counts **distinct problems**, not occurrences. Click opens the drawer on Problems. A muted or filtered *fatal* still shows `1 critical`.
- **`NotifyError` keeps its signature** (30+ call sites) and, by default, **records and badges**. A **toast** appears only when the caller asks for one (a command the user just ran from the UI, Save, Compile, Play): one line, **Open problem**, stacks, expires, never blocks input.
- A **modal** (`xeditor::BeginModal`, centered on its editor) only when **the user must decide or acknowledge** something (save failed: choose another path; discard or keep; a data-loss risk) or on a fatal. A failure alone, even a blocking one, is a toast.
- Ordinary notifications never take focus, play sounds or flash; a modal necessarily captures interaction, which is why it is rare.

### 6.3 Problems (the summary / state) and the width concern

Problems is a **state summary, not a second window**. It is one **compact header** and a **list that owns the full width**:

```text
┌ Logs ──────────────────────────────────────────────────────────────────────────────────────────────┐
│ Problems   Events                                                  Session: This launch ▾   [Pin]  │
│ Source: [All ▾]   About: [Anything ▾]        🔍 sev>=error channel:game.*      [New 2] [Active 4] [All]
├─────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ ● C2065    undeclared identifier 'Kick'                 soccer_player_system.h:80   game.build  ×3  8s │
│   ▾ details: Build Game.dll — Failed · Recurring · evidence full 3/3 · [Open source] [Show in Events]… │
│ ● LNK2019  unresolved external symbol                   Game.vcxproj                game.build  ×1  8s │
│ ▲ ECS.COMPONENT.MISSING  Physics                         Ball (entity 0x0102)        level.load  ×6  2m │
│ ▲ VUID-vkCmdDrawIndexed…   [heuristic]                   gpu.vulkan                  Material    ×2  5m │
├─────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 2 error problems · 2 warning problems · 12 occurrences · 3 hidden by mutes · capture OK · 0 dropped   │
└─────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

- **Details are inline by default**: selecting a row (Right arrow, or a click on its chevron) expands the details *under that row* and the list keeps its full width. Two rows can be open; Left arrow or `Esc` collapses.
- **A detail pane to the side is optional**, never the default: when the drawer is tall *and* wide enough that the list still keeps at least ~560 px, a splitter offers a right pane (default **30%**, never more than 40%, remembered). Narrower, the pane is unavailable; the option hides rather than squeezing the list. The **bottom strip** layout (list above, details below) is the third choice for a deep, narrow drawer. The user picks one; inline is the default.
- The list never needs the width the Resources/Assets tabs need *at the same time*: the Logs are one drawer tab, so they never sit beside the asset browser; the concern is only the list's own width, and the list keeps all of it.
- Row columns, left to right: severity glyph, code + title, subject (the asset, entity or file:line), channel/origin, occurrence count, last seen. Columns that do not fit disappear right to left (last seen first); the title and the subject are the last to go.
- **Presets**: **New** (first seen after the *baseline*), **Active**, **All**. The baseline is stored explicitly (a session id and a commit watermark plus the lens); by default it is the start of this launch, and `LogMark -Kind baseline` moves it.
- **Stable order**: Fatal/blocking, Error, Warning; inside a group new or regressed first, then recent. The list **does not reorder while the user reads or has a selection**: a chip says `3 new problems` and applies on click. Families collapse under a heading.
- **Colour**: the editor theme is muted. Severity is a **glyph and a thin left edge**; colour only on the glyph, the edge and the counts; selection from the theme. Rows are never filled red or yellow.
- **Muted rows are not drawn**; the footer says `3 hidden by mutes` and clicking it shows them.

### 6.4 Events (the evidence) and the ruler

Events is the chronological view, topped by the **ruler**. Operations live here, as spans on the ruler, not in a tab of their own.

```text
┌ Logs ───────────────────────────────────────────────────────────────────────────────────────────────┐
│ Problems   Events                                                  Session: This launch ▾   [Pin]   │
│ Source: [All ▾]   About: [Anything ▾]        🔍 sev>=warning                    [Follow] [Fold]     │
├──┬──────────────────────────────────────────────────────────────────────────────────────────────────┤
│  │ 0s        10s        20s        30s        40s        50s        1m                         now   │
│  │ ▁▁▂▁▁▁▁▃▁▁▁▁▁▁▁▁▁▁▁▁▅▇▃▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▂▁▁▁▁▁   (events per second, coloured by worst severity)    │
│op│ ├─ Load Level ─────┤ ├─ Build Game.dll ───────────────────✗┤ ├─ Play ─────────────────────────   │
│  │ ├ compile ✓ ┤ ├ compile ✗ ┤  ◆baseline            ● first seen C2065                              │
├──┴──────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 12:04:11.204  ▲  level.load       ECS.COMPONENT.MISSING  Physics on Ball                             │
│ 12:04:19.870  ●  game.build       error C2065: 'Kick' undeclared identifier        soccer_player…:80 │
│   …                                                                                   127 new events ↓│
└─────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

- **The ruler**: session start to now, an event-density strip coloured by the worst severity in each slice, **operation spans** as bars in lanes (nesting shown by lane; failed ones with a ✗), bookmarks (baseline, test, note), and *first seen* markers for problems. Wheel zooms, drag selects a time range which **filters the list below**; double-click a span selects that operation (the list filters to *within the operation*); a gap in coverage is drawn hatched.
- **The operation in the details**: an event/problem shows its operation chain as a breadcrumb (`Play > Load Level > Compile 37 shaders`) with *Show span* and *Filter to this operation*. That is all the "operations UI" the first versions need.
- **The list**: virtualized (`ImGuiListClipper`), **one line per event**: time, severity glyph, channel, the title, and a `+N lines` badge when the event has a body; selecting or expanding a row shows the whole body below it (section 3.4); attributes in the row detail; optional folding (`Physics contact rejected x420 - 3 objects - 2.1 s`, expandable). Scrolling away from the bottom suspends *UI follow*, never collection; a button `127 new events` returns.
- Original severity and payload stay visible when something is muted or grouped.

*Why not an Operations tab.* An operation answers "did that work, how long, what was inside it". The ruler answers it where the evidence already is, and the breadcrumb ties
an event to its operation. A tab would repeat the Compilation and Idle Work views. If using the Logs shows a tab is missed, it is cheap to add later: the data model and
`LogOperations` already exist. *Open decision 6.*

### 6.5 Two lenses: Source and About, plus the session

The owner's point: scope should be *any editor instance, any system, any script, or all*. That is a different question from what an event is about, so there are two
lenses, both visible as chips, both saved and pinned together:

- **Source** (who produced it; the event's `origin`): a small tree with checkboxes.

```text
Source ▾   ☑ All
           Editors     ☐ Level (Soccer)   ☐ Material (M_Hair)   ☐ Texture (Face)
           Systems     ☐ Asset pipeline   ☐ Source control   ☐ Physics   ☐ Renderer / GPU   ☐ Idle work
           Scripts     ☐ Game.dll   ☐ Soccer module
           Tools       ☐ MSBuild   ☐ cmake   ☐ shaderc
           ─────────
           Current editor      Follow focused editor ○
```

  Any subset; *Current editor* is a shortcut for the focused editor instance. The tree lists what exists (open editor instances, registered systems, loaded script modules).
- **About** (what it concerns; the event's `subjects`): *Anything*, *This asset* (the focused editor's document), *The selection* (direct references), *This operation*, *Custom*. "Include related dependencies" is an explicit toggle.
- **Follow** is off by default; when on, the chips show the real target and say "following". **Pin** freezes both while the user moves between editors. Selecting an event changes the details, never the query.
- **Session** (separate dropdown): *This launch*, *Latest play*, *Previous launches*, *Saved capture*. Query anchors: `since:last-build`, `since:last-play`, `since:last-save`.

### 6.6 Search

One query model with two faces: typing and the chips compile to the same normalized query; an invalid query explains itself inline and never silently returns nothing.

```text
sev>=error           channel:game.*            code:C2065          origin:editor:level          asset:"Characters/Hero/Face"
op:build             state:new                 session:latest-play  since:last-build              duration:>100ms
-channel:physics     "free text"               attr.format:png      outcome:failed
```

The status line says `12 matching problems · 430 matching occurrences`; if only some occurrences of a problem match, the details say so.

### 6.7 Details (order matters)

1. **What failed**: title, code, severity, state, whether it blocks.
2. **Where**: typed source and subject as buttons (*Open source*, *Reveal asset*, *Select entity*, *Show span*). A reference whose revision no longer matches offers *historical evidence* or a **clearly labelled current counterpart**; it never jumps silently to a different object.
3. **Evidence**: typed attributes, retained occurrences with changed values, the evidence state (`Full / Summarized / Partial / Expired`) with honest counts: `12,840 observed · 64 retained · rest summarized`.
4. **Before and after**: bounded surrounding events.
5. **History**: first/last seen, regressions, rate, other sessions, verification and its coverage.
6. **Actions**: Acknowledge, Mute…, Copy as context pack, Focus capture on this channel, (later) Ask AI.

### 6.8 Keys (all ordinary actions, scope `Host/Logs`: rebindable, in the palette, explained by `F1`)

| Action | Default key | Notes |
|---|---|---|
| `Host/Logs/NextProblem`, `PreviousProblem` | `F8`, `Shift+F8` | works with the drawer closed: opens the source, like an IDE |
| `Host/Logs/OpenSource` | `Enter` | the primary navigation (also double-click) |
| `Host/Logs/ExpandDetails`, `CollapseDetails` | `Right`, `Left` | inline details; `Esc` collapses |
| `Host/Logs/FocusSearch` | `Ctrl+F` while the Logs have the focus | |
| `Host/Logs/Acknowledge` | `A` | |
| `Host/Logs/Mute` | `M` | opens the presets; `Shift+M` repeats the last |
| `Host/Logs/CopyContext` | `Ctrl+C` on a selection | a context pack, not rendered lines |
| `Host/Logs/ToggleFollow`, `Pin` | unbound | |

(Space is the drawer's key, so it is not used inside.) Hints (`xeditor::hint`) say what each control does and *why it is unavailable* (e.g. *Verify is unavailable: this problem has no producer recheck*).

### 6.9 Empty and edge states

- No problems: `Nothing needs attention. 0 problems · capture OK`.
- Collector trouble (ring overflow, writer failure, storage pressure): a banner with counts; never hidden by a mute.
- A session loaded from disk with a missing or torn chunk: `Partial` and the interval; a recovered crash tail says `Confirmed crash`, `Interrupted shutdown` or `Unknown` and which launch it came from.
- A million events: virtualized lists, incremental counts, no per-event widgets.

### 6.10 Resource editors: their compile errors, generic and easy to read

Every resource editor (Texture, Material, GeomStatic, ...) has the shared top bar with **Compile (F5)** and **Feedback (F6)** (`xeditor_toolbar.h`). Today the Feedback button is a
colour, and its popup is a fixed 600 x 300 box that dumps the validation-error strings (`Model.m_pValidationErrors`) and the compiler's raw log text (`Model.m_Log`). Each editor shows
that same text, and a reader has to find the error in it. The Logs make this generic, with **no editor writing its own error UI**:

**One source.** An editor's compile is an `asset.compile` operation whose subject is its document's asset; the compiler's messages (`xresource_pipeline` `msg_type` INFO/WARNING/ERROR,
the per-asset `log.txt`) enter through an adapter as events of that operation (channel `asset.compile.<type>`); a validation error of the descriptor is a `kind=Diagnostic` event whose
subject is the property path. The editor supplies only *which asset it edits*.

**One view, embedded.** `xlog::RenderDiagnostics(hub, { .m_Subject = asset, .m_OperationKind = "asset.compile" })` draws it; the Feedback popup becomes this view, and the same call can
sit as a persistent strip under the toolbar. It reads only the store, on the host thread.

```text
┌ Build ──────────────────────────────────────────────────────────────────────────────────────┐
│ ✗ Build failed · 2 errors · 1 warning · 1.2 s · 8 s ago              [Open in Logs] [Copy]   │
├─────────────────────────────────────────────────────────────────────────────────────────────┤
│ ● TEX.UNSUPPORTED_FORMAT   Unsupported texture format 'exr' (32 bit)                         │
│     Face.exr · asset.compile.texture                                       [Open source]  ▾   │
│       supported: png, dds                       ← the rest of the event: its body, expanded   │
│ ● Property 'Filter' is out of range                                       [Select property]   │
│ ▲ Mip count clamped to 12                                                                 ▸   │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```

- **State first.** One line says what happened: *Not built yet*, *Compiling... 3 s* (with the latest progress line), *Built in 1.2 s*, *Build failed · 2 errors · 1 warning*, or *Build cancelled/abandoned*. The Feedback button's colour is this state, not a second source of truth.
- **Problems, not a log.** Errors first, then warnings (collapsed to a count until asked), each row one line: glyph, code + title, subject. The body of an event (a compiler's `note:` lines, a stack, a quoted source line) expands under its row in a monospace block that wraps to the panel.
- **Navigation through typed references.** *Open source* (file:line), *Select property* (a descriptor property path), *Select node* (a graph node): the view returns the reference and **the editor performs the navigation**, because only it knows how to select its own things. A reference whose target changed offers history, never a different object.
- **Honest.** If the output is not complete (`EvidenceReady=false`, collector loss) the line says so; an operation that failed without a diagnostic shows *failed without diagnostic details*.
- **Fits the panel**, not a fixed box: it uses the width it is given, wraps long lines, keeps the muted theme, and works in the narrow side panels the resource editors have.
- **Same keys and same data as the Logs window**: `F6` still opens it; `F8`/`Shift+F8` walk the problems; *Open in Logs* opens the drawer with the lens already set to this asset and operation; the pipe's `LogProblems -Operation n` returns exactly the rows the view shows.
- **Phase**: P1, right after the Problems window, because both use the same row renderer. P0 already carries what it needs (operations with subjects and outcomes, title + body events, typed references); the pipeline-message adapter arrives with it.

**As built in P1 (2026-10-02), and where it differs from the sketch above**

- **One bridge, not one hook per editor.** `xeditor::compile_log_bridge` (`source/Tools/Editor/xeditor_compile_logs.h`) listens to the library manager's compile notifications and records every asset compile as an `asset.compile` operation, whether or not an editor is open (the project's startup compiles are in the Logs too). Start and end of a compile share its log object, which is how the cascade notifications to dependents are told from new compiles. The compiler's text goes through `xlog::pipeline_output_adapter` (`[Info]/[Warning]/[Error]` lines, untagged continuation lines as the body, progress bars as debug-level progress). The pipeline gives no codes, so its problems are heuristic; the asset is part of the identity.
- **Feedback (F6) goes to the Logs**, it is not a popup of its own: the drawer opens on the Logs tab, Events page, filtered to `op:<the asset's last compile>` (with no compile yet: `channel:asset.compile`). The popup stays only when the descriptor has validation errors (those are the document's live state, not build events; they are not recorded as problems so a fixed one never lingers as an unverified problem). `xlog::RenderDiagnostics` (`editor/xlog_diagnostics.h`) draws that popup and can be embedded elsewhere.
- **Back.** Anything that moves the person inside the Logs (Feedback, *Show in Events*) pushes a snapshot first: the window's query, page, preset, selection, and, when the host sent them, **what the drawer had in front** (another tab, or closed). The `< Back` button (and `LogBack`) returns to it, drawer included. Bounded to 16.
- **Annotations are undoable commands** (`LogAcknowledge`, `LogMute`, `LogMark`), run through the host's history when the window has a runner; a Fatal problem cannot be muted. `LogProblems -State New|Active|All [-IncludeMuted true]` returns the window's list; `LogWindow` reports what the window shows.
- **Window**: Problems|Events with inline details on Problems (virtualized Events with the selected event's body in a strip below), presets with counts, the list not moving under the reader (a `N new problems` chip), `Mark seen`, footer with muted count and capture health.
- **The rest of P1, as built:**
  - **`NotifyError` policy**: `NotifyError(msg, style)`: *Badge* (the default: recorded, counted), *Toast* (what the person just did that failed: a line that stacks above the badge, expires after 8 s, never takes focus; `NotifyToast`), *Modal* (they must decide, or the editor cannot go on: failed inits; `NotifyModal`). Every call site is classified (38 toasts, 3 modals); every error is recorded whatever the style.
  - **Badge**: `Logs  2 errors  1 warning  3 new` at the bottom right while the drawer is not showing the Logs; distinct problems that still need attention (acknowledged and muted ones are not counted; a Fatal is counted critical whatever was done to it). `LogStatus` prints the same counts.
  - **Lenses** are tokens of the query, not state of their own: *Source* is `origin:a,b` (the chip lists the origins that have spoken, by kind), *About* is `op:N` or `asset:X` (an id of 8+ hex digits or a part of a name; the chip offers the selected row's operation and asset). Also `producer:`. `LogLens` edits the same tokens.
  - **F8 / Shift+F8** (`Host/Logs/NextProblem`, `PreviousProblem`): the next problem of the window's list, selected there, its source opened, with the drawer closed too; wraps.
  - **xGPU adapter** (`xeditor/gpu_log.h`): Vulkan validation lines become `gpu.vulkan` diagnostics of producer `vulkan.validation` with the VUID (or the VK result name) as code, where xGPU said it as the body; a message is a bug of the program, never a modal. Made-up lines (tests) have their own producer, `xlion.simulated`.
  - **Harness as a client**: `Editor.vulkan_problems()` reads them from the Logs; the report lists where the Logs and the text matching disagree, and a run fails if either finds a Vulkan error, until the Logs are trusted alone.
- **Not built**: jump-to-line in the person's IDE (a file opens with the system handler when it exists, and `path:line` goes to the clipboard).

**As built in P2 and P3 (2026-10-03)**

- **Verification** (`LogVerify`, `verification` of a problem: Unverified / Reproduced / Verified): an operation that ends *Succeeded* with a `coverage` that includes the problem's target verifies it (`Verified resolved`, with the operation that did); a success that did not check it proves nothing (coverage *Unknown* never verifies). A verified problem that comes back is a **regression** (`Regressions` counts), one the person acknowledged that comes back is **recurring** and asks for attention again. `LogVerify -Id` asks the producer to look again through the recheck registered for its channel (`game.build` is one).
- **Capture policy and Focus**: the hub captures from Debug up by default, Trace is excluded and *counted* (`LogStatus Capture`); `LogFocus -Channel p -Minutes n` collects a channel at Trace for a while (undoable: Undo restores the policy, it cannot recover what was not collected meanwhile).
- **`LogContext`**: the deterministic, bounded pack to understand a problem (what the Copy button puts on the clipboard).
- **Persistence** (`xlog_store.h`): every committed record is written by a writer thread to `<project>/Cache/Logs/<session>/stream.xlog` as framed, checksummed lines (a torn tail is cut off on read); `summary.txt` and `pinned` sit next to it. A launch ends *clean* (a marker), *confirmed crash* (the crash record `LevelEditor.problems.log` has for that pid), *interrupted* (no marker, no record) or *unknown*. The next launch imports the earlier ones on a worker thread: it reports `SESSION.CRASHED/INTERRUPTED/UNKNOWN_END` diagnostics (channel `session.previous`) and loads the last three launches back so that a problem verified or present then can regress or recur now. Retention keeps 20 launches / 200 MB: clean ones go first, pinned and the current one never. `LogSessions` lists them, `LogCompare` says what changed between two.
- **The ruler** (top of the Events page): the launch on a time axis. A density strip (events per second, built as events arrive, so it costs the width of the strip, not the number of events; the worst severity of a stretch colours it), the operations as spans in lanes (red when failed), the baseline marker. Wheel zooms around the pointer, **dragging selects a range and writes `time:A-B` in the query** (so the list, `LogEvents` and `LogProblems` show the same), a click on a bar selects `op:N`, the right button (or a double click) shows the whole launch again. `LogRuler` returns the same data. `time:` takes seconds since the launch started, either end optional; a problem matches when it was seen at some time inside the range.
- **Saved views and what you decided** (`xlog_store.h`, `StartUserState`): acknowledgements, mutes and saved views are kept in `Project.config/Logs/<user>.logs.txt` and come back in the next launch (a decision about a problem that has not appeared yet waits for it: the problem's id is its identity). **Team views** are the same views saved with `-Team true` into `Project.config/Logs/team.logs.txt`, a file of the project for source control; the person's own file wins a name clash. `LogViewSave` / `LogViewDelete` are undoable commands, `LogViews [-Load name]` lists and applies (Back returns). The window's *Views* menu is the same. `XLOG_USER_DIR` moves the files (the smoke harness keeps them out of the project).
- **Dependencies in About**: `deps:yes` next to `asset:X` also matches what X depends on (transitively, a few dozen at most). The Logs hold no graph; the editor registers a provider (`compile_log_bridge`, which reads the libraries' dependency lists for the assets the compile pipeline has told the Logs about). `LogDependencies -Asset X` shows the answer, `LogLens -About deps:X` and the About menu set it.
- **Attachments**: `LogAttach -Path64 f (-Event n | -Operation id)` copies a file into the launch's folder (`attachments/`, listed in `attachments.txt`; 8 MB each, 64 MB a launch) and the event says so (`LogEvent`, and a button in its open block in the window). They go with the launch when retention removes it.
- **stdout tap** (`xlog_stdout.h`, opt-in `LogStdout -On true`): replaces the process' stdout and stderr by pipes, turns every line into an event (`process.stdout` / `process.stderr`, origin `process`, heuristic: no code, no subject; stderr is a warning, a line that says error / fatal / assert is an error, one that says warn is a warning), and writes everything on to where it was going. It is labelled legacy-grade because its severity is a guess.
- **Remote runtimes** (`xlog_remote.h`): a runtime in another process connects its hub to the editor with `remote::Connect(hub, pipe, exe)` (a sink on the stream format; the pipe is found in `Cache/Logs/remote.txt`, or `XLOG_REMOTE_PIPE` sets it for a launched process). The editor listens (`xlion.logs.<pid>`, local clients only) and the records arrive as events and operations of origin `remote:<exe>`, with the editor's clock and the editor's operation numbers; an operation whose process went away before it ended is Abandoned. A queue that nobody listens to drops (counted); it never stalls the game. `LogRemote` / `LogStatus` say what is connected.
- **Not built**: `LogBegin/LogEnd` (operations owned by a script), a Views menu for the team scope's source control status, remote runtimes on other machines (the pipe is local), the stdout tap on other platforms.

---

## 7. AI and script commands

Same pipe, same style as everything else: workspace *query* commands (read-only) and *edit/execute* commands. Free text arguments are base64 like `-Name` elsewhere; ids are the stable ones the replies print.

### 7.1 Reply shape (every query)

```text
LogProblems: ok
Query=sev>=error channel:game.*           ← the normalized query that was run
Snapshot=7F3A  Cursor=7F3A:12             ← stable snapshot + continuation (pages never skip or repeat)
CommittedThrough=48211                    ← everything pushed before this counter is in the answer
Matched=12 Returned=12 Occurrences=430
Evidence=full  Gaps=none  Redacted=0
Excluded=trace:physics  Dropped=0 Summarized=0 Expired=0 PendingWrite=0

<one row per problem or event, tab-separated, a header row first; message text escaped (\n, \t)>
```

- **Budget.** A reply is capped (default 32 KB, far under the pipe's 64 KB buffer and a sane AI budget); `-Limit` and `-After <cursor>` page. A truncated reply says `Truncated=true` and gives the cursor.
- **Honesty fields.** `Evidence` / `Gaps` say *partial* with the missing interval; `Excluded` lists intentional capture exclusions separately from `Dropped` (collector loss). An empty list never has to mean "unobserved".
- **Severity filters** are explicit: `-MinSeverity Error` includes Fatal; there is no ambiguous `-Severity error`.

### 7.2 Read commands

| Command | Does |
|---|---|
| `LogStatus` | counts by severity (problems and occurrences), new since the baseline, capture policy and exclusions, collector health (queue depth, dropped/summarized/expired, pending write, persistence failure), current session, last build outcome, last play outcome |
| `LogSessions [-Limit]` | sessions: id, kind, start, end, termination class (clean / confirmed crash / interrupted / unknown), problem counts |
| `LogProblems [-Query q] [-Session s] [-Origin o] [-About a] [-State new|active|all] [-MinSeverity s] [-Operation id] [-Limit n] [-After c]` | one row per problem |
| `LogProblem -Id p` | the details: identity (and whether heuristic), title, code, the four state dimensions, source/subject refs, evidence state, retained occurrences, history, verification coverage |
| `LogEvents [-Query q] [-Session s] [-Operation id] [-Limit n] [-After c] [-Fold]` | chronological events |
| `LogEvent -Id e [-Context n]` | one event with typed attributes and *n* events around it |
| `LogOperations [-Kind k] [-Outcome o] [-Session s] [-Limit n]` | operations with `EvidenceReady`, `Coverage`, `VerificationTarget`; `-Tree id` gives a subtree |
| `LogContext -Problem p [-Budget bytes]` | the **context pack**: problem + evidence state, representative and variant occurrences, the operation chain, surrounding events, source refs and revision, session/environment, and what is missing, summarized, excluded or redacted. Deterministic, stable ids, bounded |
| `LogCompare -A s1 -B s2` | new / resolved / regressed problems and changed operation outcomes/durations between two sessions |

### 7.3 Write commands - and what Undo means for each

*User annotations and configuration changes use xundo where undo is meaningful. Executions and factual evidence go through the command permission and audit path but are not reversed by Undo.*

| Command | Does | Undo |
|---|---|---|
| `LogAcknowledge -Problem p` | triage state | restores the previous state |
| `LogMute -Problem p -For session|<seconds>|project [-Reason b64]` / `LogUnmute` | presentation suppression; records scope, reason, creator, expiry, hidden count | restores the previous mute state |
| `LogView -Save name -Query q` / `-Load name` (P2) | saved view | removes / restores it |
| `LogMark -Text b64 -Kind baseline|note` | a bookmark; `baseline` moves the *New* baseline | removes the annotation; the audit entry that it was made stays |
| `LogFocus -Channel c -Minutes n` / `-Off` | raises a channel's capture level for a while | restores the policy; it **cannot recover events that were not collected meanwhile** |
| `LogVerify -Problem p` | **requests the producer's recheck as a normal operation** through the command and permission path (refused with a reason when the producer has none) | **none**: a completed check cannot "unhappen". The evidence it produced sets the verification state by itself |
| `LogBegin -Kind test|... -Name b64` / `LogEnd -Id id [-Outcome ...]` | opens / closes a client-owned operation (the harness uses it per test); work started inside it inherits its correlation | not undoable (it is evidence) |

AI conclusions cite evidence ids; AI annotations are separate records; log bodies are **data, never instructions**; every write shows in the Commands tab as `Pipe`.

### 7.4 How #5 is solved (the walk-through)

```text
> Play                                  # a build is needed first
> LogOperations -Kind game.build -Limit 1
  id=0x2A  Outcome=Failed  EvidenceReady=true  Duration=41s  Problems=3  Coverage=Selected(2 units)
> LogProblems -Operation 0x2A
  C2065   undeclared identifier 'Kick'      soccer_player_system.h:80   unit soccer_game.cpp   ×3
  LNK2019 unresolved external symbol ...    Game.vcxproj                                       ×1
> LogProblem -Id <C2065>                    # message, file:line, the compiler line, evidence=full, identity discriminator 'Kick'
> (fix the file)  Play                      # the next build succeeds
> LogOperations -Kind game.build -Limit 1   # Outcome=Succeeded  Coverage=Selected(soccer_game.cpp)
> LogProblem -Id <C2065>                    # Verified resolved: its check unit was recompiled, the diagnostic did not recur   (P2)
```

In P0 the last two lines show the new build's outcome and problems; *Verified resolved* is a P2 claim. `GameBuildStatus` (the wishlist's own name) can exist as a one-line alias over `LogOperations -Kind game.build -Limit 1`.

### 7.5 The harness

- **Each test is an operation** (`LogBegin -Kind test`), and the operation id is the **correlation** that work started inside it inherits (the build, a load, a worker). Time-window attribution is only a *fallback*, labelled `Attribution=Temporal`; where neither applies the attribution stays `Unknown`.
- **Strict result contract.** The query ignores presentation mutes; it selects the severity explicitly (`-MinSeverity Error`); it polls until `EvidenceReady` / `CommittedThrough` settle. A log service that is unavailable, or a collector gap on the checked window, is **Inconclusive** (an infrastructure failure), never a pass. An unexpected error *occurrence* fails the test even if its problem was acknowledged or later verified. A test that raises errors on purpose declares a scoped expectation.
- **No regression in coverage while migrating.** The stdout regexes stay until structured parity is *demonstrated*: the xGPU adapter and the crash importer must produce the same findings on the same runs. Only then do the regexes go.
- The "editor problem report" prints problem titles, codes and counts, not regex captures.

---

## 8. Phases

Each phase ends with the smoke suite green and new tests. The order follows the review: identity and ownership first, then the barrier, then the build, then queries, then the UI.

| Phase | Ships | Why here |
|---|---|---|
| **P0** | (in-memory store with bounded segments; the disk writer arrives in P1) 1. persistent ids, owned values, stable producer names, **title + body events**; 2. operations, completeness, the ingestion barrier (`EvidenceReady`, `CommittedThrough`); 3. the **Game.dll build adapter** with an explicit build outcome; 4. pipe queries (`LogStatus/Operations/Problems/Problem/Events`) and headless parity; the old "Log" tab reads the new store | **Solves #5** and proves the model on the hardest producer, with no UI risk |
| **P0 delivered** | `xlog` as a library (core, build adapter, commands, tab); the hub owned by `xeditor::host` and drained in `pump_services()`; the Game.dll build as an operation with an outcome, EvidenceReady and the units it compiled; `NotifyError` and the command audit trail as producers; `LogStatus/Operations/Problems/Problem/Events/Event` plus the diagnostic `LogSimulateBuild` and `LogEmit`; queries run on the host thread (bounded by the store cap; the jobs of section 4.1 arrive with the window); `-Query64` for queries with quotes; `LogEvent -Offset` pages a long body. 19 smoke tests incl. headless parity | wishlist **#5** |
| **P1** | The Logs window: **Problems | Events** (no ruler yet), badge, the `NotifyError` policy (record, toast on request, modal on decision), the **resource editors' diagnostics view** (6.10) with the **pipeline-message adapter**, the **xGPU adapter**, acknowledge/mute, Source/About lenses, search, `F8`; the harness as a client (regexes kept until parity) | The daily workflow |
| **P2** | The **ruler with operation spans**, verification **coverage** and `Verified resolved`, regressions, session compare, `LogContext`, persistence recovery hardening, crash import with classification, saved views, Focus | "What changed / what caused it", and the claims that need evidence |
| **P3** | stdout tap (legacy-grade), dependency expansion of *About*, attachments, remote runtimes, team views | Reach |

---

## 9. Acceptance tests (V2's list, adapted, plus the review's)

Permanent `smoke/` tests (and store-level tests where there is no UI); none is deleted when it passes.

1. **Repeated diagnostic -> one problem**: 10,000 identical `C2065` at one site -> one problem, `Occurrences=10000`.
2. **No accidental merge**: two `C2065` on the same line with different identifiers -> two problems (discriminator); the same code in two files -> one family.
3. **Success is not verification**: a successful build that repeats a warning leaves it *Reproduced*; an incremental build verifies only the units it compiled; unknown coverage verifies nothing; a muted problem that was really rechecked with complete evidence *can* be verified.
4. **Ingestion barrier**: a query issued right after an operation ends never misses its diagnostics; `EvidenceReady=false` until the readers finish; a timeout is *not ready*, not *no problems*.
5. **A failed operation without a diagnostic is visible** ("failed without diagnostic details").
6. **Abandoned operations**: a producer that dies mid-operation leaves it Abandoned; a crash is imported at the next launch with `Original session`, a checkpoint (no double import), and a classification that does not claim a crash without a crash record.
7. **Persistent identity**: event and operation keys stay unique across launches, a copied project and an imported capture; fingerprints use stable producer names; an ambiguous stored mute becomes an *unmatched annotation*, not a broad mute.
8. **Durability**: a torn final write is truncated on open and reported; the writer queue's `PendingWrite` and `PersistenceFailed` are visible; operation records live in the authoritative stream and the projections rebuild identically.
9. **Pinned lenses survive switching editors**; search, filters, selection and scroll survive closing and reopening the drawer.
10. **Old references never mislead**: a subject at an old revision offers history or a labelled counterpart; it never selects another entity.
11. **Stable pagination** while events arrive (`Snapshot` + `Cursor`).
12. **Retention is honest**: reduction and eviction are reported by kind (`Summarized`, `Expired`, storage pressure); intentional exclusions are `Excluded`, not `Dropped`; Trace exclusion alone never makes a session *Partial*.
13. **Mute never rewrites evidence**; a Fatal and collector-health problems cannot be muted away.
14. **One store, two faces**: `LogProblems` and the window show the same rows for the same query.
15. **Headless parity**: the headless host answers the Log commands with the same results and drains without a UI.
16. **Attribution by correlation**: an error raised by a worker started inside test A, after test B began, is attributed to A; with no correlation it is `Temporal`, then `Unknown`.
17. **Harness contract**: an unavailable service or a collector gap is Inconclusive; an acknowledged error occurrence still fails its test; muted problems are still queried.
18. **Disabled logging is free**: a disabled call performs no formatting or allocation, and a Play run that would emit a million Trace events at the default policy records none and changes frame time by no more than a stated budget.
19. **Undo semantics**: Undo restores an acknowledgement or a mute; it never removes a completed check's evidence; `LogFocus -Off` restores policy but does not claim to recover events.
20. **Multi-line events**: a compiler error with its `note:` lines and source excerpt is **one** event (title + body, `BodyLines` right); a multi-paragraph Vulkan message is one event; a search for a word that appears only in the body finds it; a body over the cap is kept up to the cap, marked `Summarized`, and says how many lines were not kept; `LogEvent` returns the body as `| ` continuation lines within the reply budget.
21. **Scale**: one million events are ingested without any frame exceeding the drain budget (the backlog is shown, not hidden); a query over them returns its first page in under a second while the frame rate does not change; typing a new search cancels the running query; the ruler draws in time independent of the event count; a channel above the storm rate switches to aggregate mode with a `telemetry.compacted` record while its errors are untouched; memory stays under the segment cap.
22. **Toast/modal policy**: `NotifyError` alone records and badges; an explicit request raises a toast; only a decision raises the modal, centered on its editor.

---

## 10. Open decisions (my recommendation first)

1. **Chunk format.** *xtextfile tables* (consistent, readable, typed) behind a writer thread, with framing. Revisit if replaying very large sessions is slow.
2. **Where the store lives.** `<project>/Cache/Logs/<session id>`; the crash sink stays next to the exe.
3. **Notifier policy.** Record and badge by default; toast on request; modal only for a decision. This changes a behaviour users know, so it ships with the badge (P1).
4. **`printf`.** No stdout tap before P3: migrate producers one at a time (build, notifier, commands, xGPU first), because a tap produces events with no identity.
5. **Details placement.** Inline details by default, an *optional* right pane (default 30%, hidden when it would leave the list under ~560 px) and an optional bottom strip. *If you would rather have the side pane as the default, say so.*
6. **Operations.** No tab: spans on the Events ruler plus a breadcrumb and a filter in the details. *If you want a tab after using it, it is a small addition.*
7. **Source lens contents.** Editor instances, systems, script modules and external tools, as in section 6.5. *Anything missing from that list?*
8. **Shared mutes.** Per user first; project-wide mutes later with review.
9. **Retention defaults.** 20 sessions or 200 MB; crashed sessions and failed builds preferred, pinned captures protected, a stated policy when protected evidence alone exceeds the budget.

### What this design deliberately does not promise

- Lossless capture under overload (it reports what was rejected, summarized and expired).
- That "not observed" ever means "fixed", or that a successful build means every earlier problem is gone.
- That AI explanations are facts: they are hypotheses linked to evidence ids.
