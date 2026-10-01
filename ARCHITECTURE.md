# gamemaster-red Architecture

**Status:** v0 draft · Adapter A is the implementation target; Adapter B is specified
for future experimentation; Adapter C (embodied bots) is out of scope for now.

This document is the contract between the Minecraft server and the AI service.
If code and this document disagree, that's a bug in one of them.

---

## 1. Principles

1. **The service is separate from the server.** gamemaster-red runs as its own
   process. The server never makes an LLM call, holds an API key, or waits on
   a network round-trip. Crash the service → the server is unbothered.
2. **Transport is pluggable; the envelope is not.** Adapters (log+RCON, bridge
   plugin, future bot) differ in *how* they move bytes. Everything above the
   adapter sees one versioned event/action schema (§3). Coupling is loose
   *because the contract is tight*.
3. **Adapters are dumb.** No LLM logic, no policy, no memory inside the
   plugin/mod. Adapters translate between Minecraft's world and the envelope.
   Iterating on the brain must never require a server restart.
4. **Never block the tick loop.** Inbound events are forwarded asynchronously
   and return immediately. Outbound actions are queued and executed at a safe
   point. A 5-second model call must cost the server 0 ms.
5. **Fail open, degrade honestly.** An unparsable log line becomes a
   `raw.line` event, not a crash. An adapter lacking a capability reports it
   at handshake; the service then *declines the feature*, not the session.

## 2. Topology

```
┌──────────────────────── Minecraft server ─────────────────────────┐
│                                                                    │
│   Adapter A (v0):      logs/latest.log ──tail──┐                   │
│                        RCON TCP :25575 ◄──cmds─┤                   │
│                                                                    │
│   Adapter B (later):   bridge plugin ══ ws/JSON ══┤                │
│                        (AsyncChatEvent… →        │                 │
│                         action exec ←… )         │                 │
└────────────────────────────────────────────────────┼───────────────┘
                                              ▼
                              ┌──────────────────────────────┐
                              │    gamemaster-red service    │
                              │                               │
                              │  adapters/   (A, B, …)        │
                              │  bus/        envelope ingest  │
                              │  triggers/   rules → prompts  │
                              │  sessions/   memory (SQLite)  │
                              │  llm/        BYO model client │
                              │  tools/      wiki, crafting,  │
                              │              modpacks, MCP    │
                              │  actions/    allowlist, gates,│
                              │              audit log        │
                              └──────────────────────────────┘
```

One service instance may connect to **many servers** (future proxy/network
mode). Every envelope carries `server`, so this costs nothing to defer.

---

## 3. Envelope schema v0

JSON over the wire. UTF-8. Newline-delimited at the adapter boundary for
debuggability (one envelope per line, `jq`-friendly).

### 3.1 Inbound: Event

```json
{
  "v": 0,
  "server": "survival-01",
  "adapter": "logtail-rcon",
  "seq": 4217,
  "ts": "2026-09-29T18:42:07.112Z",
  "type": "chat.message",
  "data": { "player": "Zalty", "message": "Red, how do I make concrete?", "raw": "<Zalty> Red, how do I make concrete?" }
}
```

- `v` — schema major version. Readers must ignore unknown fields, never
  unknown-version events (drop + metric).
- `seq` — per-adapter monotonic counter; consumers detect gaps, never
  assume delivery.
- `ts` — adapter's best-effort timestamp. Adapter A derives it from the log
  line (server-local; adapters normalize to UTC and record the offset).

**Event taxonomy (v0).** `capability` marks what only some adapters can emit;
A-only events must be treated as hints, never as authoritative world state.

| type | data (summary) | capability |
|---|---|---|
| `chat.message` | player, uuid?, message, raw | all (A: no uuid) |
| `player.join` / `player.leave` | player | all |
| `player.death` | player, cause, killer? | all (from log) |
| `world.advancement` | player, advancement_id | log-only (B has real events) |
| `raw.line` | line, source | A fallback |
| `world.time` | ticks_day, phase (dawn/day/dusk/night) | B (`schedule` poll) |
| `world.weather` | state | B |
| `block.change` / `entity.spawn` / … | extensible | B+ |
| `adapter.status` | adapter, ok, detail | all (lifecycle) |

