# Game State Operations: A Portable Pattern

**GameObjects as narrative nodes. Events as immutable state. Triggers as emergent gameplay.**

This document describes a set of interlocking patterns for managing game state through immutable events and schema-driven entities. The patterns are engine-agnostic — they work in tabletop tools, turn-based systems, real-time simulations, and video games. Adapt the vocabulary; the structure holds.

---

## Core Invariant

> Only committed, immutable Events change game state. Everything else exists to propose, gate, or explain those events.

No system — UI, AI, network sync, scripting — may mutate a game entity directly. All mutations flow through the event log. This single constraint gives you: replay, undo, audit trails, deterministic networking, and a clean separation between "what the game world is" and "how players interact with it."

---

## 1. GameObjects: Schema-Driven Narrative Nodes

A **GameObject** is any entity in your game world: a character, a faction, a location, a quest, an item, a timer, a weather system. What makes them narrative nodes rather than dumb data bags is threefold:

### 1.1 Kinds (Schema as Contract)

Every GameObject has a **Kind** — a schema that declares what fields it carries, what operations are legal on it, and what actions it can participate in.

```yaml
# Example Kind definition
Character:
  fields:
    name: string
    faction:
      type: ref             # pointer to another GameObject
      target_kind: Faction
    bonds:
      type: ref[]            # list of pointers
      target_kind: [Character, Faction]
    hp:
      type: meter            # numeric with enforced bounds
      min: 0
      max: self.status.max_hp
      default: 10
    appearance:
      type: object
      fields:
        height: string
        hair_color: string

  computed:                   # derived, never written directly
    max_hp:
      expr: self.spec.constitution * 3 + 5
    bond_count:
      expr: len(self.spec.bonds)

  actions: [HealCharacter, TakeDamage, FormBond]
```

**Why Kinds matter**: They are the contract between your content (game design) and your engine (runtime). A Kind says "a Character *is* this shape" and the engine enforces it. When you add a new Kind, you don't write new code — you declare new schema, and the existing event/operation machinery handles it.

**Porting to video games**: Kinds map naturally to prefab definitions, scriptable objects, entity archetypes, or component bundles depending on your engine.

### 1.2 Spec vs Status (Authored vs Derived)

Every GameObject's data splits into two layers:

| Layer | Written by | Example |
|-------|-----------|---------|
| **Spec** | Events only | `constitution: 3`, `faction: faction_042` |
| **Status** | Computed from spec | `max_hp: 14`, `bond_count: 3` |

**Spec** is the source of truth — the deliberately authored state. **Status** is a cache of derived values, recomputed when spec changes. You never write to status directly; you write events that change spec, and status follows.

This split eliminates an entire class of bugs: desync between "the real value" and "the displayed value." There is no displayed value — there is spec (ground truth) and status (always derived from it).

### 1.3 Special Field Types

Three field types go beyond primitives and unlock most gameplay patterns:

**Meters** — Bounded numerics with overflow/underflow semantics.
```
hp: { type: meter, min: 0, max: self.status.max_hp }
```
When an operation would push a meter past its bounds, the value clamps and the system emits a boundary event (MeterOverflow / MeterUnderflow). This lets you build reactive mechanics: "when HP hits 0, trigger death sequence" isn't special-cased — it's a trigger on MeterUnderflow.

**Refs** — Typed pointers to other GameObjects, singular or list.
```
faction: { type: ref, target_kind: Faction }
bonds:   { type: ref[], target_kind: [Character, Faction] }
```
Refs make relationships first-class. You don't store a faction_id string and hope it's valid — the system enforces referential integrity and handles dangling references when targets are archived.

**Tagged Refs** — Refs with metadata annotations.
```
owners:
  - target: char_001, tags: ['primary', 'founder']
  - target: char_003, tags: ['supporting']
```
Tags on refs let you express relationship *roles* without needing a separate join entity. "Who is the primary owner?" is a query filter, not a separate data model.

### 1.4 Hierarchical Containment

Any GameObject can have a `parent` pointer to another GameObject, enabling recursive nesting:

```
Campaign (Story)
  └── Character Arc (Story)
       └── Scene Beat (Story)

Region (Location)
  └── City (Location)
       └── Building (Location)
            └── Room (Location)
```

This is not a fixed tree structure — it's a pattern available to any Kind that declares parent-child relationships. A quest system, a skill tree, an inventory, an organizational chart: all the same containment pattern with different Kinds.

---

## 2. Events: Immutable State Changes

