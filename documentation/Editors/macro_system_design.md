# The macro system: initial design (2026-10-11)

Status: **design only, nothing is built.** It is the first sketch the user gave; it is to be refined together before any code. It builds on the frozen RTCS architecture (recursive composition,
temporal identity, declarative mutation) and on what the editor already has (the command system, `xundo`, `xproperty`, the project-level key bindings that macros are meant to sit beside).

## The shift

A traditional macro says "perform these steps". This one says "construct this result from these inputs", and adds "expose the meaningful controls, preserve deliberate edits, and explain how the
result came about". The hard requirement: editing the underlying result must not silently destroy the tool, and the tool must not silently overwrite the edit.

## Three objects and one protocol

| Object | Meaning | Replaces |
|---|---|---|
| **Recipe** | A typed construction, primitive or composed | action definitions and macro definitions |
| **Application** | A recipe bound to particular inputs and targets | invocation state, adjustable-operation state |
| **Revision** | A proposed or committed change with provenance | plans, results, execution receipts |

Bindings are edges and values; permissions are execution policy; UI controls are projections; recording creates recipes from revisions.

    Recipe + bound inputs -> Application --evaluate--> proposed revision --validate and authorize--> committed revision

A primitive and a composite satisfy the same recipe interface; their implementations stay distinguishable.

## An application can keep a relationship with its output (optional)

Three lifetime policies on the same application (not three systems), default **apply once**:

- **Apply once**: commit, keep provenance only (rename, disconnect, refactor).
- **Keep adjustable**: keep inputs and output correspondence, re-evaluate explicitly (a generated node group, a layout).
- **Keep linked**: react to declared input changes under an explicit policy (procedural construction, derived views).

A user promotes a useful result from apply-once to adjustable or linked.

## Correspondence and ownership

A **correspondence map** per application ties stable *roles* of the recipe to output occurrences (`timing.start -> Node#108`). Re-evaluation reconciles the old output with the new proposal:
a matching role keeps its occurrence, a new role creates one, a removed role proposes removal, an ambiguous case asks or stops (never guesses). Roles are stable within an application, not display
names and not global ids. Planning computations may be reused (incremental evaluation, Adapton as precedent); document commits and external side effects are never cached away.

Each output field has an authority: **controlled by recipe**, **overridden locally**, or **unmanaged**. Editing a controlled field offers: change the input (when a valid mapping exists), override
here, or detach. An overridden object that is about to disappear surfaces the conflict (keep detached, remove, or revise the recipe). No silent overwriting in either direction.

## Bidirectional editing, selectively

Controls and result can both be edited (a duration slider changes the graph; a timing edit in the graph changes the slider), but arbitrary recipes are **not** auto-inverted. Explicit edit adapters:

    EditableProjection { read(application, document) -> controls
                         propose_edit(control_delta) -> input_delta | output_delta | ambiguity }

Start with: field to input, drag handle to position/size, boundary port to interface declaration, selection membership to target set. Adapters that claim lens behavior are tested for the two
round-trip laws: showing and accepting unchanged controls changes nothing; an accepted control edit is reflected when the controls are read again.

## Execution semantics (corrections to the earlier design)

- **Composite planning over virtual state**: each step is evaluated against the working state the earlier steps produced (created outputs use provisional references, resolved at commit). The
  plan is an executable proposal, not a prediction: `working = snapshot; for each step: proposal = evaluate(step, working); working = apply_to_virtual_state(working, proposal); revision = difference(snapshot, working)`.
- **Checkpoints divide transactions**: a macro is either one atomic draft that can be reviewed and edited before a single commit (first implementation), or it has explicit commit boundaries.
- **Approval binds to a proposal**: recipe revision, resolved targets, proposed changes, external effects, relevant dependency frontier. A material change of an approved scope refreshes the
  approval; unrelated document changes do not (validate the relevant read dependencies, including query-membership dependencies, not a global revision number).
- **Parallelism needs evidence**: disjoint write sets are not enough (one branch may read what another writes); unknown footprints run sequentially.

## Intent without magical goal solving

Recipes carry observable expectations: `Requires` (preconditions) and `Ensures` (postconditions such as "external connectivity is preserved", "the resulting graph compiles"). Fuzzy intent
("make this easier to understand") is kept apart: the AI uses it to propose alternatives; the deterministic executor validates only the explicit checks, and never claims a passing check proves the fuzzy goal.

## The UX emerges from the recipe's interface

A recipe declares inputs with types and hints (`duration: Time -> scrub control`, `target: NodeRef -> canvas picker`, `enabled: Boolean -> toggle`). From that the editor derives: command-palette
invocation, a compact inspector, a context-menu action, a node with typed ports, a canvas handle, and an AI-callable schema. Custom presentation is optional; naming a recipe and exposing two inputs
is already a useful tool. A strong path: select a successful edit in history -> **Make adjustable** -> expose a value -> pin its control near the output.

## The AI as a recipe editor

Four operations: **compose** existing recipes into a proposed construction; **generalize** a successful example by exposing selected inputs; **explain** an output through recorded dependencies and
provenance; **repair** a recipe or application by proposing a visible revision. No separate automation runtime; it never rewrites installed recipes on its own (it proposes a new version, runs the
tests, shows the difference). Uncertainty belongs in the proposal ("Target could mean: the selection / these exact nodes / all matching nodes. Choose one."): the executor never inherits an AI's
unstated guess.

## Worked example: expose a property as a parameter

Inputs `target: NodeRef`, `property: PropertyRef`, `name: Identifier`; construction: inspect the property type, create a compatible parameter, connect it to the target, propose placement, validate
scope and types. Afterwards the application shows controls (`Name: Speed`, `Default: 3.0`); renaming the generated parameter updates `Name` through a declared adapter; moving it makes a local
layout override; changing the target property checks compatibility before reconnecting; opening the application shows its construction; saving a specialization makes another recipe; the AI invokes
it through the same contract.

## The first slice (deferred: automatic generalization, reactive execution, remote tools, selective undo)

1. Typed recipes that evaluate into declarative patches. 2. Composite evaluation over virtual state. 3. Applications with explicit bindings. 4. Stable output-role correspondence. 5. Field-level
local overrides. 6. Generated controls and one explicit edit adapter. 7. Dependency-aware validation and atomic commit.

**The proof**: create a parameter through a recipe, reposition it manually, change its exposed default, re-evaluate, and verify that its identity and the manual position survive, with undo correct.

## Open points for the refinement (to settle with the user before building)

- Where recipes live (project-level, like the key bindings) and their file format (xtextfile / xproperty).
- How a Revision maps onto the existing `xundo` command objects (is a revision one undo step, or a group?).
- The first set of primitive recipes (the existing editor commands are the natural ones).
- Which first edit adapter proves the idea.