### 3.2 Outbound: Action

```json
{
  "v": 0,
  "server": "survival-01",
  "id": "01JD3X9K6M2Y",
  "source": "red",
  "action": "chat.send",
  "args": { "target": "Zalty", "message": "Concrete = 4 gravel + 4 sand + 1 water bottle. Blocks, actually — 3 gravel + 3 sand + water." },
  "requires_confirm": false
}
```

- `id` — caller-generated; adapters must ack exactly once with a Receipt.
- `source` — `red | trigger:<name> | operator`; feeds audit log + rate limits.
- `requires_confirm: true` — service parks the action until a player confirms
  in chat (`/red confirm <id>`). **Required by policy** for anything that
  changes the world when run by the model.

**Action registry v0** with tier support:

| action | args | A | B |
|---|---|---|---|
| `chat.send` | target?, message | ✅ (via log-parsed reply channel / RCON `tell`) | ✅ |
| `cmd.exec` | command (no leading `/`) | ✅ RCON | ✅ main-thread dispatch |
| `world.time` | set\|add (`noon`, `+6000`) | ✅ (cmd.exec sugar) | ✅ native |
| `world.weather` | clear\|rain\|thunder, duration? | ✅ sugar | ✅ native |
| `player.give` | player, item, count | ⚠️ vanilla `/give` only, no modded items | ✅ native API |
| `entity.spawn` | player/item/armor_stand templates | ⚠️ limited | ✅ |
| `ui.title` / `ui.actionbar` | player, text | ❌ | ✅ |
| `announce` | text (server-wide, styled) | ✅ (say/tellraw) | ✅ |

Anything not in the registry is rejected at dispatch (`unknown_action`),
*before* reaching the adapter. `cmd.exec` is gated by a **prefix allowlist**
(see §6), and the `world.*`/`player.*` sugar actions must resolve to
allowlisted commands in adapter A.

### 3.3 Return: Receipt

```json
{ "v": 0, "receipt_for": "01JD3X9K6M2Y", "ok": true, "output": "...", "error": null }
```

