# gamemaster-red Architecture

**Status:** permanent contract · v0 draft. This file describes *what the
system is*; [`MVP.md`](MVP.md) describes *what we are building first* — scope,
acceptance budget, conformance suite, deferred list. Nothing here schedules
anything; a section describes a design, a milestone decides when.
**§12 is normative for anything the user has to type, read, or install.**

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
┌────────────────────────────────────────────────────────────────────┐
│                                                                    │
│   Adapter Logtail (v0):      logs/latest.log ──tail──┐             │
│                        RCON TCP :25575 ◄──cmds─┤                   │
│                                                                    │
│   Adapter Bridge (spec):    bridge plugin ══ ws/JSON ══┤           │
│                        (AsyncChatEvent… →              │           │
│                         action exec ←… )               │           │
└────────────────────────────────────────────────────┼───────────────┘
                                              ▼
                              ┌──────────────────────────────┐
                              │    gamemaster-red service    │
                              │                               │
                              │  adapters/   logtail, bridge… │
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

**Adapter coexistence on one server.** Logtail and Bridge are not mutually
exclusive at the schema level — the `adapter` field and per-adapter `seq`
exist precisely so the service can multiplex. But both observe chat, so
simultaneous full operation duplicates every message. Rule: **one primary
adapter per server** (config-declared, normally the highest-capability
connected port). Actions route only through the primary; a secondary may run
in *shadow* mode (events ingested and compared for audit/parity, nothing
executed). Intended shadow use: migrating Logtail→Bridge with evidence — run
both, diff the streams, flip primary, retire Logtail. Note the Bridge ports
(paper/fabric/neoforge) are one adapter type differing only in
`hello.adapter`, and they never compete anyway: a server is exactly one
loader natively. **Platform, not content, is the discriminator** — which
Bridge port (if any) can load is decided by the server's platform software,
announced as `hello.mc.brand`, not by whether mods are installed: a Fabric
server with no mods still takes the Fabric port; a Paper server with 40
plugins still takes the Paper port; true vanilla (Mojang jar) loads *no*
Bridge port at all — Logtail-only, or the standard one-file drop-in upgrade
to Paper. The service never asks "modded?"; it branches only on capability
names, and branching on platform is a smell.

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
- `ts` — adapter's best-effort timestamp. Adapter Logtail derives it from the log
  line (server-local; adapters normalize to UTC and record the offset).

**Event taxonomy (v0).** `capability` marks what only some adapters can emit;
Logtail-only events must be treated as hints, never as authoritative world state.

| type | data (summary) | capability |
|---|---|---|
| `chat.message` | player, uuid?, message, raw | all (Logtail: no uuid) |
| `player.join` / `player.leave` | player | all |
| `player.death` | player, cause, killer? | all (from log) |
| `world.advancement` | player, advancement_id | log-only (Bridge has real events) |
| `raw.line` | line, source | Logtail fallback |
| `world.time` | ticks_day, phase (dawn/day/dusk/night) | Bridge (`schedule` poll) |
| `world.weather` | state | Bridge |
| `entity.attacked` | attacker, victim, damage (both directions) | Bridge (damage events; `entity.getTarget()` = aggro state) |
| `entity.interacted` | player, target, hand/stack | Bridge (interact/attack callbacks; mount + trade + tame are first-class where the loader provides them, else one stable Mixin point) |
| `block.change` / `entity.spawn` / … | extensible | Bridge+ |
| `adapter.status` | adapter, ok, detail | all (lifecycle) |

**Entity perception is a query, not an event stream.** "Who/what is near
player X" (hostiles, villagers, modded NPCs by registry type, tamed-owner
links) is answered on demand by the port via `entity.nearby {player,
radius}` (§3.2) — chunk-bucketed scan, main thread, compact prompt-sized
result. Continuous streams of positional truth would drown the bus; Red
asks when a turn needs it. Interaction *moments* (attack, trade, mount,
tame, interact) are events, in three tiers: first-class loader events →
single stable Mixin point → low-rate poll for subscribed players only
(following/looking-at). Logtail sees none of this — "near" and "toward"
are never logged.

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