An **Event** is an immutable record that something happened. Once committed, it is never modified or deleted. The full sequence of events is the canonical history of your game world.

### 2.1 Dual-Layer Event Design

Every event carries two layers of information:

```
Event:
  # Semantic layer — WHAT kind of thing happened
  type: "DowntimePasses"
  parameters: { days: 7 }

  # Operations layer — WHAT mutations it performs
  operations:
    - op: meter.delta
      target: faction_001
      payload: { field: progress, delta: +1 }
    - op: meter.delta
      target: faction_002
      payload: { field: progress, delta: +2 }
```

**Semantic layer** (the type name): Used for trigger matching and human reasoning. "A downtime event happened" is meaningful to game logic and narrative.

**Operations layer** (the mutation list): Used for actually updating state. These are the atomic, mechanical changes. Projections consume this layer to compute current state.

**Why both?** Because one event type can produce different operations depending on context, and different event types can produce the same operation. A "HealCharacter" and a "RestAtInn" might both emit `meter.delta` on HP, but triggers care about *why* the healing happened, not just that HP changed.

### 2.2 The Eight Operations

All state mutations reduce to combinations of eight atomic primitives:

| Operation | What it does |
|-----------|-------------|
| `object.create` | Instantiate a new GameObject with a Kind and initial data |
| `object.update` | Set a field to a new value (path-based, supports nested fields) |
| `object.archive` | Soft-delete (mark as archived, never hard-delete) |
| `meter.delta` | Adjust a meter by a signed amount (clamped to bounds) |
| `meter.set` | Set a meter to an absolute value (clamped to bounds) |
| `ref.set` | Set a singular ref to point to a target |
| `ref.add` | Add a target to a ref list |
| `ref.remove` | Remove a target from a ref list |

That's it. Every gameplay mechanic — combat, crafting, dialogue consequences, weather changes, faction politics, quest progression — decomposes into sequences of these eight primitives.

**Why so few?** Fewer operation types means fewer code paths, fewer bugs, and total replay fidelity. If you can replay eight operations, you can replay any game state. Adding a new Kind or EventType never requires new operation code.

**Porting to video games**: These map well to ECS component mutations. `meter.delta` is your health/mana/stamina changes. `ref.set` is equipping items or assigning targets. `object.create` is spawning. The vocabulary changes; the operations don't.

### 2.3 Event Metadata

Beyond type and operations, events carry metadata that enables debugging, auditing, and causal reasoning:

```
Event:
  id: ULID                          # globally unique, sortable
  game_id: ...                      # isolation boundary
  seq: 42                           # strict per-game ordering
  scope:
    primary: char_001               # main target
    refs: [faction_002, loc_003]    # other involved objects
  causality:
    parent_event_id: evt_041        # what triggered this (null if root)
    root_draft_id: draft_012        # originating player action
    depth: 1                        # cascade depth (0 = player-initiated)
  actor:
    type: user | system | trigger
    id: ...
  timestamp: ...
  narrative: "The Fog Hounds gain ground while the crew rests."
```

The `causality` block is particularly powerful. It lets you answer:
- "What player action ultimately caused this?" → follow `root_draft_id`
- "What was the chain of events?" → follow `parent_event_id` up
- "How deep is this cascade?" → check `depth`

### 2.4 System Events

Some events are emitted automatically by the engine, not by player actions:

| System Event | When |
|-------------|------|
| **MeterOverflow** | A meter operation clamps at maximum |
| **MeterUnderflow** | A meter operation clamps at minimum |
| **ObjectCreated** | A new GameObject is committed |
| **ObjectArchived** | A GameObject is soft-deleted |
| **RefDangling** | An archived object leaves behind refs pointing to it |

System events participate in the same trigger/cascade system as any other event. "Character dies when HP reaches 0" is just a trigger on MeterUnderflow where the meter is HP.

---

## 3. Projections: Derived Read Models

A **Projection** is a read-optimized view computed entirely from the event log. The current state of any GameObject is a projection — it's what you get when you replay all events from the beginning.

```
Event Log (source of truth):
  evt_001: object.create Character { name: "Vex", hp: 10, constitution: 3 }
  evt_002: meter.delta Character/Vex { field: hp, delta: -4 }
  evt_003: object.update Character/Vex { path: name, value: "Vex'ahlia" }

Current State Projection:
  Character/Vex'ahlia: { hp: 6, constitution: 3, max_hp: 14 }
```