Adapters have ≤30 s to produce a receipt; the service marks unanswered
actions `timeout` and surfaces it to the model as tool feedback ("I tried and
the server didn't answer").

### 3.4 Handshake & capabilities

Every adapter, on connect, announces itself:

```json
{ "v": 0, "kind": "hello", "adapter": "logtail-rcon", "server": "survival-01",
  "mc": { "brand": "Paper", "version": "1.21.8" },
  "capabilities": { "events": ["chat.message","player.join","player.leave","player.death","raw.line"],
                    "actions": ["chat.send","cmd.exec","announce"],
                    "events_can_emit_uuids": false, "transport_encrypted": false } }
```

The service builds a per-server **capability mask** and degrades features
explicitly — e.g. "NPC layer needs Adapter B" is a config-time message, not a
runtime surprise.

---

## 4. Adapter A — log tail + RCON (implementation target)

**Promise:** zero-install observation of chat/join/leave/death/advancement
events and allowlisted actions, on *any* Java server that writes a log file
(vanilla, Paper, Fabric, Forge, modded, containers).

### 4.1 Log tail (`logs/latest.log`)

- Follow by **inode + offset**, not filename — rotation (`latest.log` →
  dated `.gz`, recreated) must not break the stream or replay the backlog.
- On first attach: skip to EOF; optionally replay last N lines behind a
  `replay_backlog: false` default. Never double-process a line (persist offset).
- Vanilla-family line format: `[HH:MM:SS] [Thread/LEVEL]: payload` — parse with
  a **per-brand regex pack** (`vanilla`, `paper`, `purpur`, …). Known line
  kinds → taxonomy events; unknown → `raw.line` (still stored, never fed to
  the model by default).
- **Version drift is the #1 maintenance liability of this adapter.** Mitigate
  with golden-fixture tests: for each supported MC/brand version, a captured
  log corpus must still parse. CI runs it; a new MC version = new fixture PR.
- Server-clock offset: compute once at attach by correlating first-seen line
  timestamps with local clock; store in `adapter.status`.

### 4.2 RCON (outbound)

- Standard Source RCON over TCP (MC default `:25575`,
  `enable-rcon=true` + `rcon.password=` in `server.properties`).
- **Serialize commands** — one in-flight command, queue the rest. Don't rely
  on MC RCON surviving pipelining.
- **Plaintext protocol.** Default to `127.0.0.1` co-located; document that
  remote RCON must be firewalled or tunnelled (that's the service's job in
  §6 docs, not the adapter's).
- Map `cmd.exec` → RCON exec → Receipt from the response body (empty body =
  `ok`, many commands print nothing; non-empty response = `output`).
- No event subscription exists in RCON — the read side is *only* the log.
  This asymmetry is the adapter's definition, not a bug to fix.

### 4.3 Reply channel

Model replies go back as `chat.send` → RCON `tell <player> …` or `say`.
Formatting via vanilla JSON components (send `/tellraw` JSON, not §-codes),
with an "unstyled" fallback flag for hostile mod environments that strip
components.

### 4.4 Chat invocation convention (v0)

Adapter A can't intercept or cancel chat, so invocation is a **routing
convention decided in the service** after ingestion:

- `/red <text>` typed by a player *or* `@red <text>` mention (vanilla chat
  routing handles `/red`; the service sees the command echo in the log).
- Ambient mode (opt-in): Red may reply to ordinary chat with probability/
  gating rules — phase 1.5, off by default so servers aren't spammed.

## 5. Adapter B — bridge plugin (future experiment)

**Promise:** structured, cancel-safe events; native actions; real triggers.
Design constraint: the plugin stays **dumb on purpose** (~a few hundred
lines; no LLM/prompt/policy code).

- **Target: Paper first** (AsyncChatEvent, Brigadier `/red`, scheduler,
  adventure API). Fabric/NeoForge ports are separate adapters, not forks.
- **Transport: WebSocket client → service** (`ws://127.0.0.1:PORT/ingest`),
  plugin dials out — works behind NAT/containers with no server-side port.
  JSON envelopes exactly as §3; `hello` advertises richer capabilities
  (uuids, `ui.*`, native `world.*`, modded item registry).
- **Read side:** subscribe `AsyncChatEvent` (off-thread, free to forward,
  `registerCommand` for `/red` autocomplete+help), join/leave/death/
  advancement/block events → envelope events. `events_can_emit_uuids: true`.
- **Write side:** receive actions; anything touching the world re-dispatches
  to the main thread via the scheduler; execute natively (no vanilla-command
  string round-trip) so modded items/npcs work. Receipts on completion.
- **Triggers §7 data feed:** plugin-side cheap clocks — every N ticks sample
  world time/weather and publish `world.time`/`world.weather` **only on
  transition**, so the service's trigger engine fires "at dusk" without a
  20 Hz poll.
- **Reconnect:** plugin buffers events (bounded, drop-oldest, `adapter.status`
  gap reports) while the service is down; service persists offsets per
  `(server, seq)` so restarts are resume-safe.
- `/red confirm <id>` (for `requires_confirm` actions) is registered by the
  plugin and forwarded as an event; the service decides.

## 6. Core service

### 6.1 Pipeline

```
adapter event → bus → (persist raw, always)
                     → router:
                         • command match (/red, @red)      → session turn
                         • trigger rules (§7)               → synthetic turn
                         • everything else                  → context buffer only
 session turn → assemble context (§7.3) → llm (tools loop) → actions[] → dispatcher
```

### 6.2 Action dispatcher & the permission gate

Config is the allowlist — **Red can only do what the operator enumerated:**

```yaml
permissions:
  red:
    actions: [chat.send, announce]
    cmd_exec_prefixes: [ "time set", "weather ", "tell ", "say "]
    needs_confirm: [player.give, entity.spawn]   # even if allowed
  triggers:
    gamemaster:
      actions: [announce, world.time, world.weather]
```

Every dispatch writes an **audit line** (JSONL): ts, server, source, action,
args, receipt. Cheap, greppable, and the substrate for a future audit UI.
The README promise "Red can't OP itself" is enforced here: `op` is simply
not an allowlistable prefix.

### 6.3 Sessions & memory (SQLite from day one)

- `events` — every envelope (raw store; retention-configurable).
- `sessions` — per-player rolling transcript windows (token-budgeted).
- `context_buffer` — recent ambient chat (last N msgs, TTL) — what "what were
  players just talking about" costs.
- `triggers` — rule defs + fire state (cooldowns, last-fired ts).
- `npcs` (future) — persona + long-term memory per NPC.

### 6.4 LLM client & tools

- OpenAI-compatible chat completions; **BYO endpoint** (cloud or local).
  No hard dependency on any provider SDK beyond the HTTP client.
- **Tool registry** exposes wiki lookup, crafting KB, and per-modpack data as
  function-call tools; the model loops tool-calls until it answers or budget
  stops it (max iterations + max input tokens, both config).
- **MCP both ways:** consume external MCP servers as tool providers; expose
  gamemaster-red's registry over MCP so external agents can use Red's world
  tools. Tool definitions, not prompts, are the integration surface.
- Prompt assembly = persona + per-server rules + session window + trigger
  payload (if synthetic turn). Keep prompt templates in files, not code.

## 7. Triggers (Adapter A subset now, B superset later)

Rule = event pattern + predicate + prompt template + budget:

```yaml
triggers:
  dusk_greeting:
    when: world.time.phase -> dusk        # A: derived from log-derived clock; B: native
    require: players_online >= 3
    cooldown: 1h
    prompt_file: prompts/dusk_greeting.md
    default_mode: announce                # action+needs_confirm from permission gate
```

Under A *only*, the service runs its own clock approximation from observed
line timestamps (no `world.time` events exist) — document it as
**approximate**; it's for flavor triggers, not redstone-precision logic.

## 8. Compatibility & versioning

- Envelope version = major int; additive changes only within a major
  (readers ignore unknown fields); `hello.capabilities` is the negotiation
  layer so old adapters + new service (and vice versa) degrade cleanly.
- Log-parser fixtures per MC version in `testdata/`; a failing fixture is a
  *release blocker*, making version drift loud instead of silent.

## 9. Testing strategy

1. **Contract tests:** envelope fixtures validated by schema; every adapter
   (real or simulated) must pass the same suite.
2. **Golden-log tests** (§8) for Adapter A parsers.
3. **Simulated server:** canned log stream + fake RCON in CI — no JVM needed
   for core development.
4. **Matrix smoke:** vanilla + Paper, real MC versions tagged in release
   notes = "tested against".

## 10. Deliberate non-goals (for now)

- ❌ Console-window scraping (GUI artifact; `latest.log` is its structured source).
- ❌ Client-side mod (server-side install or nothing).
- ❌ Embodied bots / pathfinding (Adapter C; the mineflayer lane — mindcraft,
  Voyager — is well-occupied and it isn't what Red is).
- ❌ Bedrock (Geyser chat events will map to Adapter B late; nothing in the
  envelope blocks it).
- ❌ Multi-model orchestration beyond `model`+optional `cheap_model` for
  ambient gating.

## 11. Suggested repo layout

```
gamemaster-red/
├── ARCHITECTURE.md        # this file
├── schema/                # envelope JSON Schema (source of truth, codegen'd)
├── service/               # the brain (one language, own process)
│   ├── adapters/          # logtail_rcon (A) … bridge (B later)
│   ├── bus.py|ts/  triggers/  sessions/  llm/  tools/  actions/
├── plugin-paper/          # Adapter B experiment (gradle, dumb by design)
├── prompts/               # persona + trigger templates (markdown)
└── testdata/              # golden logs per MC/brand version
```

## 12. Open questions

1. ~~**Service stack:**~~ **Decided: Python** (LangGraph for the agent loop;
   fastest tooling around the LLM/MCP ecosystems). Single-binary distribution
   for server admins is a packaging problem to solve later (uv/pipx first,
   shiv/PyInstaller if admins demand a drop-one-file install); the envelope
   keeps the choice invisible to adapters.
2. Where does the `@red` mention trigger hook under A — `/red` only at first?
3. Ambient-reply ethics: opt-in always, or per-server "Red may chime in" toggle?
4. Token budget defaults for cheap-model ambient gating (phase 1.5).
5. Adapter B auth: shared secret in plugin config vs. service-issued token.