**Action registry v0** with tier support. The marks describe each adapter's
*boundary with the server*: Logtail's write path is a **console command
string** (everything must be expressible as text the dispatcher parses,
outcomes return as text or nothing); Bridge's is the **in-process API**
(typed calls, callbacks). ✅ = reliable; ⚠️ = expressible but brittle (no
discovery of valid IDs, syntax drift across MC versions, errors arrive only
as log text).

| action | args | Logtail | Bridge |
|---|---|---|---|
| `chat.send` | target?, message | ✅ RCON `tell` (JSON-component sugar) | ✅ native sender |
| `cmd.exec` | command (no leading `/`) | ✅ RCON — runs the server's *full* command registry, mod-registered commands included | ✅ main-thread dispatch |
| `world.time` | set\|add (`noon`, `+6000`) | ✅ (`/time`) | ✅ native |
| `world.weather` | clear\|rain\|thunder, duration? | ✅ (`/weather`) | ✅ native |
| `player.give` | player, item, count | ⚠️ `/give` resolves modded IDs on modded servers, but Logtail can't discover valid IDs and failure returns only as console text | ✅ typed API + registry validation |
| `entity.spawn` | type, pos?, nbt? | ⚠️ `/summon` exists; NBT/component string syntax is version-fragile | ✅ typed API |
| `entity.nearby` | player, radius → typed entity summaries | ❌ (spatial truth never appears in logs) | ✅ query, main-thread, summarized |
| `ui.title` / `ui.actionbar` | player, text | ⚠️ `/title` exists; JSON-component quoting through console is fragile | ✅ native packets |
| `announce` | text (server-wide, styled) | ✅ `/say`, `/tellraw` | ✅ native |

Bridge's ✅ column is one boundary: typed API, callbacks, and **direct access
to the merged dynamic registries — which is where Bridge's mod support comes
from** (see §5: Bridge is a family of per-loader ports running *inside* the
modded JVM).

Anything not in the registry is rejected at dispatch (`unknown_action`),
*before* reaching the adapter. `cmd.exec` is gated by a **prefix allowlist**
(see §6), and the `world.*`/`player.*` sugar actions must resolve to
allowlisted commands in Adapter Logtail.

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
explicitly — e.g. "NPC layer needs Adapter Bridge" is a config-time message, not a
runtime surprise.

---

## 4. Adapter Logtail — log tail + RCON

**The exemplar adapter.** Everything below is its conformance spec — the
build scope and acceptance rows live in [`MVP.md`](MVP.md) §2. Every future
adapter is written against this bar.

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

Adapter Logtail can't intercept or cancel chat, so invocation is a **routing
convention decided in the service** after ingestion:

- `/red <text>` typed by a player *or* `@red <text>` mention (vanilla chat
  routing handles `/red`; the service sees the command echo in the log).
  The mention hook is an open decision — issue #6.