**Key properties:**
- Projections are always rebuildable from events (they're caches, not sources of truth)
- Projections can be optimized per use case (full state, activity feed, aggregate counts, relationship graphs)
- Status fields are recomputed lazily — marked dirty when underlying spec changes, recomputed on next read

**Porting to video games**: You likely won't replay the full log every frame. Keep projections as your runtime state, and rebuild from events only for: loading saves, network reconciliation, replay systems, or debugging. The event log is your save file and your replay buffer.

---

## 4. Triggers and Cascades: Emergent Gameplay

A **Trigger** is a rule that watches for specific event types and automatically emits new events in response. Triggers are how you get emergent, systemic gameplay without writing procedural code for every interaction.

### 4.1 Trigger Structure

```yaml
FactionAdvanceOnDowntime:
  watches: DowntimePasses              # semantic event type
  condition: target.spec.active == true # optional guard
  emits: ProgressFaction               # what to fire
  for_each: find('Faction').where(active == true)  # iteration
```

A trigger says: "When *this kind of thing* happens, if *these conditions hold*, then *do this other thing*."

### 4.2 Cascades

When a trigger fires and emits a new event, that event can itself match other triggers. This chain is a **cascade**:

```
Player invokes "Start Downtime"
  → DowntimePasses event (depth 0)
    → Trigger: FactionAdvanceOnDowntime
      → ProgressFaction for Fog Hounds (depth 1)
      → ProgressFaction for Red Sashes (depth 1)
        → Trigger: FactionGoalComplete
          → CompleteFactionProject for Red Sashes (depth 2)
            → ObjectCreated: new Turf GameObject (depth 3)
              → [no more triggers match — cascade ends]
```

One player action ("start downtime") produced a cascade of five events across three depth levels. The player pressed one button. The game world responded systemically.

### 4.3 Cascade Safety

Unbounded cascades are infinite loops. Enforce limits:

- **Max depth**: Cascades cannot exceed N levels deep (e.g., 10)
- **Max emissions**: A single trigger firing cannot emit more than M events
- **Self-trigger prevention**: A trigger cannot re-trigger itself in the same cascade

When a limit is hit, the cascade halts and the system logs a warning. Better to stop early and surface the problem than to loop forever.

### 4.4 Why This Matters for Game Design

Triggers + cascades mean your game mechanics are **compositional**. You define small, focused rules:
- "When a character dies, drop their inventory"
- "When an item is dropped in a magic zone, it transforms"
- "When a transformed item appears, nearby NPCs react"

Each rule is simple. Together, they produce emergent behavior that no single rule anticipated. A character dies in a magic zone → their sword drops → it transforms into a cursed blade → NPCs flee. You didn't script that sequence. The system composed it from three independent rules.

**Porting to video games**: This is the observer/event-bus pattern, but with immutable records and explicit causality tracking. If you already use an event bus, the difference is: events are logged (not fire-and-forget), triggers are data (not code), and cascades have safety limits.

---

## 5. The Gating Layer: Proposals Before Commits

Not every intended action should take immediate effect. A **Draft** is a pending proposal that must be approved before it becomes an Event.

```
Intent ("I want to heal this character")
  → Draft created (editable, cancellable)
    → Approved (by GM, by game rules, by auto-policy)
      → Event committed (immutable, permanent)
```

**Why gate?** Different games need different levels of control:
- **Tabletop RPG**: GM approves or rejects player actions
- **Turn-based game**: Actions queue during planning phase, commit on turn resolution
- **Real-time game**: Most actions auto-approve instantly, but some (trades, guild actions) require confirmation
- **Multiplayer**: Server validates and approves; clients propose

The Draft/Approve/Commit flow is the same pattern at different speeds. A tabletop GM mulling over a proposal for 30 seconds and a game server validating a packet in 2ms are both doing approval.

**Auto-approval** is the degenerate case: the draft is created and immediately approved in the same tick. You still get the event log, the causality chain, and the replay — you just skip the wait.

---

## 6. Putting It Together: The Full Loop

```
┌─────────────────────────────────────────────────────┐
│                    GAME LOOP                        │
│                                                     │
│  1. ACTION                                          │
│     Player (or AI, or system) invokes an action     │
│     on a target GameObject                          │
│              │                                      │
│              ▼                                      │
│  2. DRAFT                                           │
│     Proposal created with editable parameters       │
│     (skip if auto-approve)                          │
│              │                                      │
│              ▼                                      │
│  3. APPROVE                                         │
│     Validation, authorization, rule checks          │
│              │                                      │
│              ▼                                      │
│  4. EVENT                                           │
│     Immutable record committed to log               │
│     Operations extracted                            │
│              │                                      │
│              ▼                                      │
│  5. APPLY                                           │
│     Operations mutate GameObject spec fields        │
│     Status marked dirty                             │
│              │                                      │
│              ▼                                      │
│  6. TRIGGER                                         │
│     Matching triggers fire → new Events (goto 4)    │
│     Cascade until quiescence or safety limit        │
│              │                                      │
│              ▼                                      │
│  7. PROJECT                                         │
│     Projections updated / status recomputed         │
│     UI reflects new state                           │
│                                                     │
└─────────────────────────────────────────────────────┘
```

This loop is the heartbeat of the system. It runs once per player action in a tabletop tool. It runs many times per second in a real-time game. The structure is identical; the tick rate changes.

---

## 7. Practical Porting Guide

### To a Video Game (Unity, Unreal, Godot, custom)

| This pattern | Maps to |
|-------------|---------|
| Kind | Prefab / ScriptableObject / Entity archetype |
| GameObject | Entity / Actor / Node |
| Spec fields | Component data |
| Status fields | Cached computed properties, updated in system tick |
| Meter | Numeric component with clamp + event on boundary |
| Ref | Entity reference / ID pointer |
| Event | Command object in command pattern, logged to replay buffer |
| Operation | Component mutation (set field, add to list, etc.) |
| Trigger | Observer/subscriber, but data-driven and logged |
| Cascade | Event chain with depth counter |
| Draft | Input buffer / action queue / server validation |
| Projection | The live game state (ECS world snapshot) |
| Paradigm | Mod / data pack / content module |

### What you gain by adopting these patterns

- **Replay**: Record the event log. Replay it. Get identical state. Free save system, free replay system, free debugging.
- **Undo**: Pop the last N events. Rebuild projections. The game is now N steps ago.
- **Networking**: Send events over the wire instead of full state. Deterministic replay means clients can verify.
- **Modding**: Mods add new Kinds, EventTypes, and Triggers — all data, no engine code changes.
- **Debugging**: "Why is this character dead?" → query the event log for all events targeting that character. See the exact chain.
- **Auditing**: "What happened last session?" → filter events by timestamp. Get a complete, ordered narrative.

### What you pay

- **Storage**: You're keeping every event forever. For most games, this is trivially small. For games with millions of events per second, you'll need pruning strategies.
- **Indirection**: Mutating state requires creating an event object, committing it, and applying operations — more steps than `entity.hp -= 5`. This is the cost of the guarantees above.
- **Rebuild time**: If projections are lost, rebuilding from the full event log takes time proportional to log size. Snapshotting (periodic projection checkpoints) mitigates this.

### Minimum Viable Adoption

You don't need all of this to get value. Start with:

1. **Events as the only way to mutate state** (the core invariant)
2. **An append-only event log** (even just a list in memory)
3. **Operations as a small, fixed set of mutation primitives**

That alone gives you replay, undo, and debugging. Add triggers when you want emergent mechanics. Add drafts when you want gating. Add Kinds when you want schema validation. Each layer is independently useful.

---

## Appendix: Glossary of Portable Terms

| Term | Definition |
|------|-----------|
| **GameObject** | Any entity in the game world, defined by a Kind |
| **Kind** | Schema declaring a GameObject's shape, field types, computed properties, and available actions |
| **Spec** | The authored, event-sourced fields of a GameObject (source of truth) |
| **Status** | Derived/computed fields, recalculated from spec (cache, not truth) |
| **Meter** | A bounded numeric field that emits system events on overflow/underflow |
| **Ref** | A typed pointer from one GameObject to another (singular or list, optionally tagged) |
| **Event** | An immutable record of something that happened, carrying a semantic type and a list of operations |
| **EventType** | A named schema for a category of events (e.g., "TakeDamage", "CraftItem") |
| **Operation** | One of eight atomic mutation primitives (create, update, archive, meter.delta, meter.set, ref.set, ref.add, ref.remove) |
| **Trigger** | A data-driven rule: "when EventType X occurs, if condition Y holds, emit EventType Z" |
| **Cascade** | A chain of trigger firings from a single root event, with depth tracking and safety limits |
| **Draft** | A pending, editable proposal that becomes an Event upon approval |
| **Projection** | A read-optimized view derived entirely from the event log (the "current state") |
| **Paradigm** | A modular, shareable package of Kinds, EventTypes, Triggers, and seed data (a content module / mod) |
| **Causality** | Metadata on each event tracking its parent event, root action, and cascade depth |