- Ambient mode (opt-in): Red may reply to ordinary chat with probability/
  gating rules — deferred (MVP.md §6, shape in #7), off by default so
  servers aren't spammed.

## 5. Adapter Bridge — bridge plugin (design specified; unscheduled)

**Promise:** structured, cancel-safe events; native actions; real triggers.
Design constraint: the plugin stays **dumb on purpose** (~a few hundred
lines; no LLM/prompt/policy code).

- **Target: Paper first** (AsyncChatEvent, Brigadier `/red`, scheduler,
  adventure API) — it covers the large non-modded server majority and is the
  easiest place to develop the protocol.
- **Modded servers need per-loader ports, not the Paper plugin:** a Paper
  plugin does not install on Forge/NeoForge/Fabric at all. Each port is thin
  and dumb (event → envelope, envelope → API) and shares one schema:
  **Fabric mod next** for the modded flagship (largest modded install base;
  also covers Quilt), NeoForge after. Same envelope ⇒ ports are
  translations, not forks.
- **Why Bridge is the mod-native adapter:** the port runs in the same
  process as the mods, so the merged dynamic registries are its own —
  modded item validation for `player.give`, recipe queries for the crafting
  KB, native `ui.*`, real UUIDs. Logtail talks to a merged server *through
  strings*; Bridge is *inside the merge*.
- **The Fabric/NeoForge ports are *mods*, not plugins:** no hybrid server
  (Cardboard/Arclight/Mohist) is ever required for Red — each port is a
  first-party citizen of its own loader (the LuckPerms pattern: one core,
  shipped per-platform). The Fabric mod declares `"environment": "server"`
  in `fabric.mod.json`: server-side-only, vanilla clients join without
  installing anything. Keep ports Mixin-free where possible (event-API
  subscriptions only) to minimize per-version maintenance.
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
- `npcs` (Bridge-era — MVP.md §6) — persona + long-term memory per NPC.

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

## 7. Triggers — rule engine (Logtail subset; Bridge superset)

Rule = event pattern + predicate + prompt template + budget:

```yaml
triggers:
  dusk_greeting:
    when: world.time.phase -> dusk        # Logtail: derived from log-derived clock; Bridge: native
    require: players_online >= 3
    cooldown: 1h
    prompt_file: prompts/dusk_greeting.md
    default_mode: announce                # action+needs_confirm from permission gate
```

Under Adapter Logtail *only*, the service runs its own clock approximation from observed
line timestamps (no `world.time` events exist) — document it as
**approximate**; it's for flavor triggers, not redstone-precision logic.

## 8. Compatibility & versioning

- Envelope version = major int; additive changes only within a major
  (readers ignore unknown fields); `hello.capabilities` is the negotiation
  layer so old adapters + new service (and vice versa) degrade cleanly.
- Log-parser fixtures per MC version in `testdata/`; a failing fixture is a
  *release blocker*, making version drift loud instead of silent.

- **Repo versioning (decided):** SemVer via release-please, one train for the
  whole repo — one tag bumps service, image, and `plugin-paper` jar together.
  Pre-1.0, breaking user-facing changes bump the **minor** (the `@0.3` pin
  channel in §12.3 only means something if minors are the breaking boundary);
  `1.0.0` gates on envelope v1 frozen + API stable. Commit grammar, branch
  names, and the release flow: [`CONTRIBUTING.md`](../CONTRIBUTING.md).

## 9. Testing strategy

1. **Contract tests:** envelope fixtures validated by schema; every adapter
   (real or simulated) must pass the same suite.
2. **Simulated server:** canned log stream + fake RCON in CI — no JVM needed
   for core development. This is also what `demo` runs (§12.6).

Milestone-owned tests — golden-log fixture sets (§8), the hostile-environment
matrix, the real-server matrix smoke — are acceptance measurements, not
permanent invariants: they live in the milestone spec (MVP.md §4). What is
permanent here is the *rule* (§8): a failing fixture blocks the release.

CI is split by path filter, not by repository (`python.yml` / `java.yml` on
`paths:`), so a Java contributor never waits on the Python matrix — that's the
answer to "monorepo gives me the wrong CI", and it's cheaper than a repo
boundary (§12.8).

## 10. Deliberate non-goals

Rejected *by design*, not by schedule. A non-goal that a future milestone
could certify (hybrid-core support) belongs in that milestone's deferred
list, not here (MVP.md §6).

- ❌ Console-window scraping (GUI artifact; `latest.log` is its structured source).
- ❌ Client-side mod (server-side install or nothing).
- ❌ Embodied bots / pathfinding (Adapter C) — **permanently, by design**:
  Red is not a player, and the mineflayer lane (mindcraft, Voyager) is
  well-occupied. The roadmap's NPC layer is realized through Adapter Bridge
  `entity.*` actions and in-world dialogue routing, not a bot connection.
- ❌ Bedrock (Geyser chat events map to a Bridge port when one exists; nothing
  in the envelope blocks it).
- ❌ Multi-model orchestration beyond `model`+optional `cheap_model` for
  ambient gating.

## 11. Suggested repo layout

**Single repository.** The service and the Paper plugin ship together — the
contract suite (§9.1) and the two-way degradation matrix (§8) are only cheap
when both sides are checkouts. See §12.8 for the decision and the conditions
that would revisit it.

```
gamemaster-red/
├── ARCHITECTURE.md        # this file
├── MVP.md                 # current milestone: scope, acceptance, deferred list
├── schema/                # envelope JSON Schema (source of truth, codegen'd)
├── service/               # the brain (one language, own process)
│   ├── adapters/          # logtail_rcon … bridge
│   ├── bus.py  triggers/  sessions/  llm/  tools/  actions/
│   ├── cli/               # init | setup | doctor | demo | run | service
│   └── wizard/            # first-run web/TUI onboarding (§12.4)
├── pyproject.toml         # uv-managed; the only build/packaging config in the repo
├── uv.lock                # TRACKED — one resolved dep set for devs, CI, and the image
├── .python-version        # TRACKED — uv reads this to pick the interpreter
├── Dockerfile             # + .dockerignore; uv-built, non-root, dumb-init
├── compose.yml            # beside-an-existing-server (§12.3)
├── compose.demo.yml       # override: adds its own Paper server (§12.3.5)
├── install/               # systemd unit / Windows task templates (§12.5)
├── plugin-paper/          # Adapter Bridge experiment (gradle, dumb by design)
├── prompts/               # persona + trigger templates (markdown)
└── testdata/              # golden logs per MC/brand version
```

---

## 12. Distribution & getting started

**Requirement, ranked above every other property of the system:** a non-specialist
must get Red answering in chat without reading this document. §1–§10 are how it
works; §12 is what it may not ask of a person.

If a capability requires editing a text file before the first reply, the
capability is specified wrong. Config files are an *output* of the tool, never an
input to the user.

### 12.1 Acceptance budget

The budget rows themselves are a milestone's definition-of-done and live in
[`MVP.md`](MVP.md) §3, with a measured-value column per release. The doctrine
is permanent and lives here: a capability that needs a hand-edited file
before its first reply is a capability specified wrong — and the budget's
"every failure says what to do" row is why `doctor` exists (§12.6): every
check emits `ok` or `fix: <imperative sentence>`, never a traceback.

### 12.2 Three tracks, one binary, one envelope

| track | who | server change | needs | restart | status |
|---|---|---|---|---|---|
| 🐳 **compose** | has Docker, wants zero edits | RCON toggle *(optional; §12.3.3)* | read-only mount of server dir | 0 · 1 | **MVP** |
| 🧩 **plugin + wizard** | layman; also the capability unlock | drop `plugins/*.jar` | service on same box | 1 | deferred — spec stands, tripwire #12 |
| 🐍 **`uvx` / `uv tool`** | admin with a shell, no Docker | none | `uv` (one command) | 0 | **MVP** |

Tracks differ in *plumbing*, never in behaviour: same §3 envelope, same §6.2
allowlist, same §7 triggers. Requirement: a user may start on compose and finish
on the plugin with no config rewrite — only a capability upgrade.

### 12.3 Track 1 — Docker Compose over any existing server

```yaml
# compose.yml — generated by `gamemaster-red init --docker`; users do not hand-write this
services:
  red:
    image: ghcr.io/gamemaster-red/gamemaster-red:0.3   # minor-pin, never :latest in a how-to
    restart: unless-stopped
    read_only: true            # rootfs is not writable; the data volume is
    security_opt: [no-new-privileges:true]
    volumes:
      - /srv/minecraft:/minecraft:ro          # §4.1 tailing is a filesystem read
      - red-data:/var/lib/gamemaster-red      # §6.3 memory + §4.1 offsets survive upgrades
    env_file: .env                            # 0600, written by init
    environment:
      GMR_RCON_PASSWORD_FILE: /run/secrets/rcon
    extra_hosts: ["host.docker.internal:host-gateway"]   # not network_mode: host
    ports: ["127.0.0.1:8790:8790"]            # wizard + /healthz, loopback only
```

**12.3.1 The one hard constraint.** §4.1 tails by *inode + offset*: the log file
must be a readable file in this container. Three shapes, no fourth:

1. server on the host, service in Docker → bind the server dir `:ro`.
2. server in another container sharing a named volume → mount that volume.
3. different machine → out of scope for MVP; needs a shipper sidecar —
   decision in #9. Ship it as a documented "not yet", not a user discovery.

`:ro` is the security promise: every byte Red writes leaves via RCON. The
container runs non-root with a read-only rootfs and exactly one writable path.

**12.3.2 RCON still has to be on.** Adapter Logtail cannot enable it (§4.2) and the
toggle costs one restart. So `init` reads `server.properties` off the mount and,
if `enable-rcon≠true`, prints the two lines to add plus the restart command and
keeps going in eyes-only mode rather than dying at startup.

**12.3.3 The honest floor: no RCON ⇒ eyes, no mouth.** A pure read-only mount
with no server edit at all gives Red events, memory, and context — and no reply
channel. That is a supported degraded mode (§1), stated in `doctor` output as
"Red can see everything and say nothing: enable RCON to give it a voice", not
silently. Requirement: the service must not require RCON to start.

**12.3.4 Offsets and memory are not disposable.** Anonymous volumes mean every
`docker compose up` either replays the backlog or skips it (§4.1 "never
double-process a line") and Red wakes with amnesia (§6.3). Named volume, and one
line in the README saying so.

**12.3.5 Demo profile — the command that sells the project.**
`docker compose -f compose.yml -f compose.demo.yml up` brings its own Paper
server (itzg image, `ENABLE_RCON=true`, shared logs volume, port 25565) so a
user with no server gets `/red hello` from one `.env`. Requirements: the demo
file only *adds*, the demo must not be required for the real track, and the
third-party image is documented as example-only in the same spirit as
README's Legal section.

### 12.4 Track 2 — drop-in plugin + first-run wizard (the layman path)

Reframe against the obvious reading: **the jar is the second thing a layman
installs, not the first.** A dumb adapter (§1.3) cannot answer by itself, so a
server-side drop-in still needs the service on the box. What the jar buys is
*capability*, not simplicity: uuids, `ui.*`, native `world.*`, modded items
(§3.2). Ease of use comes from the wizard; power comes from the jar.

**Status: unscheduled.** The six requirements below stand as specified;
nobody is building them yet. Tripwire #12 promotes this section to its own
milestone spec when implementation starts.

Hard requirements:

- **Zero YAML.** The jar's default is the service's loopback URL; a local
  same-box install needs *no* plugin config at all. One wrong host string is the
  difference between "works" and "mystery".
- **No mod loader.** Paper/Purpur is what hosts' one-click installs default to,
  and `plugins/*.jar` is a copy operation, not a patch — reversible by deleting
  the file. Fabric/NeoForge are separate *ports* of one adapter type (§5), never forks.
- **`/red setup` pairing.** Plugin handshakes (§3.4) → service learns the
  server's real log path from the plugin's own report, then prints
  `http://127.0.0.1:8790/setup`. The browser does the rest: endpoint + key with a
  live "send test prompt", persona name/style, and permission choices as
  **checkboxes** ("answer chat", "change the time", "give items — asks first",
  "spawn mobs — asks first") mapping onto §6.2's `actions` /
  `cmd_exec_prefixes` / `needs_confirm`. Then a guided `/red hello` in game.
  This is the single largest ease-of-use lever in the project.
- **One config writer.** `init`, `setup`, and the wizard all call the same
  config-emitting code; three formats drifting apart is how §12.1's "0 hand
  edits" dies.
- **Honest degradation while the service is down:** §5 bounded buffer + gap
  reports, one console hint (not per-tick log spam), and `/red status` that says
  what's missing in imperative terms.
- **Independent upgradability** in both directions via §8 capability
  negotiation: new service + old jar and vice versa must both run, degraded, loud.

### 12.5 Track 3 — uv (decided: the project's Python toolchain)

**Decision: uv** for dependency resolution, virtualenvs, builds, and publishing —
superseding this document's earlier provisional "uv/pipx first" stance.
No poetry/pipenv/pdm, and `pyproject.toml` is the only packaging config in the repo.
Reason isn't speed
(it is, but irrelevant to a user): it's that one tool owns Python-version
selection, lockfile, venv, and wheel, which is exactly the chain that otherwise
produces "it worked on my machine" reports.

Split by audience, same toolchain:

- **Contributors:** `uv sync` + `uv run pytest` — `.python-version` + `uv.lock`
  are tracked, so CI runs `uv sync --frozen` and everyone resolves identically.
  A lockfile conflict is a normal PR diff, not an admin-facing artifact.
- **End users (this track):** `uvx gamemaster-red@0.3` (no install, no venv, no
  PATH surgery, ephemeral) or `uv tool install gamemaster-red@0.3` (persistent,
  on PATH). `gamemaster-red service install` then writes the systemd unit
  (Linux) or scheduled task (Windows) so the box survives reboot — plus
  `doctor`, which is what makes a host install as durable as compose.
- **Still supported:** `pip install gamemaster-red`. Never the documented
  default: a Python-version error before the first reply is the worst possible
  first impression (§12.1), and `pip` can't fix the interpreter the way uv can.
- **Inside the image (§12.3):** `uv sync --frozen` in a builder stage, runtime
  stage non-root. Users never see uv — compose is the invisible path; uv is the
  visible one for shell-comfortable admins.

### 12.6 The commands that carry the promise

| command | job | ease-of-use requirement |
|---|---|---|
| `init` | **discover, don't ask** | scan mounted roots for `server.properties` + `logs/latest.log`; read `rcon.port`, `enable-rcon`, brand/version; write `config.toml` + `.env` (0600) + optional `compose.yml`; end with the exact next 3 commands |
| `setup` | browser/TUI wizard | idempotent; runnable before or after `run`; same code path as `init` |
| `doctor` | pre-flight + support tool | log readable **and advancing** (mtime < 60 s proves you're tailing the live file, not a stale copy); parse rate over the last N lines, which surfaces §8 version drift *before* the user feels it; RCON reach+auth; model endpoint latency; sqlite writable; clock offset (§4.1); `--json` for CI; nonzero exit only for blockers |
| `demo` | try it with no server | §9.2's canned log stream + fake RCON, in a terminal. Proves install and model config before touching the server — highest-leverage command here, and it already exists as CI infrastructure |
| `run`, `service` | steady state | foreground `run` for compose/FG; `service` for host installs |

`doctor` is also the support contract: "paste `gamemaster-red doctor` output" is
answerable, which is what an unpaid project's issue queue needs.

### 12.7 Secrets, state, upgrades

- Keys via env or `*_FILE`; never round-tripped into `config.toml`
  (README's "your API key never leaves your server").
- One state dir (everything restorable = `config.toml` + that dir, hence a
  one-command `backup`).
- Minor-pinned images and `uvx` pins; envelope stays v0 additive-only (§8) so
  a plugin dropped today keeps working against next month's service.
- `doctor` reports service/plugin/MC versions together — the first three lines of
  any drift bug report.

### 12.8 One repo (decision, not a default)

The three tracks are **two artifacts**, so don't count them as three products:
tracks 1 and 3 are the same Python code published two ways (`docker build` vs
wheel/`uvx`) — one source, one test suite, one CI job with two publish steps.
Only `plugin-paper/` is a genuinely separate codebase (Java 21, Gradle, Paper
API). So the real question was one repo or two, and the answer is one.

Why, all of it traceable to earlier sections:

- **§9.1** demands every adapter pass *the same* contract suite. In-tree that's
  one job over one fixture dir; cross-repo it needs a published schema artifact
  plus a pinned-plugin-against-pinned-service matrix.
- **§8** degradation must work in both directions (new service + old jar). Only
  cheaply testable when both sides are checkouts — that's the milestone spec's
  matrix smoke (MVP.md §4), one CI graph, one release-notes table.
- **§12.1**'s no-hand-edited-config principle rests on §12.4's "one config
  writer": the Python wizard emits the Java plugin's defaults. One repo keeps
  that in one place; two repos turn it into a versioned template dependency.
- **§12.3**'s `compose.yml` pins an image tag and `compose.demo.yml` can't be
  tested until the image is pushed — ordering that one workflow expresses and
  two repositories express with a release dance.
- Pre-1.0 the envelope moves weekly. Coordination cost across repos is highest
  exactly when the contract is unstable.

**The seam is `schema/`, not the tracks.** When envelope v1 freezes, extract it
to a versioned artifact (PyPI + Maven Central) and codegen both Python and Java
models from it. Until then, extracting the schema only adds a publish step to
every contract change.

Revisit only on: v1 frozen + schema shipped as a package · a Fabric/NeoForge
port landing (§5 says ports, not forks; a third loader under a maintainer
who doesn't want Python CI is the actual signal) · plugin release cadence
genuinely decoupling (Hangar/Modrinth outpacing service releases) · Java
contributors hitting setup friction that `paths:`-filtered workflows can't fix.
**Never split** the compose/demo/docs material: distribution docs away from the
code that generates them are stale within a month.

## 13. Open questions

The issue tracker is the question queue; this file no longer parks
questions. Every open question from the pre-split draft is an issue:
**#6** `@red` mention hook · **#7** ambient-reply opt-in model ·
**#8** ambient token-budget defaults · **#9** cross-machine log strategy ·
**#10** Bridge auth shape · **#11** image registry surface.

New questions get an `area/*` label and an issue, never a section. A decided
question closes with its answer written into the section that owns the
decision — rationale in the docs, state in the tracker.
